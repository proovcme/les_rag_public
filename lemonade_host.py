"""LES Lemonade Host adapter.

Windows/Ryzen AI does not have Apple MLX, but several LES runtime paths expect
an MLX-compatible local host for embeddings, rerank, validation, model switch
and unload.  This adapter exposes that small compatibility surface and forwards
the actual work to Lemonade.

Run on Windows light profile:

    uv run python lemonade_host.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Iterable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import psutil
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.inference.validator import rules_validate


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] LemonadeHost: %(message)s")
logger = logging.getLogger("les.lemonade_host")

def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _model_env(*names: str, default: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return default


LLM_MODEL = _model_env("LEMONADE_MODEL", "LLM_MODEL", default="qwen3.5-4b-FLM")
VAL_MODEL = _model_env("MLX_VAL_MODEL", "LEMONADE_VAL_MODEL", "LEMONADE_MODEL", "LLM_MODEL", default=LLM_MODEL)
EMBED_MODEL = _model_env("LEMONADE_EMBED_MODEL", "EMBED_MODEL", default="Qwen3-Embedding-0.6B-GGUF").replace(":latest", "")
RERANK_MODEL = _model_env("LEMONADE_RERANK_MODEL", default="Qwen3-Reranker-0.6B-Q8_0-GGUF")
IDLE_UNLOAD_SEC = _env_int("LES_LEMONADE_IDLE_UNLOAD_SEC", 600)
_last_activity = time.monotonic()


class ValidateRequest(BaseModel):
    question: str
    answer: str
    context: str = ""


class SwitchModelRequest(BaseModel):
    target: str = "main"
    model: str


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(default_factory=list)
    top_k: int | None = None
    top_n: int | None = None


def _touch() -> None:
    global _last_activity
    _last_activity = time.monotonic()


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _lemonade_root() -> str:
    root = (os.getenv("LEMONADE_URL") or "").strip()
    if root:
        return root.rstrip("/")
    base = (os.getenv("LEMONADE_BASE_URL") or "").strip()
    for suffix in ("/api/v1", "/v1"):
        if base.rstrip("/").endswith(suffix):
            return base.rstrip("/")[: -len(suffix)]
    return "http://127.0.0.1:13305"


def _dedup(urls: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for url in urls:
        clean = url.rstrip("/")
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def _openai_candidates(path: str) -> list[str]:
    root = _lemonade_root()
    configured = (os.getenv("LEMONADE_OPENAI_BASE_URL") or os.getenv("LEMONADE_BASE_URL") or "").strip()
    return _dedup(
        [
            _join_url(configured, path) if configured else "",
            _join_url(f"{root}/v1", path),
            _join_url(f"{root}/api/v1", path),
        ]
    )


def _api_candidates(path: str) -> list[str]:
    root = _lemonade_root()
    configured = (os.getenv("LEMONADE_API_BASE_URL") or os.getenv("LEMONADE_BASE_URL") or "").strip()
    return _dedup(
        [
            _join_url(configured, path) if configured else "",
            _join_url(f"{root}/api/v1", path),
        ]
    )


async def _post_json(urls: list[str], payload: dict[str, Any], *, timeout: float = 60.0) -> dict[str, Any]:
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for url in urls:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code in {404, 405}:
                    last_error = HTTPException(resp.status_code, f"{url}: {resp.text[:160]}")
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001 - try alternate Lemonade URL shape.
                last_error = exc
    raise HTTPException(502, f"Lemonade gateway error: {last_error}")


async def _get_json(urls: list[str], *, timeout: float = 10.0) -> dict[str, Any]:
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for url in urls:
            try:
                resp = await client.get(url)
                if resp.status_code in {404, 405}:
                    last_error = HTTPException(resp.status_code, f"{url}: {resp.text[:160]}")
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
    raise HTTPException(502, f"Lemonade gateway error: {last_error}")


async def _lemonade_unload() -> dict[str, Any]:
    return await _post_json(_api_candidates("/unload"), {}, timeout=30.0)


async def _models_loaded() -> bool:
    try:
        data = await _get_json(_api_candidates("/health"), timeout=5.0)
    except Exception:
        return False
    return bool(data.get("all_models_loaded") or data.get("model_loaded"))


async def _idle_unloader() -> None:
    if IDLE_UNLOAD_SEC <= 0:
        logger.info("[STANDBY] idle unload disabled")
        return
    logger.info("[STANDBY] idle unload after %s sec", IDLE_UNLOAD_SEC)
    while True:
        await asyncio.sleep(30)
        try:
            idle = time.monotonic() - _last_activity
            if idle >= IDLE_UNLOAD_SEC and await _models_loaded():
                logger.info("[STANDBY] idle %.0f sec -> unloading Lemonade models", idle)
                await _lemonade_unload()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[STANDBY] unload loop: %s", exc)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    asyncio.create_task(_idle_unloader())
    yield


app = FastAPI(title="LES Lemonade Host Adapter", version="1.0.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "status": "ok",
        "backend": "lemonade",
        "lemonade_root": _lemonade_root(),
        "main_model": {"path": LLM_MODEL, "loaded": True},
        "val_model": {"path": VAL_MODEL, "loaded": True},
        "embed_model": {"path": EMBED_MODEL, "profile": "windows-lemonade", "loaded": True},
        "rerank_model": {"path": RERANK_MODEL, "loaded": True},
        "memory": {
            "ram_free_gb": round(vm.available / 1e9, 1),
            "swap_used_gb": round(sw.used / 1e9, 1),
            "swap_pct": round(sw.percent, 1),
        },
    }


@app.get("/api/host_memory")
async def host_memory() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "ram_total_gb": round(vm.total / 1e9, 1),
        "ram_free_gb": round(vm.available / 1e9, 1),
        "ram_used_pct": round(vm.percent, 1),
        "swap_total_gb": round(sw.total / 1e9, 1),
        "swap_used_gb": round(sw.used / 1e9, 1),
        "swap_pct": round(sw.percent, 1),
    }


@app.post("/api/unload_all")
async def unload_all() -> dict[str, Any]:
    try:
        result = await _lemonade_unload()
        return {"status": "ok", "backend": "lemonade", "lemonade": result}
    except Exception as exc:  # noqa: BLE001
        logger.error("[UNLOAD] %s", exc)
        return {"status": "error", "backend": "lemonade", "error": str(exc)}


@app.post("/api/switch_model")
async def switch_model(req: SwitchModelRequest) -> dict[str, str]:
    global LLM_MODEL, VAL_MODEL
    model = (req.model or "").strip()
    target = (req.target or "main").strip().lower()
    if not model:
        raise HTTPException(400, "model is required")
    if target == "val":
        VAL_MODEL = model
        os.environ["MLX_VAL_MODEL"] = model
    else:
        target = "main"
        LLM_MODEL = model
        os.environ["LEMONADE_MODEL"] = model
        os.environ["LLM_MODEL"] = model
    logger.info("[SWITCH] %s -> %s", target, model)
    return {"status": "switched", "target": target, "model": model}


@app.post("/api/validate")
async def validate_answer(req: ValidateRequest) -> dict[str, Any]:
    rules_result = rules_validate(req.question or "", req.answer or "", req.context or "")
    if rules_result.get("status") in {"VERIFIED", "HALLUCINATION"} or rules_result.get("raw") == "empty_context":
        return rules_result

    prompt = (
        "Ты — строгий валидатор ответов. Отвечай ТОЛЬКО одним словом без пояснений: "
        "VERIFIED, NO_DATA или HALLUCINATION.\n\n"
        f"Вопрос: {req.question}\n"
        f"Контекст: {(req.context or '')[:6000] or 'не предоставлен'}\n"
        f"Ответ для проверки: {(req.answer or '')[:1000]}\n\n"
        "VERIFIED — ответ подтверждается контекстом И отвечает на заданный вопрос.\n"
        "NO_DATA — контекст не содержит нужных данных для ответа на вопрос.\n"
        "HALLUCINATION — ответ противоречит контексту или не отвечает на вопрос.\n"
        "Одно слово:"
    )
    payload = {
        "model": VAL_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 15,
        "stream": False,
    }
    data = await _post_json(_openai_candidates("/chat/completions"), payload, timeout=30.0)
    raw = str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).upper().strip()
    if "VERIFIED" in raw:
        status = "VERIFIED"
    elif "NO_DATA" in raw:
        status = "NO_DATA"
    elif "HALLUCINATION" in raw:
        status = "HALLUCINATION"
    else:
        status = "UNKNOWN"
    return {"status": status, "raw": raw, "backend": "lemonade", "rules_raw": rules_result.get("raw")}


@app.post("/v1/chat/completions")
async def chat_completions(req: dict[str, Any]):
    _touch()
    req = dict(req or {})
    req["model"] = LLM_MODEL
    if req.get("stream"):
        url = _openai_candidates("/chat/completions")[0]

        async def _relay():
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", url, json=req) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk

        return StreamingResponse(_relay(), media_type="text/event-stream")
    return await _post_json(_openai_candidates("/chat/completions"), req, timeout=120.0)


@app.post("/v1/embeddings")
async def embeddings(req: dict[str, Any]) -> dict[str, Any]:
    _touch()
    req = dict(req or {})
    requested_model = str(req.get("model") or "").strip()
    if not requested_model or requested_model in {"bge-m3", "user.bge-m3-GGUF", "qwen3-embedding-0.6b"}:
        req["model"] = EMBED_MODEL
    return await _post_json(_openai_candidates("/embeddings"), req, timeout=60.0)


@app.post("/v1/rerank")
async def rerank_endpoint(req: RerankRequest) -> dict[str, Any]:
    _touch()
    if not req.documents:
        return {"model": RERANK_MODEL, "results": []}
    payload: dict[str, Any] = {
        "model": RERANK_MODEL,
        "query": req.query,
        "documents": req.documents,
    }
    top_n = req.top_k if req.top_k is not None else req.top_n
    if top_n is not None:
        payload["top_n"] = top_n
    data = await _post_json(_api_candidates("/reranking"), payload, timeout=60.0)
    results = []
    for item in data.get("results", []):
        score = item.get("score", item.get("relevance_score", 0.0))
        results.append({"index": int(item.get("index", -1)), "score": float(score)})
    return {"model": data.get("model", RERANK_MODEL), "results": results}


@app.get("/api/ps")
async def api_ps() -> dict[str, Any]:
    try:
        data = await _get_json(_openai_candidates("/models"), timeout=5.0)
        models = []
        for model in data.get("data", []):
            models.append(
                {
                    "name": model.get("id"),
                    "model": model.get("id"),
                    "size": int(float(model.get("size", 0) or 0) * 1e9),
                    "details": {"family": model.get("recipe", "lemonade")},
                }
            )
        return {"models": models}
    except Exception:
        return {"models": [{"name": LLM_MODEL, "model": LLM_MODEL}]}


if __name__ == "__main__":
    port = _env_int("LEMONADE_HOST_PORT", 18080)
    bind = os.getenv("LEMONADE_HOST_BIND", "127.0.0.1")
    logger.info("Starting LES Lemonade Host Adapter on %s:%s -> %s", bind, port, _lemonade_root())
    uvicorn.run(app, host=bind, port=port)
