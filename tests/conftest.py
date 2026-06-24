"""Тестовая гигиена: изоляция глобального chat-state между тестами.

Live-фикстуры unified-harness (v0.7–v0.11) ставят глобальный `chat_router._state` через
set_chat_state и не сбрасывали его → в общей сессии состояние «протекало» в chat-тесты, идущие
следом (flaky). autouse-фикстура снимает снапшот до теста и восстанавливает после.
"""

import pytest


@pytest.fixture(autouse=True)
def _restore_chat_router_state():
    try:
        import proxy.routers.chat as _chat
    except Exception:  # noqa: BLE001
        yield
        return
    _prev = getattr(_chat, "_state", None)
    try:
        yield
    finally:
        _chat._state = _prev
