"""
MLX Native Host v3.2 — Л.Е.С.
==============================
FastAPI сервер на порту 8080.
Запуск: uv run python3 mlx_host.py

Движки:
  main_engine  — MLX_MODEL     (RAG, TTL 300с)
  val_engine   — MLX_VAL_MODEL (Т.О.С.К.А. v2, TTL 120с)
  embedder     — BGE-M3        (sentence-transformers + MPS, lazy load)
"""

import asyncio
import gc
import logging
import os
import signal
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Union

# Грузим .env из директории проекта — независимо от того, кто запустил процесс
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.mlx_adapter import MLXMemoryManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] MLX Host: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Конфигурация ──────────────────────────────────────────────────────────────
MAIN_MODEL = os.getenv("MLX_MODEL",     "mlx-community/Qwen3-14B-4bit")
VAL_MODEL  = os.getenv("MLX_VAL_MODEL", "mlx-community/Qwen3-4B-4bit")
BGE_MODEL  = os.getenv("BGE_MODEL", "BAAI/bge-m3")
BGE_BATCH_SIZE = int(os.getenv("BGE_BATCH_SIZE", "32"))

main_engine = MLXMemoryManager(model_path=MAIN_MODEL, ttl_seconds=300)
val_engine  = MLXMemoryManager(model_path=VAL_MODEL,  ttl_seconds=120)


# ── BGE-M3 через sentence-transformers (MPS на Apple Silicon) ─────────────────

class BGEEmbedder:
    """
    Lazy-load обёртка над SentenceTransformer.
    Загружается при первом запросе, выгружается через force_unload().
    sentence-transformers автоматически использует MPS на M1/M2/M4.
    """

    def __init__(self, model_id: str = BGE_MODEL):
        self.model_id = model_id
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        logger.info(f"[EMBED] Загрузка {self.model_id}...")
        self._model = SentenceTransformer(self.model_id)
        dim = self._model.get_embedding_dimension() if hasattr(self._model, 'get_embedding_dimension') else self._model.get_sentence_embedding_dimension()
        logger.info(f"[EMBED] BGE-M3 готов. dim={dim}")

    def encode(self, texts: List[str]) -> List[List[float]]:
        self._load()
        vecs = self._model.encode(
            texts,
            normalize_embeddings=True,  # L2-норма встроена
            show_progress_bar=False,
            batch_size=int(os.getenv("BGE_BATCH_SIZE", str(BGE_BATCH_SIZE))),
        )
        return [v.tolist() for v in vecs]

    def force_unload(self):
        self._model = None
        gc.collect()
        logger.info("[EMBED] BGE-M3 выгружен.")


embedder = BGEEmbedder()


# ── Lifespan ──────────────────────────────────────────────────────────────────

# Процессы которые нельзя убивать (substring match по cmdline)
_PROC_WHITELIST = (
    "python3", "python", "uvicorn",
    "docker", "com.docker", "containerd",
    "qdrant",
    "kernel_task", "launchd", "WindowServer",
    "loginwindow", "ssh", "sshd", "zsh", "bash",
    "Finder", "SystemUIServer", "Dock",
)

# Порог свопа при котором выгружаем val-модель (%)
SWAP_WARN_PCT  = 70
# Порог при котором убиваем сторонние процессы (%)
SWAP_KILL_PCT  = 85


def _kill_nonessential() -> list[str]:
    """Убивает процессы не из whitelist. Возвращает список убитых."""
    import psutil
    killed = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
            name    = proc.info["name"] or ""
            if proc.pid == os.getpid():
                continue
            if any(w.lower() in cmdline.lower() or w.lower() in name.lower()
                   for w in _PROC_WHITELIST):
                continue
            proc.send_signal(signal.SIGTERM)
            killed.append(name)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed


async def memory_guard_loop():
    """Мониторит swap каждые 30с. При давлении — выгружает val, при критическом — убивает лишние процессы."""
    import psutil
    await asyncio.sleep(30)  # даём системе стабилизироваться при старте
    while True:
        try:
            sw = psutil.swap_memory()
            if sw.percent >= SWAP_KILL_PCT:
                logger.warning(f"[MEM] Swap {sw.percent:.0f}% >= {SWAP_KILL_PCT}% — выгружаю val + убиваю посторонние")
                if val_engine.model is not None:
                    val_engine._unload_model()
                killed = await asyncio.to_thread(_kill_nonessential)
                if killed:
                    logger.warning(f"[MEM] Убито: {', '.join(set(killed))}")
            elif sw.percent >= SWAP_WARN_PCT:
                logger.warning(f"[MEM] Swap {sw.percent:.0f}% >= {SWAP_WARN_PCT}% — выгружаю val-модель")
                if val_engine.model is not None:
                    val_engine._unload_model()
            else:
                logger.debug(f"[MEM] Swap {sw.percent:.0f}% — норма")
        except Exception as e:
            logger.warning(f"[MEM] memory_guard ошибка: {e}")
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"[INIT] main  : {MAIN_MODEL}")
    logger.info(f"[INIT] val   : {VAL_MODEL}")
    logger.info(f"[INIT] embed : {BGE_MODEL} (lazy)")
    main_engine.start()
    val_engine.start()
    asyncio.create_task(memory_guard_loop())
    yield
    logger.info("[SHUTDOWN] Завершение работы.")
    embedder.force_unload()


app = FastAPI(title="LES MLX Native Host", version="3.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic схемы ────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    model:      str  = MAIN_MODEL
    prompt:     str
    stream:     bool = False
    max_tokens: int  = 2048


class EmbeddingRequest(BaseModel):
    """Ollama-совместимый запрос: принимает prompt или input."""
    input:  Optional[Union[str, List[str]]] = None
    prompt: Optional[Union[str, List[str]]] = None
    model:  str = "bge-m3"

    def get_texts(self) -> List[str]:
        raw = self.input if self.input is not None else self.prompt
        if raw is None:
            return []
        return [raw] if isinstance(raw, str) else list(raw)


class OAIMessage(BaseModel):
    role:    str
    content: Union[str, List]


class OAIChatRequest(BaseModel):
    model:       str            = MAIN_MODEL
    messages:    List[OAIMessage]
    stream:      bool           = False
    temperature: Optional[float] = 0.7
    max_tokens:  Optional[int]   = 2048


class OAIEmbeddingRequest(BaseModel):
    input: Union[str, List[str]]
    model: str = "bge-m3"


class ValidateRequest(BaseModel):
    question: str
    answer:   str
    context:  str = ""


class SwitchModelRequest(BaseModel):
    model:  str
    target: str = "main"  # "main" | "val"


# ── Хелперы ───────────────────────────────────────────────────────────────────

def _strip_think_tags(text: str) -> str:
    """Убирает блоки <think>…</think> и артефакты токенайзера из ответа Qwen3."""
    import re
    # Полный блок <think>…</think> (жадный, на случай нескольких)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Незакрытый <think> до конца строки
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    # Хвостовые стоп-токены, которые MLX иногда пропускает
    for token in ("<|im_end|>", "<|endoftext|>", "<|im_start|>", "</s>"):
        text = text.replace(token, "")
    return text.strip()


def _get_engine(model_name: str) -> "MLXMemoryManager":
    if model_name == VAL_MODEL:
        return val_engine
    return main_engine


def _messages_to_prompt(messages: List[OAIMessage], engine: "MLXMemoryManager", enable_thinking: bool = False) -> str:
    """
    Строит промпт через chat_template токенизатора движка.
    Токенизатор загружен в engine.start() — без весов модели, быстро.
    enable_thinking=False по умолчанию — RAG-система не нуждается в цепочке рассуждений.
    """
    msgs = []
    for m in messages:
        if isinstance(m.content, str):
            text = m.content
        elif isinstance(m.content, list):
            text = " ".join(
                p.get("text", "") for p in m.content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        else:
            text = str(m.content)
        msgs.append({"role": m.role, "content": text})

    return engine.apply_chat_template(msgs, enable_thinking=enable_thinking)


def _oai_response(content: str, model: str, prompt_tokens: int = 0) -> dict:
    completion_tokens = len(content.split())
    return {
        "id":      f"chatcmpl-les-{int(time.time())}",
        "object":  "chat.completion",
        "created": int(time.time()),
        "model":   model,
        "choices": [{
            "index":         0,
            "message":       {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens":     prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens":      prompt_tokens + completion_tokens,
        },
    }


# ── Системные эндпоинты ───────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    import psutil
    sw = psutil.swap_memory()
    vm = psutil.virtual_memory()
    return {
        "status":      "ok",
        "main_model":  {"path": main_engine.model_path, "loaded": main_engine.model is not None},
        "val_model":   {"path": val_engine.model_path,  "loaded": val_engine.model is not None},
        "embed_model": {
            "path": BGE_MODEL,
            "loaded": embedder._model is not None,
            "batch_size": int(os.getenv("BGE_BATCH_SIZE", str(BGE_BATCH_SIZE))),
        },
        "memory": {
            "ram_free_gb":  round(vm.available / 1e9, 1),
            "swap_used_gb": round(sw.used / 1e9, 1),
            "swap_pct":     round(sw.percent, 1),
        },
    }


@app.post("/api/unload_val")
async def unload_val():
    """Принудительная выгрузка val-модели для освобождения памяти."""
    was_loaded = val_engine.model is not None
    if was_loaded:
        val_engine._unload_model()
    return {"unloaded": was_loaded, "val_model": val_engine.model_path}


@app.post("/api/unload_all")
async def unload_all():
    """Принудительно освобождает все тяжёлые модели между стресс-тестами."""
    state = {
        "main_model": main_engine.model is not None,
        "val_model": val_engine.model is not None,
        "embed_model": embedder._model is not None,
    }
    if state["main_model"]:
        main_engine.force_unload()
    if state["val_model"]:
        val_engine.force_unload()
    if state["embed_model"]:
        embedder.force_unload()
    gc.collect()
    return {"unloaded": state}


@app.get("/api/host_memory")
async def host_memory():
    """Реальная память хоста (не Docker). Используется proxy для memory_guard."""
    import psutil
    sw = psutil.swap_memory()
    vm = psutil.virtual_memory()
    return {
        "ram_total_gb":  round(vm.total    / 1e9, 1),
        "ram_free_gb":   round(vm.available / 1e9, 1),
        "ram_used_pct":  round(vm.percent, 1),
        "swap_total_gb": round(sw.total / 1e9, 1),
        "swap_used_gb":  round(sw.used  / 1e9, 1),
        "swap_pct":      round(sw.percent, 1),
    }


@app.get("/api/ps")
async def api_ps():
    """Ollama-совместимый /api/ps — список загруженных моделей.
    Нужен proxy_server.py и metrics_collector.py для опроса статуса."""
    models = []
    if main_engine.model is not None:
        models.append({
            "name":       main_engine.model_path,
            "model":      main_engine.model_path,
            "size":       0,
            "digest":     "",
            "details":    {"family": "qwen3"},
            "expires_at": "",
        })
    if val_engine.model is not None:
        models.append({
            "name":       val_engine.model_path,
            "model":      val_engine.model_path,
            "size":       0,
            "digest":     "",
            "details":    {"family": "qwen3"},
            "expires_at": "",
        })
    return {"models": models}


@app.post("/api/switch_model")
async def switch_model(req: SwitchModelRequest):
    if req.target == "val":
        val_engine.force_unload()
        val_engine.model_path = req.model
        val_engine.reload_tokenizer()
        logger.info(f"[SWITCH] val → {req.model}")
    else:
        main_engine.force_unload()
        main_engine.model_path = req.model
        main_engine.reload_tokenizer()
        logger.info(f"[SWITCH] main → {req.model}")
    return {"status": "switched", "target": req.target, "model": req.model}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": main_engine.model_path, "object": "model", "created": 0, "owned_by": "mlx-community"},
            {"id": val_engine.model_path,  "object": "model", "created": 0, "owned_by": "mlx-community"},
            {"id": "bge-m3",               "object": "model", "created": 0, "owned_by": "mlx-community"},
        ],
    }


# ── Генерация ─────────────────────────────────────────────────────────────────

@app.post("/api/generate")
async def generate_ollama(req: GenerateRequest):
    """Ollama-совместимый endpoint для обратной совместимости."""
    engine = _get_engine(req.model)
    answer = _strip_think_tags(await engine.generate_text(prompt=req.prompt, max_tokens=req.max_tokens))
    return {"model": req.model, "response": answer, "eval_count": len(answer.split())}


@app.post("/v1/chat/completions")
async def chat_completions(req: OAIChatRequest):
    """OpenAI-совместимый — основной для прокси и Roo Code."""
    engine = _get_engine(req.model or MAIN_MODEL)
    prompt = _messages_to_prompt(req.messages, engine)
    try:
        answer = _strip_think_tags(await engine.generate_text(
            prompt=prompt,
            max_tokens=req.max_tokens or 2048,
        ))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _oai_response(answer, engine.model_path)


# ── Валидация (Т.О.С.К.А. v2) ────────────────────────────────────────────────

@app.post("/api/validate")
async def validate_answer(req: ValidateRequest):
    """Проверка ответа через Qwen3-4B. Возвращает VERIFIED / NO_DATA / HALLUCINATION."""
    # enable_thinking=False — валидатору не нужен <think> блок, нужен мгновенный ответ
    prompt = val_engine.apply_chat_template([{
        "role": "system",
        "content": (
            "Ты — строгий валидатор. Отвечай ТОЛЬКО одним словом без пояснений: "
            "VERIFIED, NO_DATA или HALLUCINATION."
        ),
    }, {
        "role": "user",
        "content": (
            f"Вопрос: {req.question}\n"
            f"Контекст: {req.context[:1500] or 'не предоставлен'}\n"
            f"Ответ для проверки: {req.answer[:1000]}\n\n"
            "VERIFIED — ответ подтверждается контекстом И отвечает на заданный вопрос.\n"
            "NO_DATA — контекст не содержит нужных данных для ответа на вопрос.\n"
            "HALLUCINATION — ответ противоречит контексту, содержит выдумки, "
            "или технически верен но НЕ отвечает на заданный вопрос.\n"
            "Одно слово:"
        ),
    }], enable_thinking=False)
    try:
        raw = _strip_think_tags(await val_engine.generate_text(prompt=prompt, max_tokens=64)).upper()
        if "VERIFIED" in raw:        status = "VERIFIED"
        elif "NO_DATA" in raw:       status = "NO_DATA"
        elif "HALLUCINATION" in raw: status = "HALLUCINATION"
        else:                        status = "UNKNOWN"
        logger.info(f"[VALIDATE] → {status}")
        return {"status": status, "raw": raw}
    except Exception as e:
        logger.warning(f"[VALIDATE] Ошибка: {e}")
        return {"status": "SKIP", "error": str(e)}


# ── Эмбеддинги ───────────────────────────────────────────────────────────────

@app.post("/api/embeddings")
async def embeddings_ollama(req: EmbeddingRequest):
    """Ollama-формат: принимает prompt или input. Для qdrant_adapter."""
    texts = req.get_texts()
    if not texts:
        raise HTTPException(400, "Укажи input или prompt")
    try:
        vectors = embedder.encode(texts)
    except Exception as e:
        logger.error(f"[EMBED] /api/embeddings error: {e}", exc_info=True)
        raise HTTPException(500, f"Embedding error: {e}")

    if len(texts) == 1:
        return {"model": req.model, "embedding": vectors[0]}
    return {"model": req.model, "data": [{"embedding": v, "index": i} for i, v in enumerate(vectors)]}


@app.post("/v1/embeddings")
async def embeddings_openai(req: OAIEmbeddingRequest):
    """OpenAI-формат: для LlamaIndex / qdrant_adapter."""
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    try:
        vectors = embedder.encode(texts)
    except Exception as e:
        logger.error(f"[EMBED] /v1/embeddings error: {e}", exc_info=True)
        raise HTTPException(500, f"Embedding error: {e}")

    total_tokens = sum(len(t.split()) for t in texts)
    return {
        "object": "list",
        "data":   [{"object": "embedding", "embedding": v, "index": i} for i, v in enumerate(vectors)],
        "model":  req.model,
        "usage":  {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
