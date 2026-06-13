"""
qdrant_adapter.py — RAG бэкенд: SQLite метабаза + Qdrant векторная база.

Исправлено по сравнению с оригиналом:
  1. embed_model.get_text_embedding → прямой httpx к MLX /v1/embeddings (нет зависимости от llama-index OpenAIEmbedding)
  2. retrieve → тоже прямой httpx (не блокирует event loop)
  3. _sync_parse батч эмбеддингов по 32 чанка вместо по одному — в 10-30x быстрее
  4. pending_names матчинг по полному rel-пути, не только file.name (дубли в разных папках)
  5. MarkdownNodeParser создаётся один раз, не на каждый файл
  6. Пустые чанки (< 20 символов) фильтруются до эмбеддинга
  7. retrieve: get_query_embedding синхронный в asyncio → заменён на async httpx
  8. _ensure_collection: race condition при параллельных startup вызовах → asyncio.Lock
"""
import asyncio
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import qdrant_client
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import Document, TextNode
from qdrant_client import models

from .converter import convert_to_markdown
from .document_router import DocumentRoute, route_document
from .interface import Chunk, DatasetInfo, RAGBackend
from .mail_profile import build_mail_vector_profile, deterministic_mail_node_id
from .parquet_writer import TableNormalizer
from .rag_config import (
    chunking_config,
    rag_chunk_overlap,
    rag_chunk_size,
    rag_collection_name,
    rag_meta_db_path,
    rag_vector_size,
)

logger = logging.getLogger(__name__)


class StructureAwareSplitter:
    """Structure-aware chunking for SP and GOST documents.
    Preserves numbered clauses (e.g. 5.2.1) as single indivisible blocks.
    Fits chunks within a target character length, and implements sentence-bounded overlap.
    """
    def __init__(self, chunk_size: int, chunk_overlap: int, len_fn=None):
        # W2.1 (ADR-7): len_fn — счётчик размера (токены эмбеддера); None = символы.
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._len = len_fn or len
        # Жёсткая нарезка патологически длинных предложений — всегда в символах:
        # при токенном режиме берём ~3 символа на токен (русский текст).
        self._hard_slice_chars = chunk_size if len_fn is None else chunk_size * 3
        self.fallback = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        
        # Regex to detect lines that start a new numbered section or markdown header
        self.boundary_pattern = re.compile(
            r"^(?:#{1,6}\s+|"
            r"(?:Пункт|Раздел|Статья|п\.|§)\s*\d+(?:\.\d+)+|"
            r"\d+(?:\.\d+)+(?:\s+|\.|$))",
            re.IGNORECASE
        )

    def _split_into_atomic_blocks(self, text: str) -> list[str]:
        lines = text.split("\n")
        blocks = []
        current_block_lines = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_block_lines:
                    current_block_lines.append(line)
                continue
                
            if self.boundary_pattern.match(stripped):
                if current_block_lines:
                    blocks.append("\n".join(current_block_lines).strip())
                    current_block_lines = []
            
            current_block_lines.append(line)
            
        if current_block_lines:
            blocks.append("\n".join(current_block_lines).strip())
            
        return [b for b in blocks if b]

    def _get_sentence_overlap(self, text_prev: str, max_overlap: int) -> str:
        if not text_prev or max_overlap <= 0:
            return ""
        sentences = re.split(r'(?<=[.!?])\s+', text_prev)
        overlap_sentences = []
        current_len = 0
        for s in reversed(sentences):
            s = s.strip()
            if not s:
                continue
            if current_len + self._len(s) + 1 <= max_overlap:
                overlap_sentences.append(s)
                current_len += self._len(s) + 1
            else:
                if not overlap_sentences:
                    return s[-max_overlap * (1 if self._len is len else 3):]
                break
        if not overlap_sentences:
            return ""
        return " ".join(reversed(overlap_sentences)) + " "

    def _split_large_block(self, text: str, max_chars: int, overlap_chars: int) -> list[str]:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = []
        current_len = 0
        
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            s_len = self._len(s)

            if s_len > max_chars:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_len = 0
                hard_max = self._hard_slice_chars
                hard_overlap = min(overlap_chars * (1 if self._len is len else 3), hard_max // 4)
                raw_len = len(s)
                i = 0
                while i < raw_len:
                    chunks.append(s[i:i + hard_max])
                    i += hard_max - hard_overlap
                    if i + hard_overlap >= raw_len:
                        if i < raw_len:
                            chunks.append(s[i:])
                        break
            else:
                separator_len = 1 if current_chunk else 0
                if current_len + separator_len + s_len <= max_chars:
                    current_chunk.append(s)
                    current_len += separator_len + s_len
                else:
                    chunks.append(" ".join(current_chunk))
                    overlap_prefix = self._get_sentence_overlap(chunks[-1], overlap_chars)
                    current_chunk = []
                    current_len = 0
                    if overlap_prefix:
                        current_chunk.append(overlap_prefix.strip())
                        current_len = self._len(overlap_prefix.strip())

                    separator_len = 1 if current_chunk else 0
                    current_chunk.append(s)
                    current_len += separator_len + s_len
                    
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        return chunks

    def get_nodes_from_documents(self, documents: list) -> list:
        all_nodes = []
        for doc in documents:
            text = doc.text
            metadata = doc.metadata or {}
            doc_id = doc.node_id if hasattr(doc, "node_id") else doc.id_
            
            atomic_blocks = self._split_into_atomic_blocks(text)
            
            chunks = []
            current_chunk_blocks = []
            current_chunk_len = 0
            
            for block in atomic_blocks:
                block_len = self._len(block)
                
                if block_len > self.chunk_size:
                    if current_chunk_blocks:
                        chunks.append("\n\n".join(current_chunk_blocks))
                        current_chunk_blocks = []
                        current_chunk_len = 0
                    
                    sub_chunks = self._split_large_block(block, self.chunk_size, self.chunk_overlap)
                    chunks.extend(sub_chunks)
                else:
                    separator_len = 2 if current_chunk_blocks else 0
                    if current_chunk_len + separator_len + block_len <= self.chunk_size:
                        current_chunk_blocks.append(block)
                        current_chunk_len += separator_len + block_len
                    else:
                        chunks.append("\n\n".join(current_chunk_blocks))
                        overlap_prefix = self._get_sentence_overlap(chunks[-1], self.chunk_overlap)
                        
                        current_chunk_blocks = []
                        current_chunk_len = 0
                        if overlap_prefix:
                            current_chunk_blocks.append(overlap_prefix.strip())
                            current_chunk_len = self._len(overlap_prefix.strip())
                            
                        separator_len = 2 if current_chunk_blocks else 0
                        current_chunk_blocks.append(block)
                        current_chunk_len += separator_len + block_len
            
            if current_chunk_blocks:
                chunks.append("\n\n".join(current_chunk_blocks))
                
            for idx, chunk_text in enumerate(chunks):
                node = TextNode(
                    text=chunk_text,
                    id_=f"{doc_id}_chunk_{idx}",
                    metadata=metadata
                )
                all_nodes.append(node)
                
        return all_nodes

EMBED_BATCH  = int(os.getenv("RAG_EMBED_BATCH", "32"))      # чанков за один запрос к MLX embeddings
MIN_CHUNK    = int(os.getenv("RAG_MIN_CHUNK_CHARS", "100"))  # W2.5: <100 симв — шум («Приложение», «А»), не индексируем
UPSERT_BATCH = int(os.getenv("RAG_UPSERT_BATCH", "100"))    # точек за один upsert в Qdrant
VERIFY_POINTS_EVERY = max(1, int(os.getenv("RAG_VERIFY_POINTS_EVERY", "10")))  # W1.2: exact-count каждый N-й файл
# W1.4: конвейер — конвертация следующего файла параллельно с эмбеддингом текущего,
# per-file таймаут конвертации (зависший файл помечается ERROR, индексация продолжается).
PARSE_PREFETCH = os.getenv("RAG_PARSE_PREFETCH", "true").lower() == "true"
PARSE_FILE_TIMEOUT = float(os.getenv("RAG_PARSE_FILE_TIMEOUT_SEC", "1800"))
CHUNK_HASH_CACHE = os.getenv("RAG_CHUNK_HASH_CACHE", "true").lower() in {"1", "true", "yes", "on"}
RAG_CHUNK_SIZE = rag_chunk_size()
RAG_CHUNK_OVERLAP = rag_chunk_overlap()
ALLOW_UNBOUNDED_PARSE = "ALLOW_UNBOUNDED_PARSE"


def _content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _embedding_cache_descriptor() -> dict[str, str]:
    backend = os.getenv("EMBED_BACKEND", "sentence_transformers").strip().lower()
    descriptor = {
        "backend": backend,
        "model_id": os.getenv("EMBEDDING_MODEL") or os.getenv("EMBED_MODEL", ""),
        "profile": os.getenv("LES_EMBED_PROFILE", ""),
        "vector_size": str(rag_vector_size()),
    }
    if backend == "coreml":
        descriptor.update(
            {
                "coreml_model": os.getenv("COREML_EMBED_MODEL", ""),
                "coreml_seq_len": os.getenv("COREML_EMBED_SEQ_LEN", ""),
                "coreml_compute_units": os.getenv("COREML_EMBED_COMPUTE_UNITS", ""),
                "coreml_fallback": os.getenv("COREML_EMBED_FALLBACK", ""),
            }
        )
    return descriptor


def _embedding_cache_fingerprint(descriptor: dict[str, str] | None = None) -> str:
    data = descriptor or _embedding_cache_descriptor()
    stable = "\n".join(f"{key}={data.get(key, '')}" for key in sorted(data))
    return hashlib.sha1(stable.encode("utf-8", errors="ignore")).hexdigest()


_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.{2,160})$")
_NUM_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,4})[.\s]+([А-ЯЁA-Z].{1,150})$")


def _section_heading_info(text: str) -> tuple[str, int]:
    """W2.5: (заголовок, уровень). Уровень: # → 1..6; «5.2.1 Текст» → глубина номера; 0 — нет."""
    for line in text.splitlines()[:6]:
        line = line.strip()
        if not line:
            continue
        md = _MD_HEADING_RE.match(line)
        if md:
            return md.group(2).strip(), len(md.group(1))
        num = _NUM_HEADING_RE.match(line)
        if num:
            return f"{num.group(1)} {num.group(2).strip()}", num.group(1).count(".") + 1
    return "", 0


def _section_heading(text: str) -> str:
    heading, _ = _section_heading_info(text)
    if heading:
        return heading
    # Старое поведение как fallback: первая осмысленная строка.
    for line in text.splitlines():
        line = line.strip(" #\t")
        if 4 <= len(line) <= 160:
            return line
    return ""


def _compact_text(text: str, limit: int = 1200) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _apply_context_metadata_to_nodes(file_nodes: list[dict], dataset_id: str, file_key: str) -> None:
    if not file_nodes:
        return

    grouped: dict[str, list[int]] = {}
    try:
        window_size = max(1, int(os.getenv("RAG_PARENT_WINDOW_CHUNKS", "4")))
    except ValueError:
        window_size = 4
    last_heading = ""
    last_level = 0
    for chunk_ord, file_node in enumerate(file_nodes):
        payload = file_node.setdefault("payload", {})
        text = str(file_node.get("text") or "")
        payload.setdefault("chunk_ord", chunk_ord)
        payload.setdefault("child_ord", chunk_ord)
        payload.setdefault("content_hash", _content_hash(text))
        # W2.5: настоящий заголовок (markdown/нумерованный) с уровнем; чанки-продолжения
        # наследуют последний найденный заголовок раздела.
        heading, level = _section_heading_info(text)
        if heading:
            last_heading, last_level = heading, level
            payload.setdefault("section_heading", heading)
            payload.setdefault("heading_level", level)
        elif last_heading:
            payload.setdefault("section_heading", last_heading)
            payload.setdefault("heading_level", last_level)
            payload.setdefault("heading_inherited", True)
        else:
            payload.setdefault("section_heading", _section_heading(text))

        source_page = payload.get("source_page") or payload.get("page") or payload.get("page_number")
        table_index = payload.get("table_index")
        if source_page is not None:
            group_key = f"page:{source_page}:table:{table_index or ''}"
            context_kind = "table_page" if payload.get("type") == "table_row" else "pdf_page"
        else:
            group_key = f"window:{chunk_ord // window_size}"
            context_kind = "markdown_window"
        grouped.setdefault(group_key, []).append(chunk_ord)
        payload.setdefault("context_kind", context_kind)

    for parent_ord, (group_key, indexes) in enumerate(grouped.items()):
        parent_id = _content_hash(f"{dataset_id}:{file_key}:{group_key}")[:24]
        heading = ""
        for idx in indexes:
            candidate = str(file_nodes[idx].get("payload", {}).get("section_heading") or "")
            if candidate:
                heading = candidate
                break
        for idx in indexes:
            payload = file_nodes[idx].setdefault("payload", {})
            payload.setdefault("parent_id", parent_id)
            payload.setdefault("parent_ord", parent_ord)
            payload.setdefault("parent_heading", heading)

    for idx, file_node in enumerate(file_nodes):
        payload = file_node.setdefault("payload", {})
        parent_id = payload.get("parent_id")
        if idx > 0 and file_nodes[idx - 1].get("payload", {}).get("parent_id") == parent_id:
            payload.setdefault("context_before", _compact_text(str(file_nodes[idx - 1].get("text") or "")))
        if idx + 1 < len(file_nodes) and file_nodes[idx + 1].get("payload", {}).get("parent_id") == parent_id:
            payload.setdefault("context_after", _compact_text(str(file_nodes[idx + 1].get("text") or "")))
# ── Прямой клиент эмбеддингов (httpx, без llama-index) ───────────────────────

class EmbedClient:
    """
    Тонкий клиент к /v1/embeddings MLX Host.
    Работает асинхронно и синхронно (для _sync_parse в threadpool).
    """
    def __init__(self, base_url: str, model: str = "bge-m3"):
        self.url   = f"{base_url.rstrip('/')}/v1/embeddings"
        self.model = model

    def encode_sync(self, texts: List[str]) -> List[List[float]]:
        """Синхронный вариант для вызова из threadpool."""
        import httpx as _httpx
        r = _httpx.post(
            self.url,
            json={"model": self.model, "input": texts},
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()["data"]
        data.sort(key=lambda x: x["index"])
        return [d["embedding"] for d in data]

    async def encode_async(self, texts: List[str]) -> List[List[float]]:
        """Асинхронный вариант для retrieve."""
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                self.url,
                json={"model": self.model, "input": texts},
            )
            r.raise_for_status()
            data = r.json()["data"]
            data.sort(key=lambda x: x["index"])
            return [d["embedding"] for d in data]


# ── SQLite метабаза ───────────────────────────────────────────────────────────

class MetaDB:
    def __init__(self, db_path: str | None = None):
        db_path = db_path or rag_meta_db_path()
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id          TEXT PRIMARY KEY,
                    name        TEXT,
                    status      TEXT,
                    chunk_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id          TEXT PRIMARY KEY,
                    dataset_id  TEXT,
                    file_name   TEXT,
                    status      TEXT,
                    file_hash   TEXT,
                    file_mtime  REAL,
                    file_size   INTEGER,
                    chunk_count INTEGER DEFAULT 0
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_docs_dataset ON documents(dataset_id)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS structured_rules (
                    id          TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    file_key    TEXT NOT NULL,
                    chunk_id    TEXT NOT NULL,
                    subject     TEXT NOT NULL,
                    parameter   TEXT NOT NULL,
                    operator    TEXT NOT NULL,
                    value       REAL NOT NULL,
                    unit        TEXT NOT NULL,
                    condition   TEXT,
                    char_start  INTEGER NOT NULL,
                    char_end    INTEGER NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rules_doc ON structured_rules(document_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rules_file ON structured_rules(file_key)"
            )
            # Миграция существующих БД
            for col, typedef in [
                ("file_hash",   "TEXT"),
                ("file_mtime",  "REAL"),
                ("file_size",   "INTEGER"),
                ("chunk_count", "INTEGER DEFAULT 0"),
                ("domain",      "TEXT DEFAULT ''"),
                ("route_dataset", "TEXT DEFAULT ''"),
                ("doc_type",    "TEXT DEFAULT ''"),
                ("content_type", "TEXT DEFAULT ''"),
                ("complexity",   "TEXT DEFAULT ''"),
                ("pipeline",     "TEXT DEFAULT ''"),
                ("last_error",   "TEXT DEFAULT ''"),
                ("stage",        "TEXT DEFAULT ''"),  # W1.4: текущая стадия конвейера (CONVERT/EMBED/UPSERT)
            ]:
                try:
                    conn.execute(f"ALTER TABLE documents ADD COLUMN {col} {typedef}")
                except Exception:
                    pass
            try:
                conn.execute("ALTER TABLE datasets ADD COLUMN chunk_count INTEGER DEFAULT 0")
            except Exception:
                pass

    def create_dataset(self, name: str) -> str:
        ds_id = str(uuid.uuid4())
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO datasets (id, name, status) VALUES (?, ?, 'IDLE')",
                (ds_id, name),
            )
        return ds_id

    def update_dataset_status(self, dataset_id: str, status: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE datasets SET status=? WHERE id=?", (status, dataset_id)
            )

    def recover_interrupted_parsing(self) -> int:
        with self._get_conn() as conn:
            cur = conn.execute("UPDATE datasets SET status='IDLE' WHERE status='PARSING'")
            return int(cur.rowcount or 0)

    def list_datasets(self) -> List[DatasetInfo]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT d.id, d.name, d.status, d.chunk_count,
                       SUM(CASE WHEN doc.status='INDEXED' THEN 1 ELSE 0 END) as indexed_count
                FROM datasets d
                LEFT JOIN documents doc ON d.id = doc.dataset_id
                GROUP BY d.id
            """).fetchall()
        return [
            DatasetInfo(
                id=r["id"], name=r["name"], status=r["status"],
                doc_count=r["indexed_count"] or 0,
                chunk_count=r["chunk_count"] or 0,
            )
            for r in rows
        ]

    def add_document(
        self, dataset_id: str, file_name: str,
        file_mtime: float = 0.0, file_size: int = 0,
    ) -> tuple:
        """Возвращает (doc_id, is_new, needs_reindex)."""
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id, file_mtime, file_size FROM documents "
                "WHERE dataset_id=? AND file_name=?",
                (dataset_id, file_name),
            ).fetchone()
            if existing:
                doc_id  = existing["id"]
                changed = (
                    abs((existing["file_mtime"] or 0) - file_mtime) > 1.0
                    or (existing["file_size"] or 0) != file_size
                )
                if changed:
                    conn.execute(
                        "UPDATE documents SET status='PENDING', file_mtime=?, file_size=? WHERE id=?",
                        (file_mtime, file_size, doc_id),
                    )
                    return doc_id, False, True
                return doc_id, False, False
            doc_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO documents (id, dataset_id, file_name, status, file_mtime, file_size) "
                "VALUES (?, ?, ?, 'PENDING', ?, ?)",
                (doc_id, dataset_id, file_name, file_mtime, file_size),
            )
            return doc_id, True, True

    def update_document_status(
        self,
        dataset_id: str,
        file_name: str,
        status: str,
        chunk_count: int = 0,
        route: DocumentRoute | None = None,
        last_error: str = "",
    ):
        with self._get_conn() as conn:
            fields = ["status=?", "chunk_count=?", "last_error=?", "stage=''"]
            values: list[Any] = [status, chunk_count, last_error[:2000]]
            if route is not None:
                fields.extend([
                    "domain=?",
                    "route_dataset=?",
                    "doc_type=?",
                    "content_type=?",
                    "complexity=?",
                    "pipeline=?",
                ])
                values.extend([
                    route.domain,
                    route.dataset_name,
                    route.doc_type,
                    route.content_type,
                    route.complexity,
                    route.pipeline,
                ])
            values.extend([dataset_id, file_name])
            cur = conn.execute(
                f"UPDATE documents SET {', '.join(fields)} "
                "WHERE dataset_id=? AND file_name=?",
                values,
            )
            if cur.rowcount != 1:
                raise RuntimeError(
                    f"document status update affected {cur.rowcount} rows "
                    f"for dataset_id={dataset_id}, file_name={file_name}"
                )

    def update_document_stage(self, dataset_id: str, file_name: str, stage: str) -> None:
        """W1.4: текущая стадия конвейера файла (CONVERT/EMBED/UPSERT) — для прогресса/диагностики."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE documents SET stage=? WHERE dataset_id=? AND file_name=?",
                (stage, dataset_id, file_name),
            )

    def update_document_route(self, dataset_id: str, file_name: str, route: DocumentRoute):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE documents SET domain=?, route_dataset=?, doc_type=?, content_type=?, complexity=?, pipeline=? "
                "WHERE dataset_id=? AND file_name=?",
                (
                    route.domain,
                    route.dataset_name,
                    route.doc_type,
                    route.content_type,
                    route.complexity,
                    route.pipeline,
                    dataset_id,
                    file_name,
                ),
            )

    def update_dataset_chunk_count(self, dataset_id: str):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(chunk_count),0) as total FROM documents "
                "WHERE dataset_id=? AND status='INDEXED'",
                (dataset_id,),
            ).fetchone()
            conn.execute(
                "UPDATE datasets SET chunk_count=? WHERE id=?",
                (row["total"] if row else 0, dataset_id),
            )

    def get_pending_files(self, dataset_id: str, limit: int | None = None) -> List[str]:
        sql = (
            "SELECT file_name FROM documents WHERE dataset_id=? AND status='PENDING' "
            "ORDER BY COALESCE(NULLIF(file_size, 0), 9223372036854775807), file_name"
        )
        params: list[Any] = [dataset_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(0, int(limit)))
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [r["file_name"] for r in rows]

    def health_snapshot(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            dataset_rows = conn.execute("""
                SELECT d.id, d.name, d.status, d.chunk_count,
                       COUNT(doc.id) AS total_files,
                       SUM(CASE WHEN doc.status='INDEXED' THEN 1 ELSE 0 END) AS indexed_files,
                       SUM(CASE WHEN doc.status='PENDING' THEN 1 ELSE 0 END) AS pending_files,
                       SUM(CASE WHEN doc.status='ERROR' THEN 1 ELSE 0 END) AS error_files,
                       COALESCE(SUM(CASE WHEN doc.status='INDEXED' THEN doc.chunk_count ELSE 0 END), 0) AS indexed_chunks
                FROM datasets d
                LEFT JOIN documents doc ON d.id = doc.dataset_id
                GROUP BY d.id
                ORDER BY d.name
            """).fetchall()
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS files, COALESCE(SUM(chunk_count),0) AS chunks "
                "FROM documents GROUP BY status"
            ).fetchall()
            route_rows = conn.execute("""
                SELECT COALESCE(NULLIF(domain, ''), 'UNCLASSIFIED') AS domain,
                       COUNT(*) AS files,
                       COALESCE(SUM(chunk_count),0) AS chunks
                FROM documents
                GROUP BY COALESCE(NULLIF(domain, ''), 'UNCLASSIFIED')
                ORDER BY files DESC
            """).fetchall()
            doc_type_rows = conn.execute("""
                SELECT COALESCE(NULLIF(doc_type, ''), 'UNCLASSIFIED') AS doc_type,
                       COUNT(*) AS files,
                       COALESCE(SUM(chunk_count),0) AS chunks
                FROM documents
                GROUP BY COALESCE(NULLIF(doc_type, ''), 'UNCLASSIFIED')
                ORDER BY files DESC
            """).fetchall()

        datasets = [
            {
                "id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "files": row["total_files"] or 0,
                "indexed_files": row["indexed_files"] or 0,
                "pending_files": row["pending_files"] or 0,
                "error_files": row["error_files"] or 0,
                "chunks": row["indexed_chunks"] or 0,
            }
            for row in dataset_rows
        ]
        totals = {
            "datasets": len(datasets),
            "files": sum(item["files"] for item in datasets),
            "indexed_files": sum(item["indexed_files"] for item in datasets),
            "pending_files": sum(item["pending_files"] for item in datasets),
            "error_files": sum(item["error_files"] for item in datasets),
            "chunks": sum(item["chunks"] for item in datasets),
        }
        return {
            "status": self._rag_status(totals, datasets),
            "totals": totals,
            "by_status": {
                row["status"]: {"files": row["files"], "chunks": row["chunks"]}
                for row in status_rows
            },
            "by_domain": {
                row["domain"]: {"files": row["files"], "chunks": row["chunks"]}
                for row in route_rows
            },
            "by_doc_type": {
                row["doc_type"]: {"files": row["files"], "chunks": row["chunks"]}
                for row in doc_type_rows
            },
            "datasets": datasets,
        }

    def _rag_status(self, totals: Dict[str, int], datasets: list[dict]) -> str:
        if totals["files"] == 0:
            return "empty"
        if totals["indexed_files"] == 0:
            return "not_indexed"
        if totals["pending_files"] or totals["error_files"]:
            return "degraded"
        if any(dataset["status"] not in ("COMPLETED", "IDLE") for dataset in datasets):
            return "degraded"
        return "ready"

    def insert_structured_rules(self, rules: List[Dict[str, Any]]) -> None:
        if not rules:
            return
        with self._get_conn() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO structured_rules (
                    id, document_id, file_key, chunk_id, subject, parameter, operator, value, unit, condition, char_start, char_end
                ) VALUES (
                    :id, :document_id, :file_key, :chunk_id, :subject, :parameter, :operator, :value, :unit, :condition, :char_start, :char_end
                )
            """, rules)

    def get_structured_rules(self, document_id: Optional[str] = None, file_key: Optional[str] = None) -> List[sqlite3.Row]:
        query = "SELECT * FROM structured_rules WHERE 1=1"
        params = []
        if document_id:
            query += " AND document_id = ?"
            params.append(document_id)
        if file_key:
            query += " AND file_key = ?"
            params.append(file_key)
        
        with self._get_conn() as conn:
            return conn.execute(query, params).fetchall()

    def clear_structured_rules(self, file_key: str) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM structured_rules WHERE file_key = ?", (file_key,))


# ── Основной адаптер ──────────────────────────────────────────────────────────

class QdrantLlamaIndexAdapter(RAGBackend):
    def __init__(
        self,
        qdrant_url:       str,
        mlx_url:       str,
        embed_model_name: str,
        content_dir:      str = "./storage/datasets",
    ):
        self.content_dir     = Path(content_dir)
        self.content_dir.mkdir(parents=True, exist_ok=True)
        self.db              = MetaDB()
        recovered = self.db.recover_interrupted_parsing()
        if recovered:
            logger.info("[INIT] Recovered %s interrupted parsing dataset(s)", recovered)
        self.aclient         = qdrant_client.AsyncQdrantClient(url=qdrant_url, timeout=60.0)
        self.qdrant_url      = qdrant_url
        self.embed           = EmbedClient(mlx_url, model=embed_model_name.replace(":latest", ""))
        self.collection_name = rag_collection_name()
        self.vector_size     = rag_vector_size()
        self._collection_ready = False
        self._collection_lock  = asyncio.Lock()

    # ── Служебные ─────────────────────────────────────────────────────────────

    async def _ensure_collection(self):
        if self._collection_ready:
            return
        async with self._collection_lock:
            if self._collection_ready:
                return
            try:
                await self.aclient.get_collection(self.collection_name)
            except Exception:
                logger.info(f"[INIT] Создаём коллекцию {self.collection_name}")
                await self.aclient.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.vector_size, distance=models.Distance.COSINE
                    ),
                )
            self._collection_ready = True

    async def health(self) -> bool:
        try:
            await self._ensure_collection()
            return True
        except Exception:
            return False

    async def health_snapshot(self) -> Dict[str, Any]:
        ok = await self.health()
        snapshot = self.db.health_snapshot()
        snapshot["qdrant"] = {"ok": ok, "collection": self.collection_name}
        if ok:
            try:
                collection = await self.aclient.get_collection(self.collection_name)
                points = collection.points_count or 0
                snapshot["qdrant"]["points"] = points
                expected_chunks = snapshot.get("totals", {}).get("chunks") or 0
                snapshot["qdrant"]["points_match_sqlite_chunks"] = points == expected_chunks
                if points != expected_chunks:
                    snapshot["qdrant"]["mismatch"] = {
                        "sqlite_chunks": expected_chunks,
                        "qdrant_points": points,
                    }
                    snapshot["status"] = "degraded"
            except Exception as error:
                snapshot["qdrant"].update({"ok": False, "error": str(error)})
        return snapshot

    # ── RAGBackend interface ───────────────────────────────────────────────────

    async def list_datasets(self) -> List[DatasetInfo]:
        return self.db.list_datasets()

    async def create_dataset(self, name: str) -> str:
        return self.db.create_dataset(name)

    async def upload_file(self, dataset_id: str, file_path: Path, relative_path: Optional[str] = None) -> str:
        dest_dir  = self.content_dir / dataset_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        rel_name = relative_path or file_path.name
        rel_path = Path(rel_name)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValueError(f"unsafe relative path: {rel_name}")
        dest_file = dest_dir / rel_path
        dest_file.parent.mkdir(parents=True, exist_ok=True)

        stat  = file_path.stat() if file_path.exists() else None
        mtime = stat.st_mtime if stat else 0.0
        size  = stat.st_size  if stat else 0

        if file_path.exists() and file_path != dest_file:
            await asyncio.to_thread(shutil.copy2, file_path, dest_file)

        doc_id, _, needs_reindex = self.db.add_document(
            dataset_id, rel_path.as_posix(), file_mtime=mtime, file_size=size
        )
        try:
            route_source = dest_file if dest_file.exists() else file_path
            route = route_document(route_source)
            if needs_reindex:
                self.db.update_document_status(dataset_id, rel_path.as_posix(), "PENDING", 0, route=route)
            else:
                self.db.update_document_route(dataset_id, rel_path.as_posix(), route)
        except Exception as error:
            logger.warning("[DOC_ROUTE] upload classification skipped for %s: %s", rel_path.as_posix(), error)
        return doc_id

    async def parse_dataset(self, dataset_id: str, limit: int | None = None) -> Dict[str, Any]:
        if limit is None and os.getenv(ALLOW_UNBOUNDED_PARSE, "").lower() not in ("1", "true", "yes"):
            return {
                "status": "rejected",
                "error": (
                    "unbounded parse is disabled; use parse_dataset(..., limit=N) "
                    f"or set {ALLOW_UNBOUNDED_PARSE}=1 explicitly"
                ),
            }
        await self._ensure_collection()
        self.db.update_dataset_status(dataset_id, "PARSING")
        res = await asyncio.to_thread(self._sync_parse, dataset_id, limit)
        status = "COMPLETED" if res.get("status") == "completed" else "ERROR"
        if res.get("errors", 0) > 0:
            status = "ERROR"
        if res.get("remaining_pending", 0) > 0 and status == "COMPLETED":
            status = "IDLE" if limit is not None else "PARSING"
        self.db.update_dataset_status(dataset_id, status)
        return res

    def _sync_parse(self, dataset_id: str, limit: int | None = None) -> Dict[str, Any]:
        """
        Синхронный парсинг в threadpool.
        Батч-эмбеддинги: 32 чанка за запрос вместо по одному.
        """
        import time as _t
        t0 = _t.time()
        timings = {
            "delete_sec": 0.0,
            "route_sec": 0.0,
            "convert_sec": 0.0,
            "chunk_sec": 0.0,
            "embed_sec": 0.0,
            "upsert_sec": 0.0,
            "count_sec": 0.0,
            "cache_sec": 0.0,
            "db_sec": 0.0,
        }

        def _add_timing(key: str, started: float) -> None:
            timings[key] = timings.get(key, 0.0) + (_t.time() - started)

        data_dir = self.content_dir / dataset_id
        if not data_dir.exists():
            return {"status": "error", "msg": "dir missing"}

        md_parser = MarkdownNodeParser()
        # W2.1 (ADR-7): чанкинг в токенах эмбеддера (RAG_CHUNK_UNIT=chars вернёт символы).
        _chunking = chunking_config()
        splitter = StructureAwareSplitter(
            chunk_size=_chunking["chunk_size"],
            chunk_overlap=_chunking["chunk_overlap"],
            len_fn=_chunking["len_fn"],
        )
        logger.info(
            "[CHUNK] unit=%s size=%s overlap=%s",
            _chunking["unit"], _chunking["chunk_size"], _chunking["chunk_overlap"],
        )

        try:
            pending_names = set(self.db.get_pending_files(dataset_id, limit=limit))
            all_files     = [
                f for f in data_dir.rglob("*")
                if f.is_file() and "_parquet" not in f.relative_to(data_dir).parts
            ]

            if not pending_names:
                return {
                    "status": "completed",
                    "chunks": 0,
                    "files_parsed": 0,
                    "files_skipped": len(all_files),
                    "remaining_pending": 0,
                    "errors": 0,
                    "elapsed_sec": 0,
                }

            sync_qdrant = qdrant_client.QdrantClient(
                url=self.qdrant_url,
                timeout=60.0
            )

            # Матчинг по относительному пути и по имени файла для совместимости
            # со старыми записями БД где хранится только f.name.
            exact_pending_names = {
                str(f.relative_to(data_dir))
                for f in all_files
                if str(f.relative_to(data_dir)) in pending_names
            }
            legacy_pending_names = pending_names - exact_pending_names
            files_to_parse = [
                f for f in all_files
                if str(f.relative_to(data_dir)) in pending_names
                or f.name in legacy_pending_names
            ]

            total     = len(files_to_parse)
            total_all = len(all_files)
            logger.info(f"[PARSE] {total}/{total_all} файлов к индексации")

            if total == 0:
                return {"status": "completed", "chunks": 0, "skipped": total_all}

            total_chunks = 0
            errors       = 0
            embedding_cache_hits = 0
            embedded_chunks = 0
            embedding_descriptor = _embedding_cache_descriptor()
            embedding_fingerprint = _embedding_cache_fingerprint(embedding_descriptor)

            # W1.4: конвейер — пока текущий файл эмбеддится/апсертится, следующий конвертируется
            # в фоновом потоке. OCR-файлы конвертируются в основном потоке (VLM не гоняем
            # параллельно с эмбеддером).
            convert_pool = (
                ThreadPoolExecutor(max_workers=1, thread_name_prefix="les-convert")
                if PARSE_PREFETCH and total > 1
                else None
            )
            _set_stage = getattr(self.db, "update_document_stage", None)

            def _stage(db_key: str, stage: str) -> None:
                if _set_stage is None:
                    return
                try:
                    _set_stage(dataset_id, db_key, stage)
                except Exception:
                    pass

            def _submit_convert(index: int):
                f = files_to_parse[index]
                fk = f.relative_to(data_dir).as_posix()
                local_timings: dict = {}
                future = convert_pool.submit(
                    QdrantLlamaIndexAdapter._convert_file, self, f, data_dir, fk, dataset_id,
                    md_parser, splitter, local_timings, False,
                )
                return future, local_timings

            next_convert = _submit_convert(0) if convert_pool else None

            for i, file_path in enumerate(files_to_parse, 1):
                file_key = file_path.relative_to(data_dir).as_posix()
                db_file_key = file_key if file_key in pending_names else file_path.name
                if i % 50 == 0 or i == total:
                    logger.info(f"[PARSE] {i}/{total} ({_t.time()-t0:.0f}с)")
                try:
                    _stage(db_file_key, "CONVERT")
                    if next_convert is not None:
                        future, local_timings = next_convert
                        try:
                            route, file_nodes = future.result(timeout=PARSE_FILE_TIMEOUT)
                        except FuturesTimeoutError:
                            # Зависший конвертер бросаем вместе с пулом; индексация продолжается.
                            convert_pool.shutdown(wait=False, cancel_futures=True)
                            convert_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="les-convert")
                            raise RuntimeError(
                                f"convert timeout: >{PARSE_FILE_TIMEOUT:.0f}s (поток конвертации брошен)"
                            )
                        finally:
                            for key, val in local_timings.items():
                                timings[key] = timings.get(key, 0.0) + val
                            next_convert = _submit_convert(i) if i < total else None
                        if file_nodes is None:
                            # OCR-конвейер: конвертируем синхронно в основном потоке.
                            route, file_nodes = QdrantLlamaIndexAdapter._convert_file(
                                self, file_path, data_dir, file_key, dataset_id,
                                md_parser, splitter, timings, True,
                            )
                    else:
                        route, file_nodes = QdrantLlamaIndexAdapter._convert_file(
                            self, file_path, data_dir, file_key, dataset_id,
                            md_parser, splitter, timings, True,
                        )

                    phase_start = _t.time()
                    existing_vectors = (
                        self._sync_existing_file_vectors_by_hash(
                            sync_qdrant,
                            dataset_id,
                            file_key,
                            embedding_fingerprint,
                        )
                        if CHUNK_HASH_CACHE and hasattr(self, "_sync_existing_file_vectors_by_hash")
                        else {}
                    )
                    _add_timing("cache_sec", phase_start)

                    # W1.4: старые точки удаляем ПОСЛЕ успешной конвертации — сбой
                    # конвертации больше не оставляет файл без старого индекса.
                    phase_start = _t.time()
                    self._sync_delete_file_points(sync_qdrant, dataset_id, file_key)
                    _add_timing("delete_sec", phase_start)

                    if not file_nodes:
                        phase_start = _t.time()
                        self.db.update_document_status(dataset_id, db_file_key, "INDEXED", 0, route=route)
                        _add_timing("db_sec", phase_start)
                        continue

                    _apply_context_metadata_to_nodes(file_nodes, dataset_id, file_key)

                    # Стираем старые правила для этого файла перед переиндексацией
                    self.db.clear_structured_rules(file_key)

                    # Извлекаем структурированные правила для нормативных и сложных документов
                    if route and route.doc_type in ("NORMATIVE", "SPEC"):
                        try:
                            from .rules_extractor import StructuredRulesExtractor
                            extractor = StructuredRulesExtractor()
                            extracted_rules = []
                            for node in file_nodes:
                                chunk_rules = extractor.extract_rules(
                                    text=node["text"],
                                    document_id=dataset_id,
                                    file_key=file_key,
                                    chunk_id=node["doc_id"]
                                )
                                if chunk_rules:
                                    extracted_rules.extend(chunk_rules)

                            if extracted_rules:
                                self.db.insert_structured_rules(extracted_rules)
                                logger.info(f"[OCR_RULES] Извлечено структурированных правил из {file_key}: {len(extracted_rules)}")
                        except Exception as rule_err:
                            logger.error(f"[OCR_RULES] Ошибка извлечения структурированных правил для {file_key}: {rule_err}", exc_info=True)

                    _stage(db_file_key, "EMBED")
                    # Батч-эмбеддинги по EMBED_BATCH чанков. Upsert начинаем только
                    # после успешного embedding всех чанков файла, чтобы не оставлять
                    # частичный индекс при сбое середины документа.
                    points = []
                    for batch_start in range(0, len(file_nodes), EMBED_BATCH):
                        batch = file_nodes[batch_start:batch_start + EMBED_BATCH]
                        batch_vectors: list[list[float] | None] = [None] * len(batch)
                        miss_indexes: list[int] = []
                        miss_texts: list[str] = []
                        for local_idx, node in enumerate(batch):
                            payload = node.get("payload") or {}
                            content_hash = str(payload.get("content_hash") or _content_hash(str(node["text"])))
                            cached_vector = existing_vectors.get(content_hash)
                            if cached_vector is not None:
                                batch_vectors[local_idx] = cached_vector
                                embedding_cache_hits += 1
                            else:
                                miss_indexes.append(local_idx)
                                miss_texts.append(str(node["text"]))

                        if miss_texts:
                            phase_start = _t.time()
                            vectors = self.embed.encode_sync(miss_texts)
                            _add_timing("embed_sec", phase_start)
                            if len(vectors) != len(miss_texts):
                                raise RuntimeError(
                                    f"embedding count mismatch: got {len(vectors)}, expected {len(miss_texts)}"
                                )
                            embedded_chunks += len(vectors)
                            for local_idx, vec in zip(miss_indexes, vectors):
                                batch_vectors[local_idx] = vec

                        for node, vec in zip(batch, batch_vectors):
                            if vec is None:
                                raise RuntimeError("missing embedding vector after cache/embed merge")
                            payload = dict(node.get("payload") or {})
                            payload.update({
                                "text":       node["text"],
                                "dataset_id": dataset_id,
                                "doc_id":     node.get("doc_id") or str(uuid.uuid4()),
                                "file_name":  file_key,
                                "embedding_fingerprint": embedding_fingerprint,
                                "embedding_backend": embedding_descriptor.get("backend", ""),
                                "embedding_model_id": embedding_descriptor.get("model_id", ""),
                                "embedding_profile": embedding_descriptor.get("profile", ""),
                                "embedding_coreml_model": embedding_descriptor.get("coreml_model", ""),
                                "embedding_coreml_seq_len": embedding_descriptor.get("coreml_seq_len", ""),
                                "embedding_coreml_compute_units": embedding_descriptor.get("coreml_compute_units", ""),
                                "embedding_coreml_fallback": embedding_descriptor.get("coreml_fallback", ""),
                            })
                            points.append(models.PointStruct(
                                id=str(uuid.uuid4()),
                                vector=vec,
                                payload=payload,
                            ))

                    _stage(db_file_key, "UPSERT")
                    # Upsert батчами после успешного embedding всего файла.
                    for point_start in range(0, len(points), UPSERT_BATCH):
                        phase_start = _t.time()
                        sync_qdrant.upsert(
                            collection_name=self.collection_name,
                            points=points[point_start:point_start + UPSERT_BATCH],
                        )
                        _add_timing("upsert_sec", phase_start)

                    file_chunk_count = len(file_nodes)
                    # W1.2: exact-count в Qdrant — дорогая проверка; выборочно (каждый N-й файл
                    # и последний), а не после каждого. Upsert-ошибки и так поднимают исключение.
                    if i % VERIFY_POINTS_EVERY == 0 or i == total:
                        phase_start = _t.time()
                        indexed_points = self._sync_count_file_points(sync_qdrant, dataset_id, file_key)
                        _add_timing("count_sec", phase_start)
                        if indexed_points != file_chunk_count:
                            raise RuntimeError(
                                f"qdrant point count mismatch: got {indexed_points}, expected {file_chunk_count}"
                            )
                    total_chunks    += file_chunk_count
                    phase_start = _t.time()
                    self.db.update_document_status(
                        dataset_id, db_file_key, "INDEXED", file_chunk_count, route=route
                    )
                    _add_timing("db_sec", phase_start)

                except Exception as file_err:
                    logger.error(f"[PARSE] ERROR {file_key}: {file_err}", exc_info=True)
                    try:
                        self._sync_delete_file_points(sync_qdrant, dataset_id, file_key)
                    except Exception as cleanup_err:
                        logger.error("[PARSE] cleanup failed %s: %s", file_key, cleanup_err)
                    phase_start = _t.time()
                    self.db.update_document_status(
                        dataset_id, db_file_key, "ERROR", 0, last_error=str(file_err)
                    )
                    _add_timing("db_sec", phase_start)
                    errors += 1

            if convert_pool is not None:
                convert_pool.shutdown(wait=False, cancel_futures=True)

            phase_start = _t.time()
            self.db.update_dataset_chunk_count(dataset_id)
            remaining_pending = len(self.db.get_pending_files(dataset_id))
            _add_timing("db_sec", phase_start)
            elapsed = _t.time() - t0
            timings = {key: round(value, 3) for key, value in timings.items()}
            logger.info(
                f"[PARSE] DONE: {total} файлов, {total_chunks} чанков, "
                f"{errors} ошибок за {elapsed:.0f}с, осталось pending={remaining_pending}, "
                f"timings={timings}"
            )
            return {
                "status":       "completed",
                "chunks":       total_chunks,
                "files_parsed": total,
                "files_skipped": total_all - total,
                "remaining_pending": remaining_pending,
                "errors":       errors,
                "embedding_cache_hits": embedding_cache_hits,
                "embedded_chunks": embedded_chunks,
                "elapsed_sec":  round(elapsed, 1),
                "timings":      timings,
            }

        except Exception as e:
            logger.error(f"[PARSE] FATAL: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    def _convert_file(
        self,
        file_path: Path,
        data_dir: Path,
        file_key: str,
        dataset_id: str,
        md_parser,
        splitter,
        timings: dict,
        allow_ocr: bool = True,
    ):
        """W1.4: стадия конвертации (route + nodes), вынесена для префетча в фоне.

        allow_ocr=False (префетч): OCR-файлы не конвертируем в фоне — возвращаем
        (route, None), основной поток выполнит конвертацию синхронно.
        """
        import time as _t

        def _add_timing(key: str, started: float) -> None:
            timings[key] = timings.get(key, 0.0) + (_t.time() - started)

        phase_start = _t.time()
        route = route_document(file_path)
        _add_timing("route_sec", phase_start)
        logger.info(
            "[DOC_ROUTE] %s domain=%s dataset=%s type=%s content=%s complexity=%s pipeline=%s",
            file_key,
            route.domain,
            route.dataset_name,
            route.doc_type,
            route.content_type,
            route.complexity,
            route.pipeline,
        )

        if route.pipeline == "markdown_needs_ocr" and not allow_ocr:
            return route, None

        if route.doc_type == "EMAIL":
            file_nodes = self._sync_mail_nodes(
                file_path, data_dir, file_key, dataset_id, splitter, route, timings
            )
        elif route.pipeline == "parquet":
            try:
                file_nodes = self._sync_table_nodes(file_path, data_dir, dataset_id, route, timings)
            except Exception as table_err:
                logger.warning(
                    "[PARQUET] fallback to markdown for %s: %s",
                    file_key,
                    table_err,
                )
                file_nodes = self._sync_markdown_nodes(
                    file_path, file_key, dataset_id, md_parser, splitter, route, timings
                )
        elif route.pipeline in ("markdown_pdf_tables", "markdown_needs_ocr"):
            file_nodes = self._sync_markdown_nodes(
                file_path, file_key, dataset_id, md_parser, splitter, route, timings
            )
            if (
                route.pipeline == "markdown_pdf_tables"
                and os.getenv("PDF_TABLE_EXTRACTION_ENABLED", "false").lower() == "true"
            ):
                try:
                    file_nodes.extend(self._sync_table_nodes(file_path, data_dir, dataset_id, route, timings))
                except Exception as table_err:
                    logger.warning(
                        "[PDF_TABLE] table extraction skipped for %s: %s",
                        file_key,
                        table_err,
                    )
        else:
            file_nodes = self._sync_markdown_nodes(
                file_path, file_key, dataset_id, md_parser, splitter, route, timings
            )
            if QdrantLlamaIndexAdapter._docx_table_extraction_enabled(file_path, route):
                try:
                    file_nodes.extend(self._sync_table_nodes(file_path, data_dir, dataset_id, route, timings))
                except Exception as table_err:
                    logger.warning(
                        "[DOCX_TABLE] table extraction skipped for %s: %s",
                        file_key,
                        table_err,
                    )
        return route, file_nodes

    def _file_filter(self, dataset_id: str, file_key: str) -> models.Filter:
        return models.Filter(must=[
            models.FieldCondition(
                key="file_name",
                match=models.MatchValue(value=file_key),
            ),
            models.FieldCondition(
                key="dataset_id",
                match=models.MatchValue(value=dataset_id),
            ),
        ])

    def _sync_delete_file_points(
        self,
        sync_qdrant: qdrant_client.QdrantClient,
        dataset_id: str,
        file_key: str,
    ) -> None:
        sync_qdrant.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=self._file_filter(dataset_id, file_key)
            ),
            wait=True,
        )

    def _sync_count_file_points(
        self,
        sync_qdrant: qdrant_client.QdrantClient,
        dataset_id: str,
        file_key: str,
    ) -> int:
        result = sync_qdrant.count(
            collection_name=self.collection_name,
            count_filter=self._file_filter(dataset_id, file_key),
            exact=True,
        )
        return int(result.count)

    def _sync_existing_file_vectors_by_hash(
        self,
        sync_qdrant: qdrant_client.QdrantClient,
        dataset_id: str,
        file_key: str,
        embedding_fingerprint: str,
    ) -> dict[str, list[float]]:
        vectors: dict[str, list[float]] = {}
        offset = None
        try:
            while True:
                points, offset = sync_qdrant.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=self._file_filter(dataset_id, file_key),
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True,
                )
                for point in points:
                    payload = getattr(point, "payload", None) or {}
                    if str(payload.get("embedding_fingerprint") or "") != embedding_fingerprint:
                        continue
                    text = str(payload.get("text") or "")
                    content_hash = str(payload.get("content_hash") or _content_hash(text))
                    vector = self._extract_point_vector(point)
                    if content_hash and vector is not None:
                        vectors.setdefault(content_hash, vector)
                if offset is None:
                    break
        except Exception as error:
            logger.warning("[PARSE] chunk hash cache unavailable for %s: %s", file_key, error)
        return vectors

    @staticmethod
    def _extract_point_vector(point: Any) -> list[float] | None:
        vector = getattr(point, "vector", None)
        if isinstance(vector, dict):
            vector = vector.get("") or vector.get("default") or next(iter(vector.values()), None)
        if isinstance(vector, list) and vector and all(isinstance(item, (int, float)) for item in vector):
            return [float(item) for item in vector]
        return None

    def _apply_context_metadata(self, file_nodes: list[dict], dataset_id: str, file_key: str) -> None:
        _apply_context_metadata_to_nodes(file_nodes, dataset_id, file_key)

    def _sync_markdown_nodes(
        self,
        file_path: Path,
        file_key: str,
        dataset_id: str,
        md_parser: MarkdownNodeParser,
        splitter: SentenceSplitter,
        route: DocumentRoute | None = None,
        timings: dict[str, float] | None = None,
    ) -> list[dict]:
        import time as _t
        phase_start = _t.time()
        md_content = convert_to_markdown(file_path, route=route)
        if timings is not None:
            timings["convert_sec"] = timings.get("convert_sec", 0.0) + (_t.time() - phase_start)
        if not md_content:
            return []

        phase_start = _t.time()
        doc = Document(
            text=md_content,
            metadata={"file_name": file_key, "dataset_id": dataset_id},
        )
        nodes = md_parser.get_nodes_from_documents([doc])

        file_nodes = []
        for node in nodes:
            node.metadata.update(doc.metadata)
            if len(node.text) > 2000:
                split_nodes = splitter.get_nodes_from_documents([node])
                file_nodes.extend(
                    {
                        "text": split_node.text,
                        "doc_id": split_node.node_id,
                        "payload": self._route_payload(route, {"type": "markdown"}),
                    }
                    for split_node in split_nodes
                    if len(split_node.text) >= MIN_CHUNK
                )
            elif len(node.text) >= MIN_CHUNK:
                file_nodes.append({
                    "text": node.text,
                    "doc_id": node.node_id,
                    "payload": self._route_payload(route, {"type": "markdown"}),
                })
        if timings is not None:
            timings["chunk_sec"] = timings.get("chunk_sec", 0.0) + (_t.time() - phase_start)
        return file_nodes

    def _sync_mail_nodes(
        self,
        file_path: Path,
        data_dir: Path,
        file_key: str,
        dataset_id: str,
        splitter: SentenceSplitter,
        route: DocumentRoute | None = None,
        timings: dict[str, float] | None = None,
    ) -> list[dict]:
        import time as _t

        phase_start = _t.time()
        profile = build_mail_vector_profile(file_path, source_dir=data_dir)
        if timings is not None:
            timings["convert_sec"] = timings.get("convert_sec", 0.0) + (_t.time() - phase_start)

        phase_start = _t.time()
        nodes: list[dict] = []
        message_payload = profile.payload()
        message_payload.update({
            "type": "mail_message",
            "mail_node_kind": "message",
        })
        nodes.extend(
            self._split_profile_text_nodes(
                profile.message_embedding_text(include_attachment_text=False),
                dataset_id,
                file_key,
                splitter,
                self._route_payload(route, message_payload),
                "message",
            )
        )

        for attachment in profile.attachments:
            attachment_payload = profile.payload()
            attachment_payload.update({
                "type": "mail_attachment",
                "mail_node_kind": "attachment",
                "mail_attachment_id": attachment.attachment_id,
                "mail_attachment_filename": attachment.filename,
                "mail_attachment_content_type": attachment.content_type,
                "mail_attachment_kind": attachment.kind,
                "mail_attachment_extraction": attachment.extraction,
                "mail_attachment_needs_ocr": attachment.needs_ocr,
                "mail_attachment_needs_vlm": attachment.needs_vlm,
                "mail_attachment_has_text": attachment.has_text,
                "mail_attachment_error": attachment.error,
            })
            nodes.extend(
                self._split_profile_text_nodes(
                    attachment.embedding_text(profile),
                    dataset_id,
                    file_key,
                    splitter,
                    self._route_payload(route, attachment_payload),
                    f"attachment:{attachment.attachment_id}",
                )
            )

        if timings is not None:
            timings["chunk_sec"] = timings.get("chunk_sec", 0.0) + (_t.time() - phase_start)
        return nodes

    def _split_profile_text_nodes(
        self,
        text: str,
        dataset_id: str,
        file_key: str,
        splitter: SentenceSplitter,
        payload: dict[str, Any],
        node_key: str,
    ) -> list[dict]:
        value = str(text or "").strip()
        if len(value) < MIN_CHUNK:
            return []
        if len(value) <= 2000:
            return [{
                "text": value,
                "doc_id": deterministic_mail_node_id(dataset_id, file_key, node_key),
                "payload": dict(payload),
            }]

        doc = Document(text=value, metadata={"file_name": file_key, "dataset_id": dataset_id})
        split_nodes = splitter.get_nodes_from_documents([doc])
        return [
            {
                "text": split_node.text,
                "doc_id": deterministic_mail_node_id(dataset_id, file_key, f"{node_key}:{idx}"),
                "payload": dict(payload),
            }
            for idx, split_node in enumerate(split_nodes)
            if len(split_node.text) >= MIN_CHUNK
        ]

    def _sync_table_nodes(
        self,
        file_path: Path,
        data_dir: Path,
        dataset_id: str,
        route: DocumentRoute | None = None,
        timings: dict[str, float] | None = None,
    ) -> list[dict]:
        import time as _t
        parquet_dir = data_dir / "_parquet" / file_path.relative_to(data_dir).parent
        normalizer = TableNormalizer(parquet_dir=str(parquet_dir), use_llm=False)
        phase_start = _t.time()
        doc_type_override = "TABLE" if route and not route.domain.startswith("TABLE_") else None
        result = asyncio.run(
            normalizer.process(str(file_path), dataset_id=dataset_id, doc_type_override=doc_type_override)
        )
        if timings is not None:
            timings["convert_sec"] = timings.get("convert_sec", 0.0) + (_t.time() - phase_start)
        parquet_path = result.get("parquet_path") or ""
        parquet_rel = ""
        if parquet_path:
            try:
                parquet_rel = Path(parquet_path).relative_to(data_dir).as_posix()
            except ValueError:
                parquet_rel = parquet_path

        phase_start = _t.time()
        nodes = []
        for i, chunk in enumerate(result.get("chunks") or []):
            text = str(chunk.get("text") or "")
            if len(text) < MIN_CHUNK:
                continue
            payload = dict(chunk.get("metadata") or {})
            payload.update({
                "type": "table_row",
                "parquet_path": parquet_rel,
                "table_row": i,
                "table_kind": self._table_kind(route),
            })
            nodes.append({
                "text": text,
                "doc_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_id}:{file_path}:{i}")),
                "payload": self._route_payload(route, payload),
            })
        if not nodes and result.get("needs_ocr"):
            scanned_pages = result.get("scanned_pages") or []
            text = (
                f"PDF {file_path.name} содержит страницы без текстового слоя; "
                f"нужна OCR/VLM обработка. Страницы: {', '.join(map(str, scanned_pages)) or '?'}"
            )
            payload = {
                "type": "pdf_needs_ocr",
                "needs_ocr": True,
                "scanned_pages": scanned_pages,
                "parquet_path": "",
                "table_kind": self._table_kind(route),
            }
            nodes.append({
                "text": text,
                "doc_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_id}:{file_path}:needs_ocr")),
                "payload": self._route_payload(route, payload),
            })
        if timings is not None:
            timings["chunk_sec"] = timings.get("chunk_sec", 0.0) + (_t.time() - phase_start)
        return nodes

    @staticmethod
    def _docx_table_extraction_enabled(file_path: Path, route: DocumentRoute | None) -> bool:
        if file_path.suffix.lower() != ".docx":
            return False
        if os.getenv("DOCX_TABLE_EXTRACTION_ENABLED", "false").lower() not in ("1", "true", "yes"):
            return False
        if route is None:
            return True
        return route.domain.startswith("NTD_") or route.domain in {"GKRF", "BOOKS"}

    @staticmethod
    def _table_kind(route: DocumentRoute | None) -> str:
        if route is None:
            return "table"
        if route.domain.startswith("TABLE_"):
            return "cost"
        if route.domain.startswith("NTD_") or route.domain in {"GKRF", "BOOKS"}:
            return "normative"
        return "table"

    def _route_payload(self, route: DocumentRoute | None, payload: dict) -> dict:
        if route is None:
            return payload
        merged = dict(payload)
        merged.update(route.metadata)
        return merged

    async def retrieve(
        self,
        query:       str,
        dataset_ids: Optional[List[str]] = None,
        top_k:       int = 5,
    ) -> List[Chunk]:
        await self._ensure_collection()

        # Async эмбеддинг запроса
        vecs = await self.embed.encode_async([query])
        query_vec = vecs[0]

        query_filter = None
        if dataset_ids:
            query_filter = models.Filter(must=[
                models.FieldCondition(
                    key="dataset_id",
                    match=models.MatchAny(any=dataset_ids),
                )
            ])

        results = await self.aclient.query_points(
            collection_name=self.collection_name,
            query=query_vec,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )

        def _is_binary_garbage(text: str) -> bool:
            """Detect base64-encoded or binary garbage chunks."""
            if not text or len(text) < 40:
                return False
            lines = text.split("\n")
            long_dense_lines = sum(
                1 for line in lines
                if len(line) > 60 and " " not in line and "/" in line + "=" in line
            )
            if long_dense_lines >= 2:
                return True
            # Check if text has no Cyrillic at all and looks like base64
            sample = text[:200].replace("\n", "")
            if len(sample) > 80:
                cyrillic = sum(1 for c in sample if "\u0400" <= c <= "\u04ff")
                spaces = sample.count(" ")
                if cyrillic == 0 and spaces < 3:
                    return True
            return False

        return [
            Chunk(
                content=p.payload.get("text", ""),
                doc_id=p.payload.get("doc_id", ""),
                doc_name=p.payload.get("file_name", "unknown"),
                score=p.score,
                meta=p.payload,
            )
            for p in results.points
            if not _is_binary_garbage(p.payload.get("text", ""))
        ]

    async def retrieve_sparse(
        self,
        query:       str,
        dataset_ids: Optional[List[str]] = None,
        top_k:       int = 5,
    ) -> List[Chunk]:
        """W2.4: поиск по BGE-M3 learned-sparse вектору (Qdrant-native), параллельно dense.

        Возвращает Chunk-и той же формы, что `retrieve`. Пустой sparse-запрос или
        отсутствие sparse-вектора в коллекции → [] (гибрид молча падает на dense+FTS).
        """
        import asyncio as _asyncio

        from backend.inference.sparse_embed import SPARSE_VECTOR_NAME, encode_one

        await self._ensure_collection()
        sv = await _asyncio.to_thread(encode_one, query)
        if not sv:
            return []

        query_filter = None
        if dataset_ids:
            query_filter = models.Filter(must=[
                models.FieldCondition(key="dataset_id", match=models.MatchAny(any=dataset_ids))
            ])

        results = await self.aclient.query_points(
            collection_name=self.collection_name,
            query=models.SparseVector(indices=list(sv.keys()), values=list(sv.values())),
            using=SPARSE_VECTOR_NAME,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        )
        return [
            Chunk(
                content=p.payload.get("text", ""),
                doc_id=p.payload.get("doc_id", ""),
                doc_name=p.payload.get("file_name", "unknown"),
                score=p.score,
                meta=p.payload,
            )
            for p in results.points
            if len(p.payload.get("text", "")) >= 1
        ]

    async def retrieve_table_rows(
        self,
        dataset_ids: Optional[List[str]] = None,
        limit: int = 64,
    ) -> List[Chunk]:
        await self._ensure_collection()

        must = [
            models.FieldCondition(
                key="type",
                match=models.MatchValue(value="table_row"),
            )
        ]
        if dataset_ids:
            must.append(
                models.FieldCondition(
                    key="dataset_id",
                    match=models.MatchAny(any=dataset_ids),
                )
            )

        points, _next_page = await self.aclient.scroll(
            collection_name=self.collection_name,
            scroll_filter=models.Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        return [
            Chunk(
                content=point.payload.get("text", ""),
                doc_id=point.payload.get("doc_id", ""),
                doc_name=point.payload.get("file_name", "unknown"),
                score=1.0,
                meta=point.payload,
            )
            for point in points
        ]
