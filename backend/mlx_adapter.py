import asyncio
import time
import logging
import gc
import inspect
import mlx.core as mx
from mlx_lm import load, generate

logger = logging.getLogger(__name__)

class MLXMemoryManager:
    def __init__(self, model_path: str, ttl_seconds: int = 180):
        self.model_path = model_path
        self.ttl_seconds = ttl_seconds
        self.model = None
        self.tokenizer = None
        self.last_used = 0
        self.lock = asyncio.Lock()
        self._watchdog_task = None
        logger.info(f"[MLX] Менеджер инициализирован: {self.model_path}")

    def start(self):
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(self._watchdog())
            logger.info(f"[MLX] Watchdog стартовал для {self.model_path}")

    async def _watchdog(self):
        while True:
            await asyncio.sleep(10)
            if self.model is None: continue
            if time.time() - self.last_used > self.ttl_seconds:
                async with self.lock:
                    if self.model is not None and time.time() - self.last_used > self.ttl_seconds:
                        self._unload_model()

    def _unload_model(self):
        logger.info(f"[MLX] Выгрузка модели {self.model_path} по таймеру...")
        self.model = None; self.tokenizer = None; gc.collect(); mx.metal.clear_cache()
        logger.info("[MLX] Память Metal очищена.")

    def force_unload(self):
        if self.model is not None: self._unload_model()

    async def generate_text(self, prompt: str, max_tokens: int = 1024) -> str:
        async with self.lock:
            if self.model is None:
                logger.info(f"[MLX] Загрузка весов {self.model_path}...")
                self.model, self.tokenizer = await asyncio.to_thread(load, self.model_path)
                logger.info("[MLX] Модель готова.")
            
            self.last_used = time.time()
            
            def _do_generate():
                # Проверяем сигнатуру функции generate
                sig = inspect.signature(generate)
                kwargs = {"prompt": prompt, "max_tokens": max_tokens}
                
                # Пытаемся добавить параметры контроля зацикливания
                if "temp" in sig.parameters:
                    kwargs["temp"] = 0.6 # Немного случайности
                if "repetition_penalty" in sig.parameters:
                    kwargs["repetition_penalty"] = 1.2 # Штраф за повторы (лечит "Надю")
                    
                try:
                    return generate(self.model, self.tokenizer, **kwargs)
                except TypeError as e:
                    logger.error(f"[MLX] Параметры не приняты: {e}. Fallback без штрафов.")
                    return generate(self.model, self.tokenizer, prompt=prompt, max_tokens=max_tokens)
            
            response = await asyncio.to_thread(_do_generate)
            self.last_used = time.time()
            return response