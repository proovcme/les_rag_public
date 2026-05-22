"""Trusted-network helpers shared by Sovushka pages."""
from __future__ import annotations

import ipaddress

from fastapi import Request

from sovushka.config import TRUSTED_NETWORK_ROLE, TRUSTED_NETWORKS


def client_ip_from_request(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    real_ip = request.headers.get("x-real-ip")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if real_ip:
        return real_ip.strip()
    return request.client.host if request and request.client else "127.0.0.1"


def trusted_role_for_ip(ip_value: str) -> str | None:
    try:
        ip = ipaddress.ip_address(ip_value)
    except ValueError:
        return None
    for net_value in TRUSTED_NETWORKS:
        try:
            if ip in ipaddress.ip_network(net_value, strict=False):
                return TRUSTED_NETWORK_ROLE
        except ValueError:
            continue
    return None
