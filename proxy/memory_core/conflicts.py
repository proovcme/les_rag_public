"""Conflict registration without confidence-based winners."""

from __future__ import annotations

from proxy.memory_core.contracts import EntryKind, MemoryEntry, ValidationStatus
from proxy.memory_core.store import MemoryStore


def register_fact_conflicts(store: MemoryStore, entry: MemoryEntry) -> str | None:
    if entry.kind != EntryKind.ASSERTION:
        return None
    existing = store.get_entries_by_project(entry.project_id, kind=EntryKind.ASSERTION, limit=500)
    incompatible = [
        item for item in existing
        if item.entry_id != entry.entry_id
        and item.subject == entry.subject
        and item.predicate == entry.predicate
        and item.value != entry.value
        and item.validation_status not in {ValidationStatus.REJECTED, ValidationStatus.DISPUTED}
    ]
    if not incompatible:
        return None
    return store.record_conflict(
        entry.project_id, entry.subject, entry.predicate,
        [entry.entry_id, *(item.entry_id for item in incompatible)],
    )
