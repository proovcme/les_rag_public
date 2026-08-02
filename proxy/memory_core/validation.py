"""Deterministic validation rules for Memory Core v1."""

from __future__ import annotations

from typing import Any

from proxy.memory_core.contracts import EntryKind, EvidenceRef, MemoryEntry, ValidationStatus


def validate_project_id(project_id: Any) -> int | None:
    try:
        value = int(project_id or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def grounded_turn_eligible(*, project_id: Any, turn: dict[str, Any]) -> bool:
    """Strict v1 enqueue predicate for ordinary grounded evidence flow."""
    if validate_project_id(project_id) is None:
        return False
    if str(turn.get("crag_status") or "") != "VERIFIED":
        return False
    if bool(turn.get("cache_hit")):
        return False
    route = turn.get("query_route") or {}
    channel = str(route.get("channel") or "").casefold()
    profile = str(((route.get("profile") or {}).get("profile_id") or "")).casefold()
    if channel in {"free", "free_mode", "command", "smeta_mode", "list"}:
        return False
    if profile in {"free_llm", "estimate_harness", "list"}:
        return False
    refs = turn.get("evidence_refs") or []
    return any(bool(ref.get("is_evidence")) for ref in refs if isinstance(ref, dict))


def initial_assertion_status(entry: MemoryEntry, refs: list[EvidenceRef]) -> ValidationStatus:
    """Ordinary model/RAG text never self-confirms."""
    if entry.kind != EntryKind.ASSERTION:
        return ValidationStatus.CANDIDATE
    exact_kind = str((entry.provenance or {}).get("confirmation_kind") or "")
    has_real_ref = any(ref.is_evidence and ref.doc_id and ref.locator for ref in refs)
    if exact_kind == "typed_exact_locator" and has_real_ref:
        return ValidationStatus.CONFIRMED
    if exact_kind == "computed" and has_real_ref:
        computed = (entry.provenance or {}).get("computed") or {}
        if computed.get("formula") and computed.get("inputs"):
            return ValidationStatus.CONFIRMED
    return ValidationStatus.CANDIDATE
