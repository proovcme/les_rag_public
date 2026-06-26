"""Общее ядро trust-логики В.О.Л.К. — единственный источник правды для доверия по сети.

Дублировалось в proxy/security.py и sovushka/trust.py (один алгоритм, разные конфиги). Здесь —
ЧИСТАЯ логика без привязки к конфигу: вызывающий передаёт свои сети/роль. Это убирает риск
расхождения двух копий security-критичного XFF-гейтинга.

Ключевой инвариант (анти-спуфинг): X-Forwarded-For / X-Real-IP учитываются ТОЛЬКО если peer
(реальный TCP-источник) входит в trusted_proxy_networks. Иначе берётся peer_ip — чужой клиент
не может выдать себя за доверенный IP через подделку заголовка.
"""

from __future__ import annotations

import ipaddress
from typing import Optional, Sequence

_TRUE_VALUES = {"1", "true", "yes", "on"}


def ip_in_networks(ip_value: str, networks: Sequence[str]) -> bool:
    """ip входит хотя бы в одну из сетей (CIDR). Кривой ip/сеть → False (fail-closed)."""
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


def resolve_client_ip(
    peer_ip: str,
    forwarded: Optional[str],
    real_ip: Optional[str],
    trusted_proxy_networks: Sequence[str],
) -> str:
    """Реальный клиентский IP. XFF/X-Real-IP — ТОЛЬКО от доверенного прокси (анти-спуфинг), иначе peer_ip."""
    if ip_in_networks(peer_ip, trusted_proxy_networks):
        if forwarded:
            return forwarded.split(",")[0].strip()
        if real_ip:
            return real_ip.strip()
    return peer_ip


def proxy_asserts_network(
    peer_ip: str,
    header_value: str,
    trusted_proxy_networks: Sequence[str],
    trusted_role: str,
) -> bool:
    """Доверенный прокси утверждает «клиент в доверенной сети» заголовком — учитываем ТОЛЬКО от прокси-peer."""
    if not ip_in_networks(peer_ip, trusted_proxy_networks):
        return False
    return (header_value or "").lower() in (_TRUE_VALUES | {trusted_role})


def network_role(ip_value: str, trusted_networks: Sequence[str], trusted_role: str) -> Optional[str]:
    """Роль для IP: trusted_role если ip в доверенных сетях, иначе None."""
    return trusted_role if ip_in_networks(ip_value, trusted_networks) else None
