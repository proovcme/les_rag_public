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


_full_cache: dict[str, Any] = {"ts": 0.0, "collection": "", "payload": None}


def build_graph_full(collection: str, max_ntd_edges: int = 4000) -> dict[str, Any]:
    """Полный граф знаний: узлы Проект→Датасет→Документ + рёбра принадлежности и NTD-ссылок.
    Документ-узел несёт project/dataset/doc_type/domain/chunks → фронт красит по любому срезу,
    размер = чанки, клик → область поиска. ADR-11: без LLM, только MetaDB + лексический индекс."""
    import sqlite3

    from backend.rag_config import rag_meta_db_path

    now = time.time()
    if (_full_cache["payload"] is not None and _full_cache["collection"] == collection
            and now - _full_cache["ts"] < CACHE_TTL_SEC):
        return _full_cache["payload"]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    ds_meta: dict[str, dict[str, Any]] = {}
    docs: list[dict[str, Any]] = []
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            for r in conn.execute(
                "SELECT id, name, COALESCE(chunk_count,0) cc, COALESCE(group_name,'') grp FROM datasets"
            ):
                ds_meta[str(r["id"])] = {"name": r["name"], "chunks": int(r["cc"]), "group": r["grp"]}
            for r in conn.execute(
                "SELECT dataset_id, file_name, COALESCE(doc_type,'') dt, COALESCE(domain,'') dm, "
                "COALESCE(chunk_count,0) cc, COALESCE(status,'') st FROM documents"
            ):
                docs.append(dict(r))
    except Exception as error:  # noqa: BLE001
        logger.warning("[GRAPH_FULL] чтение MetaDB сорвалось: %s", error)

    # Авторитетная связь проект→датасеты из реестра проектов.
    proj_of_ds: dict[str, dict[str, Any]] = {}
    try:
        from proxy.services import project_service as ps

        for p in (ps.build_registry().get("projects", []) or []):
            pid = int(p["id"]); pname = p.get("name") or f"Проект {pid}"
            for dsid in (ps.project_dataset_ids(pid) or []):
                proj_of_ds[str(dsid)] = {"id": pid, "name": pname}
    except Exception as error:  # noqa: BLE001
        logger.warning("[GRAPH_FULL] реестр проектов недоступен: %s", error)

    # Узлы проектов (агрегаты по датасетам).
    seen_proj: dict[int, str] = {}
    pchunks: dict[int, int] = {}; pdscount: dict[int, int] = {}
    for dsid, pr in proj_of_ds.items():
        pdscount[pr["id"]] = pdscount.get(pr["id"], 0) + 1
        pchunks[pr["id"]] = pchunks.get(pr["id"], 0) + ds_meta.get(dsid, {}).get("chunks", 0)
        seen_proj.setdefault(pr["id"], pr["name"])
    for pid, pname in seen_proj.items():
        nodes.append({"id": f"p:{pid}", "kind": "project", "label": pname,
                      "datasets": pdscount.get(pid, 0), "chunks": pchunks.get(pid, 0)})

    # Узлы датасетов + ребро проект→датасет.
    for dsid, meta in ds_meta.items():
        pr = proj_of_ds.get(dsid)
        nodes.append({"id": f"ds:{dsid}", "kind": "dataset", "label": meta["name"],
                      "project_id": (pr or {}).get("id"), "project": (pr or {}).get("name"),
                      "chunks": meta["chunks"]})
        if pr:
            edges.append({"source": f"p:{pr['id']}", "target": f"ds:{dsid}", "kind": "member"})

    # Узлы документов + ребро датасет→документ. id = «dataset_id:file_name» (== ключ NTD-рёбер).
    doc_ids: set[str] = set()
    for d in docs:
        dsid = str(d["dataset_id"]); fname = str(d["file_name"])
        doc_id = f"{dsid}:{fname}"
        doc_ids.add(doc_id)
        pr = proj_of_ds.get(dsid)
        nodes.append({"id": doc_id, "kind": "document", "label": fname,
                      "dataset_id": dsid, "dataset": ds_meta.get(dsid, {}).get("name", ""),
                      "project_id": (pr or {}).get("id"), "project": (pr or {}).get("name"),
                      "doc_type": d["dt"], "domain": d["dm"], "chunks": int(d["cc"]), "status": d["st"]})
        edges.append({"source": f"ds:{dsid}", "target": doc_id, "kind": "member"})

    # NTD-рёбра (документ→документ); только между существующими узлами-документами.
    ntd = build_reference_edges(collection, max_edges=max_ntd_edges)
    ntd_kept = 0
    for e in ntd.get("edges", []):
        if e["source"] in doc_ids and e["target"] in doc_ids:
            edges.append({"source": e["source"], "target": e["target"], "kind": "ntd", "weight": e.get("weight", 1)})
            ntd_kept += 1

    payload = {
        "nodes": nodes, "edges": edges,
        "stats": {"projects": len(seen_proj), "datasets": len(ds_meta), "documents": len(docs),
                  "ntd_edges": ntd_kept, "total_nodes": len(nodes), "total_edges": len(edges)},
    }
    _full_cache.update(ts=now, collection=collection, payload=payload)
    logger.info("[GRAPH_FULL] %s узлов / %s рёбер (проектов %s, датасетов %s, документов %s, NTD %s)",
                len(nodes), len(edges), len(seen_proj), len(ds_meta), len(docs), ntd_kept)
    return payload
