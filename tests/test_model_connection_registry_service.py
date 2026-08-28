from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from proxy.services.model_connection_contracts import (
    CapabilityName,
    CapabilityObservation,
    CapabilitySnapshot,
    CapabilityState,
    ConnectionLocality,
    ConnectionRole,
)
from proxy.services.model_connection_registry_service import (
    ModelConnectionRegistry,
    ModelConnectionRegistryError,
    RevisionConflictError,
)


def _create_connection(
    registry: ModelConnectionRegistry,
    *,
    name: str = "Local Qwen",
    model_id: str = "qwen3.6:35b",
):
    return registry.create_connection(
        display_name=name,
        base_url="http://127.0.0.1:1919/v1",
        model_id=model_id,
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=30_000,
        secret_ref=None,
        extension_type="freetoken",
        actor="admin:test",
    )


def test_edit_creates_revision_and_keeps_old_snapshot(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    first = _create_connection(registry)

    second = registry.revise_connection(
        first.connection_id,
        expected_revision_id=first.revision_id,
        model_id="qwen3.6:35b-fixed",
        actor="admin:test",
    )

    assert second.revision_no == 2
    assert second.revision_id != first.revision_id
    assert registry.get_revision(first.revision_id).model_id == "qwen3.6:35b"
    assert registry.get_connection(first.connection_id).revision_id == second.revision_id


def test_stale_connection_revision_is_rejected_without_extra_revision(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    first = _create_connection(registry)
    current = registry.revise_connection(
        first.connection_id,
        expected_revision_id=first.revision_id,
        model_id="qwen3.6:35b-fixed",
        actor="admin:first",
    )

    with pytest.raises(RevisionConflictError, match="CONNECTION_REVISION_CONFLICT"):
        registry.revise_connection(
            first.connection_id,
            expected_revision_id=first.revision_id,
            model_id="must-not-win",
            actor="admin:stale",
        )

    assert registry.get_connection(first.connection_id) == current
    assert registry.list_revisions(first.connection_id) == (first, current)


def test_role_binding_is_atomic_and_points_to_exact_revision(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    revision = _create_connection(registry)

    binding = registry.bind_role(
        ConnectionRole.ANSWER,
        revision.revision_id,
        expected_binding_revision=None,
        actor="admin:test",
    )

    assert binding.connection_revision_id == revision.revision_id
    assert binding.binding_revision == 1
    assert registry.get_role_binding(ConnectionRole.ANSWER) == binding


def test_stale_role_binding_cannot_overwrite_newer_binding(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    first = _create_connection(registry, name="Primary")
    second = _create_connection(registry, name="Fallback")
    initial = registry.bind_role(
        ConnectionRole.ANSWER,
        first.revision_id,
        expected_binding_revision=None,
        actor="admin:first",
    )
    current = registry.bind_role(
        ConnectionRole.ANSWER,
        second.revision_id,
        expected_binding_revision=initial.binding_revision,
        actor="admin:second",
    )

    with pytest.raises(RevisionConflictError, match="ROLE_BINDING_CONFLICT"):
        registry.bind_role(
            ConnectionRole.ANSWER,
            first.revision_id,
            expected_binding_revision=initial.binding_revision,
            actor="admin:stale",
        )

    assert registry.get_role_binding(ConnectionRole.ANSWER) == current


def test_disabled_revision_cannot_be_bound_but_old_revision_remains_readable(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    enabled = _create_connection(registry)
    disabled = registry.disable_connection(
        enabled.connection_id,
        expected_revision_id=enabled.revision_id,
        actor="admin:test",
    )

    assert disabled.enabled is False
    assert registry.get_revision(enabled.revision_id).enabled is True
    assert registry.list_connections() == ()
    assert registry.list_connections(include_disabled=True) == (disabled,)
    with pytest.raises(ModelConnectionRegistryError, match="CONNECTION_DISABLED"):
        registry.bind_role(
            ConnectionRole.ANSWER,
            disabled.revision_id,
            expected_binding_revision=None,
            actor="admin:test",
        )


def test_active_display_names_are_unique_case_insensitively(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    _create_connection(registry, name="Office Ollama")

    with pytest.raises(ModelConnectionRegistryError, match="DISPLAY_NAME_IN_USE"):
        _create_connection(registry, name=" office ollama ")


def test_capability_snapshot_round_trip_is_immutable(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    connection = _create_connection(registry)
    observed_at = datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:test:1",
        connection_revision_id=connection.revision_id,
        observations=(
            CapabilityObservation(
                capability=CapabilityName.CHAT_COMPLETIONS,
                state=CapabilityState.SUPPORTED,
                evidence_source="probe",
                observed_at=observed_at,
                detail="http_200",
            ),
            CapabilityObservation(
                capability=CapabilityName.RESPONSES,
                state=CapabilityState.UNSUPPORTED,
                evidence_source="probe",
                observed_at=observed_at,
                detail="http_404",
            ),
        ),
        observed_at=observed_at,
        expires_at=observed_at + timedelta(hours=24),
        transport_options={"max_output_field": "max_tokens"},
    )

    registry.save_capability_snapshot(snapshot, actor="admin:test")
    restored = registry.latest_capability_snapshot(connection.revision_id)

    assert restored == snapshot
    assert restored is not None
    assert restored.state(CapabilityName.CHAT_COMPLETIONS) is CapabilityState.SUPPORTED
    with pytest.raises(TypeError):
        restored.transport_options["max_output_field"] = "max_completion_tokens"


def test_snapshot_for_unknown_revision_is_rejected(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    now = datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)
    snapshot = CapabilitySnapshot(
        snapshot_id="cap:missing",
        connection_revision_id="conn:missing:r1",
        observations=(),
        observed_at=now,
        expires_at=now + timedelta(hours=1),
        transport_options={},
    )

    with pytest.raises(ModelConnectionRegistryError, match="CONNECTION_REVISION_NOT_FOUND"):
        registry.save_capability_snapshot(snapshot, actor="admin:test")
