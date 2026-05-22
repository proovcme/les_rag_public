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
import logging
import os
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

logger = logging.getLogger(__name__)

EMBED_BATCH  = 32    # чанков за один запрос к BGE-M3
MIN_CHUNK    = 20    # символов — короче не индексируем
UPSERT_BATCH = 100   # точек за один upsert в Qdrant
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
    def __init__(self, db_path: str = "./data/les_meta.db"):
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
        self, dataset_id: str, file_name: str, status: str, chunk_count: int = 0
    ):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE documents SET status=?, chunk_count=? "
                "WHERE dataset_id=? AND file_name=?",
                (status, chunk_count, dataset_id, file_name),
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

    def get_pending_files(self, dataset_id: str) -> List[str]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT file_name FROM documents WHERE dataset_id=? AND status='PENDING'",
                (dataset_id,),
            ).fetchall()
        return [r["file_name"] for r in rows]


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
        self.aclient         = qdrant_client.AsyncQdrantClient(url=qdrant_url)
        self.qdrant_url      = qdrant_url
        self.embed           = EmbedClient(mlx_url, model=embed_model_name.replace(":latest", ""))
        self.collection_name = "les_rag"
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
                        size=1024, distance=models.Distance.COSINE
                    ),
                )
            self._collection_ready = True

    async def health(self) -> bool:
        try:
            await self._ensure_collection()
            return True
        except Exception:
            return False

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

        doc_id, _, _ = self.db.add_document(
            dataset_id, rel_path.as_posix(), file_mtime=mtime, file_size=size
        )
        return doc_id

    async def parse_dataset(self, dataset_id: str) -> Dict[str, Any]:
        await self._ensure_collection()
        self.db.update_dataset_status(dataset_id, "PARSING")
        res = await asyncio.to_thread(self._sync_parse, dataset_id)
        status = "COMPLETED" if res.get("status") == "completed" else "ERROR"
        self.db.update_dataset_status(dataset_id, status)
        return res

    def _sync_parse(self, dataset_id: str) -> Dict[str, Any]:
        """
        Синхронный парсинг в threadpool.
        Батч-эмбеддинги: 32 чанка за запрос вместо по одному.
        """
        import time as _t
        t0 = _t.time()

        data_dir = self.content_dir / dataset_id
        if not data_dir.exists():
            return {"status": "error", "msg": "dir missing"}

        sync_qdrant = qdrant_client.QdrantClient(
            url=os.getenv("QDRANT_URL", "http://qdrant:6333")
        )
        md_parser = MarkdownNodeParser()
        splitter  = SentenceSplitter(chunk_size=600, chunk_overlap=60)

        try:
            pending_names = set(self.db.get_pending_files(dataset_id))
            all_files     = [
                f for f in data_dir.rglob("*")
                if f.is_file() and "_parquet" not in f.relative_to(data_dir).parts
            ]

            # Матчинг по относительному пути и по имени файла для совместимости
            # со старыми записями БД где хранится только f.name.
            files_to_parse = (
                [f for f in all_files
                 if str(f.relative_to(data_dir)) in pending_names
                 or f.name in pending_names]
                if pending_names else all_files
            )

            total     = len(files_to_parse)
            total_all = len(all_files)
            logger.info(f"[PARSE] {total}/{total_all} файлов к индексации")

            if total == 0:
                return {"status": "completed", "chunks": 0, "skipped": total_all}

            total_chunks = 0
            errors       = 0

            for i, file_path in enumerate(files_to_parse, 1):
                file_key = file_path.relative_to(data_dir).as_posix()
                if i % 50 == 0 or i == total:
                    logger.info(f"[PARSE] {i}/{total} ({_t.time()-t0:.0f}с)")
                try:
                    # Удаляем старые точки файла
                    try:
                        sync_qdrant.delete(
                            collection_name=self.collection_name,
                            points_selector=models.FilterSelector(
                                filter=models.Filter(must=[
                                    models.FieldCondition(
                                        key="file_name",
                                        match=models.MatchValue(value=file_key),
                                    ),
                                    models.FieldCondition(
                                        key="dataset_id",
                                        match=models.MatchValue(value=dataset_id),
                                    ),
                                ])
                            ),
                        )
                    except Exception:
                        pass

                    route = route_document(file_path)
                    logger.info(
                        "[DOC_ROUTE] %s type=%s content=%s complexity=%s pipeline=%s",
                        file_key,
                        route.doc_type,
                        route.content_type,
                        route.complexity,
                        route.pipeline,
                    )

                    if route.pipeline == "parquet":
                        try:
                            file_nodes = self._sync_table_nodes(file_path, data_dir, dataset_id, route)
                        except Exception as table_err:
                            logger.warning(
                                "[PARQUET] fallback to markdown for %s: %s",
                                file_key,
                                table_err,
                            )
                            file_nodes = self._sync_markdown_nodes(
                                file_path, file_key, dataset_id, md_parser, splitter, route
                            )
                    elif route.pipeline in ("markdown_pdf_tables", "markdown_needs_ocr"):
                        file_nodes = self._sync_markdown_nodes(
                            file_path, file_key, dataset_id, md_parser, splitter, route
                        )
                        if (
                            route.pipeline == "markdown_pdf_tables"
                            and os.getenv("PDF_TABLE_EXTRACTION_ENABLED", "false").lower() == "true"
                        ):
                            try:
                                file_nodes.extend(self._sync_table_nodes(file_path, data_dir, dataset_id, route))
                            except Exception as table_err:
                                logger.warning(
                                    "[PDF_TABLE] table extraction skipped for %s: %s",
                                    file_key,
                                    table_err,
                                )
                    else:
                        file_nodes = self._sync_markdown_nodes(
                            file_path, file_key, dataset_id, md_parser, splitter, route
                        )

                    if not file_nodes:
                        self.db.update_document_status(dataset_id, file_key, "INDEXED", 0)
                        continue

                    # Батч-эмбеддинги по EMBED_BATCH чанков
                    points = []
                    for batch_start in range(0, len(file_nodes), EMBED_BATCH):
                        batch = file_nodes[batch_start:batch_start + EMBED_BATCH]
                        texts = [n["text"] for n in batch]
                        try:
                            vectors = self.embed.encode_sync(texts)
                        except Exception as emb_err:
                            logger.error(f"[PARSE] embed error {file_key}: {emb_err}")
                            errors += 1
                            continue

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

                        # Upsert батчами
                        if len(points) >= UPSERT_BATCH:
                            sync_qdrant.upsert(
                                collection_name=self.collection_name, points=points
                            )
                            points = []

                    if points:
                        sync_qdrant.upsert(
                            collection_name=self.collection_name, points=points
                        )

                    file_chunk_count = len(file_nodes)
                    total_chunks    += file_chunk_count
                    self.db.update_document_status(
                        dataset_id, file_key, "INDEXED", file_chunk_count
                    )

                except Exception as file_err:
                    logger.error(f"[PARSE] ERROR {file_key}: {file_err}", exc_info=True)
                    self.db.update_document_status(dataset_id, file_key, "ERROR", 0)
                    errors += 1

            self.db.update_dataset_chunk_count(dataset_id)
            elapsed = _t.time() - t0
            logger.info(
                f"[PARSE] DONE: {total} файлов, {total_chunks} чанков, "
                f"{errors} ошибок за {elapsed:.0f}с"
            )
            return {
                "status":       "completed",
                "chunks":       total_chunks,
                "files_parsed": total,
                "files_skipped": total_all - total,
                "errors":       errors,
                "elapsed_sec":  round(elapsed, 1),
            }

        except Exception as e:
            logger.error(f"[PARSE] FATAL: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    def _sync_markdown_nodes(
        self,
        file_path: Path,
        file_key: str,
        dataset_id: str,
        md_parser: MarkdownNodeParser,
        splitter: SentenceSplitter,
        route: DocumentRoute | None = None,
    ) -> list[dict]:
        md_content = convert_to_markdown(file_path)
        if not md_content:
            return []

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
        return file_nodes

    def _sync_table_nodes(
        self,
        file_path: Path,
        data_dir: Path,
        dataset_id: str,
        route: DocumentRoute | None = None,
    ) -> list[dict]:
        parquet_dir = data_dir / "_parquet" / file_path.relative_to(data_dir).parent
        normalizer = TableNormalizer(parquet_dir=str(parquet_dir), use_llm=False)
        result = asyncio.run(normalizer.process(str(file_path), dataset_id=dataset_id))
        parquet_path = result.get("parquet_path") or ""
        parquet_rel = ""
        if parquet_path:
            try:
                parquet_rel = Path(parquet_path).relative_to(data_dir).as_posix()
            except ValueError:
                parquet_rel = parquet_path

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
