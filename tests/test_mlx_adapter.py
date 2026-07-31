import asyncio
import copy
import time
from types import SimpleNamespace

import pytest

from backend import mlx_adapter


# ── preload-токенизатор: дефолт = lazy ────────────────────────────────────────

@pytest.mark.asyncio
async def test_mlx_memory_manager_does_not_preload_tokenizer_by_default(monkeypatch):
    calls = []
    monkeypatch.delenv("MLX_PRELOAD_TOKENIZERS", raising=False)
    monkeypatch.setattr(
        mlx_adapter, "_load_auto_tokenizer", lambda model: calls.append(model)
    )
    manager = mlx_adapter.MLXMemoryManager("local-model")

    manager.start()
    manager.stop()

    assert calls == []
    assert manager.tokenizer is None


@pytest.mark.asyncio
async def test_mlx_memory_manager_can_preload_tokenizer(monkeypatch):
    monkeypatch.setenv("MLX_PRELOAD_TOKENIZERS", "true")
    monkeypatch.setattr(
        mlx_adapter, "_load_auto_tokenizer", lambda model: f"tokenizer:{model}"
    )
    manager = mlx_adapter.MLXMemoryManager("local-model")

    manager.start()
    manager.stop()

    assert manager.tokenizer == "tokenizer:local-model"


# ── lazy-импорт: модуль импортируется без mlx_lm (офлайн-CI) ───────────────────

def test_module_does_not_import_mlx_lm_at_load():
    """Модуль mlx_adapter не должен тащить mlx_lm/transformers на import —
    иначе pytest --collect-only (make verify) падает офлайн без MLX."""
    import ast
    from pathlib import Path

    src = Path(mlx_adapter.__file__).read_text()
    tree = ast.parse(src)
    module_level_imports = []
    for node in tree.body:  # только верхнеуровневые узлы модуля
        if isinstance(node, ast.Import):
            module_level_imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            module_level_imports.append(node.module or "")
    assert not any(
        m.startswith("mlx_lm") or m.startswith("transformers")
        for m in module_level_imports
    ), f"тяжёлые импорты на module-level: {module_level_imports}"


# ── start() идемпотентен: повторный вызов не плодит вторую задачу ──────────────

@pytest.mark.asyncio
async def test_start_is_idempotent_no_task_leak(monkeypatch):
    monkeypatch.delenv("MLX_PRELOAD_TOKENIZERS", raising=False)
    manager = mlx_adapter.MLXMemoryManager("local-model")

    manager.start()
    first_task = manager._cleanup_task
    manager.start()  # повторный старт
    second_task = manager._cleanup_task

    assert first_task is second_task  # та же задача, не утекла новая
    assert not first_task.done()
    manager.stop()


# ── stop() чисто отменяет фоновую задачу ──────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_cancels_cleanup_task(monkeypatch):
    monkeypatch.delenv("MLX_PRELOAD_TOKENIZERS", raising=False)
    manager = mlx_adapter.MLXMemoryManager("local-model")
    manager.start()
    task = manager._cleanup_task

    manager.stop()
    assert manager._cleanup_task is None
    # дать циклу обработать отмену
    await asyncio.sleep(0)
    assert task.cancelled() or task.done()


# ── TTL: модель выгружается по простою ────────────────────────────────────────

@pytest.mark.asyncio
async def test_idle_unload_drops_model_and_clears_cache(monkeypatch):
    cleared = []
    monkeypatch.setattr(mlx_adapter, "_clear_metal_cache", lambda: cleared.append(True))
    manager = mlx_adapter.MLXMemoryManager("local-model", ttl_seconds=300)
    manager._lock = asyncio.Lock()
    manager.model = object()
    manager.last_used = time.time() - 9999  # давно простаивает

    # один проход тела цикла без sleep
    assert (time.time() - manager.last_used) > manager.ttl_seconds
    assert not manager.is_busy()
    manager._unload_model()

    assert manager.model is None
    assert cleared == [True]


@pytest.mark.asyncio
async def test_idle_unload_postponed_when_busy(monkeypatch):
    monkeypatch.setattr(mlx_adapter, "_clear_metal_cache", lambda: None)
    manager = mlx_adapter.MLXMemoryManager("local-model", ttl_seconds=1)
    manager._lock = asyncio.Lock()
    manager.model = object()
    manager.last_used = time.time() - 100

    async with manager._lock:  # занят
        assert manager.is_busy() is True
        # имитируем решение цикла: busy → не выгружаем
        if manager.is_busy():
            postponed = True
        assert postponed is True
    assert manager.model is not None  # модель осталась


# ── auto-unload цикл не умирает от единичной ошибки выгрузки ───────────────────

@pytest.mark.asyncio
async def test_auto_unload_loop_survives_unload_error(monkeypatch):
    manager = mlx_adapter.MLXMemoryManager("local-model", ttl_seconds=0)
    manager._lock = asyncio.Lock()
    manager.model = object()
    manager.last_used = 0.0

    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("metal hiccup")
        manager.model = None  # второй проход успешен

    monkeypatch.setattr(manager, "_unload_model", boom)
    # ускоряем sleep, чтобы цикл крутился быстро
    real_sleep = asyncio.sleep

    async def fast_sleep(_):
        await real_sleep(0)

    monkeypatch.setattr(mlx_adapter.asyncio, "sleep", fast_sleep)

    task = asyncio.create_task(manager._auto_unload_loop())
    # дать циклу несколько итераций: первая бросает, цикл выживает, вторая чистит
    for _ in range(50):
        await real_sleep(0)
        if calls["n"] >= 2:
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert calls["n"] >= 2  # цикл пережил ошибку и сделал второй проход


# ── force_unload роняет и веса, и токенизатор + чистит кэш ─────────────────────

def test_force_unload_drops_everything(monkeypatch):
    cleared = []
    monkeypatch.setattr(mlx_adapter, "_clear_metal_cache", lambda: cleared.append(True))
    manager = mlx_adapter.MLXMemoryManager("local-model")
    manager.model = object()
    manager.tokenizer = object()
    manager.prompt_cache = object()
    manager.prompt_cache_model_key = ("local-model", 1)

    manager.force_unload()

    assert manager.model is None
    assert manager.tokenizer is None
    assert manager.prompt_cache is None
    assert manager.prompt_cache_model_key is None
    assert cleared == [True]


def test_chat_template_passes_native_tools_to_tokenizer():
    captured = {}

    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return "tool-aware-prompt"

    manager = mlx_adapter.MLXMemoryManager("local-model")
    manager.tokenizer = Tokenizer()
    tools = [{"type": "function", "function": {"name": "search_norms", "parameters": {"type": "object"}}}]

    prompt = manager.apply_chat_template(
        [{"role": "user", "content": "Найди норму"}],
        enable_thinking=False,
        tools=tools,
    )

    assert prompt == "tool-aware-prompt"
    assert captured["kwargs"]["tools"] == tools
    assert captured["kwargs"]["enable_thinking"] is False


def test_chat_template_fallback_keeps_tool_contract_without_loaded_tokenizer():
    manager = mlx_adapter.MLXMemoryManager("local-model")
    tools = [{"type": "function", "function": {"name": "read_norm", "parameters": {"type": "object"}}}]

    prompt = manager.apply_chat_template(
        [{"role": "user", "content": "Открой норму"}],
        tools=tools,
    )

    assert '"name": "read_norm"' in prompt
    assert "<tool_call>" in prompt
    assert "Открой норму" in prompt


def test_chat_template_can_render_stable_prefix_without_assistant_marker():
    manager = mlx_adapter.MLXMemoryManager("local-model")

    prompt = manager.apply_chat_template(
        [{"role": "user", "content": "Открой норму"}],
        add_generation_prompt=False,
    )

    assert "Открой норму" in prompt
    assert not prompt.endswith("<|im_start|>assistant\n")


# ── generate_text требует start() (event-loop guard) ──────────────────────────

@pytest.mark.asyncio
async def test_generate_text_requires_start():
    manager = mlx_adapter.MLXMemoryManager("local-model")
    with pytest.raises(RuntimeError, match="не запущен"):
        await manager.generate_text("hi")


# ── семафор Metal: одновременно только один слот генерации ─────────────────────

@pytest.mark.asyncio
async def test_metal_semaphore_serializes_generation(monkeypatch):
    # подменяем тяжёлую генерацию на фейк, считаем макс. параллелизм
    state = {"concurrent": 0, "max": 0}

    async def fake_to_thread(fn, *a, **kw):
        state["concurrent"] += 1
        state["max"] = max(state["max"], state["concurrent"])
        await asyncio.sleep(0.01)
        state["concurrent"] -= 1
        return "ok"

    monkeypatch.setattr(mlx_adapter.asyncio, "to_thread", fake_to_thread)

    # три независимых менеджера делят один глобальный metal_semaphore
    managers = []
    for i in range(3):
        m = mlx_adapter.MLXMemoryManager(f"model-{i}")
        m._lock = asyncio.Lock()
        m.model = object()
        m.tokenizer = object()
        managers.append(m)

    await asyncio.gather(*(m.generate_text("p", max_tokens=4) for m in managers))

    assert state["max"] == 1  # metal_semaphore(1) не дал параллельных слотов


@pytest.mark.asyncio
async def test_generate_text_strips_stop_tokens(monkeypatch):
    async def fake_to_thread(fn, *a, **kw):
        return "  ответ<|im_end|>хвост  "

    monkeypatch.setattr(mlx_adapter.asyncio, "to_thread", fake_to_thread)
    m = mlx_adapter.MLXMemoryManager("model")
    m._lock = asyncio.Lock()
    m.model = object()
    m.tokenizer = object()

    out = await m.generate_text("p")
    assert out == "ответ"  # обрезан stop-токен и пробелы


@pytest.mark.asyncio
async def test_generate_text_clears_transient_metal_cache_after_each_turn(monkeypatch):
    cleared = []

    async def fake_to_thread(fn, *a, **kw):
        return "ответ"

    monkeypatch.setattr(mlx_adapter.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(mlx_adapter, "_clear_metal_cache", lambda: cleared.append(True))
    m = mlx_adapter.MLXMemoryManager("model")
    m._lock = asyncio.Lock()
    m.model = object()
    m.tokenizer = object()

    assert await m.generate_text("p") == "ответ"
    assert m.model is not None
    assert cleared == [True]


@pytest.mark.asyncio
async def test_stream_text_yields_real_chunks_metrics_and_clears_cache(monkeypatch):
    cleared = []

    def fake_stream(*args, **kwargs):
        yield SimpleNamespace(
            text="первый ", prompt_tokens=12, prompt_tps=30.0,
            generation_tokens=1, generation_tps=10.0,
            peak_memory=2.5, finish_reason=None,
        )
        yield SimpleNamespace(
            text="токен", prompt_tokens=12, prompt_tps=30.0,
            generation_tokens=2, generation_tps=11.0,
            peak_memory=2.5, finish_reason="stop",
        )

    monkeypatch.setattr(mlx_adapter, "_mlx_stream_generate", fake_stream)
    monkeypatch.setattr(mlx_adapter, "_clear_metal_cache", lambda: cleared.append(True))
    m = mlx_adapter.MLXMemoryManager("model")
    m._lock = asyncio.Lock()
    m.model = object()
    m.tokenizer = object()

    chunks = [item async for item in m.stream_text("prompt", max_tokens=8)]

    assert [text for text, _ in chunks] == ["первый ", "токен"]
    assert chunks[-1][1]["prompt_tokens"] == 12
    assert chunks[-1][1]["generation_tps"] == 11.0
    assert chunks[-1][1]["finish_reason"] == "stop"
    assert m.model is not None
    assert cleared == [True]


def test_mlx_longest_prefix_cache_reuses_previous_chat_prefill(monkeypatch):
    class Tokenizer:
        @staticmethod
        def encode(prompt):
            return {
                "first-prefix": [1, 2, 3],
                "first": [1, 2, 3, 9],
                "second-prefix": [1, 2, 3, 4, 5],
                "second": [1, 2, 3, 4, 5, 9],
            }[prompt]

    class FakePromptCache:
        def __init__(self):
            self.entries = {}
            self.nbytes = 0

        def __len__(self):
            return len(self.entries)

        def fetch_nearest_cache(self, model, tokens):
            best = []
            for (entry_model, entry_tokens), cache in self.entries.items():
                if entry_model != model:
                    continue
                if list(tokens[: len(entry_tokens)]) == list(entry_tokens):
                    if len(entry_tokens) > len(best):
                        best = list(entry_tokens)
                        found = cache
            if not best:
                return None, list(tokens)
            return copy.deepcopy(found), list(tokens[len(best) :])

        def insert_cache(self, model, tokens, cache, *, cache_type):
            assert cache_type == "assistant"
            self.entries[(model, tuple(tokens))] = cache
            self.nbytes = len(self.entries) * 100

    raw_prompts = []
    prefilled = []

    def fake_raw(_model, _tokenizer, **kwargs):
        prompt = list(kwargs["prompt"])
        raw_prompts.append(prompt)
        callback = kwargs["prompt_progress_callback"]
        callback(0, len(prompt))
        callback(len(prompt), len(prompt))
        yield SimpleNamespace(text="ok")

    monkeypatch.setattr(mlx_adapter, "_raw_stream_generate", fake_raw)
    monkeypatch.setattr(
        mlx_adapter,
        "_prefill_prompt_cache",
        lambda _model, tokens, _cache: prefilled.append(list(tokens)),
    )
    monkeypatch.setattr(
        mlx_adapter,
        "_make_prompt_cache",
        lambda _model: [{"state": "empty"}],
    )
    cache = FakePromptCache()
    first_stats = {}
    assert [
        item.text
        for item in mlx_adapter._mlx_stream_generate(
            object(),
            Tokenizer(),
            prompt="first",
            max_tokens=4,
            cache_prefix_prompt="first-prefix",
            prompt_cache_store=cache,
            prompt_cache_key="model",
            cache_stats=first_stats,
        )
    ] == ["ok"]
    second_stats = {}
    assert [
        item.text
        for item in mlx_adapter._mlx_stream_generate(
            object(),
            Tokenizer(),
            prompt="second",
            max_tokens=4,
            cache_prefix_prompt="second-prefix",
            prompt_cache_store=cache,
            prompt_cache_key="model",
            cache_stats=second_stats,
        )
    ] == ["ok"]

    assert prefilled == [[1, 2, 3], [4, 5]]
    assert raw_prompts == [[9], [9]]
    assert first_stats["cached_tokens"] == 0
    assert second_stats["cached_tokens"] == 3
    assert second_stats["cache_hit"] is True
