"""No-AI document explorer over LES dataset metadata and lexical chunks.

This service is intentionally boring: it lists datasets/documents, returns
ordered chunks, and searches SQLite FTS. It does not call the model and does
not infer facts for the user.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.rag_config import rag_collection_name, rag_meta_db_path
from proxy.services.lexical_index_service import LexicalIndex, build_fts_query, lexical_db_path

DATASET_KIND_LABELS = {
    "project": "Проект",
    "norm": "Норма",
    "estimate": "Сметы",
    "catalog": "Каталог",
    "cad_bim": "CAD/BIM",
    "correspondence": "Переписка",
    "mixed": "Смешанный",
    "other": "Другое",
}
DATASET_KIND_ORDER = {
    "project": 10,
    "norm": 20,
    "estimate": 30,
    "catalog": 40,
    "cad_bim": 50,
    "correspondence": 60,
    "mixed": 70,
    "other": 80,
    "": 999,
}


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
        # A clean/updated runtime may already have MetaDB datasets/documents but
        # not the additive lexical projection yet.  Document Explorer is a
        # reader, but opening it must run the cheap schema migration instead of
        # returning 503 until a document happens to be reindexed.
        LexicalIndex.ensure_schema(conn)
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
                    COALESCE(d.dataset_scope, 'user') AS dataset_scope,
                    COALESCE(d.module_id, '') AS module_id,
                    COUNT(doc.id) AS document_count,
                    SUM(CASE WHEN doc.status = 'INDEXED' THEN 1 ELSE 0 END) AS indexed_count,
                    SUM(CASE WHEN doc.status = 'PENDING' THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN doc.status = 'ERROR' THEN 1 ELSE 0 END) AS error_count,
                    SUM(CASE WHEN doc.status = 'MISSING' THEN 1 ELSE 0 END) AS missing_count
                FROM datasets d
                LEFT JOIN documents doc ON doc.dataset_id = d.id
                {where}
                GROUP BY d.id, d.name, d.status, d.chunk_count, d.dataset_scope, d.module_id
                ORDER BY CASE WHEN COALESCE(d.dataset_scope, 'user')='system' THEN 0 ELSE 1 END,
                         LOWER(COALESCE(d.name, d.id))
                LIMIT ?
                """,
                params,
            ).fetchall()
            result = [dict(row) for row in rows]
            kinds = _dataset_profile_kinds(conn, [str(row.get("id") or "") for row in result])
        for row in result:
            from proxy.services.system_dataset_service import system_dataset_spec

            spec = system_dataset_spec(str(row.get("name") or ""))
            row["display_name"] = spec.display_name if spec else str(row.get("name") or "")
            row["source_role"] = spec.source_role if spec else ""
            row["pinned_order"] = spec.pinned_order if spec else 999
            kind = kinds.get(str(row.get("id") or ""), "")
            row["dataset_kind"] = kind
            row["dataset_kind_label"] = DATASET_KIND_LABELS.get(kind, "")
            row["dataset_kind_sort"] = DATASET_KIND_ORDER.get(kind, DATASET_KIND_ORDER[""])
        return sorted(
            result,
            key=lambda row: (
                0 if str(row.get("dataset_scope") or "user") == "system" else 1,
                int(row.get("pinned_order") or 999),
                int(row.get("dataset_kind_sort") or DATASET_KIND_ORDER[""]),
                str(row.get("name") or row.get("id") or "").casefold(),
            ),
        )

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

    def dataset_index_quality(self, dataset_id: str, *, sample_chunks_per_file: int = 2) -> dict[str, Any]:
        """Describe what was actually written to the searchable text projection.

        This is a read-only content passport, not a relevance score.  Structural
        dense/sparse/Qdrant/FTS integrity remains owned by ``audit_dataset_integrity``;
        here the operator sees file coverage, text volume and representative chunks.
        """
        sample_limit = max(1, min(int(sample_chunks_per_file or 2), 4))
        with self.connect() as conn:
            _ensure_tables(conn)
            documents = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, dataset_id, file_name, COALESCE(status, '') AS status,
                           COALESCE(file_size, 0) AS file_size,
                           COALESCE(chunk_count, 0) AS chunk_count,
                           COALESCE(doc_type, '') AS doc_type,
                           COALESCE(content_type, '') AS content_type,
                           COALESCE(domain, '') AS domain,
                           COALESCE(source_path, '') AS source_path,
                           COALESCE(last_error, '') AS last_error
                    FROM documents
                    WHERE dataset_id = ?
                    ORDER BY LOWER(file_name)
                    """,
                    (dataset_id,),
                ).fetchall()
            ]
            aggregate_rows = conn.execute(
                """
                SELECT doc_name,
                       COUNT(*) AS indexed_chunks,
                       COALESCE(SUM(LENGTH(TRIM(COALESCE(text, '')))), 0) AS characters,
                       SUM(CASE WHEN LENGTH(TRIM(COALESCE(text, ''))) = 0 THEN 1 ELSE 0 END) AS empty_chunks,
                       SUM(CASE WHEN LENGTH(TRIM(COALESCE(text, ''))) BETWEEN 1 AND 119 THEN 1 ELSE 0 END) AS short_chunks,
                       SUM(CASE WHEN TRIM(COALESCE(section_heading, '')) <> ''
                                      OR TRIM(COALESCE(parent_heading, '')) <> '' THEN 1 ELSE 0 END) AS heading_chunks,
                       SUM(CASE WHEN INSTR(COALESCE(text, ''), '|') > 0
                                      OR LOWER(COALESCE(context_kind, '')) LIKE '%table%' THEN 1 ELSE 0 END) AS table_like_chunks
                FROM lexical_chunks
                WHERE collection = ? AND dataset_id = ?
                GROUP BY doc_name
                """,
                (self.collection_name, dataset_id),
            ).fetchall()
            sample_rows = conn.execute(
                """
                WITH ranked AS (
                    SELECT doc_name, chunk_ord, section_heading, parent_heading, context_kind, text,
                           ROW_NUMBER() OVER (
                               PARTITION BY doc_name
                               ORDER BY CASE WHEN LENGTH(TRIM(COALESCE(text, ''))) > 0 THEN 0 ELSE 1 END,
                                        COALESCE(chunk_ord, 0), id
                           ) AS sample_rank
                    FROM lexical_chunks
                    WHERE collection = ? AND dataset_id = ?
                )
                SELECT doc_name, chunk_ord, section_heading, parent_heading, context_kind, text
                FROM ranked
                WHERE sample_rank <= ?
                ORDER BY LOWER(doc_name), sample_rank
                """,
                (self.collection_name, dataset_id, sample_limit),
            ).fetchall()

        aggregates = {str(row["doc_name"]): dict(row) for row in aggregate_rows}
        samples: dict[str, list[dict[str, Any]]] = {}
        for row in sample_rows:
            text = " ".join(str(row["text"] or "").split())
            samples.setdefault(str(row["doc_name"]), []).append(
                {
                    "chunk_ord": int(row["chunk_ord"] or 0),
                    "heading": str(row["section_heading"] or row["parent_heading"] or ""),
                    "context_kind": str(row["context_kind"] or ""),
                    "text": text[:700],
                }
            )

        files: list[dict[str, Any]] = []
        totals = {
            "files": len(documents),
            "indexed_files": 0,
            "files_with_searchable_text": 0,
            "declared_chunks": 0,
            "indexed_chunks": 0,
            "characters": 0,
            "empty_chunks": 0,
            "short_chunks": 0,
            "heading_chunks": 0,
            "table_like_chunks": 0,
        }
        for document in documents:
            file_name = str(document.get("file_name") or "")
            aggregate = aggregates.get(file_name, {})
            declared = int(document.get("chunk_count") or 0)
            indexed = int(aggregate.get("indexed_chunks") or 0)
            characters = int(aggregate.get("characters") or 0)
            extension = Path(file_name).suffix.lstrip(".").upper() or "ФАЙЛ"
            totals["indexed_files"] += int(str(document.get("status") or "").upper() == "INDEXED")
            totals["files_with_searchable_text"] += int(characters > 0)
            totals["declared_chunks"] += declared
            for key in (
                "indexed_chunks", "characters", "empty_chunks", "short_chunks",
                "heading_chunks", "table_like_chunks",
            ):
                totals[key] += int(aggregate.get(key) or 0)
            files.append(
                {
                    **document,
                    "extension": extension,
                    "declared_chunks": declared,
                    "indexed_chunks": indexed,
                    "characters": characters,
                    "average_chunk_chars": round(characters / indexed) if indexed else 0,
                    "empty_chunks": int(aggregate.get("empty_chunks") or 0),
                    "short_chunks": int(aggregate.get("short_chunks") or 0),
                    "heading_chunks": int(aggregate.get("heading_chunks") or 0),
                    "table_like_chunks": int(aggregate.get("table_like_chunks") or 0),
                    "samples": samples.get(file_name, []),
                }
            )

        searchable_files = int(totals["files_with_searchable_text"])
        indexed_files = int(totals["indexed_files"])
        indexed_chunks = int(totals["indexed_chunks"])
        empty_chunks = int(totals["empty_chunks"])
        state = (
            "empty" if indexed_files == 0 or indexed_chunks == 0
            else "attention" if searchable_files < indexed_files or empty_chunks > 0
            else "ready"
        )
        return {
            "schema": "les.dataset_index_quality.v1",
            "dataset_id": dataset_id,
            "state": state,
            "label": {
                "ready": "Содержимое индекса видно",
                "attention": "Есть пробелы в содержимом",
                "empty": "Поискового содержимого нет",
            }[state],
            "totals": totals,
            "files": files,
            "search_channels": ["Смысловой поиск", "Точный поиск", "Текстовый поиск"],
            "operator_note": (
                "Примеры ниже — реальный текст поисковой проекции. "
                "Графика без текстового слоя требует отдельного просмотра изображения."
            ),
        }

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            _ensure_tables(conn)
            row = conn.execute(
                """
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
                WHERE id = ?
                """,
                (doc_id,),
            ).fetchone()
            if row is None:
                # Search results historically expose the chunk-level payload
                # id (for example ``...:budget:...``), not ``documents.id``.
                # Resolve that identity across retained logical/physical
                # lexical generations back to the source document so old
                # indexes and saved conversations remain openable without a
                # reindex. Exact chunk identity stays the lookup key.
                chunk = conn.execute(
                    """
                    SELECT dataset_id, doc_name
                    FROM lexical_chunks
                    WHERE doc_id = ? OR point_id = ?
                    ORDER BY
                        CASE WHEN collection = ? THEN 0 ELSE 1 END,
                        updated_at DESC,
                        id DESC
                    LIMIT 1
                    """,
                    (doc_id, doc_id, self.collection_name),
                ).fetchone()
                if chunk is not None:
                    row = conn.execute(
                        """
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
                        WHERE dataset_id = ? AND file_name = ?
                        ORDER BY id
                        LIMIT 1
                        """,
                        (str(chunk["dataset_id"] or ""), str(chunk["doc_name"] or "")),
                    ).fetchone()
        return dict(row) if row else None

    def get_document_by_source(self, dataset_id: str, doc_name: str) -> dict[str, Any] | None:
        """Resolve one document by its exact source provenance.

        Saved chat history may retain a chunk identity after that search
        projection has been replaced.  The dataset/document pair is the
        durable identity already stored with the citation; keep this lookup
        exact so opening a source never guesses a neighbouring file.
        """
        dataset_id = str(dataset_id or "").strip()
        doc_name = str(doc_name or "").strip()
        if not dataset_id or not doc_name:
            return None
        with self.connect() as conn:
            _ensure_tables(conn)
            row = conn.execute(
                """
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
                WHERE dataset_id = ? AND file_name = ?
                ORDER BY id
                LIMIT 1
                """,
                (dataset_id, doc_name),
            ).fetchone()
        return dict(row) if row else None

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

    def document_chunks_by_id(
        self,
        doc_id: str,
        *,
        q: str = "",
        limit: int = 80,
        offset: int = 0,
        max_chars: int = 4000,
    ) -> dict[str, Any] | None:
        document = self.get_document(doc_id)
        if not document:
            return None
        dataset_id = str(document["dataset_id"])
        doc_name = str(document["file_name"])
        with self.connect() as conn:
            _ensure_tables(conn)
            if q.strip():
                result = self._search_chunks(
                    conn,
                    q=q,
                    dataset_ids=[dataset_id],
                    doc_id=doc_id,
                    limit=limit,
                    max_chars=max_chars,
                )
                if int(result.get("count") or 0) == 0:
                    result = self._search_chunks(
                        conn,
                        q=q,
                        dataset_ids=[dataset_id],
                        doc_name=doc_name,
                        limit=limit,
                        max_chars=max_chars,
                    )
                    result["warning"] = "doc_id_no_lexical_match_fallback_doc_name"
                result["document"] = document
                return result

            total = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM lexical_chunks
                    WHERE collection = ? AND doc_id = ?
                    """,
                    (self.collection_name, doc_id),
                ).fetchone()[0]
            )
            params: tuple[Any, ...] = (self.collection_name, doc_id, limit, offset)
            where = "collection = ? AND doc_id = ?"
            warning = ""
            if total == 0:
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
                where = "collection = ? AND dataset_id = ? AND doc_name = ?"
                params = (self.collection_name, dataset_id, doc_name, limit, offset)
                if total:
                    warning = "doc_id_no_lexical_match_fallback_doc_name"
            rows = conn.execute(
                f"""
                SELECT
                    point_id, dataset_id, doc_id, doc_name, text, chunk_ord,
                    COALESCE(section_heading, '') AS section_heading,
                    COALESCE(parent_heading, '') AS parent_heading,
                    COALESCE(context_kind, '') AS context_kind
                FROM lexical_chunks
                WHERE {where}
                ORDER BY COALESCE(chunk_ord, 0), id
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        payload = {
            "document": document,
            "dataset_id": dataset_id,
            "doc_id": doc_id,
            "doc_name": doc_name,
            "query": "",
            "total": total,
            "limit": limit,
            "offset": offset,
            "chunks": [_chunk_payload(row, max_chars=max_chars) for row in rows],
        }
        if warning:
            payload["warning"] = warning
        return payload

    def search(
        self,
        q: str,
        *,
        dataset_ids: list[str] | None = None,
        doc_name: str = "",
        doc_id: str = "",
        limit: int = 50,
        max_chars: int = 1200,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            _ensure_tables(conn)
            result = self._search_chunks(
                conn,
                q=q,
                dataset_ids=dataset_ids or [],
                doc_name=doc_name,
                doc_id=doc_id,
                limit=limit,
                max_chars=max_chars,
            )
            if doc_id and int(result.get("count") or 0) == 0:
                document = self.get_document(doc_id)
                if document:
                    result = self._search_chunks(
                        conn,
                        q=q,
                        dataset_ids=[str(document["dataset_id"])],
                        doc_name=str(document["file_name"]),
                        limit=limit,
                        max_chars=max_chars,
                    )
                    result["doc_id"] = doc_id
                    result["warning"] = "doc_id_no_lexical_match_fallback_doc_name"
            return result

    def _search_chunks(
        self,
        conn: sqlite3.Connection,
        *,
        q: str,
        dataset_ids: list[str],
        doc_name: str = "",
        doc_id: str = "",
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
                doc_id=doc_id,
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
        doc_id_clause = ""
        if doc_id:
            doc_id_clause = " AND c.doc_id = ?"
            params.append(doc_id)
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
                  {doc_id_clause}
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
                doc_id=doc_id,
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
                doc_id=doc_id,
                limit=limit,
                max_chars=max_chars,
                warning="fts_no_hits",
            )
        return {
            "query": q,
            "dataset_ids": dataset_ids,
            "doc_name": doc_name,
            "doc_id": doc_id,
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
        doc_id: str,
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
        if doc_id:
            clauses.append("doc_id = ?")
            params.append(doc_id)
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
            "doc_id": doc_id,
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
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(datasets)")}
    if "dataset_scope" not in columns:
        conn.execute("ALTER TABLE datasets ADD COLUMN dataset_scope TEXT DEFAULT 'user'")
    if "module_id" not in columns:
        conn.execute("ALTER TABLE datasets ADD COLUMN module_id TEXT DEFAULT ''")


def _dataset_profile_kinds(conn: sqlite3.Connection, dataset_ids: list[str]) -> dict[str, str]:
    ids = [item for item in dataset_ids if item]
    if not ids:
        return {}
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'les_dataset_profiles' AND type = 'table'",
    ).fetchone()
    if not exists:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT dataset_id, profile_json FROM les_dataset_profiles WHERE dataset_id IN ({placeholders})",
        ids,
    ).fetchall()
    result: dict[str, str] = {}
    for row in rows:
        try:
            profile = json.loads(str(row["profile_json"] or "{}"))
        except Exception:
            profile = {}
        if not isinstance(profile, dict):
            continue
        kind = str(profile.get("dataset_kind") or "").strip()
        result[str(row["dataset_id"] or "")] = kind if kind in DATASET_KIND_LABELS else ""
    return result


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
