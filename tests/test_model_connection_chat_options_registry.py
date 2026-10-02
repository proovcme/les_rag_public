"""Offline contracts for immutable operator-declared chat controls."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from threading import Event, Thread, current_thread
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from proxy.config import ADMIN_ROLE, USER_ROLE
from proxy.routers import model_connections as routes
from proxy.security import RequestUser, get_request_user
from proxy.services.model_connection_contracts import (
    CapabilityName, CapabilityObservation, CapabilitySnapshot, CapabilityState,
    ConnectionLocality, ConnectionRole,
)
from proxy.services.model_connection_registry_service import (
    ModelConnectionRegistry, RevisionConflictError,
)
from proxy.services.model_secret_service import EnvironmentSecretStore


OPTIONS = {
    "max_output_field": "max_completion_tokens",
    "reasoning_mode": "effort",
    "enabled_effort": "high",
    "temperature_mode": "omit",
    "requested_output_tokens": 16_384,
}


def _create(registry, **overrides):
    values = {
        "display_name": "Generic connection",
        "base_url": "http://127.0.0.1:1919/v1",
        "model_id": "arbitrary-model-id",
        "locality": ConnectionLocality.LOOPBACK,
        "requested_context_tokens": 262_144,
        "secret_ref": None,
        "extension_type": None,
        "actor": "admin:test",
    }
    values.update(overrides)
    return registry.create_connection(**values)


def _snapshot(revision_id, *, max_output_field="max_tokens"):
    now = datetime.now(timezone.utc)
    return CapabilitySnapshot(
        snapshot_id=f"cap:{revision_id}",
        connection_revision_id=revision_id,
        observations=tuple(
            CapabilityObservation(
                capability=item, state=CapabilityState.SUPPORTED,
                evidence_source="probe", observed_at=now, detail="http_200",
            )
            for item in (CapabilityName.CHAT_COMPLETIONS, CapabilityName.STREAMING)
        ),
        observed_at=now, expires_at=now + timedelta(hours=24),
        transport_options={"max_output_field": max_output_field},
    )


def _old_database(path):
    """Build the pre-chat-options schema without invoking the current migrator."""
    now = datetime.now(timezone.utc)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE les_model_connection_revisions (
                revision_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL,
                revision_no INTEGER NOT NULL, display_name TEXT NOT NULL,
                protocol TEXT NOT NULL, base_url TEXT NOT NULL, model_id TEXT NOT NULL,
                locality TEXT NOT NULL, requested_context_tokens INTEGER,
                secret_ref TEXT, extension_type TEXT, enabled INTEGER NOT NULL,
                created_at TEXT NOT NULL, created_by TEXT NOT NULL,
                UNIQUE(connection_id, revision_no));
            CREATE TABLE les_model_connection_heads (
                connection_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL);
            CREATE TABLE les_model_role_bindings (
                role TEXT NOT NULL, binding_revision INTEGER NOT NULL,
                connection_revision_id TEXT NOT NULL, bound_at TEXT NOT NULL,
                bound_by TEXT NOT NULL, PRIMARY KEY(role, binding_revision));
            CREATE TABLE les_model_capability_snapshots (
                snapshot_id TEXT PRIMARY KEY, connection_revision_id TEXT NOT NULL,
                observations_json TEXT NOT NULL, observed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, transport_options_json TEXT NOT NULL,
                created_by TEXT NOT NULL);
            CREATE TABLE les_model_connection_audit (
                event_id TEXT PRIMARY KEY, action TEXT NOT NULL, connection_id TEXT,
                revision_id TEXT, actor TEXT NOT NULL, created_at TEXT NOT NULL,
                details_json TEXT NOT NULL);
        """)
        conn.execute(
            "INSERT INTO les_model_connection_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("conn:old:r1", "conn:old", 1, "Old connection", "openai_compatible",
             "http://127.0.0.1:1919/v1", "old-model", "loopback", 8192,
             None, None, 1, now.isoformat(), "admin:old"),
        )
        conn.execute("INSERT INTO les_model_connection_heads VALUES (?,?)", ("conn:old", "conn:old:r1"))
        conn.execute(
            "INSERT INTO les_model_role_bindings VALUES (?,?,?,?,?)",
            ("answer", 1, "conn:old:r1", now.isoformat(), "admin:old"),
        )
        observations = [{
            "capability": "chat_completions", "state": "supported",
            "evidence_source": "probe", "observed_at": now.isoformat(), "detail": "http_200",
        }]
        conn.execute(
            "INSERT INTO les_model_capability_snapshots VALUES (?,?,?,?,?,?,?)",
            ("cap:old", "conn:old:r1", json.dumps(observations), now.isoformat(),
             (now + timedelta(hours=24)).isoformat(),
             '{"max_output_field":"max_completion_tokens"}', "admin:old"),
        )
        conn.execute(
            "INSERT INTO les_model_connection_audit VALUES (?,?,?,?,?,?,?)",
            ("audit:old", "connection_created", "conn:old", "conn:old:r1",
             "admin:old", now.isoformat(), "{}"),
        )


def test_additive_migration_preserves_old_identity_bindings_snapshot_and_wire(tmp_path):
    from proxy.services.openai_compatible_transport_service import OpenAICompatibleTransport

    path = tmp_path / "old.db"
    _old_database(path)
    registry = ModelConnectionRegistry(path)
    ModelConnectionRegistry(path)  # Repeated startup is idempotent.
    revision = registry.get_revision("conn:old:r1")
    assert revision.chat_options.to_dict() == {}
    assert registry.get_connection("conn:old").revision_id == "conn:old:r1"
    assert registry.get_role_binding(ConnectionRole.ANSWER).connection_revision_id == "conn:old:r1"
    snapshot = registry.latest_capability_snapshot("conn:old:r1")
    assert snapshot.snapshot_id == "cap:old"
    connection = SimpleNamespace(capability_snapshot=snapshot, chat_options=revision.chat_options)
    assert OpenAICompatibleTransport._output_field(connection) == "max_completion_tokens"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT chat_options_json FROM les_model_connection_revisions").fetchall() == [("{}",)]
        assert conn.execute("SELECT COUNT(*) FROM les_model_connection_revisions").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM les_model_connection_audit").fetchone() == (1,)


def test_chat_options_are_typed_frozen_and_sparse_by_default():
    from proxy.services.model_connection_contracts import ChatOptions

    assert ChatOptions().to_dict() == {}
    options = ChatOptions(**OPTIONS)
    assert options.to_dict() == OPTIONS
    with pytest.raises(FrozenInstanceError):
        options.reasoning_mode = "enabled"


def test_concurrent_old_schema_startup_cannot_add_column_twice(tmp_path, monkeypatch):
    import proxy.services.model_connection_registry_service as module

    path = tmp_path / "concurrent-old.db"
    _old_database(path)
    original_connect = sqlite3.connect
    first_checked, second_checked = Event(), Event()
    errors, results = [], []

    class InterleavingConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            cursor = super().execute(sql, *args)
            if sql == "PRAGMA table_info(les_model_connection_revisions)":
                rows = cursor.fetchall()
                if current_thread().name == "migration:first":
                    first_checked.set()
                    # Without an atomic check/add the second startup observes
                    # the same missing column before either ALTER can execute.
                    second_checked.wait(0.5)
                else:
                    second_checked.set()
                return rows
            return cursor

    monkeypatch.setattr(module.sqlite3, "connect", lambda *args, **kwargs:
                        original_connect(*args, factory=InterleavingConnection, **kwargs))

    def start():
        try:
            results.append(ModelConnectionRegistry(path).get_revision("conn:old:r1"))
        except Exception as error:
            errors.append(error)

    first = Thread(target=start, name="migration:first")
    second = Thread(target=start, name="migration:second")
    first.start()
    assert first_checked.wait(2), "First startup never reached the migration check"
    second.start()
    first.join(3)
    second.join(3)
    assert not first.is_alive() and not second.is_alive(), "Concurrent startup did not finish"
    assert errors == []
    assert len(results) == 2
    assert all(item.revision_id == "conn:old:r1" and item.chat_options.to_dict() == {} for item in results)


def test_revision_cas_preserves_omitted_controls_and_whole_reset(tmp_path):
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    first = _create(registry, chat_options=OPTIONS)
    registry.save_capability_snapshot(_snapshot(first.revision_id), actor="admin:test")
    binding = registry.bind_role(ConnectionRole.ANSWER, first.revision_id,
                                 expected_binding_revision=None, actor="admin:test")
    second = registry.revise_connection(
        first.connection_id, expected_revision_id=first.revision_id,
        actor="admin:test", display_name="Renamed connection",
    )
    assert second.chat_options.to_dict() == OPTIONS
    third = registry.revise_connection(
        first.connection_id, expected_revision_id=second.revision_id,
        actor="admin:test", chat_options={},
    )
    assert third.chat_options.to_dict() == {}
    assert registry.get_revision(first.revision_id).chat_options.to_dict() == OPTIONS
    assert registry.get_role_binding(ConnectionRole.ANSWER) == binding
    assert registry.latest_capability_snapshot(first.revision_id) is not None
    assert registry.latest_capability_snapshot(third.revision_id) is None
    with pytest.raises(RevisionConflictError):
        registry.revise_connection(first.connection_id, expected_revision_id=first.revision_id,
                                   actor="admin:stale", chat_options={"reasoning_mode": "enabled"})
    assert registry.list_revisions(first.connection_id) == (first, second, third)


@pytest.fixture
def api(tmp_path, monkeypatch):
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    secret_store = EnvironmentSecretStore(tmp_path / "fixture-env.txt", environ={})
    monkeypatch.setattr(routes, "_registry", lambda: registry)
    monkeypatch.setattr(routes, "_secret_store", lambda: secret_store)
    original_validate = routes.validate_endpoint
    monkeypatch.setattr(routes, "validate_endpoint", lambda url, locality, **kwargs:
                        original_validate(url, locality, resolver=lambda *_: ("127.0.0.1",), **kwargs))
    original_resolver = routes.ModelConnectionResolver
    monkeypatch.setattr(routes, "ModelConnectionResolver", lambda **kwargs:
                        original_resolver(address_resolver=lambda *_: ("127.0.0.1",), **kwargs))
    app = FastAPI()
    app.include_router(routes.router)

    async def request_user(request: Request):
        return RequestUser(role=request.headers.get("x-test-role", USER_ROLE),
                           holder="fixture-user", source="test")

    app.dependency_overrides[get_request_user] = request_user
    with TestClient(app) as client:
        yield client, registry


def _payload(**overrides):
    payload = {
        "display_name": "Generic connection", "base_url": "http://127.0.0.1:1919/v1",
        "model_id": "arbitrary-model-id", "locality": "loopback",
        "requested_context_tokens": 262_144, "chat_options": OPTIONS,
    }
    payload.update(overrides)
    return payload


def _admin():
    return {"x-test-role": ADMIN_ROLE}


def test_api_create_edit_copy_and_safe_projection_preserve_options_without_binding(api):
    client, registry = api
    created = client.post("/api/model-connections", json=_payload(), headers=_admin())
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["chat_options"] == OPTIONS
    assert registry.get_role_binding(ConnectionRole.ANSWER) is None
    edited = client.post(f"/api/model-connections/{first['connection_id']}/revisions",
                         headers=_admin(), json={"expected_revision_id": first["revision_id"],
                                                 "display_name": "Renamed connection"})
    assert edited.status_code == 200, edited.text
    second = edited.json()
    assert second["chat_options"] == OPTIONS
    copied = client.post("/api/model-connections", headers=_admin(),
                         json=_payload(display_name="Copied connection", chat_options=second["chat_options"]))
    assert copied.status_code == 201, copied.text
    assert copied.json()["chat_options"] == OPTIONS
    assert copied.json()["connection_id"] != first["connection_id"]
    assert registry.get_role_binding(ConnectionRole.ANSWER) is None
    registry.save_capability_snapshot(_snapshot(second["revision_id"]), actor="admin:test")
    registry.bind_role(ConnectionRole.ANSWER, second["revision_id"],
                       expected_binding_revision=None, actor="admin:test")
    safe = client.get("/api/model-connections/effective", headers={"x-test-role": USER_ROLE})
    assert safe.status_code == 200, safe.text
    answer = safe.json()["roles"]["answer"]
    assert answer["chat_options"] == OPTIONS
    assert isinstance(answer["execution_diagnostics"], dict)
    assert "base_url" not in json.dumps(safe.json())
    assert "secret_ref" not in json.dumps(safe.json())
    reset = client.post(f"/api/model-connections/{first['connection_id']}/revisions", headers=_admin(),
                        json={"expected_revision_id": second["revision_id"], "chat_options": {}})
    assert reset.status_code == 200, reset.text
    assert reset.json()["chat_options"] == {}
    assert registry.get_role_binding(ConnectionRole.ANSWER).connection_revision_id == second["revision_id"]


@pytest.mark.parametrize("invalid", [
    {"max_output_field": "max_output_tokens"}, {"reasoning_mode": "auto"},
    {"reasoning_mode": "effort"}, {"reasoning_mode": "effort", "enabled_effort": "none"},
    {"temperature_mode": "automatic"}, {"requested_output_tokens": 0},
    {"requested_output_tokens": -1}, {"requested_output_tokens": True},
    {"requested_output_tokens": 1.5}, {"unknown_option": True},
])
def test_invalid_api_options_return_422_without_creating_revision(api, invalid):
    client, registry = api
    response = client.post("/api/model-connections", json=_payload(chat_options=invalid), headers=_admin())
    assert response.status_code == 422, response.text
    assert registry.list_connections(include_disabled=True) == ()
    first = _create(registry)
    changed = client.post(f"/api/model-connections/{first.connection_id}/revisions", headers=_admin(),
                          json={"expected_revision_id": first.revision_id, "chat_options": invalid})
    assert changed.status_code == 422, changed.text
    assert registry.list_revisions(first.connection_id) == (first,)


def test_gui_payload_round_trip_and_clear_output():
    from sovushka.pages.model_connections import connection_chat_options_payload

    assert connection_chat_options_payload(**OPTIONS) == OPTIONS
    assert connection_chat_options_payload(
        max_output_field=None, reasoning_mode="unconfigured", enabled_effort=None,
        temperature_mode="profile", requested_output_tokens=None,
    ) == {}
    assert connection_chat_options_payload(
        max_output_field="max_tokens", reasoning_mode="enabled", enabled_effort=None,
        temperature_mode="profile", requested_output_tokens=16_384.0,
    ) == {"max_output_field": "max_tokens", "reasoning_mode": "enabled", "requested_output_tokens": 16_384}


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "nonnumeric"])
def test_gui_rejects_invalid_output_without_silent_integer_truncation(value):
    from sovushka.pages.model_connections import connection_chat_options_payload

    with pytest.raises(ValueError):
        connection_chat_options_payload(max_output_field=None, reasoning_mode="unconfigured",
                                        enabled_effort=None, temperature_mode="profile",
                                        requested_output_tokens=value)


def test_gui_controls_and_diagnostics_have_russian_labels():
    source = Path("sovushka/pages/model_connections.py").read_text(encoding="utf-8")
    for label in ("Лимит ответа", "Рассуждение", "Температура", "Неизвестно",
                  "Наблюдалось", "Источник", "Перезапуск не требуется"):
        assert label in source
    assert "connection_chat_options_payload(" in source
    assert 'current.get("chat_options")' in source or "current.get('chat_options')" in source


def test_gui_summary_distinguishes_local_profile_control_from_remote_unknown():
    from sovushka.pages.model_connections import connection_chat_options_summary

    for connection in (
        {"extension_type": "freetoken", "chat_options": {}},
        {"extension_type": "freetoken", "chat_options": OPTIONS},
        {"observed_chat_protocol": "native_chat_v1", "chat_options": {"reasoning_mode": "enabled"}},
    ):
        summary = connection_chat_options_summary(connection)
        reasoning = summary.split("Рассуждение: ", 1)[1].split(" · Температура:", 1)[0]
        assert "Локальный переключатель по профилю" in reasoning
        assert "удалённый протокол не применяется" in reasoning
        assert "Неизвестно" not in reasoning
        assert "reasoning.enabled" not in reasoning and "→ none" not in reasoning
    remote = connection_chat_options_summary({"locality": "remote", "chat_options": {}})
    assert "Рассуждение: Неизвестно: управление провайдером не задано" in remote


def test_gui_connection_default_is_not_presented_as_the_chat_profile_limit():
    source = Path("sovushka/pages/model_connections.py").read_text(encoding="utf-8")
    assert "Базовый резерв до применения профиля:" in source
    assert "Лимит ответа действует:" not in source


def test_explicit_top_level_thinking_control_round_trips_api_and_gui_without_binding(api):
    from sovushka.pages.model_connections import (
        connection_chat_options_payload, connection_chat_options_summary,
    )

    client, registry = api
    options = {"reasoning_mode": "enable_thinking", "temperature_mode": "omit",
               "requested_output_tokens": 16_384}
    payload = connection_chat_options_payload(
        max_output_field=None, reasoning_mode="enable_thinking", enabled_effort=None,
        temperature_mode="omit", requested_output_tokens=16_384.0,
    )
    assert payload == options
    created = client.post("/api/model-connections", headers=_admin(),
                          json=_payload(chat_options=payload))
    assert created.status_code == 201, created.text
    connection = created.json()
    assert connection["chat_options"] == options
    assert registry.get_revision(connection["revision_id"]).chat_options.to_dict() == options
    assert all(registry.get_role_binding(role) is None for role in ConnectionRole)
    summary = connection_chat_options_summary(connection)
    assert "Рассуждение: По профилю: переключатель enable_thinking" in summary
    source = Path("sovushka/pages/model_connections.py").read_text(encoding="utf-8")
    assert '"enable_thinking": "Переключатель enable_thinking"' in source
