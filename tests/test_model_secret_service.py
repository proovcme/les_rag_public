from __future__ import annotations

import pytest

from proxy.services.model_secret_service import (
    EnvironmentSecretStore,
    ModelSecretError,
)


def test_secret_value_never_appears_in_repr_receipt_or_file_metadata(tmp_path) -> None:
    env_file = tmp_path / ".env"
    environ: dict[str, str] = {}
    store = EnvironmentSecretStore(env_file, environ=environ)
    ref = "env:LES_MODEL_CONNECTION_C1_API_KEY"

    receipt = store.replace(ref, "top-secret", actor="admin:test")
    value = store.resolve(ref)

    assert value is not None
    assert value.reveal() == "top-secret"
    assert "top-secret" not in repr(value)
    assert "top-secret" not in repr(receipt)
    assert receipt.status == "configured"
    assert receipt.actor == "admin:test"
    assert store.status(ref) == "configured"
    assert environ["LES_MODEL_CONNECTION_C1_API_KEY"] == "top-secret"


def test_replace_is_atomic_and_preserves_unrelated_environment_lines(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KEEP=value\nLES_MODEL_CONNECTION_C1_API_KEY=old\n", encoding="utf-8")
    store = EnvironmentSecretStore(env_file, environ={})

    store.replace(
        "env:LES_MODEL_CONNECTION_C1_API_KEY",
        "new-value",
        actor="admin:test",
    )

    assert env_file.read_text(encoding="utf-8") == (
        "KEEP=value\nLES_MODEL_CONNECTION_C1_API_KEY=new-value\n"
    )
    assert not tuple(tmp_path.glob(".env.*.tmp"))


@pytest.mark.parametrize(
    "ref",
    (
        "env:PATH",
        "env:LES_MODEL_CONNECTION_C1_PASSWORD",
        "file:C:/secret",
        "env:LES_MODEL_CONNECTION_bad_API_KEY",
    ),
)
def test_arbitrary_secret_references_are_rejected(tmp_path, ref) -> None:
    store = EnvironmentSecretStore(tmp_path / ".env", environ={})
    with pytest.raises(ModelSecretError, match="SECRET_REF_NOT_ALLOWED"):
        store.status(ref)


@pytest.mark.parametrize("value", ("", "line1\nline2", "line1\rline2"))
def test_empty_or_multiline_secret_is_rejected_without_write(tmp_path, value) -> None:
    env_file = tmp_path / ".env"
    store = EnvironmentSecretStore(env_file, environ={})
    with pytest.raises(ModelSecretError, match="SECRET_VALUE_INVALID"):
        store.replace(
            "env:LES_MODEL_CONNECTION_C1_API_KEY",
            value,
            actor="admin:test",
        )
    assert not env_file.exists()


def test_migration_secret_refs_are_supported_without_copying_values(tmp_path) -> None:
    environ = {"FREETOKEN_API_KEY": "legacy-secret"}
    store = EnvironmentSecretStore(tmp_path / ".env", environ=environ)

    resolved = store.resolve("env:FREETOKEN_API_KEY")

    assert resolved is not None
    assert resolved.reveal() == "legacy-secret"
    assert not (tmp_path / ".env").exists()


def test_missing_and_not_required_secret_states_are_distinct(tmp_path) -> None:
    store = EnvironmentSecretStore(tmp_path / ".env", environ={})

    assert store.status(None) == "not_required"
    assert store.status("env:OPENAI_API_KEY") == "missing"
    with pytest.raises(ModelSecretError, match="SECRET_MISSING"):
        store.resolve("env:OPENAI_API_KEY")
