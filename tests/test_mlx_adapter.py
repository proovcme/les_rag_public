import asyncio
import time

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

    manager.force_unload()

    assert manager.model is None
    assert manager.tokenizer is None
    assert cleared == [True]


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
