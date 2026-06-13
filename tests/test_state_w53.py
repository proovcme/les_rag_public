"""W5.3 — индикатор «proxy недоступен», честные сообщения, TTL-кэш api_get."""

from __future__ import annotations

import httpx
import pytest

from sovushka import state as st


def setup_function(_):
    st.state["proxy_online"] = True
    st.state["proxy_offline_reason"] = ""
    st.state["last_api_error"] = None
    st._GET_CACHE.clear()


def test_timeout_marks_proxy_offline_with_honest_message():
    st._api_error("GET", "/api/metrics", httpx.ConnectTimeout("timed out"))
    assert st.proxy_online() is False
    assert st.state["proxy_offline_reason"] == "timeout"
    assert "время ожидания" in st.last_api_error_text()


def test_connect_error_marks_offline():
    st._api_error("GET", "/api/status", httpx.ConnectError("refused"))
    assert st.proxy_online() is False
    assert st.state["proxy_offline_reason"] == "offline"
    assert "недоступен" in st.last_api_error_text()


def test_success_clears_offline():
    st._api_error("GET", "/api/status", httpx.ConnectError("refused"))
    assert st.proxy_online() is False
    st._api_success()
    assert st.proxy_online() is True
    assert st.state["last_api_error"] is None


def test_http_status_error_does_not_flag_offline():
    # прикладная ошибка (404/500) — proxy на связи, просто ответил ошибкой
    resp = httpx.Response(404, request=httpx.Request("GET", "http://x/api/y"))
    st._api_error("GET", "/api/y", httpx.HTTPStatusError("nf", request=resp.request, response=resp))
    assert st.proxy_online() is True


@pytest.mark.asyncio
async def test_ttl_cache_returns_cached_within_window(monkeypatch):
    calls = {"n": 0}

    async def fake_get(path, base=None):
        calls["n"] += 1
        return {"v": calls["n"]}

    monkeypatch.setattr(st, "api_get", fake_get)
    first = await st.api_get_cached("/api/metrics", ttl=100.0)
    second = await st.api_get_cached("/api/metrics", ttl=100.0)
    assert first == second == {"v": 1}
    assert calls["n"] == 1  # второй раз — из кэша


@pytest.mark.asyncio
async def test_ttl_cache_does_not_store_none(monkeypatch):
    async def fake_get(path, base=None):
        return None

    monkeypatch.setattr(st, "api_get", fake_get)
    assert await st.api_get_cached("/api/x", ttl=100.0) is None
    assert "/api/x" not in st._GET_CACHE
