import os
import re
import logging
import asyncio
import time
import json
import shutil
import psutil
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
import httpx

from backend.qdrant_adapter import QdrantLlamaIndexAdapter
from backend.interface import DatasetInfo
from backend.metrics_collector import MetricsCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="LES Proxy v2.0", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

rag_backend = QdrantLlamaIndexAdapter(
    qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
    ollama_url=os.getenv("OLLAMA_URL", "http://host.docker.internal:11434"),
    embed_model_name=os.getenv("EMBED_MODEL", "bge-m3:latest")
)

metrics = MetricsCollector()
parse_semaphore = asyncio.Semaphore(2)
crag_stats = {"verified": 0, "no_data": 0, "needs_review": 0}
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

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

@app.middleware("http")
async def latency_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    latency = time.time() - start
    if request.url.path == "/api/chat":
        try:
            vm = psutil.virtual_memory()
            ds = await rag_backend.list_datasets()
            metrics.record(
                cpu=psutil.cpu_percent(interval=None),
                ram_used=vm.used / (1024**3),
                ram_total=vm.total / (1024**3),
                datasets=len(ds),
                chunks=parse_stats.total_chunks,
                latency=latency,
                crag_v=crag_stats["verified"],
                crag_n=crag_stats["no_data"]
            )
        except Exception: pass
    return response

@app.get("/api/health")
async def health():
    return {"status": "ok" if await rag_backend.health() else "error", "backend": "qdrant_llama"}

@app.get("/api/metrics")
async def get_metrics():
    try:
        ds = await rag_backend.list_datasets()
        latest = metrics.get_latest()
        return {
            "latest": {**latest, "datasets": len(ds), "files_processed": parse_stats.total_files, "chunks_indexed": parse_stats.total_chunks, "queue": parse_stats.queued, "active": parse_stats.active, "avg_speed_fps": parse_stats.avg_speed()},
            "history": metrics.get_history(30)
        }
    except Exception as e:
        return {"error": str(e)}

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
                    "folder": folder.name,
                    "source_files": len(src_files),
                    "dataset_id": ds.id if ds else None,
                    "dataset_status": ds.status if ds else "NOT_CREATED",
                    "indexed_files": ds.doc_count if ds else 0
                })
    return sources

@app.post("/api/rag/sync/{folder}")
async def sync_folder(folder: str):
    src_dir = Path(f"./RAG_Content/{folder}")
    if not src_dir.exists() or not src_dir.is_dir():
        raise HTTPException(404, "Папка не найдена")
    ds_list = await rag_backend.list_datasets()
    ds_name = f"{folder}_Index"
    ds = next((d for d in ds_list if d.name == ds_name), None)
    if not ds:
        ds_id = await rag_backend.create_dataset(ds_name)
        ds = DatasetInfo(id=ds_id, name=ds_name, status="IDLE", doc_count=0, chunk_count=0)
    dest_dir = Path(f"./storage/datasets/{ds.id}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in src_dir.iterdir():
        if f.is_file():
            dest = dest_dir / f.name
            if not dest.exists(): shutil.copy2(f, dest)
            await rag_backend.upload_file(ds.id, f)
            count += 1
    parse_stats.queued += 1
    async def _run_parse():
        async with parse_semaphore:
            parse_stats.queued -= 1
            parse_stats.active += 1
            try: await rag_backend.parse_dataset(ds.id)
            finally: parse_stats.active -= 1
    asyncio.create_task(_run_parse())
    return {"status": "sync_started", "dataset_id": ds.id, "files_queued": count}

@app.get("/api/rag/datasets", response_model=List[DatasetInfo])
async def list_datasets():
    return await rag_backend.list_datasets()

@app.post("/api/rag/datasets")
async def create_dataset(name: str):
    ds_id = await rag_backend.create_dataset(name)
    return {"id": ds_id, "name": name}

@app.post("/api/rag/upload/{dataset_id}")
async def upload_file(dataset_id: str, file: UploadFile = File(...)):
    temp_path = Path(f"/tmp/{file.filename}")
    with open(temp_path, "wb") as f:
        f.write(await file.read())
    doc_id = await rag_backend.upload_file(dataset_id, temp_path)
    parse_stats.queued += 1
    async def _parse_limited():
        async with parse_semaphore:
            parse_stats.queued -= 1
            parse_stats.active += 1
            start_t = time.time()
            try:
                res = await rag_backend.parse_dataset(dataset_id)
                parse_stats.total_chunks += res.get("chunks", 0)
            finally:
                parse_stats.active -= 1
                parse_stats.total_files += 1
                parse_stats.durations.append(time.time() - start_t)
                if len(parse_stats.durations) > 50: parse_stats.durations.pop(0)
    asyncio.create_task(_parse_limited())
    return {"doc_id": doc_id, "status": "queued"}

@app.get("/api/rag/delta")
async def get_delta():
    return {"new": 0, "modified": 0, "synced": 0, "errors": 0}

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
            data = resp.json()
            crag_stats["verified"] += 1
            return {"answer": data.get("response", "Ошибка генерации"), "crag_status": "VERIFIED", "sources": list(set(c.doc_name for c in chunks))}
    except httpx.HTTPStatusError as e: raise HTTPException(502, f"LLM service error: {e.response.text}")
    except Exception as e: raise HTTPException(500, str(e))

@app.get("/api/logs/stream")
async def log_stream():
    async def event_generator():
        while True:
            yield {"data": json.dumps({"level": "INFO", "module": "sys", "msg": f"Heartbeat {time.time()}", "ts": time.time()}) + "\n"}
            await asyncio.sleep(5)
    return EventSourceResponse(event_generator())

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    html_path = Path("frontend/sovushka.html")
    if html_path.exists(): return html_path.read_text(encoding="utf-8")
    return "<h1>Frontend not found.</h1>"
