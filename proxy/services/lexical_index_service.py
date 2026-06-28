"""SQLite FTS lexical side index for hybrid RAG retrieval."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from backend.interface import Chunk
from backend.rag_config import rag_meta_db_path
from proxy.services.kot_service import extract_norm_refs


TOKEN_RE = re.compile(r"[0-9a-zа-яё.-]{2,}", re.IGNORECASE)

CONTEXT_COLUMNS = {
    "parent_id": "parent_id TEXT DEFAULT ''",
    "parent_ord": "parent_ord INTEGER",
    "child_ord": "child_ord INTEGER",
    "parent_heading": "parent_heading TEXT DEFAULT ''",
    "context_before": "context_before TEXT DEFAULT ''",
    "context_after": "context_after TEXT DEFAULT ''",
    "context_kind": "context_kind TEXT DEFAULT ''",
}


@dataclass
class RetrievalTrace:
    mode: str = "vector"
    vector_count: int = 0
    lexical_count: int = 0
    merged_count: int = 0
    retry_count: int = 0
    fallback_reason: str = ""
    quality_status: str = "unchecked"
    quality_detail: str = ""
    exact_refs: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "vector_count": self.vector_count,
            "lexical_count": self.lexical_count,
            "merged_count": self.merged_count,
            "retry_count": self.retry_count,
            "fallback_reason": self.fallback_reason,
            "quality_status": self.quality_status,
            "quality_detail": self.quality_detail,
            "exact_refs": self.exact_refs,
        }


def lexical_db_path() -> str:
    return os.getenv("RAG_LEXICAL_DB_PATH") or rag_meta_db_path()


def lexical_enabled() -> bool:
    return os.getenv("RAG_HYBRID_RETRIEVAL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def retrieval_fingerprint(chunks: Iterable[Any], limit: int = 8) -> str:
    parts: list[str] = []
    for chunk in list(chunks)[:limit]:
        meta = getattr(chunk, "meta", {}) or {}
        parts.append(
            "|".join(
                [
                    str(getattr(chunk, "doc_name", "")),
                    str(meta.get("point_id") or meta.get("_point_id") or getattr(chunk, "doc_id", "")),
                    content_hash(str(getattr(chunk, "content", "")))[:16],
                ]
            )
        )
    return content_hash("\n".join(parts))


def _connect(db_path: str | None = None) -> sqlite3.Connection:
    path = Path(db_path or lexical_db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_chunk(row: sqlite3.Row, *, score: float = 0.0, extra_meta: dict[str, Any] | None = None) -> Chunk:
    meta = {
        "point_id": row["point_id"],
        "dataset_id": row["dataset_id"],
        "content_hash": row["content_hash"],
        "chunk_ord": row["chunk_ord"],
        "section_heading": row["section_heading"],
        "parent_id": row["parent_id"],
        "parent_ord": row["parent_ord"],
        "child_ord": row["child_ord"],
        "parent_heading": row["parent_heading"],
        "context_before": row["context_before"],
        "context_after": row["context_after"],
        "context_kind": row["context_kind"],
    }
    if extra_meta:
        meta.update(extra_meta)
    return Chunk(
        content=row["text"],
        doc_id=row["doc_id"],
        doc_name=row["doc_name"],
        score=score,
        meta=meta,
    )


NO_STEM_WORDS = {
    "какие", "какой", "какая", "какое", "каких", "каким", "какими",
    "где", "смотреть", "требования", "нормы", "норма", "требование",
    "найти", "пункт", "раздел", "свод", "правил", "гост", "сп",
    "случаях", "случае", "случай", "выполнять", "выполнение", "делать",
    "допускается", "допускать", "почему", "зачем", "что", "кто", "как",
    "когда", "куда", "откуда",
    "нужно", "должно", "следует", "необходимо", "быть", "может", "можно", "ли",
    "или", "для", "при", "под", "над", "все", "всех", "всеми", "чем", "тем", "только"
}


def stem_russian_word(word: str) -> str:
    """A simple, robust Russian stemmer to handle common inflections."""
    if not re.match(r"^[а-яё]+$", word):
        return word
    endings = (
        "иями", "ям", "ыми", "ейший", "ейшая", "ейшее", "ейшие", "ейших",
        "ого", "его", "ому", "ему", "ыми", "ими", "ых", "их", "ою", "ею",
        "ая", "яя", "ое", "ее", "ые", "ие", "ым", "им", "ом", "ем", "ах", "ях",
        "ов", "ев", "ей", "ам", "ям", "ит", "ет", "ут", "ют", "ат", "ят", "ти",
        "а", "ев", "ов", "е", "и", "й", "о", "у", "ы", "ь", "я", "ю", "ию"
    )
    for ending in endings:
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[:-len(ending)]
    return word


def _fts_quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def build_fts_query(question: str) -> str:
    refs = list(extract_norm_refs(question))
    tokens = [
        token.casefold().replace("ё", "е")
        for token in TOKEN_RE.findall(question)
        if len(token) >= 3
    ]
    terms = []
    for item in [*refs, *tokens]:
        normalized = re.sub(r"\s+", " ", item.strip().casefold().replace("ё", "е"))
        if normalized and normalized not in terms:
            terms.append(normalized)
    if not terms:
        return ""
    
    body_terms = []
    ref_terms = []
    for term in terms:
        is_ref = term in refs or any(c.isdigit() or c in " ." for c in term)
        if is_ref:
            ref_terms.append(_fts_quote(term))
        elif term in NO_STEM_WORDS:
            # Completely skip common stop words to prevent them from dominating search ranks
            continue
        elif len(term) >= 4:
            stemmed = stem_russian_word(term)
            if len(stemmed) >= 3 and stemmed.isalpha():
                body_terms.append(f'"{stemmed}"*')
            else:
                body_terms.append(_fts_quote(term))
        else:
            body_terms.append(_fts_quote(term))
            
    clauses = []
    if body_terms:
        # Restrict standard content terms to the body 'text' column
        # to avoid matching filenames and getting short tables boosted
        clauses.append(f"text : ({' OR '.join(body_terms[:12])})")
    if ref_terms:
        # References can match either text or doc_name
        clauses.append(f"({' OR '.join(ref_terms[:6])})")
        
    return " OR ".join(clauses)


class LexicalIndex:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or lexical_db_path()

    def connect(self) -> sqlite3.Connection:
        conn = _connect(self.db_path)
        self.ensure_schema(conn)
        return conn

    @staticmethod
    def ensure_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lexical_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                point_id TEXT NOT NULL,
                dataset_id TEXT DEFAULT '',
                doc_id TEXT DEFAULT '',
                doc_name TEXT DEFAULT '',
                text TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                chunk_ord INTEGER,
                section_heading TEXT DEFAULT '',
                parent_id TEXT DEFAULT '',
                parent_ord INTEGER,
                child_ord INTEGER,
                parent_heading TEXT DEFAULT '',
                context_before TEXT DEFAULT '',
                context_after TEXT DEFAULT '',
                context_kind TEXT DEFAULT '',
                updated_at REAL NOT NULL,
                UNIQUE(collection, point_id)
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS lexical_chunks_fts
            USING fts5(text, doc_name, content='lexical_chunks', content_rowid='id', tokenize='unicode61');
            CREATE TRIGGER IF NOT EXISTS lexical_chunks_ai AFTER INSERT ON lexical_chunks BEGIN
                INSERT INTO lexical_chunks_fts(rowid, text, doc_name) VALUES (new.id, new.text, new.doc_name);
            END;
            CREATE TRIGGER IF NOT EXISTS lexical_chunks_ad AFTER DELETE ON lexical_chunks BEGIN
                INSERT INTO lexical_chunks_fts(lexical_chunks_fts, rowid, text, doc_name)
                VALUES ('delete', old.id, old.text, old.doc_name);
            END;
            CREATE TRIGGER IF NOT EXISTS lexical_chunks_au AFTER UPDATE ON lexical_chunks BEGIN
                INSERT INTO lexical_chunks_fts(lexical_chunks_fts, rowid, text, doc_name)
                VALUES ('delete', old.id, old.text, old.doc_name);
                INSERT INTO lexical_chunks_fts(rowid, text, doc_name) VALUES (new.id, new.text, new.doc_name);
            END;
            CREATE TABLE IF NOT EXISTS lexical_index_meta (
                collection TEXT PRIMARY KEY,
                point_count INTEGER DEFAULT 0,
                indexed_count INTEGER DEFAULT 0,
                cursor_json TEXT DEFAULT '',
                updated_at REAL NOT NULL
            );
            -- Индексы под context_window (добор соседей/родителя): без них SELECT шёл ПОЛНЫМ
            -- сканом таблицы на КАЖДЫЙ чанк → context-фаза 3-4с. С индексом — seek, ~мс.
            CREATE INDEX IF NOT EXISTS idx_lexical_neighbors
                ON lexical_chunks(collection, dataset_id, doc_name, chunk_ord);
            CREATE INDEX IF NOT EXISTS idx_lexical_parent
                ON lexical_chunks(collection, parent_id);
            """
        )
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(lexical_chunks)").fetchall()
        }
        for name, ddl in CONTEXT_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE lexical_chunks ADD COLUMN {ddl}")

    def clear_collection(self, collection: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM lexical_chunks WHERE collection=?", (collection,))
            conn.execute("DELETE FROM lexical_index_meta WHERE collection=?", (collection,))

    def delete_file(self, collection: str, *, dataset_id: str, doc_name: str) -> int:
        """Remove lexical rows for one indexed source file.

        Qdrant reindex deletes points per file; the FTS side index must follow the same
        lifecycle or hybrid/notebook context will keep stale PDF/DOCX chunks.
        """
        if not collection or not dataset_id or not doc_name:
            return 0
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM lexical_chunks WHERE collection=? AND dataset_id=? AND doc_name=?",
                (collection, dataset_id, doc_name),
            )
            return int(cur.rowcount or 0)

    def upsert_chunks(self, collection: str, rows: Iterable[dict[str, Any]]) -> int:
        now = time.time()
        count = 0
        with self.connect() as conn:
            for row in rows:
                text = str(row.get("text") or "")
                point_id = str(row.get("point_id") or "")
                if not text or not point_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO lexical_chunks
                    (
                        collection, point_id, dataset_id, doc_id, doc_name, text, content_hash,
                        chunk_ord, section_heading, parent_id, parent_ord, child_ord,
                        parent_heading, context_before, context_after, context_kind, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(collection, point_id) DO UPDATE SET
                        dataset_id=excluded.dataset_id,
                        doc_id=excluded.doc_id,
                        doc_name=excluded.doc_name,
                        text=excluded.text,
                        content_hash=excluded.content_hash,
                        chunk_ord=excluded.chunk_ord,
                        section_heading=excluded.section_heading,
                        parent_id=excluded.parent_id,
                        parent_ord=excluded.parent_ord,
                        child_ord=excluded.child_ord,
                        parent_heading=excluded.parent_heading,
                        context_before=excluded.context_before,
                        context_after=excluded.context_after,
                        context_kind=excluded.context_kind,
                        updated_at=excluded.updated_at
                    """,
                    (
                        collection,
                        point_id,
                        str(row.get("dataset_id") or ""),
                        str(row.get("doc_id") or ""),
                        str(row.get("doc_name") or row.get("file_name") or ""),
                        text,
                        str(row.get("content_hash") or content_hash(text)),
                        row.get("chunk_ord"),
                        str(row.get("section_heading") or ""),
                        str(row.get("parent_id") or ""),
                        row.get("parent_ord"),
                        row.get("child_ord"),
                        str(row.get("parent_heading") or ""),
                        str(row.get("context_before") or ""),
                        str(row.get("context_after") or ""),
                        str(row.get("context_kind") or ""),
                        now,
                    ),
                )
                count += 1
        return count

    def mark_collection(self, collection: str, *, point_count: int, indexed_count: int, cursor_json: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO lexical_index_meta (collection, point_count, indexed_count, cursor_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(collection) DO UPDATE SET
                    point_count=excluded.point_count,
                    indexed_count=excluded.indexed_count,
                    cursor_json=excluded.cursor_json,
                    updated_at=excluded.updated_at
                """,
                (collection, point_count, indexed_count, cursor_json, time.time()),
            )

    def status(self, collection: str) -> dict[str, Any]:
        with self.connect() as conn:
            meta = conn.execute(
                "SELECT collection, point_count, indexed_count, cursor_json, updated_at FROM lexical_index_meta WHERE collection=?",
                (collection,),
            ).fetchone()
            count = conn.execute("SELECT COUNT(*) AS n FROM lexical_chunks WHERE collection=?", (collection,)).fetchone()["n"]
        point_count = int(meta["point_count"]) if meta else 0
        indexed_count = int(meta["indexed_count"]) if meta else count
        return {
            "ready": count > 0,
            "stale": bool(point_count and count < point_count),
            "collection": collection,
            "chunks": count,
            "point_count": point_count,
            "indexed_count": indexed_count,
            "updated_at": float(meta["updated_at"]) if meta else 0.0,
        }

    def search(
        self,
        question: str,
        *,
        collection: str,
        dataset_ids: list[str] | None = None,
        limit: int = 12,
    ) -> list[Chunk]:
        fts_query = build_fts_query(question)
        if not fts_query:
            return []
        params: list[Any] = [fts_query, collection]
        dataset_clause = ""
        if dataset_ids:
            placeholders = ",".join("?" for _ in dataset_ids)
            dataset_clause = f" AND c.dataset_id IN ({placeholders})"
            params.extend(dataset_ids)
        params.append(limit)
        try:
            with self.connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT
                        c.point_id, c.dataset_id, c.doc_id, c.doc_name, c.text, c.content_hash,
                        c.chunk_ord, c.section_heading, c.parent_id, c.parent_ord, c.child_ord,
                        c.parent_heading, c.context_before, c.context_after, c.context_kind,
                        bm25(lexical_chunks_fts) AS bm25_score
                    FROM lexical_chunks_fts
                    JOIN lexical_chunks c ON c.id = lexical_chunks_fts.rowid
                    WHERE lexical_chunks_fts MATCH ? AND c.collection=? {dataset_clause}
                    ORDER BY bm25_score ASC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            return []

        chunks: list[Chunk] = []
        for index, row in enumerate(rows, 1):
            bm25_score = float(row["bm25_score"] or 0.0)
            chunks.append(
                _row_to_chunk(
                    row,
                    score=1.0 / (index + 1),
                    extra_meta={"lexical_rank": index, "lexical_score": bm25_score},
                )
            )
        return chunks

    def context_window(self, collection: str, chunk: Any, *, radius: int = 1, limit: int = 5,
                       conn: sqlite3.Connection | None = None) -> list[Chunk]:
        """Соседние/родительские чанки. conn задан → переиспользуем (context-фаза открывает
        ОДНО соединение на все чанки: 1×connect+ensure_schema вместо N — это read, схема уже есть)."""
        meta = getattr(chunk, "meta", {}) or {}
        dataset_id = str(meta.get("dataset_id") or "")
        doc_name = str(meta.get("file_name") or getattr(chunk, "doc_name", "") or "")
        parent_id = str(meta.get("parent_id") or "")
        try:
            chunk_ord = int(meta.get("chunk_ord"))
        except (TypeError, ValueError):
            chunk_ord = None

        if not parent_id and (chunk_ord is None or not dataset_id or not doc_name):
            return []

        params: list[Any]
        where: str
        order: str
        if parent_id:
            params = [collection, parent_id, limit]
            where = "collection=? AND parent_id=?"
            order = "COALESCE(chunk_ord, 0) ASC"
        else:
            assert chunk_ord is not None
            params = [collection, dataset_id, doc_name, chunk_ord - radius, chunk_ord + radius, limit]
            where = "collection=? AND dataset_id=? AND doc_name=? AND chunk_ord BETWEEN ? AND ?"
            order = "chunk_ord ASC"

        sql = f"""
                SELECT
                    point_id, dataset_id, doc_id, doc_name, text, content_hash,
                    chunk_ord, section_heading, parent_id, parent_ord, child_ord,
                    parent_heading, context_before, context_after, context_kind
                FROM lexical_chunks
                WHERE {where}
                ORDER BY {order}
                LIMIT ?
                """
        if conn is not None:                       # переиспользуем переданное соединение (read)
            rows = conn.execute(sql, params).fetchall()
        else:
            with self.connect() as own_conn:
                rows = own_conn.execute(sql, params).fetchall()
        return [_row_to_chunk(row) for row in rows]


def merge_rrf(
    vector_chunks: list[Any],
    lexical_chunks: list[Any],
    *,
    question: str,
    limit: int,
    k: int = 60,
) -> tuple[list[Any], RetrievalTrace]:
    refs = list(extract_norm_refs(question))
    scores: dict[str, float] = {}
    chosen: dict[str, Any] = {}

    def key_for(chunk: Any) -> str:
        meta = getattr(chunk, "meta", {}) or {}
        return str(meta.get("content_hash") or content_hash(str(getattr(chunk, "content", ""))))

    def add(chunks: list[Any], weight: float, source: str) -> None:
        for rank, chunk in enumerate(chunks, 1):
            key = key_for(chunk)
            bonus = 0.0
            haystack = f"{getattr(chunk, 'doc_name', '')}\n{getattr(chunk, 'content', '')}".casefold()
            if refs and any(ref.casefold() in haystack for ref in refs):
                bonus = 0.12
            scores[key] = scores.get(key, 0.0) + weight / (k + rank) + bonus
            if key not in chosen or source == "vector":
                chosen[key] = chunk
            try:
                meta = getattr(chosen[key], "meta", None)
                if isinstance(meta, dict):
                    meta.setdefault("retrieval_sources", set()).add(source)
            except Exception:
                pass

    add(vector_chunks, 1.0, "vector")
    add(lexical_chunks, 0.9, "lexical")
    ordered = sorted(chosen, key=lambda key: scores[key], reverse=True)
    merged = [chosen[key] for key in ordered[:limit]]
    for rank, chunk in enumerate(merged, 1):
        meta = getattr(chunk, "meta", None)
        if isinstance(meta, dict):
            sources = meta.get("retrieval_sources")
            if isinstance(sources, set):
                meta["retrieval_sources"] = sorted(sources)
            meta["rrf_rank"] = rank
            meta["rrf_score"] = round(scores[key_for(chunk)], 6)
    trace = RetrievalTrace(
        mode="hybrid" if lexical_chunks else "vector",
        vector_count=len(vector_chunks),
        lexical_count=len(lexical_chunks),
        merged_count=len(merged),
        exact_refs=refs,
    )
    if not lexical_chunks:
        trace.fallback_reason = "lexical_index_empty_or_unavailable"
    return merged, trace
