"""Trusted-network helpers shared by Sovushka pages."""
from __future__ import annotations

import ipaddress

from fastapi import Request

from sovushka.config import (
    TRUSTED_NETWORK_ROLE,
    TRUSTED_NETWORKS,
    TRUSTED_PROXY_HEADER,
    TRUSTED_PROXY_NETWORKS,
)


def _ip_in_networks(ip_value: str, networks: tuple[str, ...]) -> bool:
    try:
        ip = ipaddress.ip_address(ip_value)
    except ValueError:
        return False
    for net_value in networks:
        try:
            if ip in ipaddress.ip_network(net_value, strict=False):
                return True
        except ValueError:
            continue
    return False


def _peer_ip(request: Request) -> str:
    return request.client.host if request and request.client else "127.0.0.1"


def _trusted_proxy_asserts_network(request: Request) -> bool:
    peer_ip = _peer_ip(request)
    if not _ip_in_networks(peer_ip, TRUSTED_PROXY_NETWORKS):
        return False
    value = request.headers.get(TRUSTED_PROXY_HEADER, "")
    return value.lower() in {"1", "true", "yes", "on", TRUSTED_NETWORK_ROLE}


def client_ip_from_request(request: Request) -> str:
    peer_ip = _peer_ip(request)
    if not _ip_in_networks(peer_ip, TRUSTED_PROXY_NETWORKS):
        return peer_ip

    forwarded = request.headers.get("x-forwarded-for")
    real_ip = request.headers.get("x-real-ip")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if real_ip:
        return real_ip.strip()
    return peer_ip


def trusted_role_for_ip(ip_value: str) -> str | None:
    return TRUSTED_NETWORK_ROLE if _ip_in_networks(ip_value, TRUSTED_NETWORKS) else None


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
