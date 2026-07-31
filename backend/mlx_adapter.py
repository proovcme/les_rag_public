"""
MLXMemoryManager — управление памятью Metal для LLM.

Токенизатор и веса модели грузятся лениво при первом запросе, выгружаются по TTL.
Для старого eager-поведения можно задать MLX_PRELOAD_TOKENIZERS=true.
Глобальный metal_semaphore — один движок на Metal в любой момент.
"""
import asyncio
import copy
import gc
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# Один запрос к Metal одновременно — защита от OOM при параллельных движках
metal_semaphore = asyncio.Semaphore(1)

STOP_TOKENS = ["<|im_end|>", "<|endoftext|>", "<|end|>"]


def _load_auto_tokenizer(model_path: str):
    """Ленивый импорт transformers — модуль грузится без тяжёлых зависимостей."""
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model_path)


def _mlx_load(model_path: str):
    """Ленивый импорт mlx_lm.load — модуль импортируется офлайн без MLX."""
    from mlx_lm import load

    return load(model_path)


def _new_prompt_cache():
    """Bounded MLX-LM prefix cache; imported only on a Mac inference host."""
    from mlx_lm.models.cache import LRUPromptCache

    max_entries = max(1, int(os.getenv("MLX_PROMPT_CACHE_MAX_ENTRIES", "4")))
    max_bytes = max(
        64 * 1024 * 1024,
        int(os.getenv("MLX_PROMPT_CACHE_MAX_BYTES", str(1024 * 1024 * 1024))),
    )
    return LRUPromptCache(max_size=max_entries, max_bytes=max_bytes)


def _make_prompt_cache(model):
    from mlx_lm.models.cache import make_prompt_cache

    return make_prompt_cache(model)


def _raw_stream_generate(model, tokenizer, **kwargs):
    from mlx_lm import stream_generate

    return stream_generate(model, tokenizer, **kwargs)


def _prefill_prompt_cache(model, tokens, prompt_cache) -> None:
    """Advance an existing MLX cache through tokens without generating output."""
    if not tokens:
        return
    import mlx.core as mx
    from mlx_lm.generate import generate_step

    for _ in generate_step(
        mx.array(tokens, dtype=mx.uint32),
        model,
        max_tokens=0,
        prompt_cache=prompt_cache,
    ):
        pass


def _mlx_stream_generate(
    model,
    tokenizer,
    *,
    prompt: str,
    max_tokens: int,
    cache_prefix_prompt: str = "",
    prompt_cache_store=None,
    prompt_cache_key: object | None = None,
    cache_stats: dict | None = None,
):
    """Generate with bounded longest-prefix reuse between HTTP chat turns."""
    prefill_started = time.perf_counter()
    progress_started = False
    stats = cache_stats if cache_stats is not None else {}
    prompt_tokens = tokenizer.encode(prompt)
    if hasattr(prompt_tokens, "tolist"):
        prompt_tokens = prompt_tokens.tolist()
    prompt_tokens = [int(token) for token in prompt_tokens]
    cache_key = prompt_cache_key if prompt_cache_key is not None else id(model)
    prefix_tokens: list[int] = []
    if cache_prefix_prompt:
        encoded_prefix = tokenizer.encode(cache_prefix_prompt)
        if hasattr(encoded_prefix, "tolist"):
            encoded_prefix = encoded_prefix.tolist()
        encoded_prefix = [int(token) for token in encoded_prefix]
        common = 0
        for left, right in zip(encoded_prefix, prompt_tokens):
            if left != right:
                break
            common += 1
        # Keep the generation suffix non-empty and cache only an exact prefix.
        prefix_tokens = encoded_prefix[: min(common, max(0, len(prompt_tokens) - 1))]
    cached_tokens = 0
    prompt_cache = None
    remaining_prefix = prefix_tokens
    if prompt_cache_store is not None and prefix_tokens:
        prompt_cache, remaining_prefix = prompt_cache_store.fetch_nearest_cache(
            cache_key,
            prefix_tokens,
        )
        if prompt_cache is not None:
            cached_tokens = len(prefix_tokens) - len(remaining_prefix)
    if prompt_cache is None:
        prompt_cache = _make_prompt_cache(model)
    if remaining_prefix:
        _prefill_prompt_cache(model, remaining_prefix, prompt_cache)
    if prompt_cache_store is not None and prefix_tokens:
        snapshot = copy.deepcopy(prompt_cache)
        snapshot_bytes = sum(
            int(getattr(item, "nbytes", 0) or 0) for item in snapshot
        )
        prompt_cache_store.insert_cache(
            cache_key,
            prefix_tokens,
            snapshot,
            cache_type="assistant",
        )
        stats["cache_snapshot_bytes"] = snapshot_bytes
        stats["cache_entries"] = len(prompt_cache_store)
        stats["cache_bytes"] = int(prompt_cache_store.nbytes)
        stats["cache_stored"] = len(prompt_cache_store) > 0
    generation_tokens = prompt_tokens[len(prefix_tokens) :]
    stats.update(
        {
            "prompt_tokens": len(prompt_tokens),
            "cached_tokens": cached_tokens,
            "cache_hit": cached_tokens > 0,
        }
    )

    def _prefill_progress(processed: int, total: int) -> None:
        nonlocal progress_started
        if not progress_started:
            progress_started = True
            logger.info(
                "[PREFILL] model=%s tokens=%s cached=%s started",
                getattr(model, "model_type", type(model).__name__),
                len(prompt_tokens),
                cached_tokens,
            )
        if processed >= total:
            logger.info(
                "[PREFILL] model=%s tokens=%s cached=%s completed=%.2fs",
                getattr(model, "model_type", type(model).__name__),
                len(prompt_tokens),
                cached_tokens,
                time.perf_counter() - prefill_started,
            )

    return _raw_stream_generate(
        model,
        tokenizer,
        prompt=generation_tokens,
        max_tokens=max_tokens,
        prompt_cache=prompt_cache,
        prompt_progress_callback=_prefill_progress,
    )


def _mlx_generate(
    model,
    tokenizer,
    *,
    prompt: str,
    max_tokens: int,
    cache_prefix_prompt: str = "",
    prompt_cache_store=None,
    prompt_cache_key: object | None = None,
    cache_stats: dict | None = None,
):
    return "".join(
        str(getattr(response, "text", "") or "")
        for response in _mlx_stream_generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            cache_prefix_prompt=cache_prefix_prompt,
            prompt_cache_store=prompt_cache_store,
            prompt_cache_key=prompt_cache_key,
            cache_stats=cache_stats,
        )
    )


def _clear_metal_cache():
    """
    Освобождает кэш буферов Metal после выгрузки весов.
    gc.collect() роняет питоновские ссылки, но Metal держит буферный кэш —
    на 24ГБ Apple Silicon это копит давление и ведёт к OOM. No-op если MLX нет.
    """
    try:
        import mlx.core as mx
    except Exception:
        return
    try:
        mx.clear_cache()
    except Exception:
        # старые сборки MLX: метод жил в mlx.core.metal
        try:
            mx.metal.clear_cache()  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[TTL] clear_cache недоступен: {e}")


class MLXMemoryManager:
    def __init__(self, model_path: str, ttl_seconds: int = 300):
        self.model_path    = model_path
        self.ttl_seconds   = ttl_seconds
        self.model         = None
        self.tokenizer     = None
        self.prompt_cache  = None
        self.prompt_cache_model_key = None
        self.last_generation_metrics: dict = {}
        self.last_used     = 0.0
        self._lock         = None
        self._cleanup_task = None

    def start(self):
        """Вызывается внутри lifespan когда event loop уже запущен. Идемпотентно."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        if os.getenv("MLX_PRELOAD_TOKENIZERS", "").lower() in {"1", "true", "yes", "on"}:
            try:
                logger.info(f"[TOKENIZER] Загрузка {self.model_path}...")
                self.tokenizer = _load_auto_tokenizer(self.model_path)
                logger.info(f"[TOKENIZER] Готов.")
            except Exception as e:
                logger.warning(f"[TOKENIZER] Не удалось загрузить: {e}")
        else:
            logger.info(f"[TOKENIZER] Lazy preload enabled for {self.model_path}")
        # Не плодим вторую задачу при повторном start() — иначе утечка задачи.
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._auto_unload_loop())

    def stop(self):
        """Останавливает фоновую задачу выгрузки. Вызывается при shutdown."""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        self._cleanup_task = None

    async def _auto_unload_loop(self):
        while True:
            try:
                await asyncio.sleep(10)
                if self.model is not None:
                    idle = time.time() - self.last_used
                    if idle > self.ttl_seconds:
                        if self.is_busy():
                            logger.debug(f"[TTL] {self.model_path} busy, unload postponed")
                            continue
                        logger.info(f"[TTL] Выгрузка {self.model_path} (idle {idle:.0f}s)")
                        self._unload_model()
            except asyncio.CancelledError:
                # Чистая остановка по stop() — не глотаем отмену.
                raise
            except Exception as e:  # noqa: BLE001
                # Любой сбой выгрузки не должен убивать цикл навсегда (иначе модель
                # больше никогда не выгрузится — утечка памяти).
                logger.warning(f"[TTL] Ошибка в auto-unload цикле {self.model_path}: {e}")

    def _unload_model(self):
        """Выгружает только веса, токенизатор остаётся."""
        self.model = None
        self.prompt_cache = None
        self.prompt_cache_model_key = None
        self.last_generation_metrics = {}
        gc.collect()
        _clear_metal_cache()
        logger.info(f"[TTL] Память Metal освобождена: {self.model_path}")

    def is_busy(self) -> bool:
        return bool(self._lock is not None and self._lock.locked())

    def force_unload(self):
        """Полная выгрузка включая токенизатор (при смене модели)."""
        self.model     = None
        self.tokenizer = None
        self.prompt_cache = None
        self.prompt_cache_model_key = None
        self.last_generation_metrics = {}
        gc.collect()
        _clear_metal_cache()
        logger.info(f"[SWITCH] Полная выгрузка: {self.model_path}")

    def reload_tokenizer(self):
        """Перегружает токенизатор после смены model_path."""
        try:
            self.tokenizer = _load_auto_tokenizer(self.model_path)
            logger.info(f"[TOKENIZER] Перезагружен для {self.model_path}")
        except Exception as e:
            logger.warning(f"[TOKENIZER] Ошибка перезагрузки: {e}")

    def _load_model_if_needed(self):
        """Загружает веса если не загружены. Вызывается внутри to_thread."""
        if self.model is None:
            logger.info(f"[LOAD] Загрузка весов {self.model_path} в Metal...")
            model, tokenizer = _mlx_load(self.model_path)
            self.model = model
            if self.tokenizer is None:
                self.tokenizer = tokenizer
            logger.info(f"[LOAD] Готово: {self.model_path}")
        model_key = (self.model_path, id(self.model))
        if self.prompt_cache is None or self.prompt_cache_model_key != model_key:
            self.prompt_cache = _new_prompt_cache()
            self.prompt_cache_model_key = model_key
        self.last_used = time.time()

    def apply_chat_template(
        self,
        messages: list,
        enable_thinking: bool = True,
        tools: list[dict] | None = None,
        add_generation_prompt: bool = True,
    ) -> str:
        """
        Применяет chat template токенизатора.
        enable_thinking=False отключает <think> блоки у Qwen3 — используй для валидатора.
        """
        if self.tokenizer is None:
            # Fallback: Qwen3 ChatML формат
            parts = []
            if tools:
                parts.append(
                    "<|im_start|>system\n# Tools\n\n"
                    "You have access to the following functions:\n<tools>\n"
                    + "\n".join(json.dumps(tool, ensure_ascii=False) for tool in tools)
                    + "\n</tools>\n\n"
                    "If you call functions, reply only with one or more blocks in this format:\n"
                    "<tool_call>\n<function=function_name>\n"
                    "<parameter=parameter_name>\nvalue\n</parameter>\n"
                    "</function>\n</tool_call><|im_end|>"
                )
            for m in messages:
                parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>")
            if add_generation_prompt:
                parts.append("<|im_start|>assistant\n")
            return "\n".join(parts)

        kwargs = {
            "tokenize": False,
            "add_generation_prompt": add_generation_prompt,
        }
        if tools:
            kwargs["tools"] = tools
        if not enable_thinking:
            kwargs["enable_thinking"] = False
        try:
            return self.tokenizer.apply_chat_template(messages, **kwargs)
        except TypeError:
            # Токенизатор не поддерживает enable_thinking — игнорируем параметр
            kwargs.pop("enable_thinking", None)
            return self.tokenizer.apply_chat_template(messages, **kwargs)

    async def generate_text(
        self,
        prompt: str,
        max_tokens: int = 2048,
        *,
        cache_prefix_prompt: str = "",
    ) -> str:
        if self._lock is None:
            raise RuntimeError("MLXMemoryManager не запущен — вызови start() внутри lifespan.")

        async with self._lock:
            async with metal_semaphore:
                def _run():
                    self._load_model_if_needed()
                    cache_stats: dict = {}
                    self.last_generation_metrics = cache_stats
                    return _mlx_generate(
                        self.model,
                        self.tokenizer,
                        prompt=prompt,
                        max_tokens=max_tokens,
                        cache_prefix_prompt=cache_prefix_prompt,
                        prompt_cache_store=self.prompt_cache,
                        prompt_cache_key=self.prompt_cache_model_key,
                        cache_stats=cache_stats,
                    )
                try:
                    result = await asyncio.to_thread(_run)
                    self.last_used = time.time()
                finally:
                    # ``mlx_lm.generate`` creates transient KV/prefill buffers.
                    # Keeping the model warm is useful, keeping the allocator's
                    # high-water cache between independent turns is not: on a
                    # 24 GB Mac it pushes otherwise fitting 4B/9B models into
                    # swap. Referenced model weights remain resident.
                    _clear_metal_cache()

        # Обрезаем stop-токены если модель их включила в ответ
        for stop in STOP_TOKENS:
            if stop in result:
                result = result[:result.index(stop)]
        return result.strip()

    async def stream_text(
        self,
        prompt: str,
        max_tokens: int = 2048,
        *,
        cache_prefix_prompt: str = "",
    ):
        """Стримит реальные токены MLX и финальные метрики генерации.

        Синхронный ``mlx_lm.stream_generate`` выполняется в worker thread, а
        ответы передаются в event loop через очередь. В отличие от прежней
        имитации SSE, первый токен доходит до клиента сразу после prefill.
        """
        if self._lock is None:
            raise RuntimeError("MLXMemoryManager не запущен — вызови start() внутри lifespan.")

        async with self._lock:
            async with metal_semaphore:
                loop = asyncio.get_running_loop()
                queue: asyncio.Queue = asyncio.Queue()
                sentinel = object()
                cache_stats: dict = {}

                def _run():
                    try:
                        self._load_model_if_needed()
                        self.last_generation_metrics = cache_stats
                        for response in _mlx_stream_generate(
                            self.model,
                            self.tokenizer,
                            prompt=prompt,
                            max_tokens=max_tokens,
                            cache_prefix_prompt=cache_prefix_prompt,
                            prompt_cache_store=self.prompt_cache,
                            prompt_cache_key=self.prompt_cache_model_key,
                            cache_stats=cache_stats,
                        ):
                            loop.call_soon_threadsafe(queue.put_nowait, response)
                    except BaseException as exc:  # передать ошибку в async consumer
                        loop.call_soon_threadsafe(queue.put_nowait, exc)
                    finally:
                        loop.call_soon_threadsafe(queue.put_nowait, sentinel)

                task = asyncio.create_task(asyncio.to_thread(_run))
                try:
                    while True:
                        item = await queue.get()
                        if item is sentinel:
                            break
                        if isinstance(item, BaseException):
                            raise item
                        metrics = {
                            "prompt_tokens": int(
                                cache_stats.get("prompt_tokens")
                                or getattr(item, "prompt_tokens", 0)
                                or 0
                            ),
                            "cached_tokens": int(
                                cache_stats.get("cached_tokens") or 0
                            ),
                            "cache_hit": bool(cache_stats.get("cache_hit")),
                            "prompt_tps": float(getattr(item, "prompt_tps", 0.0) or 0.0),
                            "generation_tokens": int(getattr(item, "generation_tokens", 0) or 0),
                            "generation_tps": float(getattr(item, "generation_tps", 0.0) or 0.0),
                            "peak_memory_gb": float(getattr(item, "peak_memory", 0.0) or 0.0),
                            "finish_reason": getattr(item, "finish_reason", None),
                        }
                        yield str(getattr(item, "text", "") or ""), metrics
                    await task
                    self.last_used = time.time()
                finally:
                    if not task.done():
                        task.cancel()
                    _clear_metal_cache()
