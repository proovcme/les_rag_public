import os
import re
import logging
import asyncio
import time
import json
import shutil
import collections
import sqlite3
import psutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from fastapi import Request, FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
import httpx

from backend.metrics_collector import DB_PATH, heartbeats, init_db, metrics_loop
from backend.qdrant_adapter import QdrantLlamaIndexAdapter
from backend.interface import DatasetInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="LES Proxy v2.0", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

log_history = collections.deque(maxlen=2000)
class LogCapture(logging.Handler):
    def emit(self, record):
        log_history.append(self.format(record))
logging.getLogger().addHandler(LogCapture())

parse_semaphore = asyncio.Semaphore(2)
crag_stats = {"verified": 0, "no_data": 0}
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

rag_backend = None
job_tracker = {}
import time
from collections import defaultdict

error_counts = defaultdict(int)
llm_queue_size = 0
chat_metrics = {
    "latency_search": [], 
    "latency_gen": [], 
    "tokens": [], 
    "crag_pass": 0, 
    "crag_fail": 0
}  # job_id -> {dataset_id, status, total, processed, message}

metrics_cache = {
    "cpu": 0.0, "ram_used": 0.0, "ram_total": 1.0,
    "datasets": 0, "files_processed": 0, "chunks_indexed": 0,
    "queue": 0, "active": 0, "avg_speed_fps": 0.0,
    "crag_verified": 0, "crag_no_data": 0
}

class ParseStats:
    def __init__(self):
        self.queued = 0
        self.active = 0
        self.total_files = 0
        self.total_chunks = 0
        self.durations = []
    def avg_speed(self):
        if not self.durations: return 0.0
        avg = sum(self.durations) / len(self.durations)
        return round(1.0 / avg, 2) if avg > 0 else 0.0

parse_stats = ParseStats()

class ChatRequest(BaseModel):
    question: str
    dataset_ids: Optional[List[str]] = None

def _get_db_files():
    try:
        conn = sqlite3.connect("./data/les_meta.db")
        count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        conn.close()
        return count
    except Exception: return 0

async def metrics_collector_loop():
    while True:
        try:
            cpu = await asyncio.to_thread(psutil.cpu_percent, interval=None)
            vm = await asyncio.to_thread(psutil.virtual_memory)
            files = await asyncio.to_thread(_get_db_files)
            
            chunks = 0
            ds_count = 0
            if rag_backend:
                try:
                    ds_list = await rag_backend.list_datasets()
                    ds_count = len(ds_list)
                    if rag_backend._collection_ready:
                        info = await rag_backend.aclient.get_collection("les_rag")
                        chunks = getattr(info, 'points_count', 0) or 0
                except Exception: pass

            metrics_cache.update({
                "cpu": cpu,
                "ram_used": vm.used / (1024**3),
                "ram_total": vm.total / (1024**3),
                "datasets": ds_count,
                "files_processed": files,
                "chunks_indexed": chunks,
                "queue": parse_stats.queued,
                "active": parse_stats.active,
                "avg_speed_fps": parse_stats.avg_speed(),
                "crag_verified": crag_stats["verified"],
                "crag_no_data": crag_stats["no_data"]
            })
        except Exception: pass
        await asyncio.sleep(3)

@app.on_event("startup")
async def startup():
    global rag_backend
    try:
        rag_backend = QdrantLlamaIndexAdapter(
            qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
            ollama_url=os.getenv("OLLAMA_URL", "http://host.docker.internal:11434"),
            embed_model_name=os.getenv("EMBED_MODEL", "bge-m3:latest")
        )
        await rag_backend.health()
        logger.info("[INIT] Backend initialized successfully")
        asyncio.create_task(metrics_collector_loop())
    except Exception as e:
        logger.error(f"[INIT] Backend initialization failed: {e}")
        raise


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(metrics_loop())

@app.middleware("http")
async def track_errors(request: Request, call_next):
    response = await call_next(request)
    if response.status_code >= 400:
        error_counts[response.status_code] += 1
    return response

@app.get("/api/health")
async def health():
    if not rag_backend: return {"status": "starting", "backend": "none"}
    return {"status": "ok" if await rag_backend.health() else "error", "backend": "qdrant_llama"}

@app.get("/api/metrics")
async def get_metrics():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM metrics ORDER BY id DESC LIMIT 60").fetchall()
    conn.close()

    rag_stats = {"datasets": 0, "files": 0, "chunks": 0, "status": "unknown"}
    try:
        _c = sqlite3.connect('./data/les_meta.db')
        _c.execute("SELECT COUNT(*) FROM datasets")
        rag_stats["datasets"] = _c.fetchone()[0] or 0
        _c.execute("SELECT COUNT(*) FROM documents")
        rag_stats["files"] = _c.fetchone()[0] or 0
        _c.close()
        if rag_backend:
            coll = await rag_backend.aclient.get_collection("les_rag")
            rag_stats["chunks"] = coll.points_count or 0
            rag_stats["status"] = "ready" if rag_stats["chunks"] > 0 else "indexing"
    except Exception as e:
        logger.warning(f"RAG stats error: {e}")
        rag_stats["status"] = "error"

    return {
        "system": {
            "cpu": rows[0]["cpu"] if rows else 0,
            "ram_used": rows[0]["ram_used"] if rows else 0,
            "ram_total": rows[0]["ram_total"] if rows else 0,
            "swap_used": rows[0]["swap_used"] if rows else 0,
            "disk_used": rows[0]["disk_used"] if rows else 0,
            "disk_total": rows[0]["disk_total"] if rows else 0,
            "ollama_ram": rows[0]["ollama_ram"] if rows else 0,
            "network_ok": rows[0]["network_ok"] if rows else 0
        },
        "pipeline": {
            "latency_search": chat_metrics["latency_search"][-10:],
            "latency_gen": chat_metrics["latency_gen"][-10:],
            "tokens": chat_metrics["tokens"][-10:],
            "crag_pass_rate": chat_metrics["crag_pass"] / max(1, chat_metrics["crag_pass"] + chat_metrics["crag_fail"])
        },
        "queue": {"llm_waiting": llm_queue_size},
        "errors": dict(error_counts),
        "heartbeats": heartbeats,
        "rag": rag_stats
    }

@app.get("/api/rag/datasets")
async def list_datasets(): return await rag_backend.list_datasets()

@app.post("/api/rag/datasets")
async def create_dataset(name: str):
    return {"id": await rag_backend.create_dataset(name), "name": name}

@app.get("/api/rag/sources")
async def list_sources():
    base_dir = Path("./RAG_Content")
    sources = []
    if base_dir.exists():
        ds_list = await rag_backend.list_datasets()
        for folder in sorted(base_dir.iterdir()):
            if folder.is_dir() and not UUID_RE.match(folder.name):
                src_files = [f for f in folder.iterdir() if f.is_file()]
                if not src_files: continue
                ds_name = f"{folder.name}_Index"
                ds = next((d for d in ds_list if d.name == ds_name), None)
                sources.append({
                    "folder": folder.name, "source_files": len(src_files),
                    "dataset_id": ds.id if ds else None,
                    "dataset_status": ds.status if ds else "NOT_CREATED",
                    "indexed_files": ds.doc_count if ds else 0
                })
    return sources

@app.post("/api/rag/sync/{folder}")
async def sync_folder(folder: str):
    src_dir = Path(f"./RAG_Content/{folder}")
    if not src_dir.exists() or not src_dir.is_dir(): raise HTTPException(404, "Folder not found")
    ds_list = await rag_backend.list_datasets()
    ds_name = f"{folder}_Index"
    ds = next((d for d in ds_list if d.name == ds_name), None)
    if not ds:
        ds_id = await rag_backend.create_dataset(ds_name)
        ds = DatasetInfo(id=ds_id, name=ds_name, status="IDLE", doc_count=0, chunk_count=0)

    job_id = str(uuid.uuid4())[:8]
    job_tracker[job_id] = {"dataset_id": ds.id, "dataset_name": ds_name, "status": "SCANNING", "total": 0, "processed": 0, "started_at": datetime.now().isoformat(), "message": "Сканирование..."}

    dest_dir = Path(f"./storage/datasets/{ds.id}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    new_count, skip_count = 0, 0
    files = [f for f in src_dir.iterdir() if f.is_file()]
    job_tracker[job_id]["total"] = len(files)

    for i, f in enumerate(files):
        dest = dest_dir / f.name
        is_new = not dest.exists()
        if not is_new:
            s_src, s_dst = f.stat(), dest.stat()
            if s_src.st_size != s_dst.st_size or abs(s_src.st_mtime - s_dst.st_mtime) > 1.0: is_new = True
        if is_new:
            await asyncio.to_thread(shutil.copy2, f, dest)
            await rag_backend.upload_file(ds.id, f)
            new_count += 1
        else: skip_count += 1
        job_tracker[job_id]["processed"] = i + 1
        job_tracker[job_id]["message"] = f"Копирование: {f.name}"
        log_history.append(f"[JOB {job_id}] {f.name} ({i+1}/{len(files)})")

    job_tracker[job_id]["status"] = "PARSING" if new_count > 0 else "COMPLETED"
    job_tracker[job_id]["message"] = "Векторизация (bge-m3)..." if new_count > 0 else "Нет новых файлов"

    if new_count > 0:
        async def _run():
            try:
                async with parse_semaphore: await rag_backend.parse_dataset(ds.id)
                job_tracker[job_id]["status"] = "COMPLETED"
                job_tracker[job_id]["message"] = f"Готово. Новых: {new_count}, Пропущено: {skip_count}"
            except Exception as e:
                job_tracker[job_id]["status"] = "FAILED"
                job_tracker[job_id]["message"] = f"Ошибка: {str(e)}"
        asyncio.create_task(_run())

    return {"status": "sync_started", "job_id": job_id, "dataset_id": ds.id, "new_files": new_count, "skipped_files": skip_count}

@app.post("/api/rag/upload/{dataset_id}")
async def upload_file(dataset_id: str, file: UploadFile = File(...)):
    temp_path = Path(f"/tmp/{file.filename}")
    content = await file.read()
    await asyncio.to_thread(temp_path.write_bytes, content)
    doc_id = await rag_backend.upload_file(dataset_id, temp_path)
    async def _parse():
        async with parse_semaphore: await rag_backend.parse_dataset(dataset_id)
    asyncio.create_task(_parse())
    return {"doc_id": doc_id, "status": "queued"}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.question.strip(): raise HTTPException(400, "Empty question")
    try:
        chunks = await rag_backend.retrieve(req.question, dataset_ids=req.dataset_ids, top_k=5)
    except Exception as e: raise HTTPException(500, f"Retrieval failed: {e}")
    if not chunks:
        crag_stats["no_data"] += 1
        return {"answer": "Нет данных в выбранных источниках.", "crag_status": "NO_DATA", "sources": []}
    context = "\n".join([f"[{c.doc_name}]: {c.content}" for c in chunks])
    prompt = f"Ты — инженер Л.Е.С. Ответь строго по контексту.\nКонтекст:\n{context}\n\nВопрос: {req.question}\nОтвет:"
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{os.getenv('OLLAMA_URL')}/api/generate", json={"model": os.getenv("LLM_MODEL", "qwen3:14b"), "prompt": prompt, "stream": False})
            resp.raise_for_status()
            crag_stats["verified"] += 1
            return {"answer": resp.json().get("response"), "crag_status": "VERIFIED", "sources": list(set(c.doc_name for c in chunks))}
    except httpx.HTTPStatusError as e: raise HTTPException(502, f"LLM error: {e.response.text}")
    except Exception as e: raise HTTPException(500, str(e))


@app.get("/api/jobs")
async def get_jobs():
    return job_tracker

@app.get("/api/logs/stream")
async def log_stream():
    async def gen():
        for line in log_history: yield {"data": line + "\n"}
        idx = len(log_history)
        while True:
            await asyncio.sleep(0.5)
            if len(log_history) != idx:
                for line in list(log_history)[idx:]: yield {"data": line + "\n"}
                idx = len(log_history)
    return EventSourceResponse(gen())

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    p = Path("frontend/sovushka.html")
    return p.read_text(encoding="utf-8") if p.exists() else "<h1>No UI</h1>"
