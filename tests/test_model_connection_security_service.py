from __future__ import annotations

import ipaddress

import httpx
import pytest

from proxy.services.model_connection_contracts import ConnectionLocality
from proxy.services.model_connection_security_service import (
    ConnectionSecurityError,
    join_openai_path,
    validate_connected_peer,
    validate_endpoint,
)


def _resolver(*addresses: str):
    def resolve(_host: str, _port: int):
        return tuple(addresses)

    return resolve


@pytest.mark.parametrize(
    "url",
    (
        "https://user:pass@example.com/v1",
        "https://example.com/v1#fragment",
        "https://example.com/v1?api_key=secret",
        "ftp://example.com/v1",
    ),
)
def test_endpoint_rejects_credentials_fragments_queries_and_unknown_schemes(url) -> None:
    with pytest.raises(ConnectionSecurityError):
        validate_endpoint(
            url,
            ConnectionLocality.REMOTE,
            resolver=_resolver("93.184.216.34"),
        )


def test_remote_endpoint_requires_https() -> None:
    with pytest.raises(ConnectionSecurityError, match="REMOTE_HTTPS_REQUIRED"):
        validate_endpoint(
            "http://models.example/v1",
            ConnectionLocality.REMOTE,
            resolver=_resolver("93.184.216.34"),
        )


def test_loopback_http_requires_every_dns_answer_to_be_loopback() -> None:
    endpoint = validate_endpoint(
        "HTTP://LOCALHOST:1919/v1/",
        ConnectionLocality.LOOPBACK,
        resolver=_resolver("127.0.0.1", "::1"),
    )

    assert endpoint.canonical_base_url == "http://localhost:1919/v1"
    assert endpoint.allowed_addresses == frozenset(
        {ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1")}
    )

    with pytest.raises(ConnectionSecurityError, match="LOCALITY_ADDRESS_MISMATCH"):
        validate_endpoint(
            "http://localhost:1919/v1",
            ConnectionLocality.LOOPBACK,
            resolver=_resolver("127.0.0.1", "10.0.0.8"),
        )


def test_private_http_requires_explicit_policy() -> None:
    with pytest.raises(ConnectionSecurityError, match="PRIVATE_HTTP_NOT_ALLOWED"):
        validate_endpoint(
            "http://models.office/v1",
            ConnectionLocality.PRIVATE_NETWORK,
            resolver=_resolver("10.10.1.20"),
        )

    endpoint = validate_endpoint(
        "http://models.office/v1",
        ConnectionLocality.PRIVATE_NETWORK,
        resolver=_resolver("10.10.1.20"),
        allow_private_http=True,
    )
    assert endpoint.host == "models.office"


@pytest.mark.parametrize(
    "address",
    ("169.254.169.254", "0.0.0.0", "224.0.0.1", "::"),
)
def test_ssrf_policy_rejects_metadata_link_local_unspecified_and_multicast(address) -> None:
    with pytest.raises(ConnectionSecurityError, match="FORBIDDEN_DESTINATION"):
        validate_endpoint(
            f"https://[{address}]/v1" if ":" in address else f"https://{address}/v1",
            ConnectionLocality.REMOTE,
            resolver=_resolver(address),
        )


class _NetworkStream:
    def __init__(self, address: str):
        self.address = address

    def get_extra_info(self, name: str):
        assert name == "server_addr"
        return (self.address, 443)


def _response(status: int, peer: str) -> httpx.Response:
    return httpx.Response(
        status,
        request=httpx.Request("GET", "https://models.example/v1/models"),
        extensions={"network_stream": _NetworkStream(peer)},
    )


def test_connected_peer_must_match_prevalidated_dns_set() -> None:
    endpoint = validate_endpoint(
        "https://models.example/v1",
        ConnectionLocality.REMOTE,
        resolver=_resolver("93.184.216.34"),
    )

    validate_connected_peer(_response(200, "93.184.216.34"), endpoint)
    with pytest.raises(ConnectionSecurityError, match="CONNECTED_PEER_MISMATCH"):
        validate_connected_peer(_response(200, "10.0.0.8"), endpoint)


def test_redirects_and_missing_peer_evidence_fail_closed() -> None:
    endpoint = validate_endpoint(
        "https://models.example/v1",
        ConnectionLocality.REMOTE,
        resolver=_resolver("93.184.216.34"),
    )

    with pytest.raises(ConnectionSecurityError, match="UPSTREAM_REDIRECT_REJECTED"):
        validate_connected_peer(_response(302, "93.184.216.34"), endpoint)
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://models.example/v1/models"),
    )
    with pytest.raises(ConnectionSecurityError, match="CONNECTED_PEER_UNAVAILABLE"):
        validate_connected_peer(response, endpoint)


def test_openai_path_join_preserves_existing_api_root() -> None:
    endpoint = validate_endpoint(
        "http://127.0.0.1:13305/api/v1",
        ConnectionLocality.LOOPBACK,
        resolver=_resolver("127.0.0.1"),
    )

    assert join_openai_path(endpoint, "/chat/completions") == (
        "http://127.0.0.1:13305/api/v1/chat/completions"
    )

