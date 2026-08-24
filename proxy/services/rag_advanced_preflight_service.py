"""Read-only RAPTOR/ColBERT capacity preflight without loading ML models."""

from __future__ import annotations

import importlib.util
import math
from typing import Any

from backend.raptor_qdrant_store import target_collection_name
from proxy.services.rag_advanced_policy_service import load_policy, load_status
from proxy.services.raptor_publication_service import checkpoint_path_for


PREFLIGHT_SCHEMA = "les.rag.advanced-preflight.v1"
COLBERT_DIMENSION = 1024
FLOAT16_BYTES = 2
QDRANT_MULTIVECTOR_OVERHEAD_RATIO = 1.25
BGE_M3_EXPECTED_CACHE_BYTES = 2_400_000_000


def _bge_m3_cache() -> dict[str, Any]:
    """Inspect Hugging Face cache metadata; never import or instantiate a model."""
    try:
        from huggingface_hub import scan_cache_dir

        cache = scan_cache_dir()
        repositories = [
            repo for repo in cache.repos
            if str(getattr(repo, "repo_id", "")).casefold() == "baai/bge-m3"
        ]
        size = sum(int(getattr(repo, "size_on_disk", 0) or 0) for repo in repositories)
        return {
            "status": "ready" if size > 0 else "missing",
            "bytes": size,
            "path": str(getattr(cache, "cache_dir", "") or ""),
            "error_code": "" if size > 0 else "COLBERT_MODEL_CACHE_MISSING",
        }
    except Exception as error:  # cache inspection must never block the runtime
        return {
            "status": "unknown",
            "bytes": 0,
            "path": "",
            "error_code": "COLBERT_CACHE_INSPECTION_FAILED",
            "exception_type": type(error).__name__,
        }


def estimate_colbert_storage(
    *,
    evidence_points: int,
    max_passage_tokens: int,
    dimension: int = COLBERT_DIMENSION,
) -> dict[str, int | float]:
    raw = (
        max(0, int(evidence_points))
        * max(1, int(max_passage_tokens))
        * max(1, int(dimension))
        * FLOAT16_BYTES
    )
    estimated = math.ceil(raw * QDRANT_MULTIVECTOR_OVERHEAD_RATIO)
    return {
        "evidence_points": max(0, int(evidence_points)),
        "max_passage_tokens": max(1, int(max_passage_tokens)),
        "dimension": max(1, int(dimension)),
        "bytes_per_component": FLOAT16_BYTES,
        "raw_bytes": raw,
        "estimated_bytes": estimated,
        "overhead_ratio": QDRANT_MULTIVECTOR_OVERHEAD_RATIO,
    }


def estimate_raptor_nodes(*, evidence_points: int, fanout: int, max_depth: int) -> int:
    remaining = max(0, int(evidence_points))
    nodes = 0
    for _ in range(max(1, int(max_depth))):
        if remaining <= 1:
            break
        remaining = math.ceil(remaining / max(2, int(fanout)))
        nodes += remaining
    return nodes


def advanced_preflight(rag_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a GUI-safe plan. This function performs no model load or write."""
    policy = load_policy()
    qdrant = rag_snapshot.get("qdrant") or {}
    total_points = int(qdrant.get("points") or 0)
    hierarchy_points = int(qdrant.get("hierarchy_navigation_points") or 0)
    evidence_points = int(qdrant.get("evidence_points") or 0)
    if not evidence_points and total_points:
        evidence_points = max(0, total_points - hierarchy_points)
    colbert_policy = policy["colbert"]
    raptor_policy = policy["raptor"]
    dependency_ready = importlib.util.find_spec("FlagEmbedding") is not None
    cache = _bge_m3_cache()
    storage = estimate_colbert_storage(
        evidence_points=evidence_points,
        max_passage_tokens=int(colbert_policy["max_passage_tokens"]),
    )
    model_remaining = max(0, BGE_M3_EXPECTED_CACHE_BYTES - int(cache.get("bytes") or 0))
    raptor_status = load_status()["raptor"]
    source_collection = str(
        qdrant.get("physical_collection") or qdrant.get("collection") or ""
    )
    planned_target = target_collection_name(source_collection)
    blockers = []
    if not dependency_ready:
        blockers.append("COLBERT_DEPENDENCY_MISSING")
    if cache.get("status") != "ready":
        blockers.append(str(cache.get("error_code") or "COLBERT_MODEL_CACHE_MISSING"))
    if not evidence_points:
        blockers.append("COLBERT_EVIDENCE_POINTS_MISSING")
    return {
        "schema": PREFLIGHT_SCHEMA,
        "read_only": True,
        "model_loaded": False,
        "colbert": {
            "status": "blocked" if blockers else "ready",
            "blockers": blockers,
            "dependency": {
                "module": "FlagEmbedding",
                "installed": dependency_ready,
            },
            "model": {
                "id": colbert_policy["model"],
                "cache": cache,
                "expected_cache_bytes": BGE_M3_EXPECTED_CACHE_BYTES,
                "download_remaining_bytes": model_remaining,
            },
            "qdrant_multivector": storage,
            "storage_target": {
                "kind": "qdrant_collection",
                "collection": str(qdrant.get("collection") or ""),
                "free_bytes": None,
                "free_space_status": "unknown",
                "detail": "Qdrant API does not expose free bytes of the Docker volume",
            },
        },
        "raptor": {
            "status": "ready" if evidence_points else "blocked",
            "evidence_points": evidence_points,
            "estimated_navigation_nodes": estimate_raptor_nodes(
                evidence_points=evidence_points,
                fanout=int(raptor_policy.get("fanout") or 8),
                max_depth=int(raptor_policy["max_depth"]),
            ),
            "summary_backend": raptor_policy.get("summary_backend"),
            "summary_model": raptor_policy.get("summary_model"),
            "target_collection": str(
                raptor_status.get("target_collection") or planned_target
            ),
            "checkpoint_path": str(
                raptor_status.get("checkpoint_path")
                or checkpoint_path_for(planned_target)
            ),
        },
    }
