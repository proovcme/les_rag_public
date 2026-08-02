"""Active project-scoped adapter between LES application services and Memory Core."""

from __future__ import annotations

import re
from typing import Any

from proxy.memory_core.config import MemoryConfig
from proxy.memory_core.contracts import (
    MemoryMode,
    RouteEvidenceCacheDTO,
    SmetaRecallMode,
    SmetaSuccessTrace,
    SmetaTraceTrust,
    ValidationStatus,
)
from proxy.memory_core.store import MemoryStore
from proxy.memory_core.validation import grounded_turn_eligible
from proxy.services.memory_port import MemoryPort


_WORD = re.compile(r"[а-яёa-z0-9]{3,}", re.IGNORECASE)


def normalized_knowledge_edition(value: Any) -> str:
    text = " ".join(str(value or "").strip().upper().split())
    return text.replace("ФСНБ", "FSNB")


def normalized_work_signature(features: dict[str, Any]) -> str:
    title = " ".join(_WORD.findall(str(features.get("title") or "").casefold()))
    unit = " ".join(str(features.get("unit") or "").casefold().split())
    function = " ".join(_WORD.findall(str(features.get("function") or features.get("note") or "").casefold()))
    return "|".join((title, unit, function))


def _tokens(value: str) -> set[str]:
    return set(_WORD.findall(value.casefold()))


class ActiveMemoryPort(MemoryPort):
    def __init__(self, store: MemoryStore, config: MemoryConfig):
        self.store = store
        self.config = config

    def get_mode(self) -> MemoryMode:
        return self.config.mode

    def get_smeta_recall_mode(self) -> SmetaRecallMode:
        return self.config.smeta_recall

    def enqueue_rag_turn(self, project_id: int, turn_data: dict[str, Any]) -> bool:
        if self.config.mode == MemoryMode.OFF:
            return False
        if not grounded_turn_eligible(project_id=project_id, turn=turn_data):
            return False
        self.store.enqueue(project_id, "grounded_rag_turn", turn_data)
        return True

    def recall_project_advisory(self, project_id: int, question: str) -> str:
        if self.config.mode != MemoryMode.ON:
            return ""
        query = _tokens(question)
        if not query:
            return ""
        entries = self.store.get_entries_by_project(
            project_id,
            statuses=(ValidationStatus.CONFIRMED, ValidationStatus.CANDIDATE),
            limit=200,
        )
        ranked: list[tuple[float, Any]] = []
        for entry in entries:
            haystack = f"{entry.subject} {entry.predicate} {entry.value}"
            words = _tokens(haystack)
            score = len(query & words) / max(1, len(query))
            if score >= 0.34:
                ranked.append((score, entry))
        ranked.sort(key=lambda item: (-item[0], item[1].created_at))
        if not ranked:
            return ""
        lines = [
            "Память проекта (advisory, НЕ evidence текущего запроса; норматив и факты перепроверь по источникам):"
        ]
        for _, entry in ranked[:5]:
            status = "подтверждено" if entry.validation_status == ValidationStatus.CONFIRMED else "кандидат"
            lines.append(f"- [{status}] {entry.subject} — {entry.predicate}: {entry.value}")
        return "\n".join(lines)

    def record_smeta_trace(self, trace: SmetaSuccessTrace) -> bool:
        if self.config.mode == MemoryMode.OFF or not self.config.smeta_capture:
            return False
        return self.store.save_smeta_trace(trace)

    def confirm_smeta_revision(
        self, source_revision_id: str, locked_revision_id: str, review_note: str
    ) -> int:
        if self.config.mode == MemoryMode.OFF or not self.config.smeta_capture:
            return 0
        return self.store.confirm_smeta_revision(
            source_revision_id,
            locked_revision_id=locked_revision_id,
            review_note=review_note,
        )

    def recall_smeta_advisory(self, project_id: int, work_features: dict[str, Any]) -> list[dict[str, Any]]:
        if self.config.mode != MemoryMode.ON or self.config.smeta_recall == SmetaRecallMode.OFF:
            return []
        query = _tokens(normalized_work_signature(work_features))
        ranked: list[tuple[float, SmetaSuccessTrace]] = []
        for trace in self.store.get_smeta_traces(project_id, limit=200):
            if trace.trust_level not in {
                SmetaTraceTrust.ACCEPTED_PROJECT,
                SmetaTraceTrust.VERIFIED_PATTERN,
            }:
                continue
            words = _tokens(normalized_work_signature(trace.normalized_work_features))
            score = len(query & words) / max(1, len(query))
            if score > 0:
                ranked.append((score, trace))
        ranked.sort(key=lambda item: -item[0])
        return [
            {
                "trace_id": trace.trace_id,
                "similarity": round(score, 3),
                "finality": trace.finality,
                "trust_level": trace.trust_level.value,
                "work_features": trace.normalized_work_features,
                "selected_norm_refs": list(trace.selected_norm_refs),
                "knowledge_edition": trace.knowledge_edition_identity,
                "context_role": "experience_not_current_evidence",
                "is_evidence": False,
            }
            for score, trace in ranked[:8]
        ]

    def recall_route_cache(self, project_id: int, work_features: dict[str, Any]) -> list[RouteEvidenceCacheDTO]:
        if self.config.mode != MemoryMode.ON or self.config.smeta_recall != SmetaRecallMode.ROUTE_REUSE:
            return []
        signature = normalized_work_signature(work_features)
        if not signature.strip("|"):
            return []
        current_edition = str(work_features.get("knowledge_edition") or "").strip()
        matches: list[RouteEvidenceCacheDTO] = []
        for trace in self.store.get_smeta_traces(project_id, limit=200):
            if trace.trust_level not in {
                SmetaTraceTrust.ACCEPTED_PROJECT,
                SmetaTraceTrust.VERIFIED_PATTERN,
            }:
                continue
            if normalized_work_signature(trace.normalized_work_features) != signature:
                continue
            if not current_edition or trace.knowledge_edition_identity != current_edition:
                continue
            for route in trace.typed_catalog_routes:
                if route.work_signature != signature or route.knowledge_edition != current_edition:
                    continue
                matches.append(route)
            if matches:
                self.store.mark_smeta_used(trace.trace_id)
                break
        return matches[:8]
