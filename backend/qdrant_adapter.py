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
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import qdrant_client
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.schema import Document
from qdrant_client import models

from .converter import convert_to_markdown
from .document_router import DocumentRoute, route_document
from .interface import Chunk, DatasetInfo, RAGBackend
from .parquet_writer import TableNormalizer
from .rag_config import (
    rag_chunk_overlap,
    rag_chunk_size,
    rag_collection_name,
    rag_meta_db_path,
    rag_vector_size,
)

logger = logging.getLogger(__name__)

EMBED_BATCH  = int(os.getenv("RAG_EMBED_BATCH", "32"))      # чанков за один запрос к MLX embeddings
MIN_CHUNK    = int(os.getenv("RAG_MIN_CHUNK_CHARS", "20"))  # символов — короче не индексируем
UPSERT_BATCH = int(os.getenv("RAG_UPSERT_BATCH", "100"))    # точек за один upsert в Qdrant
RAG_CHUNK_SIZE = rag_chunk_size()
RAG_CHUNK_OVERLAP = rag_chunk_overlap()
ALLOW_UNBOUNDED_PARSE = "ALLOW_UNBOUNDED_PARSE"


def _content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _section_heading(text: str) -> str:
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
    for chunk_ord, file_node in enumerate(file_nodes):
        payload = file_node.setdefault("payload", {})
        text = str(file_node.get("text") or "")
        payload.setdefault("chunk_ord", chunk_ord)
        payload.setdefault("child_ord", chunk_ord)
        payload.setdefault("content_hash", _content_hash(text))
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
            fields = ["status=?", "chunk_count=?", "last_error=?"]
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
        self.aclient         = qdrant_client.AsyncQdrantClient(url=qdrant_url)
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
            "db_sec": 0.0,
        }

        def _add_timing(key: str, started: float) -> None:
            timings[key] = timings.get(key, 0.0) + (_t.time() - started)

        data_dir = self.content_dir / dataset_id
        if not data_dir.exists():
            return {"status": "error", "msg": "dir missing"}

        md_parser = MarkdownNodeParser()
        splitter  = SentenceSplitter(chunk_size=RAG_CHUNK_SIZE, chunk_overlap=RAG_CHUNK_OVERLAP)

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
                url=self.qdrant_url
            )

            # Матчинг по относительному пути и по имени файла для совместимости
            # со старыми записями БД где хранится только f.name.
            files_to_parse = [
                f for f in all_files
                if str(f.relative_to(data_dir)) in pending_names
                or f.name in pending_names
            ]

            total     = len(files_to_parse)
            total_all = len(all_files)
            logger.info(f"[PARSE] {total}/{total_all} файлов к индексации")

            if total == 0:
                return {"status": "completed", "chunks": 0, "skipped": total_all}

            total_chunks = 0
            errors       = 0

            for i, file_path in enumerate(files_to_parse, 1):
                file_key = file_path.relative_to(data_dir).as_posix()
                db_file_key = file_key if file_key in pending_names else file_path.name
                if i % 50 == 0 or i == total:
                    logger.info(f"[PARSE] {i}/{total} ({_t.time()-t0:.0f}с)")
                try:
                    # Удаляем старые точки файла до переиндексации. Если удаление
                    # не удалось, нельзя честно подтвердить итоговый point count.
                    phase_start = _t.time()
                    self._sync_delete_file_points(sync_qdrant, dataset_id, file_key)
                    _add_timing("delete_sec", phase_start)

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

                    if route.pipeline == "parquet":
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

                    if not file_nodes:
                        phase_start = _t.time()
                        self.db.update_document_status(dataset_id, db_file_key, "INDEXED", 0, route=route)
                        _add_timing("db_sec", phase_start)
                        continue

                    _apply_context_metadata_to_nodes(file_nodes, dataset_id, file_key)

                    # Батч-эмбеддинги по EMBED_BATCH чанков. Upsert начинаем только
                    # после успешного embedding всех чанков файла, чтобы не оставлять
                    # частичный индекс при сбое середины документа.
                    points = []
                    for batch_start in range(0, len(file_nodes), EMBED_BATCH):
                        batch = file_nodes[batch_start:batch_start + EMBED_BATCH]
                        texts = [n["text"] for n in batch]
                        phase_start = _t.time()
                        vectors = self.embed.encode_sync(texts)
                        _add_timing("embed_sec", phase_start)
                        if len(vectors) != len(batch):
                            raise RuntimeError(
                                f"embedding count mismatch: got {len(vectors)}, expected {len(batch)}"
                            )

                        for node, vec in zip(batch, vectors):
                            payload = dict(node.get("payload") or {})
                            payload.update({
                                "text":       node["text"],
                                "dataset_id": dataset_id,
                                "doc_id":     node.get("doc_id") or str(uuid.uuid4()),
                                "file_name":  file_key,
                            })
                            points.append(models.PointStruct(
                                id=str(uuid.uuid4()),
                                vector=vec,
                                payload=payload,
                            ))

                    # Upsert батчами после успешного embedding всего файла.
                    for point_start in range(0, len(points), UPSERT_BATCH):
                        phase_start = _t.time()
                        sync_qdrant.upsert(
                            collection_name=self.collection_name,
                            points=points[point_start:point_start + UPSERT_BATCH],
                        )
                        _add_timing("upsert_sec", phase_start)

                    file_chunk_count = len(file_nodes)
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
                "elapsed_sec":  round(elapsed, 1),
                "timings":      timings,
            }

        except Exception as e:
            logger.error(f"[PARSE] FATAL: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

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
        md_content = convert_to_markdown(file_path)
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
        result = asyncio.run(normalizer.process(str(file_path), dataset_id=dataset_id))
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
            }
            nodes.append({
                "text": text,
                "doc_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_id}:{file_path}:needs_ocr")),
                "payload": self._route_payload(route, payload),
            })
        if timings is not None:
            timings["chunk_sec"] = timings.get("chunk_sec", 0.0) + (_t.time() - phase_start)
        return nodes

    def _route_payload(self, route: DocumentRoute | None, payload: dict) -> dict:
        if route is None:
            return payload
        merged = dict(route.metadata)
        merged.update(payload)
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

        return [
            Chunk(
                content=p.payload.get("text", ""),
                doc_id=p.payload.get("doc_id", ""),
                doc_name=p.payload.get("file_name", "unknown"),
                score=p.score,
                meta=p.payload,
            )
            for p in results.points
        ]
