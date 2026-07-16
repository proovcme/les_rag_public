"""Universal model-visible norm browser over the typed machine base.

It retrieves exact/full-code or lexical cards. It never returns a selected norm and
contains no object-specific boosts, family guesses or applicability decisions.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
from time import perf_counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import QdrantClient, models

from backend.inference.bm25_sparse import SPARSE_VECTOR_NAME, encode_bm25
from backend.qdrant_adapter import EmbedClient
from backend.rag_config import prepare_query_for_embedding

from proxy.services.smeta_norm_store import SmetaNormRow, get_smeta_norm_store
from proxy.smeta_core.integrity import normative_base_integrity


_FULL_CODE_RE = re.compile(
    r"((?:ГЭСНМР|ГЭСНМ|ГЭСНП|ГЭСНР|ГЭСН|ФЕРМР|ФЕРМ|ФЕРП|ФЕРР|ФЕР|ТЕРМР|ТЕРМ|ТЕРП|ТЕРР|ТЕР)"
    r"\s*:?\s*(\d{2}-\d{2}-\d{3}-\d{2}))",
    re.IGNORECASE,
)

_RUSSIAN_SUFFIXES = tuple(sorted({
    "иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "ение", "ания",
    "ения", "ование", "ировать", "ировка", "ический", "ическая", "ические",
    "ость", "ости", "овка", "евка", "ками", "ями", "ами", "ами", "ого",
    "ая", "яя", "ое", "ее", "ые", "ие", "ый", "ий", "ой", "ов", "ев",
    "ам", "ям", "ах", "ях", "ка", "ки", "ку", "я", "а", "ы", "и", "у",
}, key=len, reverse=True))


def _base_path() -> Path:
    from proxy.smeta_core.base_registry import active_base

    return Path(active_base()["base_path"])


def _connect_base_readonly(base_path: Path) -> sqlite3.Connection:
    """Open the immutable normative base without asking SQLite for write access."""
    from proxy.smeta_core.base_registry import runtime_data_path

    resolved = runtime_data_path(base_path)
    try:
        return sqlite3.connect(
            f"{resolved.as_uri()}?mode=ro&immutable=1",
            uri=True,
            timeout=30.0,
        )
    except sqlite3.OperationalError as error:
        raise sqlite3.OperationalError(
            f"unable to open normative database {resolved}: {error}"
        ) from error


def _norm_key(value: str) -> str:
    match = _FULL_CODE_RE.search(str(value or ""))
    if not match:
        return ""
    full = re.sub(r"\s+", "", match.group(1)).replace(":", "")
    bare = match.group(2)
    family = full[: -len(bare)]
    family = "ГЭСН" + family[4:].lower() if family.upper().startswith("ГЭСН") else family
    family = "ФЕР" + family[3:].lower() if family.upper().startswith("ФЕР") else family
    family = "ТЕР" + family[3:].lower() if family.upper().startswith("ТЕР") else family
    return f"{family}:{bare}"


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _card(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    resources = conn.execute(
        """
        SELECT kind, count(*) AS count
        FROM resources WHERE parent_norm_id = ? GROUP BY kind ORDER BY kind
        """,
        (row["norm_id"],),
    ).fetchall()
    preview = conn.execute(
        """
        SELECT kind, resource_code, resource_name, resource_unit
        FROM resources
        WHERE parent_norm_id = ? AND trim(coalesce(resource_name, '')) <> ''
        ORDER BY CASE kind WHEN 'machine' THEN 0 WHEN 'material' THEN 1 ELSE 2 END,
                 resource_code, resource_name
        LIMIT 16
        """,
        (row["norm_id"],),
    ).fetchall()
    return {
        "norm_id": row["norm_id"],
        "norm_code": row["display_code"],
        "norm_key": row["norm_key"],
        "edition": row["edition"],
        "base_type": row["base_type"],
        "title": row["norm_name"],
        "measure_unit": row["norm_unit"],
        "work_steps": _json_list(row["work_steps"]),
        "resource_count": int(row["resource_count"]),
        "resource_kinds": {str(item["kind"]): int(item["count"]) for item in resources},
        # Names are diagnostic evidence for technology mismatch (cranes, welding,
        # nuclear-only machinery, etc.), not an independent reason to bind a norm.
        "resource_preview": [
            {
                "kind": str(item["kind"] or ""),
                "code": str(item["resource_code"] or ""),
                "name": str(item["resource_name"] or ""),
                "unit": str(item["resource_unit"] or ""),
            }
            for item in preview
        ],
        "source_ref": f"{row['source_doc']}#guid={row['source_guid']}",
    }


def _cards_by_norm_keys(norm_keys: list[str], *, base_path: Path) -> list[dict[str, Any]]:
    ordered = [str(key) for key in norm_keys if str(key)]
    if not ordered or not base_path.exists():
        return []
    conn = _connect_base_readonly(base_path)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in ordered)
        rows = conn.execute(
            f"SELECT * FROM norms WHERE norm_key IN ({placeholders})",
            ordered,
        ).fetchall()
        by_key = {str(row["norm_key"]): _card(conn, row) for row in rows}
        return [by_key[key] for key in ordered if key in by_key]
    finally:
        conn.close()


def _rag_collection() -> str:
    from proxy.smeta_core.base_registry import active_base

    return os.getenv("LES_SMETA_NORM_RAG_COLLECTION", "").strip() or str(active_base().get("rag_collection") or "")


def _rag_embedding_model() -> str:
    from proxy.smeta_core.base_registry import active_base

    return (
        os.getenv("LES_SMETA_NORM_EMBED_MODEL", "").strip()
        or str(active_base().get("rag_embedding_model") or "qwen3-embedding-0.6b")
    )


@lru_cache(maxsize=1)
def _retrieval_vocabulary() -> tuple[dict[str, Any], ...]:
    path = Path(__file__).resolve().parents[2] / "config" / "domain" / "smeta_retrieval_vocabulary.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    rules = payload.get("rules") if isinstance(payload, dict) else []
    return tuple(rule for rule in (rules or []) if isinstance(rule, dict))


def _query_variants(query: str) -> list[str]:
    """Expose documented user-language → normative-language search variants."""
    original = " ".join(str(query or "").split()).strip()
    if not original:
        return []
    low = original.casefold().replace("ё", "е")
    expansions_found: list[str] = []
    for rule in _retrieval_vocabulary():
        triggers = [str(value or "").casefold().replace("ё", "е") for value in rule.get("match_any") or []]
        expansions = [rule.get("query")] if rule.get("query") else list(rule.get("queries") or [])
        if any(trigger and trigger in low for trigger in triggers):
            expansions_found.extend(
                expansion
                for value in expansions
                if (expansion := " ".join(str(value or "").split()).strip())
            )
    # Normative-language variants lead retrieval; the untouched user query is
    # retained as the final recall channel and remains visible in trace.
    return list(dict.fromkeys([*expansions_found, original]))


@lru_cache(maxsize=8)
def _sha256_for_stat(path: str, mtime_ns: int, size: int) -> str:
    del mtime_ns, size
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rag_manifest_status(*, base_path: Path, collection: str, embedding_model: str) -> tuple[bool, str]:
    """Fail closed when a sibling vector index is stale or built by another embedder."""
    manifest_path = base_path.with_name("les_smeta_norm_rag_manifest.json")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "manifest_missing_or_invalid"
    if str(payload.get("status") or "") != "passed":
        return False, "manifest_not_passed"
    if str(payload.get("collection") or "") != collection:
        return False, "collection_mismatch"
    if str(payload.get("embedding_model") or "") != embedding_model:
        return False, "embedding_model_mismatch"
    try:
        stat = base_path.stat()
        current_sha = _sha256_for_stat(str(base_path.resolve()), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return False, "base_unreadable"
    if str(payload.get("base_sha256") or "") != current_sha:
        return False, "base_revision_mismatch"
    return True, "compatible"


def _rag_index_mode(base_path: Path) -> str:
    try:
        payload = json.loads(
            base_path.with_name("les_smeta_norm_rag_manifest.json").read_text(encoding="utf-8")
        )
    except Exception:
        return ""
    return str(payload.get("index_mode") or "hybrid")


def _rag_dense_compatibility(base_path: Path) -> tuple[bool, str]:
    """Dense is usable only in a proven query/document embedding space."""
    try:
        payload = json.loads(
            base_path.with_name("les_smeta_norm_rag_manifest.json").read_text(encoding="utf-8")
        )
    except Exception:
        return False, "manifest_missing_or_invalid"
    built_backend = str(payload.get("embedding_backend") or "").strip().lower()
    query_backend = os.getenv("EMBED_BACKEND", "sentence_transformers").strip().lower()
    if built_backend == query_backend:
        return True, "same_backend"
    verified_space = str(payload.get("embedding_space_id") or "").strip()
    expected_space = os.getenv("LES_SMETA_EMBEDDING_SPACE_ID", "").strip()
    if (
        payload.get("embedding_space_verified") is True
        and verified_space
        and expected_space
        and verified_space == expected_space
    ):
        return True, "verified_embedding_space"
    return False, f"embedding_backend_mismatch:{built_backend or 'missing'}!={query_backend}"


def _rag_cards_many(
    queries: list[str],
    *,
    limit: int,
    base_path: Path,
    trace: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    out = {query: [] for query in queries}
    collection = _rag_collection()
    if not collection or not queries:
        if trace is not None:
            trace.update({"status": "disabled", "reason": "collection_or_queries_missing"})
        return out
    embedding_model = _rag_embedding_model()
    compatible, reason = _rag_manifest_status(
        base_path=base_path,
        collection=collection,
        embedding_model=embedding_model,
    )
    if not compatible:
        if trace is not None:
            trace.update({"status": "degraded_sparse_only", "reason": reason, "collection": collection})
        return out
    client = QdrantClient(
        url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        timeout=60.0,
        check_compatibility=False,
    )
    try:
        if not client.collection_exists(collection):
            if trace is not None:
                trace.update({"status": "degraded_sparse_only", "reason": "collection_missing", "collection": collection})
            return out
        index_mode = _rag_index_mode(base_path)
        dense_compatible, dense_reason = _rag_dense_compatibility(base_path)
        embedding_ms = 0.0
        dense_vectors: list[Any] = [None] * len(queries)
        sparse_mode = index_mode in {"sparse_only", "building_dense"} or not dense_compatible
        if not sparse_mode:
            embed = EmbedClient(
                os.getenv("MLX_URL", "http://127.0.0.1:8080"),
                model=embedding_model,
            )
            embedding_started = perf_counter()
            dense_vectors = embed.encode_sync([prepare_query_for_embedding(query) for query in queries])
            embedding_ms = round((perf_counter() - embedding_started) * 1000, 2)
        rehydrated_counts: dict[str, int] = {}
        missing_counts: dict[str, int] = {}
        retrieval_started = perf_counter()
        for query, dense in zip(queries, dense_vectors, strict=True):
            sparse = encode_bm25(query)
            prefetch = []
            if dense is not None:
                prefetch.append(models.Prefetch(query=dense, using="dense", limit=max(24, limit * 3)))
            if sparse:
                prefetch.append(models.Prefetch(
                    query=models.SparseVector(indices=list(sparse), values=list(sparse.values())),
                    using=SPARSE_VECTOR_NAME,
                    limit=max(24, limit * 3),
                ))
            result = client.query_points(
                collection_name=collection,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=max(1, min(limit, 50)),
                with_payload=True,
            )
            keys = [str((point.payload or {}).get("norm_key") or "") for point in result.points]
            out[query] = _cards_by_norm_keys(keys, base_path=base_path)
            rehydrated_counts[query] = len(out[query])
            missing_counts[query] = max(0, len([key for key in keys if key]) - len(out[query]))
        if trace is not None:
            trace.update({
                "status": "degraded_sparse_only" if sparse_mode else "ok",
                "reason": (
                    "dense_index_not_built"
                    if index_mode in {"sparse_only", "building_dense"}
                    else (dense_reason if not dense_compatible else "")
                ),
                "index_mode": index_mode,
                "dense_compatible": dense_compatible,
                "collection": collection,
                "embedding_model": embedding_model,
                "rehydrated_counts": rehydrated_counts,
                "missing_norm_keys": missing_counts,
                "embedding_ms": embedding_ms,
                "retrieval_ms": round((perf_counter() - retrieval_started) * 1000, 2),
            })
    except Exception as exc:
        # Dense retrieval is an additive candidate channel. The caller still has
        # exact/FTS cards and exposes the degraded backend in its trace.
        if trace is not None:
            trace.update({"status": "degraded_sparse_only", "reason": type(exc).__name__, "collection": collection})
        return out
    finally:
        client.close()
    return out


def _rrf_cards(*rankings: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    cards: dict[str, dict[str, Any]] = {}
    for ranking in rankings:
        for rank, card in enumerate(ranking, 1):
            identity = str(card.get("norm_key") or card.get("norm_code") or "")
            if not identity:
                continue
            cards.setdefault(identity, card)
            scores[identity] = scores.get(identity, 0.0) + 1.0 / (60.0 + rank)
    ordered = sorted(cards, key=lambda identity: (-scores[identity], identity))
    return [cards[identity] for identity in ordered[:limit]]


def _coverage_merge(*rankings: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Round-robin variant heads before RRF remainder so no variant is hidden by a tie."""
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_depth = max((len(ranking) for ranking in rankings), default=0)
    for depth in range(max_depth):
        for ranking in rankings:
            if depth >= len(ranking):
                continue
            card = ranking[depth]
            identity = str(card.get("norm_key") or card.get("norm_code") or "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            output.append(card)
            if len(output) >= limit:
                return output
    return output


def _rerank_cards(query: str, cards: list[dict[str, Any]], *, limit: int) -> tuple[list[dict[str, Any]], bool]:
    if len(cards) <= 3 or os.getenv("LES_SMETA_NORM_RERANK", "true").strip().casefold() not in {
        "1", "true", "yes", "on",
    }:
        return cards[:limit], False
    documents = [
        "\n".join(filter(None, [
            str(card.get("title") or ""),
            f"Измеритель: {card.get('measure_unit') or ''}",
            f"Состав: {'; '.join(str(step) for step in (card.get('work_steps') or [])[:8])}",
            "Ресурсы для проверки технологии: " + "; ".join(
                str(item.get("name") or "")
                for item in (card.get("resource_preview") or [])[:12]
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ),
        ]))[:1600]
        for card in cards
    ]
    try:
        response = httpx.post(
            f"{os.getenv('MLX_URL', 'http://127.0.0.1:8080').rstrip('/')}/v1/rerank",
            json={"query": query, "documents": documents, "top_k": min(limit, len(cards))},
            timeout=45.0,
        )
        response.raise_for_status()
        order = [int(item.get("index", -1)) for item in response.json().get("results") or []]
        valid_order = list(dict.fromkeys(index for index in order if 0 <= index < len(cards)))
        ranked = [cards[index] for index in valid_order]
        # A partial/malformed reranker response must not shrink the candidate menu.
        used = set(valid_order)
        ranked.extend(card for index, card in enumerate(cards) if index not in used)
        return ranked[:limit], bool(valid_order)
    except Exception:
        return cards[:limit], False


def _fts_prefix(term: str) -> str:
    normalized = term.casefold().replace("ё", "е")
    if not normalized.isalpha() or len(normalized) < 5:
        return normalized
    for suffix in _RUSSIAN_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 4:
            return normalized[: -len(suffix)]
    return normalized[:-1] if len(normalized) >= 7 else normalized


def _fts_query(terms: list[str], *, prefix: bool, joiner: str) -> str:
    parts = []
    for term in terms[:12]:
        token = _fts_prefix(term) if prefix else term.casefold().replace("ё", "е")
        token = token.replace('"', "")
        if token:
            parts.append(f'"{token}"*' if prefix and token.isalpha() else f'"{token}"')
    return f" {joiner} ".join(parts)


def _typed_cards(
    query: str,
    *,
    limit: int,
    base_path: Path,
    base_types: tuple[str, ...] = (),
    collections: tuple[str, ...] = (),
) -> list[dict[str, Any]] | None:
    if not base_path.exists():
        return None
    conn = _connect_base_readonly(base_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        if "norms" not in tables or "norms_fts" not in tables:
            return None
        exact_key = _norm_key(query)
        filters: list[str] = []
        filter_params: list[Any] = []
        if base_types:
            filters.append("n.base_type IN (" + ",".join("?" for _ in base_types) + ")")
            filter_params.extend(base_types)
        if collections:
            filters.append("substr(n.bare_code,1,2) IN (" + ",".join("?" for _ in collections) + ")")
            filter_params.extend(collections)
        filter_sql = (" AND " + " AND ".join(filters)) if filters else ""
        if exact_key:
            rows = conn.execute(
                "SELECT n.* FROM norms n WHERE n.norm_key = ?" + filter_sql + " LIMIT ?",
                (exact_key, *filter_params, limit),
            ).fetchall()
        else:
            terms = [term for term in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", query) if len(term) > 1]
            if not terms:
                return []
            rows = []
            queries = [
                _fts_query(terms, prefix=False, joiner="AND"),
                _fts_query(terms, prefix=True, joiner="AND"),
            ]
            if len(terms) > 1:
                queries.append(_fts_query(terms, prefix=True, joiner="OR"))
            for fts_query in dict.fromkeys(item for item in queries if item):
                rows = conn.execute(
                    """
                    SELECT n.* FROM norms_fts f
                    JOIN norms n ON n.norm_key = f.norm_key
                    WHERE norms_fts MATCH ?
                    {filter_sql}
                    ORDER BY bm25(norms_fts, 0.0, 6.0, 1.0), n.norm_key
                    LIMIT ?
                    """.format(filter_sql=filter_sql),
                    (fts_query, *filter_params, limit),
                ).fetchall()
                if rows:
                    break
        return [_card(conn, row) for row in rows]
    finally:
        conn.close()


def search_rows(words: list[str]) -> list[SmetaNormRow]:
    """Legacy adapter during migration; it returns candidates, never a binding."""
    return get_smeta_norm_store().search_rows(words)


def browse_norm_catalog(
    *,
    family: str = "",
    collection: str = "",
    table: str = "",
    limit: int = 100,
    base_path: str | Path | None = None,
) -> dict[str, Any]:
    """Navigate typed identity without guessing: family -> collection -> table -> norms."""
    path = Path(base_path) if base_path is not None else _base_path()
    integrity = normative_base_integrity(base_path=path)
    if not path.exists():
        return {
            "schema": "smeta_norm_catalog_v1",
            "level": "missing",
            "items": [],
            "source_integrity": integrity,
        }
    bounded_limit = max(1, min(int(limit), 1000))
    family_value = str(family or "").strip()
    collection_value = re.sub(r"\D", "", str(collection or ""))[:2]
    table_value = re.sub(r"[^0-9-]", "", str(table or "")).strip("-")
    conn = _connect_base_readonly(path)
    conn.row_factory = sqlite3.Row
    try:
        if not family_value:
            level = "family"
            rows = conn.execute(
                "SELECT base_type key, count(*) norm_count, sum(resource_count) resource_count "
                "FROM norms GROUP BY base_type ORDER BY base_type LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        elif not collection_value:
            level = "collection"
            rows = conn.execute(
                "SELECT substr(bare_code,1,2) key, count(*) norm_count, "
                "sum(resource_count) resource_count FROM norms WHERE base_type=? "
                "GROUP BY substr(bare_code,1,2) ORDER BY key LIMIT ?",
                (family_value, bounded_limit),
            ).fetchall()
        elif not table_value:
            level = "table"
            rows = conn.execute(
                "SELECT substr(bare_code,1,9) key, count(*) norm_count, "
                "sum(resource_count) resource_count FROM norms "
                "WHERE base_type=? AND substr(bare_code,1,2)=? "
                "GROUP BY substr(bare_code,1,9) ORDER BY key LIMIT ?",
                (family_value, collection_value, bounded_limit),
            ).fetchall()
        else:
            level = "norm"
            normalized_table = table_value[:9]
            rows = conn.execute(
                "SELECT * FROM norms WHERE base_type=? AND substr(bare_code,1,9)=? "
                "ORDER BY bare_code LIMIT ?",
                (family_value, normalized_table, bounded_limit),
            ).fetchall()
            return {
                "schema": "smeta_norm_catalog_v1",
                "level": level,
                "selection_owner": "model_or_user",
                "filters": {"family": family_value, "collection": collection_value, "table": normalized_table},
                "source_integrity": integrity,
                "items": [_card(conn, row) for row in rows],
            }
        return {
            "schema": "smeta_norm_catalog_v1",
            "level": level,
            "selection_owner": "model_or_user",
            "filters": {"family": family_value, "collection": collection_value, "table": table_value},
            "source_integrity": integrity,
            "items": [dict(row) for row in rows],
        }
    finally:
        conn.close()


def browse_norms(query: str, *, limit: int = 8, base_path: str | Path | None = None) -> dict[str, Any]:
    return browse_norms_many([query], limit=limit, base_path=base_path, rerank=True)[str(query)]


def browse_norms_many(
    queries: list[str],
    *,
    limit: int = 8,
    base_path: str | Path | None = None,
    base_types: list[str] | tuple[str, ...] | None = None,
    collections: list[str] | tuple[str, ...] | None = None,
    rerank: bool | None = None,
) -> dict[str, dict[str, Any]]:
    tool_started = perf_counter()
    bounded_limit = max(1, min(int(limit), 50))
    pool_limit = min(50, max(bounded_limit, bounded_limit * 4, 24))
    path = Path(base_path) if base_path is not None else _base_path()
    integrity = normative_base_integrity(base_path=path)
    clean_queries = list(dict.fromkeys(str(query).strip() for query in queries if str(query).strip()))
    clean_base_types = tuple(dict.fromkeys(str(value).strip() for value in (base_types or ()) if str(value).strip()))
    clean_collections = tuple(dict.fromkeys(
        re.sub(r"\D", "", str(value))[:2] for value in (collections or ()) if re.sub(r"\D", "", str(value))
    ))
    # A large first-pass triage is already batch-embedded and hybrid-fused. The
    # local reranker endpoint is single-query and would serialize dozens of
    # independent 4-7 second calls. Defer it to later narrow searches where it
    # materially reduces a small candidate set; the model still opens cards.
    # The endpoint is single-query. A model may request rerank, but a mass
    # batch stays RRF-only; the model can issue a later disputed shortlist of
    # at most four queries and receive the reranker there. This changes no
    # candidate decision and prevents serialized multi-minute execution.
    rerank_enabled = (bool(rerank) if rerank is not None else True) and len(clean_queries) <= 4
    variants_by_query = {query: _query_variants(query) for query in clean_queries}
    all_variants = list(dict.fromkeys(
        variant for query in clean_queries for variant in variants_by_query.get(query) or [query]
    ))
    rag_trace: dict[str, Any] = {}
    rag_by_query = _rag_cards_many(all_variants, limit=pool_limit, base_path=path, trace=rag_trace)
    out: dict[str, dict[str, Any]] = {}
    rerank_ms = 0.0
    for query in clean_queries:
        query_variants = variants_by_query.get(query) or [query]
        lexical_rankings = [
            _typed_cards(
                variant,
                limit=pool_limit,
                base_path=path,
                base_types=clean_base_types,
                collections=clean_collections,
            )
            for variant in query_variants
        ]
        lexical_lists = [ranking for ranking in lexical_rankings if ranking is not None]
        lexical = _coverage_merge(*lexical_lists, limit=pool_limit) if lexical_lists else None
        backend = "typed_sqlite_fts"
        if lexical is None:
            backend = "legacy_navigation_only"
            words = [word for word in query.split() if word]
            lexical = [
                {
                    "norm_code": row.code,
                    "title": row.title,
                    "measure_unit": row.measure_unit,
                    "profile": row.profile(),
                }
                for row in search_rows(words)[:pool_limit]
            ]
        rag_variant_lists = [rag_by_query.get(variant) or [] for variant in query_variants]
        rag_merged = _coverage_merge(*rag_variant_lists, limit=pool_limit) if rag_variant_lists else []
        rag_cards = [
            card for card in rag_merged
            if (not clean_base_types or str(card.get("base_type") or "") in clean_base_types)
            and (
                not clean_collections
                or re.sub(r"\D", "", str(card.get("norm_code") or ""))[:2] in clean_collections
            )
        ]
        # Qdrant performs dense+sparse RRF internally; fuse that hybrid ranking
        # with the independent typed/FTS safety channel through RRF as well.
        # No channel is allowed to become a hidden selector for the model.
        fused = _rrf_cards(lexical, rag_cards, limit=pool_limit) if rag_cards else lexical
        cards = fused[:bounded_limit]
        reranked = False
        if rag_cards:
            backend = f"{backend}+smeta_norm_qdrant_hybrid"
            if rerank_enabled:
                rerank_started = perf_counter()
                cards, reranked = _rerank_cards(query, fused, limit=bounded_limit)
                rerank_ms += (perf_counter() - rerank_started) * 1000
                if reranked:
                    backend = f"{backend}+bge_rerank"
            else:
                backend = f"{backend}+rerank_deferred"
        out[query] = {
            "schema": "smeta_norm_browse_v1",
            "query": query,
            "backend": backend,
            "selection_owner": "model_or_user",
            "selected_code": "",
            "source_integrity": integrity,
            "retrieval_trace": {
                "lexical_candidates": len(lexical),
                "rag_candidates": len(rag_cards),
                "fusion_candidates": len(fused),
                "returned_candidates": len(cards),
                "rerank_deferred": bool(rag_cards and not rerank_enabled),
                "reranked": reranked,
                "rag": dict(rag_trace),
                "filters": {"base_types": list(clean_base_types), "collections": list(clean_collections)},
                "query_variants": query_variants,
                "embedding_ms": float(rag_trace.get("embedding_ms") or 0.0),
                "retrieval_ms": float(rag_trace.get("retrieval_ms") or 0.0),
                "rerank_ms": round(rerank_ms, 2),
                "tool_total_ms": round((perf_counter() - tool_started) * 1000, 2),
                "queries_count": len(queries),
                "unique_queries_count": len(clean_queries),
            },
            "cards": cards,
        }
    batch_total_ms = round((perf_counter() - tool_started) * 1000, 2)
    for result in out.values():
        trace = result.get("retrieval_trace") or {}
        trace["rerank_ms"] = round(rerank_ms, 2)
        trace["tool_total_ms"] = batch_total_ms
    return out
