import pytest

from proxy.routers import diagnostics


@pytest.fixture()
def diagnostics_state():
    previous = diagnostics._state
    diagnostics.set_diagnostics_state(
        diagnostics.DiagnosticsRouterState(
            crag_stats={"verified": 7, "no_data": 2, "hallucination": 1},
            proxy_start=0.0,
        )
    )
    yield
    diagnostics._state = previous


@pytest.mark.asyncio
async def test_run_diagnostics_aggregates_check_statuses(monkeypatch, diagnostics_state):
    async def fake_check(name, coro):
        if name == "Т.О.С.К.А. статистика":
            status, value, expected, message = await coro
            diagnostics_results.append((status, value, expected, message))

    diagnostics_results = []
    original_time = diagnostics.time.time
    monkeypatch.setattr(diagnostics.time, "time", lambda: original_time())
    # Directly exercise the state-dependent CRAG branch by running the full route with
    # external checks forced into harmless failures through short-circuit monkeypatches.
    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip external")))
    monkeypatch.setattr(diagnostics.psutil, "virtual_memory", lambda: type("VM", (), {"percent": 10, "used": 1, "total": 2})())
    monkeypatch.setattr(diagnostics.psutil, "cpu_percent", lambda interval=0.0: 1.0)
    monkeypatch.setattr(diagnostics.psutil, "disk_usage", lambda path: type("DU", (), {"percent": 10, "free": 1024**3})())

    result = await diagnostics.run_diagnostics(_internal=object())

    crag = next(check for check in result["checks"] if check["name"] == "Т.О.С.К.А. статистика")
    assert crag["status"] == "ok"
    assert "V:7 N:2 H:1" in crag["value"]
    assert result["embedding"]["profile"]
    assert result["embedding"]["collection"]
    assert result["ok_count"] >= 1


@pytest.mark.asyncio
async def test_ollama_provider_diag_uses_tags_not_mlx_health(monkeypatch, diagnostics_state):
    class Response:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            text = str(url)
            if text.endswith("/api/tags"):
                return Response({"models": [{"name": "qwen3.5:9b"}, {"name": "bge-m3:latest"}]})
            if text.endswith("/api/health"):
                raise AssertionError("ollama provider must not call MLX /api/health")
            if text.endswith("/collections"):
                return Response({"result": {"collections": []}})
            return Response({}, status_code=404)

    monkeypatch.setenv("LES_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:9b")
    monkeypatch.setenv("MLX_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(diagnostics.httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        diagnostics.psutil,
        "virtual_memory",
        lambda: type("VM", (), {"percent": 10, "used": 1, "total": 2})(),
    )
    monkeypatch.setattr(diagnostics.psutil, "cpu_percent", lambda interval=0.0: 1.0)
    monkeypatch.setattr(
        diagnostics.psutil,
        "disk_usage",
        lambda path: type("DU", (), {"percent": 10, "free": 1024**3})(),
    )
    monkeypatch.setattr(
        diagnostics.socket,
        "create_connection",
        lambda *a, **k: (_ for _ in ()).throw(OSError("skip")),
    )

    result = await diagnostics.run_diagnostics(_internal=object())

    names = {check["name"]: check for check in result["checks"]}
    assert "Ollama" in names
    assert "MLX Backend" not in names
    assert names["Ollama"]["status"] == "ok"
    assert "2 моделей" in names["Ollama"]["value"]
    assert names["Ollama latency"]["status"] == "ok"
    assert "Ollama tags OK" in names["Ollama latency"]["message"]


@pytest.mark.asyncio
async def test_clean_runtime_without_verifiable_answers_is_warning(monkeypatch):
    previous = diagnostics._state
    diagnostics.set_diagnostics_state(
        diagnostics.DiagnosticsRouterState(
            crag_stats={"verified": 0, "no_data": 2, "hallucination": 0, "unvalidated": 0},
            proxy_start=0.0,
        )
    )
    monkeypatch.setattr(
        diagnostics.httpx,
        "AsyncClient",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip external")),
    )
    monkeypatch.setattr(
        diagnostics.psutil,
        "virtual_memory",
        lambda: type("VM", (), {"percent": 10, "used": 1, "total": 2})(),
    )
    monkeypatch.setattr(diagnostics.psutil, "cpu_percent", lambda interval=0.0: 1.0)
    monkeypatch.setattr(
        diagnostics.psutil,
        "disk_usage",
        lambda path: type("DU", (), {"percent": 10, "free": 1024**3})(),
    )
    try:
        result = await diagnostics.run_diagnostics(_internal=object())
    finally:
        diagnostics._state = previous

    crag = next(check for check in result["checks"] if check["name"] == "Т.О.С.К.А. статистика")
    assert crag["status"] == "warn"
    assert "нет проверяемых ответов" in crag["message"]


@pytest.mark.asyncio
async def test_sparse_validation_sample_is_warning_not_runtime_error(monkeypatch):
    previous = diagnostics._state
    diagnostics.set_diagnostics_state(
        diagnostics.DiagnosticsRouterState(
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0, "unvalidated": 1},
            proxy_start=0.0,
        )
    )
    monkeypatch.setattr(
        diagnostics.httpx,
        "AsyncClient",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip external")),
    )
    monkeypatch.setattr(
        diagnostics.psutil,
        "virtual_memory",
        lambda: type("VM", (), {"percent": 10, "used": 1, "total": 2})(),
    )
    monkeypatch.setattr(diagnostics.psutil, "cpu_percent", lambda interval=0.0: 1.0)
    monkeypatch.setattr(
        diagnostics.psutil,
        "disk_usage",
        lambda path: type("DU", (), {"percent": 10, "free": 1024**3})(),
    )
    try:
        result = await diagnostics.run_diagnostics(_internal=object())
    finally:
        diagnostics._state = previous

    crag = next(check for check in result["checks"] if check["name"] == "Т.О.С.К.А. статистика")
    assert crag["status"] == "warn"
    assert "мало проверяемых ответов" in crag["message"]
