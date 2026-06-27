"""W5.2 — офлайн-проверки push-канала /api/live.

Живой замер «≤2 фоновых HTTP/мин на вкладку» — [live]; здесь: сборка снимка на
сервере (устойчивость к сбою ветки) и клиентский применятель/парсер SSE.
"""
import httpx
import pytest

from proxy.routers import runtime as runtime_router
from sovushka import state as sov_state


# ── сервер: _live_snapshot ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_snapshot_aggregates_and_survives_branch_error(monkeypatch):
    async def ok_metrics():
        return {"system": {"cpu": 1}}

    async def ok_status():
        return {"proxy": "ok", "mode": {"mode": "rag"}}

    async def boom_indexing():
        raise RuntimeError("indexing down")

    async def ok_jobs(limit=120, active_only=False, _user=None):
        return {"count": 0, "jobs": []}

    class _Disp:
        def reindex_status_payload(self):
            return {"running": True, "completed": 3, "total": 10}

    monkeypatch.setattr(runtime_router, "get_metrics", ok_metrics)
    monkeypatch.setattr(runtime_router, "get_status", ok_status)
    monkeypatch.setattr(runtime_router, "get_indexing_mode", boom_indexing)
    monkeypatch.setattr("proxy.routers.jobs.get_jobs_summary", ok_jobs)
    monkeypatch.setattr(runtime_router, "get_runtime_state", lambda: object())
    monkeypatch.setattr(runtime_router, "dispatcher_for_state", lambda _s: _Disp())

    snap = await runtime_router._live_snapshot()
    assert snap["metrics"] == {"system": {"cpu": 1}}
    assert snap["status"]["mode"]["mode"] == "rag"
    # упавшая ветка не роняет снимок, а отдаёт {"error": ...}
    assert "error" in snap["indexing_mode"]
    assert snap["jobs_summary"]["count"] == 0
    assert snap["reindex"]["completed"] == 3


# ── клиент: _apply_live_snapshot ─────────────────────────────────────

def test_apply_live_snapshot_updates_state():
    sov_state.state["metrics"] = {}
    sov_state.state["reindex"] = {}
    sov_state._apply_live_snapshot({
        "metrics": {"system": {"cpu": 9}},
        "status": {"proxy": "ok", "mode": {"mode": "indexing"}},
        "indexing_mode": {"active": True},
        "reindex": {"running": True, "completed": 5, "total": 20},
        "jobs_summary": {"jobs": [{"id": "j1", "status": "RUNNING"}]},
    })
    assert sov_state.state["metrics"]["system"]["cpu"] == 9
    assert sov_state.state["mode"] == "indexing"
    assert sov_state.state["indexing_mode"]["active"] is True
    assert sov_state.state["reindex"]["total"] == 20
    assert "j1" in sov_state.state["jobs"]


def test_apply_live_snapshot_skips_error_branches():
    sov_state.state["metrics"] = {"keep": 1}
    sov_state._apply_live_snapshot({"metrics": {"error": "down"}})
    assert sov_state.state["metrics"] == {"keep": 1}  # ошибочная ветка не затирает


# ── клиент: live_subscribe (SSE GET) ─────────────────────────────────

class _FakeStream:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status
        self.request = httpx.Request("GET", "http://x/api/live")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln


class _FakeClient:
    def __init__(self, lines, status=200):
        self._lines, self._status = lines, status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, **kw):
        return _FakeStream(self._lines, self._status)


@pytest.mark.asyncio
async def test_live_subscribe_applies_snapshots(monkeypatch):
    lines = [
        "event: snapshot",
        'data: {"metrics": {"system": {"cpu": 42}}, "reindex": {"running": false, "completed": 0, "total": 0}}',
        "",
    ]
    monkeypatch.setattr(sov_state.httpx, "AsyncClient", lambda *a, **k: _FakeClient(lines))
    sov_state.state["metrics"] = {}
    opened = await sov_state.live_subscribe()
    assert opened is True
    assert sov_state.state["metrics"]["system"]["cpu"] == 42


@pytest.mark.asyncio
async def test_live_subscribe_non_200_returns_false(monkeypatch):
    monkeypatch.setattr(sov_state.httpx, "AsyncClient", lambda *a, **k: _FakeClient([], status=503))
    opened = await sov_state.live_subscribe()
    assert opened is False
