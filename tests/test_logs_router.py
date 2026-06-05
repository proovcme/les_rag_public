from collections import deque

import pytest

from proxy.routers import logs


@pytest.mark.asyncio
async def test_recent_logs_returns_tail(monkeypatch):
    history = deque((f"line {i}" for i in range(10)), maxlen=20)
    logs.set_logs_state(logs.LogsRouterState(log_history=history))

    result = await logs.recent_logs(limit=3)

    assert result == {
        "count": 3,
        "limit": 3,
        "lines": ["line 7", "line 8", "line 9"],
    }


@pytest.mark.asyncio
async def test_recent_logs_clamps_limit(monkeypatch):
    history = deque(("line",), maxlen=20)
    logs.set_logs_state(logs.LogsRouterState(log_history=history))

    result = await logs.recent_logs(limit=0)

    assert result["limit"] == 1
    assert result["lines"] == ["line"]
