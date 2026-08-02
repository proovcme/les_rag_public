"""Read-only application adapter for estimating Memory.

It can seed typed catalog navigation only.  Norm selection, applicability,
resources, coefficients and prices remain owned by the estimating model.
"""

from __future__ import annotations

from typing import Any

from proxy.services.memory_port import get_memory_port


class SmetaMemoryAdapter:
    def advisory(self, project_id: int, work_features: dict[str, Any]) -> list[dict[str, Any]]:
        return get_memory_port().recall_smeta_advisory(project_id, work_features)

    def route_cache(self, project_id: int, work_features: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "cache_id": route.cache_id,
                "family": route.family,
                "collection": route.collection,
                "section": route.section,
                "table_code": route.table_code,
                "source": route.source,
                "decision_owner": route.decision_owner,
                "applicability": route.applicability,
                "memory_source_revision": route.source_revision,
                "memory_knowledge_edition": route.knowledge_edition,
                "memory_context_role": "navigation_not_current_evidence",
            }
            for route in get_memory_port().recall_route_cache(project_id, work_features)
        ]
