"""Log streaming routes."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api", tags=["logs"])


@dataclass
class LogsRouterState:
    log_history: deque


_state: LogsRouterState | None = None


def set_logs_state(state: LogsRouterState) -> None:
    global _state
    _state = state


def get_logs_state() -> LogsRouterState:
    if _state is None:
        raise RuntimeError("logs router state is not configured")
    return _state


@router.get("/logs/recent")
async def recent_logs(limit: int = 120):
    log_history = get_logs_state().log_history
    limit = max(1, min(int(limit), 500))
    lines = list(log_history)[-limit:]
    return {
        "count": len(lines),
        "limit": limit,
        "lines": lines,
    }


@router.get("/logs/stream")
async def log_stream():
    log_history = get_logs_state().log_history

    async def gen():
        for line in log_history:
            yield {"data": line + "\n"}
        idx = len(log_history)
        while True:
            await asyncio.sleep(0.5)
            if len(log_history) != idx:
                for line in list(log_history)[idx:]:
                    yield {"data": line + "\n"}
                idx = len(log_history)

    return EventSourceResponse(gen())
