"""Truthful operator status for the production RAG retrieval stages."""

from __future__ import annotations

import os
import sys
from typing import Any

from proxy.services.rag_advanced_policy_service import load_policy, load_status
from proxy.services.rag_readiness_service import user_readiness_dimensions


PIPELINE_SCHEMA = "les.rag.retrieval-pipeline-status.v1"


def _stage(status: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "detail": detail, **extra}


def build_retrieval_pipeline_status(rag_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Describe capabilities without claiming that optional stages ran.

    Request-specific execution remains in the retrieval trace.  This snapshot
    answers the operator's separate question: which stages are ready to run in
    the active runtime and index generation?
    """
    contract_status = rag_snapshot.get("index_contract") or {}
    contract = contract_status.get("actual") or {}
    qdrant = rag_snapshot.get("qdrant") or {}

    fingerprint_match = qdrant.get("point_fingerprint_match")
    if fingerprint_match is None:
        # Older installed runtimes did not expose the exact fingerprint count.
        fingerprint_match = bool(contract_status.get("compatible"))
    generation_points = int(contract.get("generation_points") or 0)
    physical_points = int(qdrant.get("points") or 0)
    compatible_points = int(qdrant.get("compatible_fingerprint_points") or 0)
    generation_counts_match = bool(
        generation_points
        and physical_points == generation_points
        and compatible_points == physical_points
    )
    leaf_counts_match = qdrant.get("points_match_sqlite_chunks") is not False
    all_points_compatible = bool(
        physical_points
        and compatible_points == physical_points
        and fingerprint_match
    )
    index_usable = bool(
        qdrant.get("ok")
        and contract_status.get("compatible")
        and all_points_compatible
    )
    index_exact = bool(index_usable and (generation_counts_match or leaf_counts_match))
    totals = rag_snapshot.get("totals") or {}
    indexing_active = int(totals.get("pending_files") or 0) > 0
    index_stage_status = "ready" if index_exact else (
        "indexing" if index_usable and indexing_active else "degraded"
    )
    named_hybrid = bool(
        index_usable
        and contract.get("qdrant_schema") == "named"
        and contract.get("dense_vector_name")
        and contract.get("sparse_vector_name")
    )
    hierarchy_ready = bool(
        named_hybrid
        and contract.get("hierarchy_schema") == "les.rag.hierarchy.v1"
        and contract.get("navigation_evidence_policy") == "navigation_not_evidence"
    )

    advanced_policy = load_policy()
    advanced_status = load_status()
    raptor_mode = str(advanced_policy["raptor"]["mode"])
    raptor_runtime = advanced_status["raptor"]
    raptor_schema = str(raptor_runtime.get("schema") or "")
    raptor_points = int(raptor_runtime.get("published_nodes") or 0)
    raptor_readiness = str(raptor_runtime.get("readiness") or "not_built")
    active_physical = str(qdrant.get("physical_collection") or qdrant.get("collection") or "")
    raptor_source_match = bool(
        active_physical
        and str(raptor_runtime.get("source_collection") or "") == active_physical
    )
    raptor_ready = bool(
        hierarchy_ready
        and raptor_readiness == "ready"
        and raptor_points > 0
        and raptor_source_match
    )
    colbert_mode = str(advanced_policy["colbert"]["mode"])
    colbert_enabled = colbert_mode != "off"
    colbert_model = str(advanced_policy["colbert"]["model"])
    colbert_verified = bool(rag_snapshot.get("colbert_verified"))

    reranker_backend = os.getenv("RERANKER_BACKEND", "").strip().lower()
    if not reranker_backend:
        reranker_backend = "sentence_transformers" if sys.platform.startswith("win") else "cross_encoder"
    reranker_model = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3").strip()

    stages = {
        "index": _stage(
            index_stage_status,
            (
                "Контракт, fingerprint и generation counts подтверждены"
                if index_exact
                else (
                    f"Индексация продолжается · ожидают: {int(totals.get('pending_files') or 0)}"
                    if index_stage_status == "indexing"
                    else "Контракт, fingerprint или counts не подтверждены"
                )
            ),
        ),
        "native_rrf": _stage(
            "ready" if named_hybrid else "blocked",
            "dense + BM25 sparse → native RRF" if named_hybrid else "Нет подтверждённой пары dense + sparse",
        ),
        "hierarchy": _stage(
            "ready" if hierarchy_ready else "blocked",
            "Глобальный поиск + маршрутизация к потомкам" if hierarchy_ready else "Иерархический контракт не подтверждён",
        ),
        "raptor": _stage(
            "ready" if raptor_ready and raptor_mode != "off" else (
                "indexing" if raptor_readiness in {"queued", "building", "verifying"}
                else "blocked" if raptor_readiness == "blocked"
                else "configured" if raptor_mode != "off" else "disabled"
            ),
            (
                f"{raptor_points} summary-узлов в отдельной RAPTOR-генерации"
                if raptor_ready and raptor_mode != "off"
                else ("Summary-дерево ещё не опубликовано в активной генерации" if raptor_mode != "off" else "RAPTOR выключен в GUI")
            ),
            schema=raptor_schema,
            points=raptor_points,
            progress=float(raptor_runtime.get("progress") or 0.0),
            error_code=str(raptor_runtime.get("last_error_code") or ""),
            circuit_state=str(raptor_runtime.get("circuit_state") or "closed"),
            source_match=raptor_source_match,
        ),
        "colbert": _stage(
            "ready" if colbert_enabled and colbert_verified else (
                "configured" if colbert_enabled else "disabled"
            ),
            (
                f"Late interaction · {colbert_model}"
                if colbert_enabled
                else "Late interaction выключен в GUI"
            ),
            model=colbert_model,
            points=int(qdrant.get("colbert_points") or 0),
            circuit_state=str((advanced_status.get("colbert") or {}).get("circuit_state") or "closed"),
        ),
        "reranker": _stage(
            "configured",
            f"{reranker_backend} · {reranker_model}",
            model=reranker_model,
        ),
        "parent_context": _stage(
            "configured",
            "Parent-card hydration и context expansion после rerank",
        ),
        "exact_evidence": _stage(
            "configured",
            "Только leaf-evidence допускается в цитаты",
        ),
    }
    required_ready = all(
        stages[key]["status"] == "ready"
        for key in ("native_rrf", "hierarchy")
    )
    pipeline_status = "degraded"
    if required_ready and index_stage_status == "ready":
        pipeline_status = "ready"
    elif required_ready and index_stage_status == "indexing":
        pipeline_status = "indexing"
    dimensions = user_readiness_dimensions(
        backend_available=bool(qdrant.get("ok")),
        contract_complete=bool(named_hybrid and hierarchy_ready),
        optional_stages={
            "raptor": {
                "status": stages["raptor"]["status"],
                "reason": str(raptor_runtime.get("last_bypass_reason") or ""),
            },
            "colbert": {
                "status": stages["colbert"]["status"],
                "reason": str((advanced_status.get("colbert") or {}).get("last_bypass_reason") or ""),
            },
        },
        query_quality=(
            rag_snapshot.get("query_quality")
            if isinstance(rag_snapshot.get("query_quality"), dict)
            else {"status": "not_measured", "detail": "per-query only"}
        ),
    )
    return {
        "schema": PIPELINE_SCHEMA,
        "status": pipeline_status,
        "overall": dimensions["overall"],
        "blocking_dimension": dimensions["blocking_dimension"],
        "dimensions": {
            key: value
            for key, value in dimensions.items()
            if key not in {"overall", "blocking_dimension"}
        },
        "stages": stages,
        "execution_note": "Фактическое прохождение стадий показывается в trace конкретного ответа.",
    }
