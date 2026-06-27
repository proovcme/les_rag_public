"""
MLXMemoryManager — управление памятью Metal для LLM.

Токенизатор и веса модели грузятся лениво при первом запросе, выгружаются по TTL.
Для старого eager-поведения можно задать MLX_PRELOAD_TOKENIZERS=true.
Глобальный metal_semaphore — один движок на Metal в любой момент.
"""
import asyncio
import gc
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


def _mlx_generate(model, tokenizer, *, prompt: str, max_tokens: int):
    """Ленивый импорт mlx_lm.generate."""
    from mlx_lm import generate

    return generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=max_tokens,
        verbose=False,
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
        gc.collect()
        _clear_metal_cache()
        logger.info(f"[TTL] Память Metal освобождена: {self.model_path}")

    def is_busy(self) -> bool:
        return bool(self._lock is not None and self._lock.locked())

    def force_unload(self):
        """Полная выгрузка включая токенизатор (при смене модели)."""
        self.model     = None
        self.tokenizer = None
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
        self.last_used = time.time()

    def apply_chat_template(self, messages: list, enable_thinking: bool = True) -> str:
        """
        Применяет chat template токенизатора.
        enable_thinking=False отключает <think> блоки у Qwen3 — используй для валидатора.
        """
        if self.tokenizer is None:
            # Fallback: Qwen3 ChatML формат
            parts = []
            for m in messages:
                parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>")
            parts.append("<|im_start|>assistant\n")
            return "\n".join(parts)

        kwargs = {"tokenize": False, "add_generation_prompt": True}
        if not enable_thinking:
            kwargs["enable_thinking"] = False
        try:
            return self.tokenizer.apply_chat_template(messages, **kwargs)
        except TypeError:
            # Токенизатор не поддерживает enable_thinking — игнорируем параметр
            kwargs.pop("enable_thinking", None)
            return self.tokenizer.apply_chat_template(messages, **kwargs)

    async def generate_text(self, prompt: str, max_tokens: int = 2048) -> str:
        if self._lock is None:
            raise RuntimeError("MLXMemoryManager не запущен — вызови start() внутри lifespan.")

        async with self._lock:
            async with metal_semaphore:
                def _run():
                    self._load_model_if_needed()
                    return _mlx_generate(
                        self.model,
                        self.tokenizer,
                        prompt=prompt,
                        max_tokens=max_tokens,
                    )
                result = await asyncio.to_thread(_run)
                self.last_used = time.time()

        # Обрезаем stop-токены если модель их включила в ответ
        for stop in STOP_TOKENS:
            if stop in result:
                result = result[:result.index(stop)]
        return result.strip()
