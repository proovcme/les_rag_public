"""Compatibility facade for typed estimating traces in MemoryStore."""

from __future__ import annotations

from proxy.memory_core.contracts import SmetaSuccessTrace
from proxy.memory_core.store import MemoryStore


class SmetaTraceStore:
    def __init__(self, store: MemoryStore):
        self.store = store

    def save_trace(self, trace: SmetaSuccessTrace) -> bool:
        return self.store.save_smeta_trace(trace)

    def get_traces_by_project(self, project_id: int | str, limit: int = 200) -> list[SmetaSuccessTrace]:
        return self.store.get_smeta_traces(project_id, limit=limit)
