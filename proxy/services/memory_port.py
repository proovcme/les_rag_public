"""Replaceable Memory Core port and default Null implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from proxy.memory_core.contracts import MemoryMode, RouteEvidenceCacheDTO, SmetaRecallMode, SmetaSuccessTrace


class MemoryPort(ABC):
    @abstractmethod
    def get_mode(self) -> MemoryMode: ...

    @abstractmethod
    def get_smeta_recall_mode(self) -> SmetaRecallMode: ...

    @abstractmethod
    def enqueue_rag_turn(self, project_id: int, turn_data: dict[str, Any]) -> bool: ...

    @abstractmethod
    def recall_project_advisory(self, project_id: int, question: str) -> str: ...

    @abstractmethod
    def record_smeta_trace(self, trace: SmetaSuccessTrace) -> bool: ...

    @abstractmethod
    def confirm_smeta_revision(
        self, source_revision_id: str, locked_revision_id: str, review_note: str
    ) -> int: ...

    @abstractmethod
    def recall_smeta_advisory(self, project_id: int, work_features: dict[str, Any]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def recall_route_cache(self, project_id: int, work_features: dict[str, Any]) -> list[RouteEvidenceCacheDTO]: ...

    def project_advisory_items(self, project_id: int, *, limit: int = 5) -> list[dict[str, Any]]:
        """Return typed advisory facts; default ports expose no project state."""
        return []


class NullMemoryPort(MemoryPort):
    def get_mode(self) -> MemoryMode:
        return MemoryMode.OFF

    def get_smeta_recall_mode(self) -> SmetaRecallMode:
        return SmetaRecallMode.OFF

    def enqueue_rag_turn(self, project_id: int, turn_data: dict[str, Any]) -> bool:
        return False

    def recall_project_advisory(self, project_id: int, question: str) -> str:
        return ""

    def record_smeta_trace(self, trace: SmetaSuccessTrace) -> bool:
        return False

    def confirm_smeta_revision(
        self, source_revision_id: str, locked_revision_id: str, review_note: str
    ) -> int:
        return 0

    def recall_smeta_advisory(self, project_id: int, work_features: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def recall_route_cache(self, project_id: int, work_features: dict[str, Any]) -> list[RouteEvidenceCacheDTO]:
        return []


_port: MemoryPort = NullMemoryPort()


def configure_memory_port(port: MemoryPort | None) -> None:
    global _port
    _port = port or NullMemoryPort()


def get_memory_port() -> MemoryPort:
    return _port


def project_advisory_items(project_id: int, *, limit: int = 5) -> list[dict[str, Any]]:
    return list(_port.project_advisory_items(project_id, limit=limit))
