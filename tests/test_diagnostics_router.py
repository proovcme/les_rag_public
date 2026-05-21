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
    assert result["ok_count"] >= 1
