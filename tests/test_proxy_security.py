import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import proxy.security as security


def _request(ip: str, headers: dict | None = None):
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=ip))


def _init_auth_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE auth_keys (
            key_value TEXT PRIMARY KEY,
            holder_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            expires_at TEXT DEFAULT NULL,
            device_fingerprint TEXT DEFAULT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO auth_keys (key_value, holder_name, role, is_active, expires_at) VALUES (?, ?, ?, ?, ?)",
        [
            ("admin-key", "Admin", "admin", 1, None),
            ("user-key", "User", "user", 1, None),
            ("disabled-key", "Disabled", "user", 0, None),
            (
                "expired-key",
                "Expired",
                "user",
                1,
                (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def auth_db(tmp_path, monkeypatch):
    path = tmp_path / "les_meta.db"
    _init_auth_db(path)
    monkeypatch.setattr(security, "META_DB_PATH", path)
    monkeypatch.setattr(security, "TRUSTED_NETWORKS", ("127.0.0.0/8", "::1/128", "10.10.10.0/24"))
    monkeypatch.setattr(security, "TRUSTED_PROXY_NETWORKS", ("127.0.0.0/8", "::1/128"))
    monkeypatch.setattr(security, "TRUSTED_NETWORK_ROLE", "admin")
    return path


@pytest.mark.asyncio
async def test_configured_private_network_is_admin(auth_db):
    local = await security.get_request_user(_request("127.0.0.1"), x_api_key=None, authorization=None)
    private_client = await security.get_request_user(_request("10.10.10.98"), x_api_key=None, authorization=None)

    assert local.role == "admin"
    assert local.holder == "trusted-network"
    assert private_client.role == "admin"


@pytest.mark.asyncio
async def test_public_ip_without_key_is_unauthorized(auth_db):
    with pytest.raises(HTTPException) as exc:
        await security.get_request_user(_request("203.0.113.10"), x_api_key=None, authorization=None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_forwarded_headers_only_trusted_from_proxy_network(auth_db):
    spoofed = _request("203.0.113.10", {"x-forwarded-for": "10.10.10.98"})
    with pytest.raises(HTTPException) as exc:
        await security.get_request_user(spoofed, x_api_key=None, authorization=None)
    assert exc.value.status_code == 401

    proxied = _request("127.0.0.1", {"x-forwarded-for": "10.10.10.98"})
    user = await security.get_request_user(proxied, x_api_key=None, authorization=None)
    assert user.role == "admin"
    assert user.source == "10.10.10.98"


@pytest.mark.asyncio
async def test_trusted_proxy_header_only_trusted_from_proxy_network(auth_db):
    spoofed = _request("203.0.113.10", {"x-les-trusted-network": "1"})
    with pytest.raises(HTTPException) as exc:
        await security.get_request_user(spoofed, x_api_key=None, authorization=None)
    assert exc.value.status_code == 401

    proxied = _request("127.0.0.1", {"x-forwarded-for": "203.0.113.10", "x-les-trusted-network": "1"})
    user = await security.get_request_user(proxied, x_api_key=None, authorization=None)
    assert user.role == "admin"
    assert user.holder == "trusted-proxy"


@pytest.mark.asyncio
async def test_api_key_roles_and_admin_guard(auth_db):
    admin = await security.get_request_user(_request("203.0.113.10"), x_api_key="admin-key")
    user = await security.get_request_user(
        _request("203.0.113.10", {"authorization": "Bearer user-key"}),
        x_api_key=None,
        authorization="Bearer user-key",
    )

    assert admin.role == "admin"
    assert admin.holder == "Admin"
    assert user.role == "user"
    assert user.holder == "User"

    with pytest.raises(HTTPException) as exc:
        await security.require_admin(user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_internal_or_admin_guard_allows_admin_key_and_internal(auth_db):
    public_admin = await security.require_internal_or_admin(
        _request("203.0.113.10"),
        x_api_key="admin-key",
        authorization=None,
    )
    local_internal = await security.require_internal_or_admin(
        _request("127.0.0.1"),
        x_api_key=None,
        authorization=None,
    )

    assert public_admin.role == "admin"
    assert public_admin.source == "api_key"
    assert local_internal.role == "admin"
    assert local_internal.holder == "internal"

    with pytest.raises(HTTPException) as user_key:
        await security.require_internal_or_admin(
            _request("203.0.113.10"),
            x_api_key="user-key",
            authorization=None,
        )
    with pytest.raises(HTTPException) as no_key:
        await security.require_internal_or_admin(
            _request("203.0.113.10"),
            x_api_key=None,
            authorization=None,
        )

    assert user_key.value.status_code == 403
    assert no_key.value.status_code == 403


@pytest.mark.asyncio
async def test_disabled_and_expired_keys_are_unauthorized(auth_db):
    with pytest.raises(HTTPException) as disabled:
        await security.get_request_user(_request("203.0.113.10"), x_api_key="disabled-key")
    with pytest.raises(HTTPException) as expired:
        await security.get_request_user(_request("203.0.113.10"), x_api_key="expired-key")

    assert disabled.value.status_code == 401
    assert expired.value.status_code == 401
