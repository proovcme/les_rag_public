from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from proxy.config import ADMIN_ROLE, USER_ROLE
from proxy.routers import model_connections as routes
from proxy.security import RequestUser, get_request_user
from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilityObservation,
    CapabilitySnapshot,
    CapabilityState,
)
from proxy.services.model_connection_registry_service import ModelConnectionRegistry
from proxy.services.model_secret_service import EnvironmentSecretStore
from proxy.services.canonical_route_service import PromotionReceipt


NOW = datetime.now(timezone.utc)


class FakeProbe:
    def __init__(self) -> None:
        self.requests: list[tuple[str, tuple[CapabilityName, ...]]] = []

    async def probe_and_store(self, connection, *, requested, registry, actor):
        requested_capabilities = tuple(sorted(map(CapabilityName, requested), key=lambda item: item.value))
        self.requests.append((connection.revision_id, requested_capabilities))
        snapshot = CapabilitySnapshot(
            snapshot_id=f"cap:{connection.revision_id}:{len(self.requests)}",
            connection_revision_id=connection.revision_id,
            observations=tuple(
                CapabilityObservation(
                    capability=capability,
                    state=(
                        CapabilityState.SUPPORTED
                        if capability in requested_capabilities
                        else CapabilityState.UNKNOWN
                    ),
                    evidence_source=("probe" if capability in requested_capabilities else "unavailable"),
                    observed_at=NOW,
                    detail=("http_200" if capability in requested_capabilities else "not_requested"),
                )
                for capability in CapabilityName
            ),
            observed_at=NOW,
            expires_at=NOW + timedelta(hours=24),
            transport_options={"max_output_field": "max_tokens"},
        )
        registry.save_capability_snapshot(snapshot, actor=actor)
        return snapshot


@pytest.fixture
def api(tmp_path, monkeypatch):
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    secret_store = EnvironmentSecretStore(tmp_path / ".env", environ={})
    probe = FakeProbe()
    monkeypatch.setattr(routes, "_registry", lambda: registry)
    monkeypatch.setattr(routes, "_secret_store", lambda: secret_store)
    monkeypatch.setattr(routes, "_probe", lambda *_args: probe)

    app = FastAPI()
    app.include_router(routes.router)

    async def request_user(request: Request) -> RequestUser:
        role = request.headers.get("x-test-role", USER_ROLE)
        return RequestUser(role=role, holder=f"fixture-{role}", source="test")

    app.dependency_overrides[get_request_user] = request_user
    with TestClient(app) as client:
        yield client, registry, secret_store, probe


def _headers(role: str) -> dict[str, str]:
    return {"x-test-role": role}


def _valid_connection(**overrides):
    payload = {
        "display_name": "Local Qwen",
        "base_url": "http://127.0.0.1:1919/v1",
        "model_id": "qwen3.6:35b",
        "locality": "loopback",
        "requested_context_tokens": 30_000,
        "extension_type": "freetoken",
    }
    payload.update(overrides)
    return payload


def _create_test_bind(client: TestClient, *, secret_value: str | None = None) -> dict:
    request = _valid_connection()
    if secret_value is not None:
        request["secret_value"] = secret_value
    created = client.post(
        "/api/model-connections",
        headers=_headers(ADMIN_ROLE),
        json=request,
    )
    assert created.status_code == 201, created.text
    connection = created.json()
    tested = client.post(
        f"/api/model-connections/{connection['connection_id']}/test",
        headers=_headers(ADMIN_ROLE),
        json={
            "revision_id": connection["revision_id"],
            "capabilities": ["chat_completions", "streaming"],
        },
    )
    assert tested.status_code == 200, tested.text
    bound = client.put(
        "/api/model-connections/roles/answer",
        headers=_headers(ADMIN_ROLE),
        json={
            "connection_revision_id": connection["revision_id"],
            "expected_binding_revision": None,
        },
    )
    assert bound.status_code == 200, bound.text
    return connection


def test_user_reads_only_effective_safe_projection(api) -> None:
    client, _registry, _secrets, _probe = api
    connection = _create_test_bind(client, secret_value="must-never-leak")

    assert client.get(
        "/api/model-connections", headers=_headers(USER_ROLE)
    ).status_code == 403
    response = client.get(
        "/api/model-connections/effective", headers=_headers(USER_ROLE)
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["roles"]["answer"]["revision_id"] == connection["revision_id"]
    rendered = json.dumps(payload).lower()
    assert "base_url" not in rendered
    assert "secret_ref" not in rendered
    assert "must-never-leak" not in rendered


def test_admin_create_test_bind_and_confirm_bound_disable(api) -> None:
    client, registry, _secrets, probe = api
    connection = _create_test_bind(client)

    assert probe.requests == [
        (
            connection["revision_id"],
            (CapabilityName.CHAT_COMPLETIONS, CapabilityName.STREAMING),
        )
    ]
    blocked = client.post(
        f"/api/model-connections/{connection['connection_id']}/disable",
        headers=_headers(ADMIN_ROLE),
        json={"expected_revision_id": connection["revision_id"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "BOUND_CONNECTION_CONFIRMATION_REQUIRED"

    disabled = client.post(
        f"/api/model-connections/{connection['connection_id']}/disable",
        headers=_headers(ADMIN_ROLE),
        json={
            "expected_revision_id": connection["revision_id"],
            "confirm_bound_roles": True,
        },
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert registry.get_connection(connection["connection_id"]).enabled is False


def test_role_assignment_automatically_probes_unchecked_connection(api) -> None:
    client, registry, _secrets, probe = api
    created = client.post(
        "/api/model-connections",
        headers=_headers(ADMIN_ROLE),
        json=_valid_connection(extension_type="ollama"),
    ).json()

    response = client.put(
        "/api/model-connections/roles/answer",
        headers=_headers(ADMIN_ROLE),
        json={
            "connection_revision_id": created["revision_id"],
            "expected_binding_revision": None,
        },
    )

    assert response.status_code == 200, response.text
    requested = probe.requests[-1]
    assert requested[0] == created["revision_id"]
    assert CapabilityName.CHAT_COMPLETIONS in requested[1]
    assert CapabilityName.TOOLS in requested[1]
    assert registry.latest_capability_snapshot(created["revision_id"]) is not None


def test_stale_revision_and_role_binding_return_conflict(api) -> None:
    client, _registry, _secrets, _probe = api
    created = client.post(
        "/api/model-connections",
        headers=_headers(ADMIN_ROLE),
        json=_valid_connection(),
    ).json()
    revised = client.post(
        f"/api/model-connections/{created['connection_id']}/revisions",
        headers=_headers(ADMIN_ROLE),
        json={
            "expected_revision_id": created["revision_id"],
            "display_name": "Local Qwen revised",
        },
    )
    assert revised.status_code == 200

    stale = client.post(
        f"/api/model-connections/{created['connection_id']}/revisions",
        headers=_headers(ADMIN_ROLE),
        json={
            "expected_revision_id": created["revision_id"],
            "model_id": "must-not-win",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "CONNECTION_REVISION_CONFLICT"


def test_unsafe_endpoint_is_rejected_before_registry_write(api) -> None:
    client, registry, _secrets, _probe = api
    response = client.post(
        "/api/model-connections",
        headers=_headers(ADMIN_ROLE),
        json=_valid_connection(
            base_url="http://169.254.169.254/v1",
            locality="remote",
        ),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] in {
        "REMOTE_HTTPS_REQUIRED",
        "FORBIDDEN_DESTINATION",
    }
    assert registry.list_connections(include_disabled=True) == ()


def test_admin_can_bind_http_model_on_explicit_private_network(api) -> None:
    client, _registry, _secrets, _probe = api
    created = client.post(
        "/api/model-connections",
        headers=_headers(ADMIN_ROLE),
        json=_valid_connection(
            display_name="Qwen 35B · Mac mini",
            base_url="http://10.195.146.98:8080/v1",
            locality="private_network",
            extension_type="mlx",
        ),
    )

    assert created.status_code == 201, created.text
    connection = created.json()
    tested = client.post(
        f"/api/model-connections/{connection['connection_id']}/test",
        headers=_headers(ADMIN_ROLE),
        json={
            "revision_id": connection["revision_id"],
            "capabilities": ["chat_completions", "streaming"],
        },
    )
    assert tested.status_code == 200, tested.text
    bound = client.put(
        "/api/model-connections/roles/answer",
        headers=_headers(ADMIN_ROLE),
        json={
            "connection_revision_id": connection["revision_id"],
            "expected_binding_revision": None,
        },
    )
    assert bound.status_code == 200, bound.text

    effective = client.get(
        "/api/model-connections/effective", headers=_headers(USER_ROLE)
    )
    assert effective.status_code == 200
    assert effective.json()["roles"]["answer"]["locality"] == "private_network"


def test_secret_replacement_is_masked_and_server_owns_reference(api) -> None:
    client, registry, secret_store, _probe = api
    created = client.post(
        "/api/model-connections",
        headers=_headers(ADMIN_ROLE),
        json=_valid_connection(),
    ).json()

    response = client.post(
        f"/api/model-connections/{created['connection_id']}/secret",
        headers=_headers(ADMIN_ROLE),
        json={
            "expected_revision_id": created["revision_id"],
            "secret_value": "new-private-value",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    rendered = json.dumps(payload)
    assert payload["secret_status"] == "configured"
    assert "new-private-value" not in rendered
    assert "secret_ref" not in rendered
    current = registry.get_connection(created["connection_id"])
    assert current.revision_id != created["revision_id"]
    assert secret_store.status(current.secret_ref) == "configured"

    invalid_value = "must-not-echo\nsecond-line"
    invalid = client.post(
        f"/api/model-connections/{created['connection_id']}/secret",
        headers=_headers(ADMIN_ROLE),
        json={
            "expected_revision_id": current.revision_id,
            "secret_value": invalid_value,
        },
    )
    assert invalid.status_code == 422
    assert invalid_value not in invalid.text


def test_templates_are_admin_only_and_contain_no_credentials(api) -> None:
    client, _registry, _secrets, _probe = api
    assert client.get(
        "/api/model-connections/templates", headers=_headers(USER_ROLE)
    ).status_code == 403

    response = client.get(
        "/api/model-connections/templates", headers=_headers(ADMIN_ROLE)
    )
    assert response.status_code == 200
    names = {item["template_id"] for item in response.json()["templates"]}
    assert names == {
        "freetoken",
        "ollama",
        "lemonade",
        "mlx",
        "lm_studio",
        "llama_cpp",
        "openai_compatible",
    }
    rendered = json.dumps(response.json()).lower()
    assert "api_key" not in rendered
    assert "secret_ref" not in rendered


def test_engine_extension_status_is_admin_only_and_unsupported_is_explicit(api) -> None:
    client, _registry, _secrets, _probe = api
    created = client.post(
        "/api/model-connections",
        headers=_headers(ADMIN_ROLE),
        json=_valid_connection(extension_type="ollama"),
    ).json()

    path = f"/api/model-connections/{created['connection_id']}/extension/status"
    assert client.get(path, headers=_headers(USER_ROLE)).status_code == 403
    response = client.get(path, headers=_headers(ADMIN_ROLE))

    assert response.status_code == 200
    assert response.json() == {"status": "unsupported", "extension_type": "ollama"}


def test_promotion_acceptance_is_admin_only_and_never_changes_route(api, monkeypatch) -> None:
    client, _registry, _secrets, _probe = api
    monkeypatch.setattr(
        routes,
        "accept_promotion_report",
        lambda *_args, **_kwargs: PromotionReceipt(
            source_commit="a" * 40,
            build_number=624,
            preset_id="qwen-9b-restrictive",
            observed_model_identity="qwen3.5:9b",
            acceptance_sha256="b" * 64,
            passed=True,
        ),
    )
    payload = {"report": {"redacted": True}, "operator_confirmed": True}

    path = "/api/model-connections/promotion/accept"
    assert client.post(path, headers=_headers(USER_ROLE), json=payload).status_code == 403
    response = client.post(path, headers=_headers(ADMIN_ROLE), json=payload)

    assert response.status_code == 200
    assert response.json()["route_mode_changed"] is False
    assert "report" not in response.json()


def test_router_is_registered_in_application() -> None:
    source = Path(routes.__file__).parents[1] / "app.py"
    text = source.read_text(encoding="utf-8")

    assert "model_connections_router" in text
    assert "include_router(model_connections_router)" in text
