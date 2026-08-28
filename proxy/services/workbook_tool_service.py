"""Canonical workbook contracts and provenance-bound execution handlers."""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from proxy.services.artifact_revision_service import (
    ArtifactRevisionRequest,
    ArtifactRevisionStore,
)
from proxy.services.chat_attachment_service import resolve_read_attachment
from proxy.services.tool_contract_service import (
    EffectClass, IdempotencyPolicy, ResultBudget, RetryPolicy, ToolContract,
)
from proxy.services.tool_registry_service import ToolRegistration, ToolRegistry
from proxy.services.workflow_checkpoint_service import (
    CheckpointBeginRequest,
    WorkflowCheckpoint,
    WorkflowCheckpointService,
)


_INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["attachment_id"],
    "properties": {
        "attachment_id": {"type": "string", "minLength": 1},
        "question": {"type": "string"},
        "project_id": {"type": ["integer", "null"]},
        "parent_revision_id": {"type": ["string", "null"]},
        "dataset_ids": {"type": ["array", "null"], "items": {"type": "string"}},
    },
}


def _contract(name: str, title: str, summary: str, model_owned_fields: tuple[str, ...]) -> ToolContract:
    return ToolContract(
        name=name, version="1.0.0", title=title, category="workbook", summary=summary,
        input_schema=_INPUT_SCHEMA, result_schema="les.workbook_tool_result.v1",
        effect=EffectClass.DRAFT, scopes=("chat_attachment", "dataset"),
        timeout_seconds=900, retry=RetryPolicy.IDEMPOTENCY_KEY,
        idempotency=IdempotencyPolicy.REQUIRED,
        result_budget=ResultBudget(max_chars=12_000, max_items=200),
        model_owned_fields=model_owned_fields,
        provenance="artifact_revision_required", tags=("workbook", "immutable_revision"),
    )


BUILD_LSR_WORKBOOK = _contract(
    "build_lsr_workbook", "Build LSR workbook",
    "Build an immutable priced LSR draft from a server-owned attachment.",
    ("norm_code", "analogue", "coverage", "coefficient"),
)
BUILD_VOR_WORKBOOK = _contract(
    "build_vor_workbook", "Build VOR workbook",
    "Build an immutable VOR draft preserving source rows and quantities.", (),
)


WorkbookAdapter = Callable[
    [Path, Mapping[str, Any], Path, Callable[[str, int, int | None], None]],
    Mapping[str, Any] | Awaitable[Mapping[str, Any]],
]


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


_ALLOWED_ARGS = set(_INPUT_SCHEMA["properties"])
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


def _normalized_args(args: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {key: args.get(key) for key in _ALLOWED_ARGS if key in args}
    normalized["attachment_id"] = str(normalized.get("attachment_id") or "").strip()
    normalized["question"] = str(normalized.get("question") or "").strip()
    normalized["project_id"] = normalized.get("project_id")
    normalized["parent_revision_id"] = str(normalized.get("parent_revision_id") or "").strip() or None
    normalized["dataset_ids"] = list(dict.fromkeys(
        str(item).strip() for item in (normalized.get("dataset_ids") or []) if str(item).strip()
    ))
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

    rows = await asyncio.to_thread(
        rows_from_spec_xlsx,
        source_path,
        source_label=str(args.get("_source_name") or source_path.name),
    )
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
    progress("source_rows", len(rows), len(rows))
    return {
        "file_path": output_path,
        "source_rows": len(rows),
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


async def _build_workbook(
    tool_name: str, artifact_kind: str, args: Mapping[str, Any], ctx: WorkbookExecutionContext,
) -> dict[str, Any]:
    forbidden = sorted(set(args) & _MODEL_COMPUTED_FIELDS)
    if forbidden:
        return {**_rejected(
            "MODEL_DECISION_FIELD_NOT_ALLOWED",
            f"computed workbook fields are not accepted: {', '.join(forbidden)}",
        ), "tool": tool_name}
    unknown = sorted(set(args) - _ALLOWED_ARGS)
    if unknown:
        return {**_rejected("INVALID_TOOL_ARGUMENTS", f"unknown arguments: {', '.join(unknown)}"), "tool": tool_name}
    normalized = _normalized_args(args)
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
    supported = {".xlsx", ".xlsm"} if artifact_kind == "vor_workbook" else {".pdf", ".xlsx", ".xlsm"}
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
        adapter_args = {**normalized, "_source_name": str(attachment_meta["original_name"])}
        generated = await _call_adapter(adapter, source_path, adapter_args, output_path, progress)
        generated_path = Path(str(generated.get("file_path") or output_path))
        missing = tuple(str(item) for item in (generated.get("missing") or ()))
        blockers = tuple(str(item) for item in (generated.get("blockers") or ()))
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
            tool_calls=({
                "name": tool_name,
                "version": "1.0.0",
                "idempotency_key": ctx.idempotency_key,
                "model_decision_revision": ctx.model_decision_revision,
                "source_rows": int(generated.get("source_rows") or 0),
            },),
            decision_checkpoint_id=checkpoint.checkpoint_id,
            missing=missing,
            blockers=blockers,
            parent_revision_id=normalized["parent_revision_id"],
        ))
        completed = ctx.checkpoints.complete(checkpoint.checkpoint_id, revision.revision_id)
        return {**_result_from_revision(
            revision=revision,
            checkpoint=completed,
            attachment_meta=attachment_meta,
            source_rows=int(generated.get("source_rows") or 0),
            resumed=checkpoint.status != "running" or checkpoint.phase != "started",
        ), "tool": tool_name}
    except Exception as error:
        failed = ctx.checkpoints.record_status(
            checkpoint.checkpoint_id,
            status="failed",
            blockers=(f"{type(error).__name__}: {error}",),
        )
        return {
            "schema": "les.workbook_tool_result.v1",
            "tool": tool_name,
            "status": "failed",
            "code": "WORKBOOK_GENERATION_FAILED",
            "message": str(error),
            "checkpoint": _checkpoint_payload(failed, resumed=checkpoint.status != "running"),
            "missing": list(failed.missing),
            "blockers": list(failed.blockers),
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
