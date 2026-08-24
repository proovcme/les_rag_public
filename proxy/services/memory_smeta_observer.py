"""Read-only observer for already published estimating results."""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from uuid import uuid4

from proxy.memory_core.contracts import (
    RouteEvidenceCacheDTO,
    SmetaSuccessTrace,
    SmetaTraceTrust,
)
from proxy.services.memory_port import get_memory_port
from proxy.services.memory_rag_adapter import (
    normalized_knowledge_edition,
    normalized_work_signature,
)


logger = logging.getLogger(__name__)


def _positive_project(value: Any) -> int | None:
    try:
        project_id = int(value or 0)
    except (TypeError, ValueError):
        return None
    return project_id if project_id > 0 else None


def observe_published_smeta(
    *,
    project_id: Any,
    attachment_id: str,
    source_sha256: str,
    user_request: str,
    workflow: dict[str, Any],
) -> int:
    """Capture compact projections after XLSX/report publication.

    Missing catalog edition deliberately disables route reuse; it is never
    filled with a guessed current edition.
    """
    project = _positive_project(project_id)
    summary = (workflow.get("lsr") or {}).get("summary") or {}
    finality = str(summary.get("result_status") or "")
    if project is None or finality not in {"priced_draft", "priced_final"}:
        return 0
    if not source_sha256 or not workflow.get("xlsx_path") or not workflow.get("report_path"):
        return 0

    revision_id = str((workflow.get("mapping_run") or {}).get("current_mapping_revision_id") or "")
    if not revision_id:
        return 0
    selections = workflow.get("selections") or {}
    raw_routes = workflow.get("route_evidence_cache") or []
    opened_by_work = workflow.get("opened_cards") or {}
    conflicted_work_ids = {
        str(work_id)
        for conflict in (workflow.get("professional_conflicts") or [])
        if isinstance(conflict, dict)
        for work_id in (conflict.get("work_ids") or [])
        if str(work_id).strip()
    }
    captured = 0
    request_signature = hashlib.sha256(user_request.strip().casefold().encode()).hexdigest()
    for work in (workflow.get("intake") or {}).get("work_items") or []:
        if not isinstance(work, dict):
            continue
        work_id = str(work.get("work_id") or "")
        selection = selections.get(work_id) or {}
        # A calculated candidate is useful to the user, but it is not a
        # successful precedent. Memory must never teach it back to the model.
        if str(selection.get("review_status") or "") == "model_batch_candidate":
            continue
        norm_code = str(selection.get("norm_code") or "").strip()
        # Memory is a precedent cache, not a diary of every attempted row.
        # Unbound/MISSING and professionally conflicted decisions must never be
        # promoted later merely because the surrounding mapping was locked.
        if not norm_code or norm_code == "MISSING" or work_id in conflicted_work_ids:
            continue
        features = {
            "title": str(work.get("title") or ""),
            "unit": str(work.get("unit") or ""),
            "function": str(work.get("function") or work.get("note") or ""),
        }
        signature = normalized_work_signature(features)
        routes: list[RouteEvidenceCacheDTO] = []
        editions: set[str] = set()
        opened = opened_by_work.get(work_id) or {}
        opened_values = opened.values() if isinstance(opened, dict) else opened
        opened_editions = {
            str(card.get("edition") or "").strip()
            for card in opened_values
            if isinstance(card, dict) and str(card.get("edition") or "").strip()
        }
        for raw in raw_routes:
            if not isinstance(raw, dict) or str(raw.get("source_work_id") or "") != work_id:
                continue
            edition = normalized_knowledge_edition(raw.get("knowledge_edition"))
            if not edition and len(opened_editions) == 1:
                edition = normalized_knowledge_edition(next(iter(opened_editions)))
            source_revision = str(raw.get("source_revision") or revision_id).strip()
            if not edition or not source_revision:
                continue
            try:
                route = RouteEvidenceCacheDTO(
                    cache_id=str(raw["cache_id"]), family=str(raw["family"]),
                    collection=str(raw["collection"]), section=str(raw["section"]),
                    table_code=str(raw["table_code"]), knowledge_edition=edition,
                    source_revision=source_revision, work_signature=signature,
                )
            except (KeyError, TypeError, ValueError):
                continue
            routes.append(route)
            editions.add(edition)
        # The trace remains useful for advisory recall without a reusable route.
        edition_identity = next(iter(editions)) if len(editions) == 1 else "unresolved"
        trace = SmetaSuccessTrace(
            trace_id=uuid4().hex,
            project_id=project,
            source_kind="attachment",
            source_id=attachment_id,
            revision_id=f"{revision_id}:{work_id}",
            source_sha256=source_sha256,
            finality=finality,
            question_signature=request_signature,
            normalized_work_features=features,
            typed_catalog_routes=tuple(routes),
            selected_norm_refs=(norm_code,) if norm_code else (),
            calculation_evidence_refs=tuple(
                str(ref) for ref in (work.get("source_refs") or []) if str(ref).strip()
            ),
            knowledge_edition_identity=edition_identity,
            trust_level=(
                SmetaTraceTrust.ACCEPTED_PROJECT
                if finality == "priced_final"
                else SmetaTraceTrust.CANDIDATE
            ),
        )
        if get_memory_port().record_smeta_trace(trace):
            captured += 1
    return captured
