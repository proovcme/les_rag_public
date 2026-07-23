"""Honest operator status for general and smeta RRF indexes."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models

from backend.rag_config import index_contract_status, rag_collection_name, rag_meta_db_path


_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SEC = 10.0


def _scope(dataset_id: str | None) -> models.Filter | None:
    if not dataset_id:
        return None
    return models.Filter(
        must=[models.FieldCondition(key="dataset_id", match=models.MatchValue(value=dataset_id))]
    )


def _count(
    client: QdrantClient,
    collection: str,
    *,
    dataset_id: str | None = None,
    vector: str = "",
    fingerprint: str = "",
) -> int:
    conditions: list[Any] = list((_scope(dataset_id).must if _scope(dataset_id) else []))
    if vector:
        conditions.append(models.HasVectorCondition(has_vector=vector))
    if fingerprint:
        conditions.append(
            models.FieldCondition(
                key="embedding_fingerprint",
                match=models.MatchValue(value=fingerprint),
            )
        )
    count_filter = models.Filter(must=conditions) if conditions else None
    return int(client.count(collection, count_filter=count_filter, exact=True).count)


def _aliases(client: QdrantClient) -> dict[str, str]:
    try:
        return {item.alias_name: item.collection_name for item in client.get_aliases().aliases}
    except Exception:
        return {}


def _source_chunks(dataset_id: str | None) -> int | None:
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            if dataset_id:
                row = conn.execute(
                    "SELECT coalesce(sum(chunk_count), 0) FROM documents "
                    "WHERE dataset_id=? AND status='INDEXED'",
                    (dataset_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT coalesce(sum(chunk_count), 0) FROM documents WHERE status='INDEXED'"
                ).fetchone()
        return int((row or [0])[0] or 0)
    except (OSError, sqlite3.Error):
        return None


def _lexical_status(collection: str, dataset_id: str | None = None) -> dict[str, Any]:
    try:
        from proxy.services.lexical_index_service import LexicalIndex

        index = LexicalIndex(rag_meta_db_path())
        status = index.status(collection)
        if dataset_id:
            with index.connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM lexical_chunks WHERE collection=? AND dataset_id=?",
                    (collection, dataset_id),
                ).fetchone()
            status["scope_chunks"] = int((row or {"n": 0})["n"] or 0)
        return status
    except Exception:
        return {"collection": collection, "ready": False, "stale": True, "chunks": 0}


def _general_status(
    client: QdrantClient,
    aliases: dict[str, str],
    *,
    dataset_id: str | None,
) -> dict[str, Any]:
    alias = "les_rag"
    configured = rag_collection_name()
    physical = aliases.get(alias) or configured
    activated = bool(
        (aliases.get(alias) == physical and aliases.get(alias))
        or (not aliases.get(alias) and configured == physical)
    )
    contract = index_contract_status()
    actual_contract = contract.get("actual") if isinstance(contract.get("actual"), dict) else {}
    fingerprint = str(actual_contract.get("point_embedding_fingerprint") or "")
    result: dict[str, Any] = {
        "alias": alias,
        "configured_collection": configured,
        "physical_generation": physical,
        "activated": activated,
        "contract_status": str(contract.get("status") or "missing"),
        "contract_compatible": bool(contract.get("compatible")),
        "fusion": "rrf",
        "dataset_id": dataset_id or "",
    }
    if not physical or not client.collection_exists(physical):
        result.update({"state": "missing", "ready": False, "reason": "collection_missing"})
        return result
    total = _count(client, physical, dataset_id=dataset_id)
    dense = _count(client, physical, dataset_id=dataset_id, vector="dense")
    sparse = _count(client, physical, dataset_id=dataset_id, vector="bm25_sparse")
    compatible = (
        _count(client, physical, dataset_id=dataset_id, fingerprint=fingerprint)
        if fingerprint
        else 0
    )
    generation_datasets = (
        actual_contract.get("generation_datasets")
        if isinstance(actual_contract.get("generation_datasets"), dict)
        else {}
    )
    if dataset_id and dataset_id in generation_datasets:
        expected = int(generation_datasets[dataset_id])
    elif not dataset_id and actual_contract.get("generation_points") is not None:
        expected = int(actual_contract.get("generation_points") or 0)
    else:
        # Legacy fallback is diagnostic only. A clean generation may split one
        # source point into several budget-safe child points, so the activated
        # alias contract is the authoritative destination count.
        expected = _source_chunks(dataset_id)
    channel_complete = bool(total > 0 and total == dense == sparse)
    fingerprint_complete = bool(fingerprint and compatible == total)
    source_complete = expected is not None and expected > 0 and expected == total
    lexical = _lexical_status(alias if activated else physical, dataset_id)
    if dataset_id:
        lexical_complete = bool(
            lexical.get("ready")
            and lexical.get("stale") is False
            and int(lexical.get("scope_chunks") or 0) == total
        )
    else:
        lexical_point_count = int(lexical.get("point_count") or 0)
        lexical_complete = bool(
            lexical.get("ready")
            and lexical.get("stale") is False
            and int(lexical.get("chunks") or 0) == total
            # Incremental indexing predates lexical_index_meta on some clean
            # Windows states. Exact FTS/Qdrant/MetaDB equality is sufficient;
            # a missing advisory marker must not invent a degraded runtime.
            and lexical_point_count in {0, total}
            and int(lexical.get("indexed_count") or 0) == total
        )
    ready = bool(
        contract.get("compatible")
        and channel_complete
        and fingerprint_complete
        and source_complete
        and lexical_complete
    )
    if ready and activated:
        state, reason = "ready", ""
    elif ready:
        state, reason = "awaiting_activation", "alias_not_activated"
    else:
        state = "degraded" if total else "blocked"
        if not contract.get("compatible"):
            reason = "contract_incompatible"
        elif not channel_complete or not fingerprint_complete:
            reason = "dense_sparse_or_fingerprint_incomplete"
        elif not source_complete:
            reason = "generation_coverage_incomplete"
        else:
            reason = "lexical_projection_incomplete"
    result.update(
        {
            "state": state,
            "reason": reason,
            "ready": ready,
            "points": total,
            "dense_points": dense,
            "sparse_points": sparse,
            "compatible_fingerprint_points": compatible,
            "expected_source_points": expected,
            "expected_generation_points": expected,
            "lexical": {**lexical, "ready": lexical_complete},
            "rrf_ready": ready,
        }
    )
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _smeta_status(client: QdrantClient, aliases: dict[str, str]) -> dict[str, Any]:
    from proxy.smeta_core.base_registry import active_base
    from proxy.smeta_core.integrity import normative_base_integrity

    alias = "les_smeta_norm_cards"
    base = active_base()
    base_path = Path(str(base.get("base_path") or ""))
    manifest_path = base_path.with_name("les_smeta_norm_rag_manifest.json")
    manifest = _read_json(manifest_path)
    build = _read_json(base_path.with_name("les_smeta_norm_rag_build.json"))
    quality = _read_json(base_path.with_name("les_smeta_norm_rag_quality.json"))
    configured = str(base.get("rag_collection") or alias)
    manifest_collection = str(manifest.get("physical_generation") or manifest.get("collection") or "")
    build_collection = str(build.get("collection") or "") if build.get("status") == "building" else ""
    if not build_collection and not aliases.get(alias):
        try:
            candidates = [
                item.name
                for item in client.get_collections().collections
                if item.name.startswith(alias + "_")
            ]
            if candidates:
                latest = sorted(
                    candidates,
                    key=lambda value: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", value)],
                )[-1]
                if latest != manifest_collection:
                    build_collection = latest
        except Exception:
            pass
    physical = aliases.get(alias) or build_collection or manifest_collection or configured
    activated = aliases.get(alias) == physical and bool(aliases.get(alias))
    expected = int(build.get("expected_points") or manifest.get("expected_points") or manifest.get("points") or 0)
    active_identity = build if build_collection else manifest
    fingerprint = str(active_identity.get("point_embedding_fingerprint") or "")
    result: dict[str, Any] = {
        "alias": alias,
        "configured_collection": configured,
        "physical_generation": physical,
        "activated": activated,
        "manifest_status": str(active_identity.get("status") or "missing"),
        "index_mode": str(active_identity.get("index_mode") or ("building_dense" if build_collection else "")),
        "embedding_backend": str(active_identity.get("embedding_backend") or ""),
        "embedding_model": str(active_identity.get("embedding_model") or ""),
        "expected_points": expected,
        "fusion": "rrf",
        "quality_probe": {
            "status": str(quality.get("status") or "not_run"),
            "queries": int(quality.get("queries") or 0),
            "both_channels_in_rrf_top5": int(quality.get("both_channels_in_rrf_top5") or 0),
            "all_cards_rehydrated": bool(quality.get("all_cards_rehydrated")),
            "generated_at": quality.get("generated_at"),
            "collection": str(quality.get("collection") or ""),
        },
    }
    integrity = normative_base_integrity()
    mechanical_ready = bool(
        base_path.is_file()
        and (integrity.get("trusted_for_pricing") or integrity.get("trusted_for_navigation"))
    )
    result["mechanical_base"] = {
        "state": "ready" if mechanical_ready else str(integrity.get("status") or "missing"),
        "ready": mechanical_ready,
        "trusted_for_pricing": bool(integrity.get("trusted_for_pricing")),
        "trusted_for_navigation": bool(integrity.get("trusted_for_navigation")),
        "base_path": str(base_path),
    }
    result["search_index"] = {
        "state": "unknown",
        "ready": False,
        "optional": True,
    }
    if not physical or not client.collection_exists(physical):
        result["search_index"].update({"state": "missing", "reason": "collection_missing"})
        result.update(
            {
                "state": "ready" if mechanical_ready else "missing",
                "ready": mechanical_ready,
                "reason": "" if mechanical_ready else "mechanical_base_missing_or_untrusted",
                "rrf_ready": False,
                "progress_pct": 0.0,
            }
        )
        return result
    total = _count(client, physical)
    dense = _count(client, physical, vector="dense")
    sparse = _count(client, physical, vector="bm25_sparse")
    compatible = _count(client, physical, fingerprint=fingerprint) if fingerprint else 0
    complete = bool(
        expected > 0
        and total == dense == sparse == compatible == expected
        and active_identity.get("status") in {"passed", "completed"}
        and active_identity.get("index_mode", "hybrid") == "hybrid"
    )
    if complete and activated:
        state, reason = "ready", ""
    elif complete:
        state, reason = "awaiting_activation", "alias_not_activated"
    elif build_collection or (expected > 0 and total < expected):
        state, reason = "building", "index_build_in_progress"
    else:
        state, reason = "blocked", "manifest_or_vector_coverage_incomplete"
    result.update(
        {
            "state": state,
            "reason": reason,
            "ready": complete,
            "rrf_ready": complete,
            "points": total,
            "dense_points": dense,
            "sparse_points": sparse,
            "compatible_fingerprint_points": compatible,
            "progress_pct": round((100.0 * total / expected), 2) if expected else 0.0,
        }
    )
    result["search_index"].update(
        {
            "state": state,
            "ready": complete,
            "reason": reason,
            "points": total,
            "expected_points": expected,
        }
    )
    # The typed SQLite reader is the operational smeta base. The vector card
    # index is an optional model-navigation accelerator and must not make a
    # verified mechanical base look absent.
    if mechanical_ready:
        result["state"] = "ready"
        result["ready"] = True
        result["reason"] = ""
    return result


def rag_readiness(*, dataset_id: str | None = None, force: bool = False) -> dict[str, Any]:
    """Return cached, read-only readiness without pretending one channel is RRF."""
    key = str(dataset_id or "__all__")
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and not force and now - cached[0] < _CACHE_TTL_SEC:
            return dict(cached[1])
    client = QdrantClient(
        url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        timeout=60.0,
        check_compatibility=False,
    )
    try:
        aliases = _aliases(client)
        payload = {
            "schema": "les.rag.readiness.v1",
            "status": "ok",
            "generated_at": time.time(),
            "general": _general_status(client, aliases, dataset_id=dataset_id),
            "smeta": _smeta_status(client, aliases),
        }
    except Exception as exc:
        payload = {
            "schema": "les.rag.readiness.v1",
            "status": "error",
            "generated_at": time.time(),
            "error": type(exc).__name__,
            "general": {"state": "unknown", "ready": False, "rrf_ready": False},
            "smeta": {"state": "unknown", "ready": False, "rrf_ready": False},
        }
    finally:
        client.close()
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
    return dict(payload)
