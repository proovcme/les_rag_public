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
from collections.abc import Iterable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import psutil
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.inference.validator import rules_validate
from extensions.lemonade.model_policy import apply_recipe_options_bootstrap
from extensions.lemonade.role_model import (
    RoleModelCache,
    answer_model_from_registry,
    select_chat_model,
)
from extensions.lemonade.vendor_status import (
    _record_proves_loaded,
    EMBEDDING_BACKEND,
    EMBEDDING_MODEL_ID,
    EMBEDDING_VECTOR_SIZE,
    embedding_identity,
    lemonade_health_from_vendor,
    vendor_has_loaded_models,
    VendorIdleGuard,
)


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
EMBED_MODEL = EMBEDDING_MODEL_ID
# bge-reranker-v2-m3 на том же CPU втрое быстрее Qwen3-Reranker-0.6B при том же порядке
# кандидатов (замер 11.10: 48 карточек норм — 17,6 с против 54 с). Общая настройка
# RERANK_MODEL действует и здесь, чтобы имя модели не расходилось с реестром LES.
RERANK_MODEL = _model_env("LEMONADE_RERANK_MODEL", "RERANK_MODEL", default="bge-reranker-v2-m3-GGUF")
IDLE_UNLOAD_SEC = _env_int("LES_LEMONADE_IDLE_UNLOAD_SEC", 600)
_last_activity = time.monotonic()

# Выбранную модель ответа знает реестр ролей; окружение отстаёт от смены ревизии и
# называет прежнюю. Короткий кэш держит SQLite вне горячего пути запроса.
_role_cache = RoleModelCache(
    answer_model_from_registry,
    ttl_seconds=float(_env_int("LES_LEMONADE_ROLE_TTL_SEC", 5)),
)


def _role_answer_model() -> str:
    """Имя модели роли «Ответы»; пустая строка, если реестр недоступен."""
    return _role_cache.get()


async def _vendor_model_ids() -> list[str]:
    """Идентификаторы каталога вендора; при недоступности — пустой список."""
    try:
        catalogue = await _get_json(_openai_candidates("/models"), timeout=5.0)
    except Exception as error:  # noqa: BLE001 — каталог не обязателен для решения
        logger.warning("[MODEL] vendor catalogue unavailable: %s", error)
        return []
    data = catalogue.get("data") if isinstance(catalogue, dict) else None
    return [str(item.get("id")) for item in (data or []) if isinstance(item, dict) and item.get("id")]


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
    return vendor_has_loaded_models(data)


async def _idle_unloader() -> None:
    if IDLE_UNLOAD_SEC <= 0:
        logger.info("[STANDBY] idle unload disabled")
        return
    logger.info("[STANDBY] idle unload after %s sec", IDLE_UNLOAD_SEC)
    vendor_idle = VendorIdleGuard()
    while True:
        await asyncio.sleep(30)
        try:
            now = time.monotonic()
            idle = now - _last_activity
            health = await _get_json(_api_candidates("/health"), timeout=5.0)
            vendor_safe = vendor_idle.may_unload(health, now=now, idle_seconds=IDLE_UNLOAD_SEC)
            if idle >= IDLE_UNLOAD_SEC and vendor_safe:
                logger.info("[STANDBY] idle %.0f sec -> unloading Lemonade models", idle)
                await _lemonade_unload()
        except Exception as exc:  # noqa: BLE001
            vendor_idle = VendorIdleGuard()
            logger.warning("[STANDBY] unload loop: %s", exc)


async def _bootstrap_recipe_options() -> None:
    """Восполнить настройки наших моделей в кэше Lemonade, если их там нет.

    `recipe_options.json` принадлежит вендору и живёт вне репозитория: после
    переустановки модель стартует без `ctx_size`, снимок теряет
    `observed_context_tokens`, а исполнение падает на пресет qwen-9b-restrictive.
    Дописываем только отсутствующее; ручные правки оператора не трогаем.
    """
    path = os.getenv("LEMONADE_RECIPE_OPTIONS_PATH") or str(
        Path.home() / ".cache" / "lemonade" / "recipe_options.json"
    )
    try:
        catalogue = await _get_json(_api_candidates("/models"), timeout=10.0)
        model_ids = [
            str(item.get("id"))
            for item in (catalogue.get("data") or [])
            if isinstance(item, dict) and item.get("id")
        ]
        if not model_ids:
            return
        report = apply_recipe_options_bootstrap(path, model_ids)
        if report.get("added"):
            logger.info(
                "recipe options bootstrapped: added=%s backup=%s",
                report["added"],
                report.get("backup"),
            )
        if report.get("differs"):
            logger.info("recipe options differ from verified values: %s", report["differs"])
    except Exception as error:  # noqa: BLE001 — вендор недоступен: старт не блокируем
        logger.warning("recipe options bootstrap skipped: %s", error)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    asyncio.create_task(_idle_unloader())
    asyncio.create_task(_bootstrap_recipe_options())
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
    try:
        vendor = await _get_json(_api_candidates("/health"), timeout=5.0)
    except Exception:
        vendor = None
    snapshot = lemonade_health_from_vendor(
        vendor,
        chat_model=_role_answer_model() or LLM_MODEL,
        validation_model=VAL_MODEL,
        rerank_model=RERANK_MODEL,
    )
    role_keys = {
        "chat": "main_model",
        "validation": "val_model",
        "embedding": "embed_model",
        "rerank": "rerank_model",
    }
    vendor_types = {
        "chat": "llm",
        "validation": "llm",
        "embedding": "embedding",
        "rerank": "reranking",
    }
    roles = {
        role_keys[descriptor.role]: {
            "path": descriptor.model_id,
            "type": vendor_types[descriptor.role],
            "loaded": descriptor.loaded,
            "backend": descriptor.backend,
        }
        for descriptor in snapshot.models
    }
    all_roles_loaded = all(role["loaded"] for role in roles.values())
    status = "unavailable" if not snapshot.available else ("ok" if all_roles_loaded else "degraded")
    reason = snapshot.detail if not snapshot.available else ("ready" if all_roles_loaded else "required_models_not_ready")
    roles["embed_model"].update(
        {
            "profile": "windows-lemonade",
            "embedding_backend": EMBEDDING_BACKEND,
            "vector_size": EMBEDDING_VECTOR_SIZE,
            "embedding_identity": embedding_identity(),
        }
    )
    return {
        "status": status,
        "reason": reason,
        "backend": "lemonade",
        "lemonade_root": _lemonade_root(),
        **roles,
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
    # Имя роли валидатора историческое, MLX-овское (mlx-community/…), а на Windows у
    # вендора такой модели нет: опыт 18.09 на живом стенде вернул 404 model_not_found.
    # То есть валидация молча падала бы на каждом вызове. Отправляем имя, которое
    # вендор действительно знает, — по тому же правилу, что и чат.
    payload = {
        "model": select_chat_model(
            VAL_MODEL,
            catalogue=await _vendor_model_ids(),
            role_model=_role_answer_model(),
            fallback=LLM_MODEL,
        ),
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
    req["model"] = select_chat_model(
        req.get("model"),
        catalogue=await _vendor_model_ids(),
        role_model=_role_answer_model(),
        fallback=LLM_MODEL,
    )
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
    if requested_model and requested_model.casefold().removesuffix(":latest") != EMBED_MODEL.casefold():
        raise HTTPException(409, "embedding_model_mismatch")
    req["model"] = EMBED_MODEL
    data = await _post_json(_openai_candidates("/embeddings"), req, timeout=60.0)
    data["embedding_model"] = EMBED_MODEL
    data["embedding_backend"] = EMBEDDING_BACKEND
    data["embedding_identity"] = embedding_identity()
    return data


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
    """Модели, которые сейчас в памяти вендора, — не каталог скачанного.

    Прежняя редакция строила ответ из `/models` и при нуле загруженных отдавала весь
    каталог; сборщик метрик суммировал его `size` и показывал 72 ГБ занятой моделями
    памяти на машине с 31 ГБ ОЗУ. Недоступный вендор даёт пустой список: молчание
    честнее выдуманной резидентности.

    `size` вендор в этих записях не сообщает, а брать его из каталога нельзя —
    скачанный вес не равен занятой памяти. Ноль означает «неизвестно».
    """
    try:
        vendor = await _get_json(_api_candidates("/health"), timeout=5.0)
    except Exception as error:  # noqa: BLE001 — вендор недоступен, резидентных моделей нет
        logger.warning("[PS] vendor health unavailable: %s", error)
        return {"models": []}
    records = vendor.get("all_models_loaded") if isinstance(vendor, dict) else None
    models = [
        {
            "name": str(record.get("model_name")),
            "model": str(record.get("model_name")),
            "size": 0,
            "details": {"family": str(record.get("recipe") or "lemonade")},
        }
        for record in (records or [])
        if isinstance(record, Mapping) and record.get("model_name") and _record_proves_loaded(record)
    ]
    return {"models": models}


if __name__ == "__main__":
    port = _env_int("LEMONADE_HOST_PORT", 18080)
    bind = os.getenv("LEMONADE_HOST_BIND", "127.0.0.1")
    logger.info("Starting LES Lemonade Host Adapter on %s:%s -> %s", bind, port, _lemonade_root())
    uvicorn.run(app, host=bind, port=port)
