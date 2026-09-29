"""Canonical workbook contracts and provenance-bound execution handlers."""
from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping

from proxy.services.artifact_revision_service import (
    ArtifactNotFoundError,
    ArtifactRevisionRequest,
    ArtifactRevisionStore,
)
from proxy.services.chat_attachment_service import resolve_read_attachment
from proxy.services.packaging_recovery_service import (
    memory_pressure_note,
    packaging_fault,
)
from proxy.services.tool_contract_service import (
    EffectClass, IdempotencyPolicy, ResultBudget, RetryPolicy, ToolContract,
)
from proxy.services.tool_registry_service import ToolRegistration, ToolRegistry
from proxy.services.workflow_checkpoint_service import (
    CheckpointBeginRequest,
    WorkflowCheckpoint,
    WorkflowCheckpointService,
)


_BASE_INPUT_PROPERTIES = {
    "attachment_id": {"type": "string", "minLength": 1},
    "question": {"type": "string"},
    "project_id": {"type": ["integer", "null"]},
    "parent_revision_id": {"type": ["string", "null"]},
    "dataset_ids": {"type": ["array", "null"], "items": {"type": "string"}},
    # Explicit draft marking for intermediates of a durable research job;
    # optional, so an ordinary final call keeps its pre-existing identity.
    "draft": {"type": "boolean"},
}

_VOR_INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["attachment_id"],
    "properties": {
        **_BASE_INPUT_PROPERTIES,
        "decisions": {
            "type": "array",
            "items": {"type": "object"},
        },
    },
}

_LSR_DECISION_SCHEMA = {"type": "object"}
_LSR_CONFIRMED_DATA_SCHEMA = {
    "type": "object",
    "additionalProperties": {"type": "object"},
}

_LSR_INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["attachment_id", "decisions"],
    "properties": {
        **_BASE_INPUT_PROPERTIES,
        "decisions": {
            "type": "array",
            "minItems": 1,
            "items": _LSR_DECISION_SCHEMA,
        },
        "confirmed_data": _LSR_CONFIRMED_DATA_SCHEMA,
        # stage D: explicit user/model pricebook request (GUI chat path)
        "pricebook": {"type": "string"},
        # Task 2026-09-28 § 4: the basis this very document was already priced
        # in, replayed by code on a continuation turn so «продолжи» cannot zero
        # out the region and quarter. Server-owned, never model-authored.
        "document_price_basis": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "pricebook": {"type": "string"},
                "region": {"type": "string"},
                "quarter": {"type": "string"},
                "binding": {"type": "string"},
                "revision_id": {"type": "string"},
            },
        },
    },
}


def _contract(
    name: str,
    title: str,
    summary: str,
    model_owned_fields: tuple[str, ...],
    *,
    input_schema: Mapping[str, Any],
) -> ToolContract:
    return ToolContract(
        name=name, version="1.0.0", title=title, category="workbook", summary=summary,
        input_schema=input_schema, result_schema="les.workbook_tool_result.v1",
        effect=EffectClass.DRAFT, scopes=("chat_attachment", "dataset"),
        timeout_seconds=900, retry=RetryPolicy.IDEMPOTENCY_KEY,
        idempotency=IdempotencyPolicy.REQUIRED,
        result_budget=ResultBudget(max_chars=500_000, max_items=20_000),
        model_owned_fields=model_owned_fields,
        provenance="artifact_revision_required",
        tags=("workbook", "immutable_revision", "execution_context_required"),
    )


BUILD_LSR_WORKBOOK = _contract(
    "build_lsr_workbook", "Build LSR workbook",
    "Build an immutable priced ЛСР (локальный сметный расчёт) draft from a "
    "server-owned attachment. Choose it when the user asks for a ЛСР/смета that "
    "needs a norm code, analogue and price per work row; it requires "
    "model-authored decisions.",
    ("norm_code", "analogue", "coverage", "coefficient"),
    input_schema=_LSR_INPUT_SCHEMA,
)
BUILD_VOR_WORKBOOK = _contract(
    "build_vor_workbook", "Build VOR workbook",
    "Build an immutable ВОР (ведомость объёма работ) draft that preserves the "
    "source specification rows, quantities and units WITHOUT norm pricing. Choose "
    "it when the user asks for a ВОР/ведомость from a specification or source "
    "table; it needs only the attachment, never model decisions.", (),
    input_schema=_VOR_INPUT_SCHEMA,
)


def workbook_download_filename(
    *,
    artifact_kind: str,
    source_name: str = "",
    when: datetime | None = None,
    draft: bool = False,
) -> str:
    """Build a stable operator-facing workbook name without filesystem details."""

    stamp = (when or datetime.now()).strftime("%Y-%m-%d_%H%M")
    prefix = ("VOR" if str(artifact_kind) == "vor_workbook" else "LSR")
    if draft:
        # A paused durable job must never look like the finished document.
        prefix = f"draft_{prefix}"
    stem = Path(str(source_name or "")).stem
    from proxy.services.lsr_workbook_adapter_service import is_question_like_title

    if is_question_like_title(stem):
        stem = ""
    stem = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("._")
    stem = re.sub(r"_+", "_", stem)[:48]
    if is_question_like_title(stem.replace("_", " ")):
        stem = ""
    name = f"{prefix}_{stem}_{stamp}.xlsx" if stem else f"{prefix}_{stamp}.xlsx"
    return name.replace('"', "").replace("/", "_").replace("\\", "_")


def _vor_rows_from_draft(draft: Any, *, source_label: str) -> list[dict[str, Any]]:
    """Map already-authored rows to VOR cells without selecting or renumbering them."""

    rows: list[dict[str, Any]] = []
    for item in draft or []:
        if not isinstance(item, Mapping):
            continue
        source_row = item.get("source_row")
        if source_row in (None, ""):
            raise ValueError("source_row is required for model-authored VOR rows")
        name = str(item.get("title") or item.get("name") or item.get("work_name") or "").strip()
        if not name:
            raise ValueError(f"title is required for source_row {source_row}")
        rows.append({
            "section": str(item.get("section") or "").strip(),
            "name": name,
            "code": str(item.get("mark") or item.get("code") or "").strip(),
            "unit": str(item.get("unit") or "").strip(),
            "qty": item.get("quantity") if item.get("quantity") not in (None, "") else item.get("qty"),
            "source_file": source_label,
            "pos": source_row,
        })
    return rows


WorkbookAdapter = Callable[
    [Path, Mapping[str, Any], Path, Callable[[str, int, int | None], None]],
    Mapping[str, Any] | Awaitable[Mapping[str, Any]],
]


def chat_workbook_adapters() -> Mapping[str, WorkbookAdapter]:
    """Single manifest for workbook capabilities executable by ordinary chat."""
    from proxy.services.lsr_workbook_adapter_service import build_lsr_workbook_from_decisions

    return MappingProxyType({
        BUILD_LSR_WORKBOOK.name: build_lsr_workbook_from_decisions,
        BUILD_VOR_WORKBOOK.name: _default_vor_adapter,
    })


def available_chat_workbook_tools(*, executor_configured: bool) -> frozenset[str]:
    """Return workbook tools the current chat executor can actually run.

    Both workbook tools have in-process adapters. Registering their contracts
    alone still must not advertise them without the chat executor boundary.
    """
    if not executor_configured:
        return frozenset()
    return frozenset(chat_workbook_adapters())


@dataclass(frozen=True)
class WorkbookExecutionContext:
    session_id: str
    idempotency_key: str
    model_decision_revision: str
    profile_revision_id: str
    model_identity: str
    model_preset: str
    attachment_root: Path
    work_dir: Path
    checkpoints: WorkflowCheckpointService
    artifacts: ArtifactRevisionStore
    lsr_adapter: WorkbookAdapter | None = None
    vor_adapter: WorkbookAdapter | None = None
    progress_sink: Callable[[Mapping[str, Any]], None] | None = None


_MODEL_COMPUTED_FIELDS = {
    "rows", "prices", "price", "unit_prices", "totals", "total", "amounts", "calculated_rows",
}


def _rejected(code: str, message: str) -> dict[str, Any]:
    return {
        "schema": "les.workbook_tool_result.v1",
        "status": "rejected",
        "code": code,
        "message": message,
        "missing": [],
        "blockers": [],
    }


def _normalized_args(args: Mapping[str, Any], *, allowed_args: set[str]) -> dict[str, Any]:
    normalized = {key: args.get(key) for key in allowed_args if key in args}
    normalized["attachment_id"] = str(normalized.get("attachment_id") or "").strip()
    normalized["question"] = str(normalized.get("question") or "").strip()
    normalized["pricebook"] = str(normalized.get("pricebook") or "").strip()
    if "draft" in args:
        normalized["draft"] = bool(args.get("draft"))
    normalized["project_id"] = normalized.get("project_id")
    normalized["parent_revision_id"] = str(normalized.get("parent_revision_id") or "").strip() or None
    normalized["dataset_ids"] = list(dict.fromkeys(
        str(item).strip() for item in (normalized.get("dataset_ids") or []) if str(item).strip()
    ))
    if "decisions" in allowed_args:
        normalized["decisions"] = [dict(item) for item in (normalized.get("decisions") or [])]
    if "confirmed_data" in allowed_args:
        overlays = normalized.get("confirmed_data")
        payload: dict[str, dict[str, Any]] = {}
        if isinstance(overlays, Mapping):
            for key, value in overlays.items():
                locator = str(key or "").strip()
                if locator and isinstance(value, Mapping):
                    payload[locator] = dict(value)
        normalized["confirmed_data"] = payload
    if "document_price_basis" in allowed_args:
        # Server-owned continuation of the basis (§ 4).  Only the five known
        # strings survive; an unknown key or a non-string value is dropped, so
        # nothing can smuggle a basis in through this field, and a book that is
        # not installed cannot be bound by it either (explicit_only=True).
        stored = normalized.get("document_price_basis")
        fields = {
            key: str(stored.get(key) or "").strip()
            for key in ("pricebook", "region", "quarter", "binding", "revision_id")
        } if isinstance(stored, Mapping) else {}
        normalized["document_price_basis"] = (
            fields if any(fields.values()) else {}
        )
    return normalized


def _checkpoint_payload(checkpoint: WorkflowCheckpoint, *, resumed: bool) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "phase": checkpoint.phase,
        "status": checkpoint.status,
        "completed_items": checkpoint.completed_items,
        "total_items": checkpoint.total_items,
        "resumed": resumed,
    }


def _result_from_revision(
    *, revision, checkpoint: WorkflowCheckpoint, attachment_meta: Mapping[str, Any],
    source_rows: int = 0, resumed: bool,
) -> dict[str, Any]:
    if not source_rows and revision.tool_calls:
        source_rows = int(revision.tool_calls[-1].get("source_rows") or 0)
    return {
        "schema": "les.workbook_tool_result.v1",
        "status": "complete",
        "artifact": revision.to_dict(),
        "source": {
            "attachment_id": attachment_meta["attachment_id"],
            "name": attachment_meta["original_name"],
            "sha256": attachment_meta["sha256"],
            "rows": int(source_rows),
        },
        "checkpoint": _checkpoint_payload(checkpoint, resumed=resumed),
        "missing": list(revision.missing),
        "blockers": list(revision.blockers),
    }


async def _default_vor_adapter(
    source_path: Path, args: Mapping[str, Any], output_path: Path,
    progress: Callable[[str, int, int | None], None],
) -> Mapping[str, Any]:
    from proxy.services.bor_service import source_rows_to_vor_xlsx
    from proxy.services.spec_to_bor_service import rows_from_spec_xlsx

    source_label = str(args.get("_source_name") or source_path.name)
    rows: list[dict[str, Any]] = []
    spec_error: Exception | None = None
    if source_path.suffix.lower() in {".xlsx", ".xlsm"}:
        try:
            rows = await asyncio.to_thread(
                rows_from_spec_xlsx,
                source_path,
                source_label=source_label,
            )
        except Exception as error:  # noqa: BLE001 - exact draft fallback remains available
            spec_error = error
    if not rows:
        rows = _vor_rows_from_draft(args.get("decisions") or [], source_label=source_label)
    if not rows and spec_error is not None:
        raise spec_error
    from proxy.services.spec_to_bor_service import derive_work_for_item

    requires_decision_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        proposed, needs = derive_work_for_item(str(row.get("name") or row.get("work_name") or ""))
        row["derived_work"] = proposed
        row["requires_decision"] = (
            bool(row.get("requires_decision")) or needs or bool(row.get("quantity_issue"))
        )
        if row["requires_decision"]:
            requires_decision_count += 1
    progress("source_rows", 0, len(rows))
    await asyncio.to_thread(
        source_rows_to_vor_xlsx,
        rows,
        output_path,
        title=str(args.get("question") or "Ведомость объёмов работ"),
    )
    missing: list[str] = []
    for index, row in enumerate(rows, 1):
        if not str(row.get("unit") or "").strip():
            missing.append(f"row:{index}:unit")
        if row.get("qty") is None:
            missing.append(f"row:{index}:quantity")
            if row.get("quantity_issue") == "formula_without_cached_value":
                missing.append(f"row:{index}:quantity_formula_without_cached_value")
    progress("source_rows", len(rows), len(rows))
    return {
        "file_path": output_path,
        "source_rows": len(rows),
        "requires_decision_count": requires_decision_count,
        "missing": missing,
        "blockers": (["NO_SOURCE_ROWS"] if not rows else []),
    }


async def _call_adapter(
    adapter: WorkbookAdapter, source_path: Path, args: Mapping[str, Any],
    output_path: Path, progress: Callable[[str, int, int | None], None],
) -> Mapping[str, Any]:
    generated = adapter(source_path, args, output_path, progress)
    if inspect.isawaitable(generated):
        generated = await generated
    if not isinstance(generated, Mapping):
        raise RuntimeError("workbook adapter returned an invalid result")
    return generated


def _packaging_parent(
    ctx: WorkbookExecutionContext,
    *,
    tool_name: str,
    attachment_id: str,
    explicit: Any,
) -> tuple[str | None, str]:
    """Resolve which revision this delivery continues, and why.

    The revision chain belongs to the application, not to the model: the caller
    that packages the next decision set for the same source document must extend
    the same downloadable file.  An explicit parent (the durable research job's
    recorded packaging lineage) wins.  Otherwise the newest revision this chat
    session already delivered for the same attachment is used, which covers the
    routes that produce a file before any research job exists.  Scoping by
    ``session_id`` keeps the build 812 guarantee that a new chat does not reopen
    another chat's document.

    A parent that is no longer in the artifact store is dropped instead of
    failing delivery: the user keeps the file, and ``tool_calls`` says which link
    was missing.
    """
    value = str(explicit or "").strip()
    if value:
        return value, "explicit"
    try:
        candidate = ctx.checkpoints.last_completed_revision(
            session_id=ctx.session_id,
            attachment_id=attachment_id,
            tool_name=tool_name,
        )
    except Exception:  # noqa: BLE001 - lineage is an improvement, never a blocker
        return None, "checkpoint_store_unavailable"
    if not candidate:
        return None, "first_revision"
    try:
        ctx.artifacts.get_revision(candidate)
    except ArtifactNotFoundError:
        return None, "parent_missing_from_store"
    return candidate, "session_lineage"


async def _build_workbook(
    tool_name: str, artifact_kind: str, args: Mapping[str, Any], ctx: WorkbookExecutionContext,
) -> dict[str, Any]:
    forbidden = sorted(set(args) & _MODEL_COMPUTED_FIELDS)
    if forbidden:
        return {**_rejected(
            "MODEL_DECISION_FIELD_NOT_ALLOWED",
            f"computed workbook fields are not accepted: {', '.join(forbidden)}",
        ), "tool": tool_name}
    input_schema = BUILD_LSR_WORKBOOK.input_schema if artifact_kind == "lsr_workbook" else BUILD_VOR_WORKBOOK.input_schema
    allowed_args = set(input_schema["properties"])
    unknown = sorted(set(args) - allowed_args)
    if unknown:
        return {**_rejected("INVALID_TOOL_ARGUMENTS", f"unknown arguments: {', '.join(unknown)}"), "tool": tool_name}
    normalized = _normalized_args(args, allowed_args=allowed_args)
    if not normalized["attachment_id"]:
        return {**_rejected("INVALID_TOOL_ARGUMENTS", "attachment_id is required"), "tool": tool_name}
    try:
        source_path, attachment_meta = await asyncio.to_thread(
            resolve_read_attachment,
            normalized["attachment_id"],
            root=ctx.attachment_root,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        return {**_rejected("ATTACHMENT_INVALID", str(error)), "tool": tool_name}
    draft_rows = [
        dict(item) for item in (normalized.get("decisions") or []) if isinstance(item, Mapping)
    ]
    if artifact_kind == "vor_workbook":
        supported = {".xlsx", ".xlsm"}
        if draft_rows:
            supported.add(".pdf")
    else:
        supported = {".pdf", ".xlsx", ".xlsm"}
    if source_path.suffix.lower() not in supported:
        return {**_rejected("UNSUPPORTED_ATTACHMENT_TYPE", f"unsupported attachment type: {source_path.suffix}"), "tool": tool_name}

    checkpoint = ctx.checkpoints.begin_or_resume(CheckpointBeginRequest(
        session_id=ctx.session_id,
        idempotency_key=ctx.idempotency_key,
        tool_name=tool_name,
        attachment_id=normalized["attachment_id"],
        attachment_sha256=str(attachment_meta["sha256"]),
        normalized_args=normalized,
        model_decision_revision=ctx.model_decision_revision,
    ))
    if checkpoint.status == "complete" and checkpoint.artifact_revision_id:
        revision = ctx.artifacts.get_revision(checkpoint.artifact_revision_id)
        return {**_result_from_revision(
            revision=revision,
            checkpoint=checkpoint,
            attachment_meta=attachment_meta,
            resumed=True,
        ), "tool": tool_name}

    def progress(phase: str, completed: int, total: int | None) -> None:
        ctx.checkpoints.record_progress(
            checkpoint.checkpoint_id, phase=phase, completed=completed, total=total
        )
        if ctx.progress_sink is not None:
            ctx.progress_sink({
                "checkpoint_id": checkpoint.checkpoint_id,
                "tool_name": tool_name,
                "phase": phase,
                "completed": completed,
                "total": total,
            })

    output_path = ctx.work_dir / checkpoint.checkpoint_id / f"{tool_name}.xlsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    adapter = ctx.vor_adapter or _default_vor_adapter if artifact_kind == "vor_workbook" else ctx.lsr_adapter
    if adapter is None:
        failed = ctx.checkpoints.record_status(
            checkpoint.checkpoint_id,
            status="failed",
            blockers=("LSR_ADAPTER_REQUIRED",),
        )
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": tool_name,
            "status": "failed",
            "code": "WORKBOOK_ADAPTER_UNAVAILABLE",
            "message": "LSR workbook adapter is not configured",
            "checkpoint": _checkpoint_payload(failed, resumed=checkpoint.status != "running"),
            "missing": [],
            "blockers": list(failed.blockers),
        }
    try:
        # Operator-injected, default-off: lets the recovery path be verified on
        # an installed build without waiting for a real memory-pressure incident.
        packaging_fault()
        adapter_payload = {
            key: value for key, value in normalized.items() if key != "draft"
        }
        adapter_args = {**adapter_payload, "_source_name": str(attachment_meta["original_name"])}
        generated = await _call_adapter(adapter, source_path, adapter_args, output_path, progress)
        generated_path = Path(str(generated.get("file_path") or output_path))
        display_name = workbook_download_filename(
            artifact_kind=artifact_kind,
            source_name=str(attachment_meta.get("original_name") or ""),
            draft=bool(normalized.get("draft")),
        )
        named_path = generated_path.with_name(display_name)
        if named_path.resolve() != generated_path.resolve() and generated_path.exists():
            generated_path.replace(named_path)
            generated_path = named_path
        missing = tuple(str(item) for item in (generated.get("missing") or ()))
        blockers = tuple(str(item) for item in (generated.get("blockers") or ()))
        tool_call_meta = {
            "name": tool_name,
            "version": "1.0.0",
            "idempotency_key": ctx.idempotency_key,
            "model_decision_revision": ctx.model_decision_revision,
            "source_rows": int(generated.get("source_rows") or 0),
        }
        if normalized.get("draft"):
            tool_call_meta["draft"] = True
        applied_basis = (
            generated.get("price_basis")
            if isinstance(generated.get("price_basis"), Mapping)
            else {}
        )
        inherited_from = str(applied_basis.get("inherited_from_document") or "").strip()
        if inherited_from:
            # § 4 evidence the other way round: the artifact itself says which
            # revision's basis this delivery continued, so a reader of the file
            # can tell a preserved choice from a re-derived one.
            tool_call_meta["price_basis_inherited_from"] = inherited_from
            tool_call_meta["pricebook"] = str(applied_basis.get("actual_book") or "")
        parent_revision_id, parent_source = _packaging_parent(
            ctx,
            tool_name=tool_name,
            attachment_id=normalized["attachment_id"],
            explicit=normalized["parent_revision_id"],
        )
        tool_call_meta["parent_revision_source"] = parent_source
        revision = ctx.artifacts.create_revision(ArtifactRevisionRequest(
            artifact_kind=artifact_kind,
            file_path=generated_path,
            source_scope=tuple(
                [f"attachment:{normalized['attachment_id']}"]
                + [f"dataset:{item}" for item in normalized["dataset_ids"]]
                + ([f"project:{normalized['project_id']}"] if normalized.get("project_id") is not None else [])
            ),
            profile_revision_id=ctx.profile_revision_id,
            model_identity=ctx.model_identity,
            model_preset=ctx.model_preset,
            tool_calls=(tool_call_meta,),
            decision_checkpoint_id=checkpoint.checkpoint_id,
            missing=missing,
            blockers=blockers,
            parent_revision_id=parent_revision_id,
        ))
        completed = ctx.checkpoints.complete(checkpoint.checkpoint_id, revision.revision_id)
        payload = {
            **_result_from_revision(
                revision=revision,
                checkpoint=completed,
                attachment_meta=attachment_meta,
                source_rows=int(generated.get("source_rows") or 0),
                resumed=checkpoint.status != "running" or checkpoint.phase != "started",
            ),
            "tool": tool_name,
        }
        for key in (
            "pricing_status",
            "norms_status",
            "price_gaps",
            "price_basis",
            # the adapter flags rows whose own wording names the opposite
            # operation; without this key the question dies here and the
            # operator never sees it in chat (task § 11 №8)
            "norm_conflicts",
            "calculated_positions",
            # § 4: the projection is what the readiness counters are computed from,
            # so it has to travel with the numbers it explains.
            "row_projection",
            "positions_built",
            "confirmed_amount",
            "preliminary_amount",
        ):
            if generated.get(key) not in (None, "", [], ()):
                payload[key] = generated[key]
        return payload
    except Exception as error:
        failed = ctx.checkpoints.record_status(
            checkpoint.checkpoint_id,
            status="failed",
            blockers=(f"{type(error).__name__}: {error}",),
        )
        error_type = type(error).__name__
        memory_pressure = error_type == "MemoryError" or "memory" in str(error).casefold()
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": tool_name,
            "status": "failed",
            "code": "WORKBOOK_GENERATION_FAILED",
            "error_type": error_type,
            "memory_pressure": memory_pressure,
            "message": str(error) or f"{error_type}: сборка файла не удалась",
            "checkpoint": _checkpoint_payload(failed, resumed=checkpoint.status != "running"),
            "missing": list(failed.missing),
            "blockers": list(failed.blockers),
            # The saved model decision is untouched by a packaging failure, so
            # the only correct next step is a rebuild that does not call the
            # model.  Stating it here keeps the repair with the failure.
            "recovery": {
                "action": "repack",
                "endpoint": "/api/chat/repack-lsr",
                "model_called": False,
                "note": memory_pressure_note(
                    {"code": error_type, "message": str(error)}
                ),
            },
        }


async def build_lsr_workbook(
    args: Mapping[str, Any], execution_context: WorkbookExecutionContext
) -> dict[str, Any]:
    return await _build_workbook("build_lsr_workbook", "lsr_workbook", args, execution_context)


async def build_vor_workbook(
    args: Mapping[str, Any], execution_context: WorkbookExecutionContext
) -> dict[str, Any]:
    return await _build_workbook("build_vor_workbook", "vor_workbook", args, execution_context)


def _handler_requires_execution_context(_args: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("WORKBOOK_EXECUTION_CONTEXT_REQUIRED")


def register_workbook_contracts(registry: ToolRegistry) -> ToolRegistry:
    for contract in (BUILD_LSR_WORKBOOK, BUILD_VOR_WORKBOOK):
        if registry.get(contract.name) is None:
            registry.register(ToolRegistration(contract=contract, handler=_handler_requires_execution_context))
    return registry
