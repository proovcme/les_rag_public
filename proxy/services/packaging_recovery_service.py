"""Durable packaging recovery for the model-owned workbook path.

Two problems live here.

1. A *completed* research job must always end with a downloadable document.
   Packaging is the only step that can still fail (the Windows commit limit
   raises ``MemoryError`` inside the price-book / catalog loaders), and when it
   does the job is already terminal: the model decision is saved, the work is
   finished, only the file is missing.  ``describe_packaging_document`` turns
   the job's own durable ``workbook_packaged`` events into one authoritative
   answer — is the document ready, is it only a draft, or is a completed job
   still waiting for its file — so both the API and the interface can offer
   "rebuild the file without the model" instead of silently restarting.

2. ``release_memory_for_packaging`` gives the bounded retry a real chance of
   succeeding: it drops the process-wide reference tables (price books, GESN
   norm copies, source catalogs) that packaging materialises, then collects.
   It never touches a job, checkpoint or artifact.

``packaging_fault`` is a default-off operator hook used to verify the recovery
path on an installed build; with no environment set it does nothing at all.
"""
from __future__ import annotations

import gc
import os
from typing import Any, Iterable, Mapping

SCHEMA = "les.packaging-recovery.v1"

#: The single repair action a client may offer.  It always maps to
#: ``POST /api/chat/repack-lsr`` (saved decisions, no model call).
REPACK_ACTION: dict[str, str] = {
    "id": "repack",
    "label": "Пересобрать файл",
    "kind": "repack",
}

_DOCUMENT_STATES = {"ready", "draft_only", "pending", "none"}


def _recorded_price_basis(
    payload: Mapping[str, Any],
    revision_id: str,
) -> dict[str, Any]:
    """The basis this packaged revision was priced in, if the event carries one.

    Events written before build 821 store no basis; they yield ``{}``, so an old
    document simply has nothing to inherit and the operator is asked as before.
    """

    basis = payload.get("price_basis")
    if not isinstance(basis, Mapping):
        return {}
    book = str(basis.get("pricebook") or basis.get("actual_book") or "").strip()
    if not book:
        return {}
    return {
        "pricebook": book,
        "region": str(basis.get("region") or basis.get("actual_region") or "").strip(),
        "quarter": str(basis.get("quarter") or basis.get("actual_quarter") or "").strip(),
        "binding": str(basis.get("binding") or "").strip(),
        "match": str(basis.get("match") or "").strip(),
        "revision_id": str(revision_id or ""),
        **({"pricebook_sha256": str(basis["pricebook_sha256"]).strip()}
           if basis.get("pricebook_sha256") else {}),
    }


def _env_flag(name: str) -> str:
    try:
        return str(os.environ.get(name) or "").strip()
    except Exception:  # noqa: BLE001 - environment is advisory only
        return ""


# --------------------------------------------------------------------------- #
# durable document state
# --------------------------------------------------------------------------- #
def workbook_document_from_events(
    events: Iterable[Mapping[str, Any]], *, status: str = "", accepted_row_count: int = 0,
) -> dict[str, Any]:
    """Use the tool recorded by this job, without treating a VOR as a missing LSR."""
    records = list(events or [])
    tool = "build_lsr_workbook"
    for event in records:
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event") or event.get("event_type") or "") != "workbook_packaged":
            continue
        payload = event.get("data") or event.get("payload") or {}
        candidate = payload.get("tool") if isinstance(payload, Mapping) else None
        if candidate in {"build_lsr_workbook", "build_vor_workbook"}:
            tool = candidate
    return describe_packaging_document(
        records, status=status, tool=tool, accepted_row_count=accepted_row_count,
        artifact_kind="vor_workbook" if tool == "build_vor_workbook" else "lsr_workbook",
    )


def describe_packaging_document(
    events: Iterable[Mapping[str, Any]],
    *,
    status: str = "",
    tool: str = "build_lsr_workbook",
    artifact_kind: str = "lsr_workbook",
    accepted_row_count: int = 0,
) -> dict[str, Any]:
    """Project the durable packaging history of one job into a file state.

    ``events`` are ``WorkbookResearchJobService.events_after`` rows
    (``{"event", "data"}``) or raw ``_append_event`` rows
    (``{"event_type", "payload"}``); both shapes are accepted so the helper
    works on a live connection and in unit tests.

    ``state`` is one of:

    * ``ready``      — a final (non-draft) document was packaged after the
      last decision-changing event;
    * ``draft_only`` — only intermediate drafts exist; the finished document
      was never produced;
    * ``pending``    — a terminal job has no final document, or a paused job
      has durable decisions but no downloadable draft;
    * ``none``       — nothing packaged and the job is still open.
    """

    final_revision = ""
    draft_revision = ""
    packaged_tools: set[str] = set()
    final_basis: dict[str, Any] = {}
    last_basis: dict[str, Any] = {}
    first_for_book: dict[str, str] = {}
    for event in events or ():
        if not isinstance(event, Mapping):
            continue
        name = str(
            event.get("event") or event.get("event_type") or ""
        ).strip()
        if name != "workbook_packaged":
            continue
        payload = event.get("data")
        if not isinstance(payload, Mapping):
            payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        event_tool = str(payload.get("tool") or "")
        revision_id = str(payload.get("revision_id") or "")
        if not revision_id:
            continue
        if event_tool and event_tool != tool:
            continue
        packaged_tools.add(event_tool or tool)
        recorded = _recorded_price_basis(payload, revision_id)
        if recorded:
            first_for_book.setdefault(recorded["pricebook"], revision_id)
            last_basis = recorded
        if bool(payload.get("draft")):
            draft_revision = revision_id
        else:
            final_revision = revision_id
            if recorded:
                final_basis = recorded

    normalized_status = str(status or "").strip().casefold()
    terminal = normalized_status in {"complete", "failed"}
    paused_without_file = (
        normalized_status == "paused" and accepted_row_count > 0
        and not final_revision and not draft_revision
    )
    if final_revision:
        state = "ready"
    elif draft_revision:
        state = "draft_only" if terminal else "none"
    else:
        state = "pending" if terminal or paused_without_file else "none"
    if state not in _DOCUMENT_STATES:  # defensive: projection stays closed
        state = "none"

    needs_document = (
        state in {"draft_only", "pending"} and normalized_status == "complete"
    ) or paused_without_file
    recovery_reason = ""
    if paused_without_file:
        recovery_reason = (
            "Задание приостановлено. Можно собрать черновик из сохранённых решений "
            "без вызова модели. Необработанные строки останутся открытыми для продолжения."
        )
    elif needs_document:
        recovery_reason = (
            "Задание завершено, но финальный файл не собран. "
            "Сохранённые решения модели не пересматриваются."
            if state == "pending"
            else "Собран только промежуточный черновик. "
            "Финальный документ ещё не упакован из сохранённых решений."
        )

    basis = final_basis or last_basis
    if basis:
        # The revision that first bound this book is the one the operator chose.
        # Stamping the newest revision that re-priced it would make the label
        # grow on every turn, and because the repack route sends this record as
        # a tool argument the same document would read as a different request on
        # a replay.  The chat continuation inherits its provenance from the very
        # same rule, so the card, the file header and the arguments agree (§ 10).
        basis = {
            **basis,
            "revision_id": first_for_book.get(
                str(basis.get("pricebook") or ""), str(basis.get("revision_id") or "")
            ),
        }

    return {
        "schema": SCHEMA,
        "state": state,
        "status": str(status or ""),
        "tool": tool,
        "artifact_kind": artifact_kind,
        "final_revision_id": final_revision,
        "draft_revision_id": draft_revision,
        # The basis the document itself carries: the finished revision's when
        # there is one, otherwise the last revision that bound a book.  A
        # continuation turn inherits it instead of re-deriving it from its own
        # text (task 2026-09-28 § 4).
        "price_basis": basis,
        "packaged": bool(final_revision) or bool(draft_revision),
        "needs_document": needs_document,
        "recovery_reason": recovery_reason,
        "actions": [dict(REPACK_ACTION)] if needs_document else [],
    }


def packaging_recovery_payload(
    job: Mapping[str, Any],
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """The resume payload the interface needs to repair the file itself.

    Everything comes from the durable job: no new research, no model call.
    """

    identity = job.get("identity") if isinstance(job.get("identity"), Mapping) else {}
    decisions = [
        dict(item)
        for item in (job.get("accepted_rows") or ())
        if isinstance(item, Mapping)
    ]
    return {
        "schema": SCHEMA,
        "action": "repack",
        "endpoint": "/api/chat/repack-lsr",
        "model_called": False,
        "job_id": str(job.get("job_id") or ""),
        "session_id": str(identity.get("session_id") or ""),
        "attachment_id": str(identity.get("attachment_id") or ""),
        "question": (
            "Пересобери ЛСР из сохранённых решений"
            if (job.get("task_context") or {}).get("price_basis")
            else str((job.get("task_context") or {}).get("original_question") or identity.get("question") or "")
        ),
        "decision_count": len(decisions),
        "remaining": [
            str(item) for item in (job.get("remaining") or ()) if str(item).strip()
        ],
        "state": str(document.get("state") or ""),
        # The basis travels with the repair payload so a rebuild of the saved
        # decisions stays priced in the book the document already used.
        "price_basis": (
            document.get("price_basis")
            if isinstance(document.get("price_basis"), Mapping)
            else {}
        ),
        "recovery_reason": str(document.get("recovery_reason") or ""),
        "actions": [dict(item) for item in (document.get("actions") or ()) if isinstance(item, Mapping)],
    }


# --------------------------------------------------------------------------- #
# memory relief + fault injection
# --------------------------------------------------------------------------- #
def release_memory_for_packaging(reason: str = "") -> dict[str, Any]:
    """Drop the big packaging-side reference tables, then collect.

    Best-effort by design: every cache is optional, so a missing or broken
    loader can never turn recovery itself into a failure.
    """

    released: list[str] = []
    errors: list[str] = []
    for label, clear in (
        ("fgis_pricebook", "proxy.services.fgis_price_service.get_pricebook"),
        ("gesn_norms", "proxy.services.gesn_service.load_base_norms"),
        ("gesn_structured", "proxy.services.gesn_service.load_structured_base_norms"),
        ("smeta_norm_store", "proxy.services.smeta_norm_store._norm_store_for_signature"),
    ):
        try:
            module_path, attr = _split(clear)
            module = __import__(module_path, fromlist=[attr])
            fn = getattr(module, attr, None)
            cache_clear = getattr(fn, "cache_clear", None)
            if callable(cache_clear):
                cache_clear()
                released.append(label)
        except Exception as error:  # noqa: BLE001 - relief is advisory
            errors.append(f"{label}:{type(error).__name__}")
    try:
        collected = gc.collect()
    except Exception as error:  # noqa: BLE001
        collected = 0
        errors.append(f"gc:{type(error).__name__}")
    return {
        "schema": SCHEMA,
        "reason": str(reason or ""),
        "released": released,
        "collected": int(collected),
        "errors": errors,
    }


def _split(attr_name: str) -> tuple[str, str]:
    module_path, _, attr = attr_name.rpartition(".")
    return module_path, attr


_FAULT_COUNTER: dict[str, int] = {}


def packaging_fault() -> None:
    """Optional operator-injected packaging failure (default: never).

    ``LES_DEBUG_PACKAGING_FAULT`` selects the exception raised from inside the
    packaging step so the recovery path can be verified on an installed build
    without waiting for a real memory-pressure incident.  Unset or unknown
    values are inert.

    ``LES_DEBUG_PACKAGING_FAULT_ROUNDS`` limits it to the first N packaging
    calls of this process, which is what makes the scenario testable at all:
    the turn's packaging fails, and the repair asked for from the interface
    afterwards succeeds.  Without a limit every retry fails identically and the
    recovery could not be observed.
    """

    kind = _env_flag("LES_DEBUG_PACKAGING_FAULT").casefold()
    if kind not in {"memoryerror", "memory", "oom", "runtimeerror", "runtime"}:
        return
    limit = _env_flag("LES_DEBUG_PACKAGING_FAULT_ROUNDS")
    if limit:
        try:
            rounds = int(limit)
        except ValueError:
            rounds = 0
        _FAULT_COUNTER["n"] = int(_FAULT_COUNTER.get("n", 0)) + 1
        if _FAULT_COUNTER["n"] > max(0, rounds):
            return
    if kind in {"memoryerror", "memory", "oom"}:
        raise MemoryError("injected packaging fault (LES_DEBUG_PACKAGING_FAULT)")
    raise RuntimeError("injected packaging fault (LES_DEBUG_PACKAGING_FAULT)")


def reset_packaging_fault() -> None:
    """Clear the injected-fault counter (used by tests and by a new run)."""

    _FAULT_COUNTER.clear()


def memory_pressure_note(payload: Mapping[str, Any]) -> str:
    """A plain-language line for the interface; never a stack trace."""

    code = str(payload.get("code") or "")
    message = str(payload.get("message") or "")
    if "MemoryError" in code or "MemoryError" in message:
        return (
            "Сборке файла не хватило памяти. Решения модели сохранены — "
            "файл можно пересобрать без нового запроса к модели."
        )
    if code:
        return f"Файл не собран ({code}). Решения модели сохранены."
    return "Файл не собран. Решения модели сохранены."
