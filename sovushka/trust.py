"""Trusted-network helpers shared by Sovushka pages."""
from __future__ import annotations

from fastapi import Request

from sovushka.config import (
    TRUSTED_NETWORK_ROLE,
    TRUSTED_NETWORKS,
    TRUSTED_PROXY_HEADER,
    TRUSTED_PROXY_NETWORKS,
)

# Единое ядро trust-логики (общее с proxy/security.py) — алгоритм один, конфиг свой.
from backend.trust_core import (
    ip_in_networks as _core_ip_in_networks,
    network_role as _core_network_role,
    proxy_asserts_network as _core_proxy_asserts,
    resolve_client_ip as _core_resolve_client_ip,
)


def _ip_in_networks(ip_value: str, networks: tuple[str, ...]) -> bool:
    return _core_ip_in_networks(ip_value, networks)


def _peer_ip(request: Request) -> str:
    return request.client.host if request and request.client else "127.0.0.1"


def _trusted_proxy_asserts_network(request: Request) -> bool:
    return _core_proxy_asserts(
        _peer_ip(request),
        request.headers.get(TRUSTED_PROXY_HEADER, ""),
        TRUSTED_PROXY_NETWORKS,
        TRUSTED_NETWORK_ROLE,
    )


def client_ip_from_request(request: Request) -> str:
    return _core_resolve_client_ip(
        _peer_ip(request),
        request.headers.get("x-forwarded-for"),
        request.headers.get("x-real-ip"),
        TRUSTED_PROXY_NETWORKS,
    )


def trusted_role_for_ip(ip_value: str) -> str | None:
    return _core_network_role(ip_value, TRUSTED_NETWORKS, TRUSTED_NETWORK_ROLE)


def trusted_role_for_request(request: Request) -> str | None:
    if _trusted_proxy_asserts_network(request):
        return TRUSTED_NETWORK_ROLE
    return trusted_role_for_ip(client_ip_from_request(request))


def trust_diagnostics(request: Request) -> dict[str, object]:
    peer_ip = _peer_ip(request)
    client_ip = client_ip_from_request(request)
    role = trusted_role_for_request(request)
    return {
        "peer_ip": peer_ip,
        "client_ip": client_ip,
        "x_forwarded_for": request.headers.get("x-forwarded-for", ""),
        "x_real_ip": request.headers.get("x-real-ip", ""),
        "trusted_proxy_peer": _ip_in_networks(peer_ip, TRUSTED_PROXY_NETWORKS),
        "trusted_proxy_header": request.headers.get(TRUSTED_PROXY_HEADER, ""),
        "trusted": bool(role),
        "role": role or "",
        "holder": "trusted-network" if role else "",
        "source": client_ip,
        "trusted_networks": list(TRUSTED_NETWORKS),
        "trusted_proxy_networks": list(TRUSTED_PROXY_NETWORKS),
    }
