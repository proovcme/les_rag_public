"""#6: parse-admission не должен блокировать индексацию без MLX-хоста (Windows-lite).

MLX-memory-guard (proof перед парсом) ходит на {MLX_URL}/api/health за RAM/swap. На Windows
MLX_URL указывает на ollama, который 404-ит /api/health → раньше parse_memory_state кидал 503
и `upload` навечно оставался queued. Теперь при недостижимом/не-MLX хосте guard пропускается
(нечего защищать от OOM локального MLX), индексация идёт. На Mac (MLX жив) guard остаётся.
"""

import pytest

from proxy.routers import datasets


@pytest.mark.asyncio
async def test_parse_memory_state_permissive_when_no_mlx(monkeypatch):
    class _BadClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise RuntimeError("404 Not Found (ollama, не MLX)")

    monkeypatch.setattr(datasets.httpx, "AsyncClient", lambda *a, **k: _BadClient())
    state = await datasets.parse_memory_state()
    # не кидает 503, а отдаёт пермиссивное состояние → admission пройдёт
    assert state["mlx_available"] is False
    assert state["ram_free_gb"] >= 999.0
    assert state["swap_pct"] == 0.0
    assert state["state"] == "ok"


@pytest.mark.asyncio
async def test_parse_memory_state_reads_real_memory_when_mlx_up(monkeypatch):
    class _OkClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            class _R:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"memory": {"ram_free_gb": 12.5, "swap_pct": 3.0}}

            return _R()

    monkeypatch.setattr(datasets.httpx, "AsyncClient", lambda *a, **k: _OkClient())
    state = await datasets.parse_memory_state()
    # MLX жив → читаем реальную память (guard активен, как на Mac)
    assert state["ram_free_gb"] == 12.5 and state["swap_pct"] == 3.0
    assert "mlx_available" not in state or state.get("mlx_available") is not False
