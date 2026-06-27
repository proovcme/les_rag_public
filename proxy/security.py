"""Server-side auth and role guards for LES Proxy v3."""

from __future__ import annotations

import ipaddress
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request

from proxy.config import (
    ADMIN_ROLE,
    META_DB_PATH,
    TRUSTED_NETWORK_ROLE,
    TRUSTED_NETWORKS,
    TRUSTED_PROXY_HEADER,
    TRUSTED_PROXY_NETWORKS,
    USER_ROLE,
)

# Единое ядро trust-логики (общее с sovushka/trust.py) — алгоритм один, конфиг свой.
from backend.trust_core import (
    ip_in_networks as _core_ip_in_networks,
    network_role as _core_network_role,
    proxy_asserts_network as _core_proxy_asserts,
    resolve_client_ip as _core_resolve_client_ip,
)


@dataclass(frozen=True)
class RequestUser:
    role: str
    holder: str = ""
    key_value: str = ""
    source: str = "anonymous"

    @property
    def is_admin(self) -> bool:
        return self.role == ADMIN_ROLE


def _client_ip(request: Request) -> str:
    peer_ip = request.client.host if request.client else ""
    return _core_resolve_client_ip(
        peer_ip,
        request.headers.get("x-forwarded-for"),
        request.headers.get("x-real-ip"),
        TRUSTED_PROXY_NETWORKS,
    )


def _ip_in_networks(ip_value: str, networks: tuple[str, ...]) -> bool:
    return _core_ip_in_networks(ip_value, networks)


def _trusted_network_role(ip_value: str) -> Optional[str]:
    return _core_network_role(ip_value, TRUSTED_NETWORKS, TRUSTED_NETWORK_ROLE)


def _trusted_proxy_asserts_network(request: Request) -> bool:
    peer_ip = request.client.host if request.client else ""
    return _core_proxy_asserts(
        peer_ip,
        request.headers.get(TRUSTED_PROXY_HEADER, ""),
        TRUSTED_PROXY_NETWORKS,
        TRUSTED_NETWORK_ROLE,
    )


def _trusted_request_user(request: Request, ip_value: str) -> Optional[RequestUser]:
    if _trusted_proxy_asserts_network(request):
        return RequestUser(role=TRUSTED_NETWORK_ROLE, holder="trusted-proxy", source=ip_value)

    trusted_role = _trusted_network_role(ip_value)
    if trusted_role:
        return RequestUser(role=trusted_role, holder="trusted-network", source=ip_value)
    return None


def trust_diagnostics(request: Request) -> dict[str, object]:
    peer_ip = request.client.host if request.client else ""
    ip_value = _client_ip(request)
    trusted_user = _trusted_request_user(request, ip_value)
    return {
        "peer_ip": peer_ip,
        "client_ip": ip_value,
        "x_forwarded_for": request.headers.get("x-forwarded-for", ""),
        "x_real_ip": request.headers.get("x-real-ip", ""),
        "trusted_proxy_peer": _ip_in_networks(peer_ip, TRUSTED_PROXY_NETWORKS),
        "trusted_proxy_header": request.headers.get(TRUSTED_PROXY_HEADER, ""),
        "trusted": trusted_user is not None,
        "role": trusted_user.role if trusted_user else "",
        "holder": trusted_user.holder if trusted_user else "",
        "source": trusted_user.source if trusted_user else ip_value,
        "trusted_networks": list(TRUSTED_NETWORKS),
        "trusted_proxy_networks": list(TRUSTED_PROXY_NETWORKS),
    }


def _extract_key(api_key: Optional[str], authorization: Optional[str]) -> str:
    if api_key:
        return api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _load_key(key_value: str) -> Optional[sqlite3.Row]:
    conn = sqlite3.connect(META_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT key_value, holder_name, role, expires_at FROM auth_keys "
            "WHERE key_value=? AND is_active=1",
            (key_value,),
        ).fetchone()
    finally:
        conn.close()


def _is_expired(expires_at: Optional[str]) -> bool:
    if not expires_at:
        return False
    return datetime.now() > datetime.fromisoformat(expires_at.replace(" ", "T"))


async def get_request_user(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> RequestUser:
    ip_value = _client_ip(request)
    key_value = _extract_key(x_api_key, authorization)
    if key_value:
        row = _load_key(key_value)
        if not row:
            trusted_user = _trusted_request_user(request, ip_value)
            if trusted_user:
                return trusted_user
            raise HTTPException(status_code=401, detail="Invalid or disabled API key")
        if _is_expired(row["expires_at"]):
            trusted_user = _trusted_request_user(request, ip_value)
            if trusted_user:
                return trusted_user
            raise HTTPException(status_code=401, detail="API key expired")
        return RequestUser(
            role=row["role"],
            holder=row["holder_name"] or "",
            key_value=row["key_value"],
            source="api_key",
        )

    trusted_user = _trusted_request_user(request, ip_value)
    if trusted_user:
        return trusted_user

    raise HTTPException(status_code=401, detail="Authentication required")


async def require_user(user: RequestUser = Depends(get_request_user)) -> RequestUser:
    if user.role not in (USER_ROLE, ADMIN_ROLE):
        raise HTTPException(status_code=403, detail="User role required")
    return user


async def require_admin(user: RequestUser = Depends(get_request_user)) -> RequestUser:
    if user.role != ADMIN_ROLE:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


async def require_internal(request: Request) -> RequestUser:
    ip_value = _client_ip(request)
    try:
        ip = ipaddress.ip_address(ip_value)
    except ValueError:
        raise HTTPException(status_code=403, detail="Internal network required")
    if ip.is_loopback or _trusted_network_role(ip_value) == ADMIN_ROLE:
        return RequestUser(role=ADMIN_ROLE, holder="internal", source=ip_value)
    raise HTTPException(status_code=403, detail="Internal network required")


async def require_internal_or_admin(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> RequestUser:
    if _extract_key(x_api_key, authorization):
        user = await get_request_user(request, x_api_key=x_api_key, authorization=authorization)
        if user.role == ADMIN_ROLE:
            return user
        raise HTTPException(status_code=403, detail="Admin role or internal network required")
    return await require_internal(request)
