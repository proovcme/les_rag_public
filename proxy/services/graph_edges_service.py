"""Рёбра перекрёстных ссылок между нормативами — W5.7-v2 (LES3_PLAN).

ADR-11: детерминированно, без LLM. Номер норматива извлекается из имени
документа (СП 4.13130, ГОСТ 26963, СНиП 3.05.03), упоминания других номеров
ищутся FTS-запросами по лексическому индексу. Результат кэшируется в памяти.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from proxy.services.lexical_index_service import LexicalIndex, lexical_enabled

logger = logging.getLogger(__name__)

# Номер НТД в имени файла: «СП 4.13130», «ГОСТ Р 53300», «СНиП 3.05.03-85».
DOC_NUMBER_RE = re.compile(
    r"\b(СП|ГОСТ\s*Р?|СНиП)\s*([\d]+(?:\.[\d]+)+)",
    re.IGNORECASE,
)

_cache: dict[str, Any] = {"ts": 0.0, "collection": "", "edges": None}
CACHE_TTL_SEC = 600


def _doc_number(file_name: str) -> str | None:
    match = DOC_NUMBER_RE.search(file_name)
    if not match:
        return None
    return match.group(2)


def build_reference_edges(collection: str, max_edges: int = 4000) -> dict[str, Any]:
    """Рёбра «документ → документ» по упоминаниям номеров НТД в текстах."""
    now = time.time()
    if (
        _cache["edges"] is not None
        and _cache["collection"] == collection
        and now - _cache["ts"] < CACHE_TTL_SEC
    ):
        return _cache["edges"]

    if not lexical_enabled():
        return {"edges": [], "docs_with_numbers": 0, "note": "lexical index disabled"}

    index = LexicalIndex()
    edges: dict[tuple[str, str], int] = {}
    with index.connect() as conn:
        docs = [
            (str(row[0]), str(row[1]))
            for row in conn.execute(
                "SELECT DISTINCT dataset_id, doc_name FROM lexical_chunks WHERE collection=?",
                (collection,),
            )
        ]
        number_to_doc: dict[str, tuple[str, str]] = {}
        for dataset_id, doc_name in docs:
            number = _doc_number(doc_name)
            if number and number not in number_to_doc:
                number_to_doc[number] = (dataset_id, doc_name)

        for number, (target_ds, target_doc) in number_to_doc.items():
            # FTS-фраза по номеру: документы, упоминающие этот номер.
            try:
                rows = conn.execute(
                    """
                    SELECT DISTINCT c.dataset_id, c.doc_name
                    FROM lexical_chunks_fts f
                    JOIN lexical_chunks c ON c.id = f.rowid
                    WHERE lexical_chunks_fts MATCH ? AND c.collection = ?
                    LIMIT 200
                    """,
                    (f'"{number}"', collection),
                ).fetchall()
            except Exception:
                continue
            for source_ds, source_doc in rows:
                if source_doc == target_doc:
                    continue
                key = (f"{source_ds}:{source_doc}", f"{target_ds}:{target_doc}")
                edges[key] = edges.get(key, 0) + 1
            if len(edges) >= max_edges:
                break

    payload = {
        "edges": [
            {"source": src, "target": dst, "weight": weight}
            for (src, dst), weight in sorted(edges.items(), key=lambda kv: -kv[1])[:max_edges]
        ],
        "docs_with_numbers": len(number_to_doc),
    }
    _cache.update(ts=now, collection=collection, edges=payload)
    logger.info("[GRAPH_EDGES] %s рёбер по %s нумерованным документам", len(payload["edges"]), len(number_to_doc))
    return payload
