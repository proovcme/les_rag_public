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
from proxy.services.model_connection_registry_service import ModelConnectionRegistry
from proxy.services.model_connection_resolver_service import (
    LegacyConnectionImporter,
    ModelConnectionResolutionError,
    ModelConnectionResolver,
)
from proxy.services.model_secret_service import EnvironmentSecretStore


NOW = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)


def _snapshot(
    revision_id: str,
    *capabilities: CapabilityName,
    expires_at: datetime | None = None,
    observed_context_tokens: int | None = None,
) -> CapabilitySnapshot:
    options = {"max_output_field": "max_tokens"}
    if observed_context_tokens is not None:
        options["observed_context_tokens"] = str(observed_context_tokens)
    effective_expires_at = expires_at or NOW + timedelta(hours=24)
    observed_at = min(NOW, effective_expires_at - timedelta(hours=1))
    return CapabilitySnapshot(
        snapshot_id=f"cap:{revision_id}",
        connection_revision_id=revision_id,
        observations=tuple(
            CapabilityObservation(
                capability=capability,
                state=CapabilityState.SUPPORTED,
                evidence_source="probe",
                observed_at=observed_at,
                detail="http_200",
            )
            for capability in capabilities
        ),
        observed_at=observed_at,
        expires_at=effective_expires_at,
        transport_options=options,
    )


def _connection(
    registry: ModelConnectionRegistry,
    *,
    name: str,
    model: str = "qwen3.5:9b",
    secret_ref: str | None = None,
):
    revision = registry.create_connection(
        display_name=name,
        base_url="http://127.0.0.1:1919/v1",
        model_id=model,
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192,
        secret_ref=secret_ref,
        extension_type=None,
        actor="admin:test",
    )
    registry.save_capability_snapshot(
        _snapshot(revision.revision_id, CapabilityName.CHAT_COMPLETIONS),
        actor="admin:test",
    )
    return revision


def _resolver(registry: ModelConnectionRegistry, tmp_path, *, environ=None):
    return ModelConnectionResolver(
        registry=registry,
        secret_store=EnvironmentSecretStore(tmp_path / ".env", environ=environ or {}),
        address_resolver=lambda _host, _port: ("127.0.0.1",),
        clock=lambda: NOW,
    )


def test_legacy_freetoken_import_references_secret_without_copying_it(tmp_path) -> None:
    env = {
        "LES_LLM_PROVIDER": "freetoken",
        "FREETOKEN_BASE_URL": "http://127.0.0.1:1919/v1",
        "FREETOKEN_MODEL": "qwen-35b",
        "FREETOKEN_API_KEY": "must-not-enter-sqlite",
        "FREETOKEN_CONTEXT_TOKENS": "30000",
    }
    original = dict(env)
    registry = ModelConnectionRegistry(tmp_path / "meta.db")

    imported = LegacyConnectionImporter(registry, env).import_effective(actor="migration")

    assert imported.connection_id == "legacy:freetoken"
    assert imported.secret_ref == "env:FREETOKEN_API_KEY"
    assert imported.requested_context_tokens == 30_000
    assert registry.get_role_binding(ConnectionRole.ANSWER).connection_revision_id == imported.revision_id
    assert b"must-not-enter-sqlite" not in (tmp_path / "meta.db").read_bytes()
    assert env == original


def test_legacy_import_is_idempotent_and_does_not_rebind_existing_role(tmp_path) -> None:
    env = {
        "LES_LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": "qwen3.5:9b",
    }
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    importer = LegacyConnectionImporter(registry, env)
    first = importer.import_effective(actor="migration:first")
    binding = registry.get_role_binding(ConnectionRole.ANSWER)

    env["OLLAMA_MODEL"] = "changed-after-import"
    second = importer.import_effective(actor="migration:second")

    assert second == first
    assert registry.list_revisions(first.connection_id) == (first,)
    assert registry.get_role_binding(ConnectionRole.ANSWER) == binding


@pytest.mark.parametrize(
    ("provider", "extra", "expected_id", "expected_base", "expected_model", "expected_locality"),
    (
        ("mlx", {"MLX_URL": "http://127.0.0.1:8080", "LLM_MODEL": "local"},
         "legacy:mlx", "http://127.0.0.1:8080", "local", ConnectionLocality.LOOPBACK),
        ("openai", {"OPENAI_BASE_URL": "https://api.openai.com/v1", "OPENAI_MODEL": "gpt-test", "OPENAI_API_KEY": "12345678"},
         "legacy:openai", "https://api.openai.com/v1", "gpt-test", ConnectionLocality.REMOTE),
        ("openrouter", {"OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1", "OPENROUTER_MODEL": "router/test", "OPENROUTER_API_KEY": "12345678"},
         "legacy:openrouter", "https://openrouter.ai/api/v1", "router/test", ConnectionLocality.REMOTE),
        ("ollama", {"OLLAMA_BASE_URL": "http://127.0.0.1:11434", "OLLAMA_MODEL": "qwen"},
         "legacy:ollama", "http://127.0.0.1:11434", "qwen", ConnectionLocality.LOOPBACK),
        ("lemonade", {"LEMONADE_BASE_URL": "http://127.0.0.1:13305/api/v1", "LEMONADE_MODEL": "qwen"},
         "legacy:lemonade", "http://127.0.0.1:13305/api/v1", "qwen", ConnectionLocality.LOOPBACK),
    ),
)
def test_legacy_templates_become_plain_openai_compatible_revisions(
    tmp_path,
    provider,
    extra,
    expected_id,
    expected_base,
    expected_model,
    expected_locality,
) -> None:
    registry = ModelConnectionRegistry(tmp_path / f"{provider}.db")
    imported = LegacyConnectionImporter(
        registry,
        {"LES_LLM_PROVIDER": provider, **extra},
    ).import_effective(actor="migration")

    assert imported.connection_id == expected_id
    assert imported.protocol == "openai_compatible"
    assert imported.base_url == expected_base
    assert imported.model_id == expected_model
    assert imported.locality is expected_locality


def test_remote_cloud_without_key_imports_effective_mlx_answer(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    imported = LegacyConnectionImporter(
        registry,
        {
            "LES_LLM_PROVIDER": "openai",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "OPENAI_MODEL": "gpt-test",
            "MLX_URL": "http://127.0.0.1:8080",
            "LLM_MODEL": "qwen-local",
        },
    ).import_effective(actor="migration")

    assert imported.connection_id == "legacy:mlx"
    assert registry.get_role_binding(ConnectionRole.LOCAL_FALLBACK) is None


def test_legacy_lan_hostname_is_imported_as_private_network_without_mlx_substitution(
    tmp_path,
) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    imported = LegacyConnectionImporter(
        registry,
        {
            "LES_LLM_PROVIDER": "ollama",
            "OLLAMA_BASE_URL": "http://macmini.local:11434/v1",
            "OLLAMA_MODEL": "qwen3.5:35b",
        },
        address_resolver=lambda _host, _port: ("10.195.146.98",),
    ).import_effective(actor="migration")

    assert imported.connection_id == "legacy:ollama"
    assert imported.locality is ConnectionLocality.PRIVATE_NETWORK


def test_resolver_uses_exact_answer_and_explicit_fallback_bindings(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    primary = _connection(registry, name="Primary")
    fallback = _connection(registry, name="Fallback")
    registry.bind_role(ConnectionRole.ANSWER, primary.revision_id,
                       expected_binding_revision=None, actor="admin:test")
    registry.bind_role(ConnectionRole.LOCAL_FALLBACK, fallback.revision_id,
                       expected_binding_revision=None, actor="admin:test")
    resolver = _resolver(registry, tmp_path)

    assert resolver.resolve(ConnectionRole.ANSWER).revision_id == primary.revision_id
    assert resolver.resolve_fallback(primary.revision_id).revision_id == fallback.revision_id


def test_live_acceptance_can_resolve_exact_unbound_revision(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    revision = _connection(registry, name="Acceptance target")

    resolved = _resolver(registry, tmp_path).resolve_revision(
        revision.revision_id,
        required_capabilities=frozenset({CapabilityName.CHAT_COMPLETIONS}),
    )

    assert resolved.revision_id == revision.revision_id
    assert resolved.capability_snapshot.snapshot_id == f"cap:{revision.revision_id}"


def test_resolver_never_scans_for_unbound_fallback(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    primary = _connection(registry, name="Primary")
    _connection(registry, name="Convenient but unbound")
    registry.bind_role(ConnectionRole.ANSWER, primary.revision_id,
                       expected_binding_revision=None, actor="admin:test")

    with pytest.raises(ModelConnectionResolutionError, match="ROLE_BINDING_MISSING: local_fallback"):
        _resolver(registry, tmp_path).resolve_fallback(primary.revision_id)


def test_resolver_rejects_missing_secret_before_transport(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    primary = _connection(
        registry,
        name="Secured",
        secret_ref="env:LES_MODEL_CONNECTION_C1_API_KEY",
    )
    registry.bind_role(ConnectionRole.ANSWER, primary.revision_id,
                       expected_binding_revision=None, actor="admin:test")

    with pytest.raises(ModelConnectionResolutionError, match="CONNECTION_SECRET_MISSING"):
        _resolver(registry, tmp_path).resolve(ConnectionRole.ANSWER)


def test_resolver_rejects_stale_capability_snapshot(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    primary = registry.create_connection(
        display_name="Stale",
        base_url="http://127.0.0.1:1919/v1",
        model_id="qwen3.5:9b",
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=8192,
        secret_ref=None,
        extension_type=None,
        actor="admin:test",
    )
    registry.save_capability_snapshot(
        _snapshot(
            primary.revision_id,
            CapabilityName.CHAT_COMPLETIONS,
            expires_at=NOW - timedelta(seconds=1),
        ),
        actor="admin:test",
    )
    registry.bind_role(ConnectionRole.ANSWER, primary.revision_id,
                       expected_binding_revision=None, actor="admin:test")

    with pytest.raises(ModelConnectionResolutionError, match="CAPABILITY_SNAPSHOT_STALE"):
        _resolver(registry, tmp_path).resolve(ConnectionRole.ANSWER)


def test_observed_35b_capacity_selects_extended_preset_and_requested_limit(tmp_path) -> None:
    registry = ModelConnectionRegistry(tmp_path / "meta.db")
    revision = registry.create_connection(
        display_name="35B",
        base_url="http://127.0.0.1:1919/v1",
        model_id="Qwen3.6-35B-A3B",
        locality=ConnectionLocality.LOOPBACK,
        requested_context_tokens=30_000,
        secret_ref=None,
        extension_type=None,
        actor="admin:test",
    )
    registry.save_capability_snapshot(
        _snapshot(
            revision.revision_id,
            CapabilityName.CHAT_COMPLETIONS,
            observed_context_tokens=40_000,
        ),
        actor="admin:test",
    )
    registry.bind_role(ConnectionRole.ANSWER, revision.revision_id,
                       expected_binding_revision=None, actor="admin:test")

    resolved = _resolver(registry, tmp_path).resolve(ConnectionRole.ANSWER)

    assert resolved.effective_preset.preset_id == "qwen-35b-extended"
    assert resolved.effective_preset.input_token_limit == 30_000
    assert resolved.endpoint.allowed_addresses
