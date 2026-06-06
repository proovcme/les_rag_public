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

from mlx_lm import load, generate
from transformers import AutoTokenizer

logger = logging.getLogger(__name__)

# Один запрос к Metal одновременно — защита от OOM при параллельных движках
metal_semaphore = asyncio.Semaphore(1)

STOP_TOKENS = ["<|im_end|>", "<|endoftext|>", "<|end|>"]


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
        """Вызывается внутри lifespan когда event loop уже запущен."""
        self._lock = asyncio.Lock()
        if os.getenv("MLX_PRELOAD_TOKENIZERS", "").lower() in {"1", "true", "yes", "on"}:
            try:
                logger.info(f"[TOKENIZER] Загрузка {self.model_path}...")
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
                logger.info(f"[TOKENIZER] Готов.")
            except Exception as e:
                logger.warning(f"[TOKENIZER] Не удалось загрузить: {e}")
        else:
            logger.info(f"[TOKENIZER] Lazy preload enabled for {self.model_path}")
        self._cleanup_task = asyncio.create_task(self._auto_unload_loop())

    async def _auto_unload_loop(self):
        while True:
            await asyncio.sleep(10)
            if self.model is not None:
                idle = time.time() - self.last_used
                if idle > self.ttl_seconds:
                    if self.is_busy():
                        logger.debug(f"[TTL] {self.model_path} busy, unload postponed")
                        continue
                    logger.info(f"[TTL] Выгрузка {self.model_path} (idle {idle:.0f}s)")
                    self._unload_model()

    def _unload_model(self):
        """Выгружает только веса, токенизатор остаётся."""
        self.model = None
        gc.collect()
        logger.info(f"[TTL] Память Metal освобождена: {self.model_path}")

    def is_busy(self) -> bool:
        return bool(self._lock is not None and self._lock.locked())

    def force_unload(self):
        """Полная выгрузка включая токенизатор (при смене модели)."""
        self.model     = None
        self.tokenizer = None
        gc.collect()
        logger.info(f"[SWITCH] Полная выгрузка: {self.model_path}")

    def reload_tokenizer(self):
        """Перегружает токенизатор после смены model_path."""
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            logger.info(f"[TOKENIZER] Перезагружен для {self.model_path}")
        except Exception as e:
            logger.warning(f"[TOKENIZER] Ошибка перезагрузки: {e}")

    def _load_model_if_needed(self):
        """Загружает веса если не загружены. Вызывается внутри to_thread."""
        if self.model is None:
            logger.info(f"[LOAD] Загрузка весов {self.model_path} в Metal...")
            model, tokenizer = load(self.model_path)
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
                    return generate(
                        self.model,
                        self.tokenizer,
                        prompt=prompt,
                        max_tokens=max_tokens,
                        verbose=False,
                    )
                result = await asyncio.to_thread(_run)
                self.last_used = time.time()

        # Обрезаем stop-токены если модель их включила в ответ
        for stop in STOP_TOKENS:
            if stop in result:
                result = result[:result.index(stop)]
        return result.strip()
