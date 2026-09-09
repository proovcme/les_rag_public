"""Shared proxy-environment policy for internal HTTP clients.

Loopback services are part of one LES installation and must never be routed
through HTTP(S)/ALL_PROXY inherited from the desktop or service account.
External URLs keep httpx's normal environment behavior.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from urllib.parse import urlsplit


def is_loopback_url(url: str) -> bool:
    """Return True only for localhost names and loopback IP addresses."""
    try:
        host = (urlsplit(str(url or "")).hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def trust_env_for_url(url: str) -> bool:
    """Preserve proxy env for external URLs and bypass it for loopback only."""
    return not is_loopback_url(url)



PROXY_VARIABLES = ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY")
HTTPX_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})


def environment_without_unsupported_proxies(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy an environment without proxy variables httpx cannot parse.

    A desktop VPN can export ``ALL_PROXY=socks4://…``; httpx raises
    ``ValueError: Unknown scheme for proxy URL`` while merely constructing a client,
    so a background job inheriting that variable dies before its first request.
    Supported schemes and every other variable are preserved untouched.
    """
    source = dict(os.environ if environment is None else environment)
    for name in list(source):
        if name.upper() not in PROXY_VARIABLES:
            continue
        scheme = urlsplit(str(source[name] or "").strip()).scheme.lower()
        if scheme and scheme not in HTTPX_PROXY_SCHEMES:
            del source[name]
    return source
