import os
import uuid
import sqlite3
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any

from llama_index.core import Settings
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.core.schema import Document

import qdrant_client
from qdrant_client import models

from .interface import RAGBackend, Chunk, DatasetInfo
from .converter import convert_to_markdown

logger = logging.getLogger(__name__)

class MetaDB:
    def __init__(self, db_path: str = "./data/les_meta.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS datasets (id TEXT PRIMARY KEY, name TEXT, status TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, dataset_id TEXT, file_name TEXT, status TEXT)")

    def create_dataset(self, name: str) -> str:
        ds_id = str(uuid.uuid4())
        with self._get_conn() as conn:
            conn.execute("INSERT INTO datasets (id, name, status) VALUES (?, ?, 'IDLE')", (ds_id, name))
        return ds_id

    def update_dataset_status(self, dataset_id: str, status: str):
        with self._get_conn() as conn:
            conn.execute("UPDATE datasets SET status = ? WHERE id = ?", (status, dataset_id))

    def list_datasets(self) -> List[DatasetInfo]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT d.id, d.name, d.status, COUNT(doc.id) as doc_count
                FROM datasets d
                LEFT JOIN documents doc ON d.id = doc.dataset_id
                GROUP BY d.id
            """).fetchall()
            return [DatasetInfo(id=r["id"], name=r["name"], status=r["status"], doc_count=r["doc_count"], chunk_count=0) for r in rows]

    def add_document(self, dataset_id: str, file_name: str) -> str:
        with self._get_conn() as conn:
            existing = conn.execute("SELECT id FROM documents WHERE dataset_id = ? AND file_name = ?", (dataset_id, file_name)).fetchone()
            if existing:
                return existing["id"]
            doc_id = str(uuid.uuid4())
            conn.execute("INSERT INTO documents (id, dataset_id, file_name, status) VALUES (?, ?, ?, 'PENDING')", (doc_id, dataset_id, file_name))
            return doc_id

class QdrantLlamaIndexAdapter(RAGBackend):
    def __init__(self, qdrant_url: str, ollama_url: str, embed_model_name: str, content_dir: str = "./storage/datasets"):
        self.content_dir = Path(content_dir)
        self.content_dir.mkdir(parents=True, exist_ok=True)
        self.db = MetaDB()
        self.aclient = qdrant_client.AsyncQdrantClient(url=qdrant_url)
        self.embed_model = OllamaEmbedding(model_name=embed_model_name, base_url=ollama_url, embed_batch_size=10)
        Settings.embed_model = self.embed_model
        self.collection_name = "les_rag"
        self._collection_ready = False

    async def _ensure_collection(self):
        if self._collection_ready: return
        try:
            await self.aclient.get_collection(self.collection_name)
        except Exception:
            logger.info(f"[INIT] Creating collection {self.collection_name}")
            await self.aclient.create_collection(collection_name=self.collection_name, vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE))
        self._collection_ready = True

    async def health(self) -> bool:
        try:
            await self._ensure_collection()
            return True
        except Exception: return False

    async def list_datasets(self) -> List[DatasetInfo]:
        return self.db.list_datasets()

    async def create_dataset(self, name: str) -> str:
        return self.db.create_dataset(name)

    async def upload_file(self, dataset_id: str, file_path: Path) -> str:
        dest_dir = self.content_dir / dataset_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / file_path.name
        if file_path.exists():
            import shutil
            shutil.copy2(file_path, dest_file)
        return self.db.add_document(dataset_id, file_path.name)

    async def parse_dataset(self, dataset_id: str) -> Dict[str, Any]:
        await self._ensure_collection()
        self.db.update_dataset_status(dataset_id, "PARSING")
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, self._sync_parse, dataset_id)
        status = "COMPLETED" if res.get("status") == "completed" else "ERROR"
        self.db.update_dataset_status(dataset_id, status)
        return res

    def _sync_parse(self, dataset_id: str):
        logger.info(f"[PARSE] Start dataset {dataset_id}")
        data_dir = self.content_dir / dataset_id
        if not data_dir.exists(): return {"status": "error", "msg": "dir missing"}

        try:
            final_nodes = []
            files = [f for f in data_dir.rglob('*') if f.is_file()]
            total = len(files)
            logger.info(f"[PARSE] Found {total} files (recursive)")

            for i, file_path in enumerate(files, 1):
                if i % 50 == 0 or i == total:
                    logger.info(f"[PARSE] Progress: {i}/{total} files")
                
                md_content = convert_to_markdown(file_path)
                if md_content:
                    doc = Document(text=md_content, metadata={"file_name": file_path.name, "dataset_id": dataset_id})
                    parser = MarkdownNodeParser()
                    nodes = parser.get_nodes_from_documents([doc])
                    splitter = SentenceSplitter(chunk_size=600, chunk_overlap=60)
                    for node in nodes:
                        node.metadata.update(doc.metadata)
                        if len(node.text) > 2000:
                            final_nodes.extend(splitter.get_nodes_from_documents([node]))
                        else:
                            final_nodes.append(node)
            
            if not final_nodes:
                return {"status": "empty", "msg": "no parsable content"}

            logger.info(f"[PARSE] Embedding {len(final_nodes)} chunks...")
            points = []
            sync_client = qdrant_client.QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
            for node in final_nodes:
                vec = self.embed_model.get_text_embedding(node.text)
                points.append(models.PointStruct(
                    id=str(uuid.uuid4()), vector=vec,
                    payload={"text": node.text, "dataset_id": dataset_id, "doc_id": node.node_id, "file_name": node.metadata.get("file_name", "unknown")}
                ))
            
            logger.info(f"[PARSE] Upserting {len(points)} points...")
            sync_client.upsert(collection_name=self.collection_name, points=points)
            logger.info("[PARSE] DONE")
            return {"status": "completed", "chunks": len(points)}
        except Exception as e:
            logger.error(f"[PARSE] ERROR: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    async def retrieve(self, query: str, dataset_ids: Optional[List[str]] = None, top_k: int = 5) -> List[Chunk]:
        await self._ensure_collection()
        query_filter = None
        if dataset_ids:
            query_filter = models.Filter(must=[models.FieldCondition(key="dataset_id", match=models.MatchAny(any=dataset_ids))])
        query_vec = self.embed_model.get_query_embedding(query)
        results = await self.aclient.query_points(collection_name=self.collection_name, query=query_vec, query_filter=query_filter, limit=top_k, with_payload=True)
        return [Chunk(content=p.payload.get("text", ""), doc_id=p.payload.get("doc_id", ""), doc_name=p.payload.get("file_name", "unknown"), score=p.score, meta=p.payload) for p in results.points]
