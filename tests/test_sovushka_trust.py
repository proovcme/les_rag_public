from types import SimpleNamespace

import sovushka.trust as trust


def _request(ip: str, headers: dict | None = None):
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=ip))


def test_forwarded_headers_are_only_used_from_trusted_proxy(monkeypatch):
    monkeypatch.setattr(trust, "TRUSTED_NETWORKS", ("127.0.0.0/8", "10.10.10.0/24"))
    monkeypatch.setattr(trust, "TRUSTED_PROXY_NETWORKS", ("127.0.0.0/8",))
    monkeypatch.setattr(trust, "TRUSTED_NETWORK_ROLE", "admin")

    assert trust.client_ip_from_request(_request("203.0.113.1", {"x-forwarded-for": "10.10.10.98"})) == "203.0.113.1"
    assert trust.trusted_role_for_request(_request("203.0.113.1", {"x-forwarded-for": "10.10.10.98"})) is None

    assert trust.client_ip_from_request(_request("127.0.0.1", {"x-forwarded-for": "10.10.10.98"})) == "10.10.10.98"
    assert trust.trusted_role_for_request(_request("127.0.0.1", {"x-forwarded-for": "10.10.10.98"})) == "admin"


def test_trusted_proxy_header_requires_trusted_proxy_peer(monkeypatch):
    monkeypatch.setattr(trust, "TRUSTED_NETWORKS", ("127.0.0.0/8", "10.10.10.0/24"))
    monkeypatch.setattr(trust, "TRUSTED_PROXY_NETWORKS", ("127.0.0.0/8",))
    monkeypatch.setattr(trust, "TRUSTED_NETWORK_ROLE", "admin")
    monkeypatch.setattr(trust, "TRUSTED_PROXY_HEADER", "x-les-trusted-network")

    assert trust.trusted_role_for_request(_request("203.0.113.1", {"x-les-trusted-network": "1"})) is None
    assert trust.trusted_role_for_request(_request("127.0.0.1", {"x-les-trusted-network": "1"})) == "admin"
