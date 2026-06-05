from types import SimpleNamespace

import pytest

from sovushka import lite_chat
from sovushka.lite_chat import bridge_proxy_request, bridge_request_allowed, lite_chat_html


def test_lite_chat_html_uses_static_shell_and_local_bridge():
    html = lite_chat_html()

    assert "Л.Е.С. LITE" in html
    assert "без NiceGUI client state" in html
    assert "/lite-api" in html
    assert 'path.replace(/^\\/api(?=\\/)/, "")' in html
    assert "/api/chat" in html
    assert "/api/chat/history/" in html
    assert "history_id: data.history_id || null" in html
    assert "Плохой ответ" in html
    assert "bad_answer" in html
    assert "Источник не из того датасета" in html
    assert "/api/mail/threads" in html
    assert "Е.Ж.И.К. Почта" in html
    assert "/classic" in html
    assert "Индексирование активно:" in html
    assert 'const isLocalUi = location.port === "8051";' in html
    assert "bot.innerHTML" not in html


def test_bridge_allows_auth_verify_without_existing_key():
    assert bridge_request_allowed("auth/verify", has_key=False, is_loopback=False)
    assert bridge_request_allowed("auth/trust", has_key=False, is_loopback=False)


def test_bridge_requires_key_for_remote_chat_requests():
    assert not bridge_request_allowed("chat", has_key=False, is_loopback=False)
    assert bridge_request_allowed("chat", has_key=True, is_loopback=False)


def test_bridge_allows_loopback_without_key_for_local_trusted_runtime():
    assert bridge_request_allowed("indexing-mode", has_key=False, is_loopback=True)


def test_loopback_uses_resolved_forwarded_client(monkeypatch):
    monkeypatch.setattr(lite_chat, "client_ip_from_request", lambda request: "203.0.113.10")
    request = SimpleNamespace(headers={"x-forwarded-for": "203.0.113.10"}, client=SimpleNamespace(host="127.0.0.1"))

    assert not lite_chat._client_is_loopback(request)


def test_bridge_allows_configured_trusted_network_without_key():
    assert bridge_request_allowed(
        "settings",
        has_key=False,
        is_loopback=False,
        is_trusted_network=True,
    )


def test_bridge_forwards_trusted_network_assertion(monkeypatch):
    monkeypatch.setattr(lite_chat, "TRUSTED_NETWORK_ROLE", "admin")
    monkeypatch.setattr(lite_chat, "TRUSTED_PROXY_HEADER", "x-les-trusted-network")
    monkeypatch.setattr(lite_chat, "trusted_role_for_request", lambda request: "admin")
    monkeypatch.setattr(lite_chat, "client_ip_from_request", lambda request: "10.10.10.98")

    request = SimpleNamespace(headers={"x-api-key": "stale"}, client=SimpleNamespace(host="10.10.10.98"))
    headers = lite_chat._forward_headers(request)

    assert headers["X-API-Key"] == "stale"
    assert headers["x-les-trusted-network"] == "admin"
    assert headers["X-Forwarded-For"] == "10.10.10.98"


@pytest.mark.asyncio
async def test_bridge_auth_trust_uses_frontdoor_diagnostics(monkeypatch):
    monkeypatch.setattr(lite_chat, "trust_diagnostics", lambda request: {"trusted": False, "client_ip": "203.0.113.10"})
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))

    response = await bridge_proxy_request("auth/trust", request)

    assert response.status_code == 200
    assert b'"trusted":false' in response.body.replace(b" ", b"")
    assert b"203.0.113.10" in response.body
