"""Network boundary for administrator-configured model endpoints."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx

from proxy.services.model_connection_contracts import ConnectionLocality


class ConnectionSecurityError(ValueError):
    """A connection endpoint violates the fail-closed network policy."""


Address = ipaddress.IPv4Address | ipaddress.IPv6Address
AddressResolver = Callable[[str, int], Iterable[str]]

_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)


@dataclass(frozen=True)
class ValidatedEndpoint:
    canonical_base_url: str
    locality: ConnectionLocality
    host: str
    port: int
    allowed_addresses: frozenset[Address]


def system_resolver(host: str, port: int) -> tuple[str, ...]:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ConnectionSecurityError("ENDPOINT_DNS_UNAVAILABLE") from exc
    return tuple(str(item[4][0]) for item in answers)


def _forbidden(address: Address) -> bool:
    return bool(
        address in _METADATA_ADDRESSES
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    )


def _validate_locality(addresses: frozenset[Address], locality: ConnectionLocality) -> None:
    if any(_forbidden(address) for address in addresses):
        raise ConnectionSecurityError("FORBIDDEN_DESTINATION")
    if locality is ConnectionLocality.LOOPBACK:
        if not all(address.is_loopback for address in addresses):
            raise ConnectionSecurityError("LOCALITY_ADDRESS_MISMATCH")
        return
    if locality is ConnectionLocality.PRIVATE_NETWORK:
        if not all(address.is_private and not address.is_loopback for address in addresses):
            raise ConnectionSecurityError("LOCALITY_ADDRESS_MISMATCH")
        return
    if any(address.is_private or address.is_loopback for address in addresses):
        raise ConnectionSecurityError("LOCALITY_ADDRESS_MISMATCH")


def _canonical_netloc(parsed: SplitResult, host: str, port: int) -> str:
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    return rendered_host if port == default_port else f"{rendered_host}:{port}"


def validate_endpoint(
    base_url: str,
    locality: ConnectionLocality,
    *,
    resolver: AddressResolver = system_resolver,
    allow_private_http: bool = False,
) -> ValidatedEndpoint:
    raw = str(base_url or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ConnectionSecurityError("ENDPOINT_URL_INVALID") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ConnectionSecurityError("ENDPOINT_SCHEME_INVALID")
    if parsed.username is not None or parsed.password is not None:
        raise ConnectionSecurityError("ENDPOINT_CREDENTIALS_FORBIDDEN")
    if parsed.query:
        raise ConnectionSecurityError("ENDPOINT_QUERY_FORBIDDEN")
    if parsed.fragment:
        raise ConnectionSecurityError("ENDPOINT_FRAGMENT_FORBIDDEN")
    if not parsed.hostname:
        raise ConnectionSecurityError("ENDPOINT_HOST_REQUIRED")
    if any(part == ".." for part in parsed.path.split("/")):
        raise ConnectionSecurityError("ENDPOINT_PATH_INVALID")

    canonical_locality = ConnectionLocality(locality)
    if canonical_locality is ConnectionLocality.REMOTE and scheme != "https":
        raise ConnectionSecurityError("REMOTE_HTTPS_REQUIRED")
    if (
        canonical_locality is ConnectionLocality.PRIVATE_NETWORK
        and scheme == "http"
        and not allow_private_http
    ):
        raise ConnectionSecurityError("PRIVATE_HTTP_NOT_ALLOWED")

    host = parsed.hostname.encode("idna").decode("ascii").lower()
    effective_port = port or (443 if scheme == "https" else 80)
    raw_addresses = tuple(resolver(host, effective_port))
    if not raw_addresses:
        raise ConnectionSecurityError("ENDPOINT_DNS_EMPTY")
    try:
        addresses = frozenset(ipaddress.ip_address(value) for value in raw_addresses)
    except ValueError as exc:
        raise ConnectionSecurityError("ENDPOINT_DNS_INVALID") from exc
    _validate_locality(addresses, canonical_locality)

    path = parsed.path.rstrip("/")
    canonical = urlunsplit(
        (
            scheme,
            _canonical_netloc(parsed, host, effective_port),
            path,
            "",
            "",
        )
    )
    return ValidatedEndpoint(
        canonical_base_url=canonical,
        locality=canonical_locality,
        host=host,
        port=effective_port,
        allowed_addresses=addresses,
    )


def validate_connected_peer(response: httpx.Response, endpoint: ValidatedEndpoint) -> None:
    if 300 <= response.status_code < 400:
        raise ConnectionSecurityError("UPSTREAM_REDIRECT_REJECTED")
    network_stream = response.extensions.get("network_stream")
    if network_stream is None or not hasattr(network_stream, "get_extra_info"):
        raise ConnectionSecurityError("CONNECTED_PEER_UNAVAILABLE")
    server_addr = network_stream.get_extra_info("server_addr")
    if not server_addr:
        raise ConnectionSecurityError("CONNECTED_PEER_UNAVAILABLE")
    raw_address = server_addr[0] if isinstance(server_addr, tuple) else server_addr
    try:
        address = ipaddress.ip_address(str(raw_address))
    except ValueError as exc:
        raise ConnectionSecurityError("CONNECTED_PEER_INVALID") from exc
    if _forbidden(address) or address not in endpoint.allowed_addresses:
        raise ConnectionSecurityError("CONNECTED_PEER_MISMATCH")
    _validate_locality(frozenset({address}), endpoint.locality)


def join_openai_path(endpoint: ValidatedEndpoint, path: str) -> str:
    suffix = "/" + str(path or "").lstrip("/")
    base = endpoint.canonical_base_url.rstrip("/")
    if base.endswith("/v1") or base.endswith("/api/v1"):
        return f"{base}{suffix}"
    return f"{base}/v1{suffix}"
