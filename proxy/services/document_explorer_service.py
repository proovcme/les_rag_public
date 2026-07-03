"""No-AI document explorer over LES dataset metadata and lexical chunks.

This service is intentionally boring: it lists datasets/documents, returns
ordered chunks, and searches SQLite FTS. It does not call the model and does
not infer facts for the user.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.rag_config import rag_collection_name, rag_meta_db_path
from proxy.services.lexical_index_service import build_fts_query, lexical_db_path


@dataclass(frozen=True)
class DocumentExplorer:
    db_path: str | None = None
    collection: str | None = None

    @property
    def path(self) -> str:
        return self.db_path or lexical_db_path() or rag_meta_db_path()

    @property
    def collection_name(self) -> str:
        return self.collection or rag_collection_name()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_datasets(self, *, q: str = "", limit: int = 200) -> list[dict[str, Any]]:
        where = ""
        params: list[Any] = []
        if q.strip():
            where = "WHERE id LIKE ? OR name LIKE ?"
            like = f"%{q.strip()}%"
            params.extend([like, like])
        params.append(limit)
        with self.connect() as conn:
            _ensure_tables(conn)
            rows = conn.execute(
                f"""
                SELECT
                    d.id,
                    d.name,
                    COALESCE(d.status, '') AS status,
                    COALESCE(d.chunk_count, 0) AS chunk_count,
                    COUNT(doc.id) AS document_count,
                    SUM(CASE WHEN doc.status = 'INDEXED' THEN 1 ELSE 0 END) AS indexed_count
                FROM datasets d
                LEFT JOIN documents doc ON doc.dataset_id = d.id
                {where}
                GROUP BY d.id, d.name, d.status, d.chunk_count
                ORDER BY LOWER(COALESCE(d.name, d.id))
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_documents(
        self,
        dataset_id: str,
        *,
        q: str = "",
        status: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses = ["dataset_id = ?"]
        params: list[Any] = [dataset_id]
        if q.strip():
            clauses.append("file_name LIKE ?")
            params.append(f"%{q.strip()}%")
        if status.strip():
            clauses.append("status = ?")
            params.append(status.strip())
        where = " AND ".join(clauses)
        with self.connect() as conn:
            _ensure_tables(conn)
            total = int(conn.execute(f"SELECT COUNT(*) FROM documents WHERE {where}", params).fetchone()[0])
            rows = conn.execute(
                f"""
                SELECT
                    id,
                    dataset_id,
                    file_name,
                    COALESCE(status, '') AS status,
                    COALESCE(file_size, 0) AS file_size,
                    COALESCE(chunk_count, 0) AS chunk_count,
                    COALESCE(doc_type, '') AS doc_type,
                    COALESCE(content_type, '') AS content_type,
                    COALESCE(domain, '') AS domain,
                    COALESCE(source_path, '') AS source_path,
                    COALESCE(last_error, '') AS last_error
                FROM documents
                WHERE {where}
                ORDER BY LOWER(file_name)
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
        return {"dataset_id": dataset_id, "total": total, "limit": limit, "offset": offset, "documents": [dict(row) for row in rows]}

    def document_chunks(
        self,
        dataset_id: str,
        doc_name: str,
        *,
        q: str = "",
        limit: int = 80,
        offset: int = 0,
        max_chars: int = 4000,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            _ensure_tables(conn)
            if q.strip():
                return self._search_chunks(
                    conn,
                    q=q,
                    dataset_ids=[dataset_id],
                    doc_name=doc_name,
                    limit=limit,
                    max_chars=max_chars,
                )

            total = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM lexical_chunks
                    WHERE collection = ? AND dataset_id = ? AND doc_name = ?
                    """,
                    (self.collection_name, dataset_id, doc_name),
                ).fetchone()[0]
            )
            rows = conn.execute(
                """
                SELECT
                    point_id, dataset_id, doc_id, doc_name, text, chunk_ord,
                    COALESCE(section_heading, '') AS section_heading,
                    COALESCE(parent_heading, '') AS parent_heading,
                    COALESCE(context_kind, '') AS context_kind
                FROM lexical_chunks
                WHERE collection = ? AND dataset_id = ? AND doc_name = ?
                ORDER BY COALESCE(chunk_ord, 0), id
                LIMIT ? OFFSET ?
                """,
                (self.collection_name, dataset_id, doc_name, limit, offset),
            ).fetchall()
        return {
            "dataset_id": dataset_id,
            "doc_name": doc_name,
            "query": "",
            "total": total,
            "limit": limit,
            "offset": offset,
            "chunks": [_chunk_payload(row, max_chars=max_chars) for row in rows],
        }

    def search(
        self,
        q: str,
        *,
        dataset_ids: list[str] | None = None,
        doc_name: str = "",
        limit: int = 50,
        max_chars: int = 1200,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            _ensure_tables(conn)
            return self._search_chunks(
                conn,
                q=q,
                dataset_ids=dataset_ids or [],
                doc_name=doc_name,
                limit=limit,
                max_chars=max_chars,
            )

    def _search_chunks(
        self,
        conn: sqlite3.Connection,
        *,
        q: str,
        dataset_ids: list[str],
        doc_name: str = "",
        limit: int,
        max_chars: int,
    ) -> dict[str, Any]:
        fts = build_fts_query(q)
        if not fts:
            return self._like_search(
                conn,
                q=q,
                dataset_ids=dataset_ids,
                doc_name=doc_name,
                limit=limit,
                max_chars=max_chars,
                warning="empty_fts_query",
            )
        params: list[Any] = [fts, self.collection_name]
        dataset_clause = ""
        if dataset_ids:
            dataset_clause = " AND c.dataset_id IN (" + ",".join("?" for _ in dataset_ids) + ")"
            params.extend(dataset_ids)
        doc_clause = ""
        if doc_name:
            doc_clause = " AND c.doc_name = ?"
            params.append(doc_name)
        params.append(limit)
        try:
            rows = conn.execute(
                f"""
                SELECT
                    c.point_id, c.dataset_id, c.doc_id, c.doc_name, c.text,
                    c.chunk_ord, COALESCE(c.section_heading, '') AS section_heading,
                    COALESCE(c.parent_heading, '') AS parent_heading,
                    COALESCE(c.context_kind, '') AS context_kind,
                    bm25(lexical_chunks_fts) AS bm25_score
                FROM lexical_chunks_fts
                JOIN lexical_chunks c ON c.id = lexical_chunks_fts.rowid
                WHERE lexical_chunks_fts MATCH ?
                  AND c.collection = ?
                  {dataset_clause}
                  {doc_clause}
                ORDER BY bm25_score ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError as exc:
            return self._like_search(
                conn,
                q=q,
                dataset_ids=dataset_ids,
                doc_name=doc_name,
                limit=limit,
                max_chars=max_chars,
                warning=f"fts_error: {str(exc)[:120]}",
            )

        hits = []
        for index, row in enumerate(rows, 1):
            item = _chunk_payload(row, max_chars=max_chars)
            item["rank"] = index
            item["score"] = round(float(row["bm25_score"] or 0.0), 6)
            item["snippet"] = _snippet(str(row["text"] or ""), q, max_chars=max_chars)
            hits.append(item)
        if not hits:
            return self._like_search(
                conn,
                q=q,
                dataset_ids=dataset_ids,
                doc_name=doc_name,
                limit=limit,
                max_chars=max_chars,
                warning="fts_no_hits",
            )
        return {
            "query": q,
            "dataset_ids": dataset_ids,
            "doc_name": doc_name,
            "count": len(hits),
            "hits": hits,
        }

    def _like_search(
        self,
        conn: sqlite3.Connection,
        *,
        q: str,
        dataset_ids: list[str],
        doc_name: str,
        limit: int,
        max_chars: int,
        warning: str,
    ) -> dict[str, Any]:
        tokens = _plain_search_tokens(q)
        if not tokens:
            return {"query": q, "count": 0, "hits": [], "warning": warning}
        clauses = ["collection = ?"]
        params: list[Any] = [self.collection_name]
        if dataset_ids:
            clauses.append("dataset_id IN (" + ",".join("?" for _ in dataset_ids) + ")")
            params.extend(dataset_ids)
        if doc_name:
            clauses.append("doc_name = ?")
            params.append(doc_name)
        for token in tokens:
            variants = _token_variants(token)
            clauses.append("(" + " OR ".join("text LIKE ?" for _ in variants) + ")")
            params.extend(f"%{variant}%" for variant in variants)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT
                point_id, dataset_id, doc_id, doc_name, text, chunk_ord,
                COALESCE(section_heading, '') AS section_heading,
                COALESCE(parent_heading, '') AS parent_heading,
                COALESCE(context_kind, '') AS context_kind
            FROM lexical_chunks
            WHERE {" AND ".join(clauses)}
            ORDER BY COALESCE(chunk_ord, 0), id
            LIMIT ?
            """,
            params,
        ).fetchall()
        hits = []
        for index, row in enumerate(rows, 1):
            item = _chunk_payload(row, max_chars=max_chars)
            item["rank"] = index
            item["score"] = None
            item["snippet"] = _snippet(str(row["text"] or ""), q, max_chars=max_chars)
            hits.append(item)
        return {
            "query": q,
            "dataset_ids": dataset_ids,
            "doc_name": doc_name,
            "count": len(hits),
            "hits": hits,
            "warning": warning,
            "fallback": "like",
        }


def _ensure_tables(conn: sqlite3.Connection) -> None:
    missing = []
    for table in ("datasets", "documents", "lexical_chunks", "lexical_chunks_fts"):
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ? AND type IN ('table', 'view')",
            (table,),
        ).fetchone()
        if not exists:
            missing.append(table)
    if missing:
        raise RuntimeError("document explorer requires tables: " + ", ".join(missing))


def _chunk_payload(row: sqlite3.Row, *, max_chars: int) -> dict[str, Any]:
    text = str(row["text"] or "")
    return {
        "point_id": row["point_id"],
        "dataset_id": row["dataset_id"],
        "doc_id": row["doc_id"],
        "doc_name": row["doc_name"],
        "chunk_ord": row["chunk_ord"],
        "section_heading": row["section_heading"],
        "parent_heading": row["parent_heading"],
        "context_kind": row["context_kind"],
        "text": text[:max_chars],
        "text_truncated": len(text) > max_chars,
    }


def _snippet(text: str, query: str, *, max_chars: int) -> str:
    tokens = [t for t in re.findall(r"[0-9A-Za-zА-Яа-яЁё.-]{3,}", query) if len(t) >= 3]
    low = text.casefold().replace("ё", "е")
    pos = -1
    for token in tokens:
        pos = low.find(token.casefold().replace("ё", "е"))
        if pos >= 0:
            break
    if pos < 0:
        return text[:max_chars]
    half = max(80, max_chars // 2)
    start = max(0, pos - half)
    end = min(len(text), pos + half)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _plain_search_tokens(query: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё.-]{3,}", query):
        if token not in tokens:
            tokens.append(token)
    return tokens[:8]


def _token_variants(token: str) -> list[str]:
    variants = []
    for value in (token, token.lower(), token.upper(), token.capitalize()):
        if value not in variants:
            variants.append(value)
    return variants


def explorer(db_path: str | None = None, collection: str | None = None) -> DocumentExplorer:
    return DocumentExplorer(db_path=db_path, collection=collection)
