import os

import pytest

from proxy.services import runtime_config_registry_service as registry


@pytest.fixture()
def isolated_registry(monkeypatch, tmp_path):
    path = tmp_path / "config with spaces" / ".env"
    monkeypatch.setenv("LES_ENV_PATH", str(path))
    monkeypatch.setattr(registry, "env_path", lambda: path)
    monkeypatch.setattr(
        registry,
        "declared_env_keys",
        lambda: frozenset(
            {
                "RAG_TOP_K",
                "LES_EXTERNAL_ALLOW_ANY",
                "OPENAI_API_KEY",
                "LES_RUNTIME_HOME",
                "UNICODE_PATH_SETTING",
            }
        ),
    )
    monkeypatch.chdir(tmp_path)
    return path


def test_registry_exposes_every_factor_but_never_secret_value(isolated_registry, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    snapshot = registry.registry_snapshot()
    by_key = {item["key"]: item for item in snapshot["factors"]}

    assert by_key["OPENAI_API_KEY"]["set"] is True
    assert by_key["OPENAI_API_KEY"]["effective_value"] is None
    assert "super-secret" not in str(snapshot)
    assert by_key["LES_EXTERNAL_ALLOW_ANY"]["danger_label"] == "Danger"
    assert by_key["LES_RUNTIME_HOME"]["mutable"] is False
    assert snapshot["unregistered_runtime_factors"] == []
    assert {row["id"] for row in snapshot["effective_factors"]} >= {
        "model_preset",
        "context_input_tokens",
        "generation_reserve",
        "reasoning",
    }


def test_registry_reports_literal_default_as_effective_value(monkeypatch):
    monkeypatch.delenv("RAG_CHAT_TOP_K", raising=False)
    factor = registry._factor("RAG_CHAT_TOP_K", {})
    assert factor["source"] == "default"
    assert factor["effective_value"] == "64"
    assert factor["declared_default"] == "64"


def test_index_recovery_limits_are_visible_as_danger_factors(monkeypatch):
    monkeypatch.delenv("RAG_BOUNDED_REPAIR_MAX_FILES", raising=False)

    factor = registry._factor("RAG_BOUNDED_REPAIR_MAX_FILES", {})

    assert factor["effective_value"] == "50"
    assert factor["danger_label"] == "Danger"
    assert factor["restart_required"] is True


def test_canonical_route_mode_is_visible_danger_and_requires_restart(monkeypatch):
    monkeypatch.delenv("LES_CANONICAL_AGENT_ROUTE_MODE", raising=False)

    factor = registry._factor("LES_CANONICAL_AGENT_ROUTE_MODE", {})

    assert factor["effective_value"] == "shadow"
    assert factor["danger_label"] == "Danger"
    assert factor["restart_required"] is True


def test_demo_provider_override_is_visible_danger_and_requires_restart(monkeypatch):
    monkeypatch.delenv("LES_DEMO_PROVIDER_OVERRIDE_ENABLED", raising=False)

    factor = registry._factor("LES_DEMO_PROVIDER_OVERRIDE_ENABLED", {})

    assert factor["effective_value"] == "false"
    assert factor["danger_label"] == "Danger"
    assert factor["restart_required"] is True


def test_freetoken_runtime_defaults_are_visible_and_require_restart(monkeypatch):
    registry.declared_env_defaults.cache_clear()
    monkeypatch.delenv("FREETOKEN_BASE_URL", raising=False)

    factor = registry._factor("FREETOKEN_BASE_URL", {})

    assert factor["effective_value"] == "http://127.0.0.1:1919/v1"
    assert factor["source"] == "default"
    assert factor["restart_required"] is True


def test_qdrant_url_is_a_named_editable_runtime_connection(monkeypatch):
    registry.declared_env_defaults.cache_clear()
    monkeypatch.delenv("QDRANT_URL", raising=False)

    factor = registry._factor("QDRANT_URL", {})

    assert factor["effective_value"] == "http://127.0.0.1:6333"
    assert factor["label"] == "Адрес Qdrant"
    assert factor["help_text"] == "Хранилище индекса: локальная машина, LAN или VPS."
    assert factor["mutable"] is True
    assert factor["restart_required"] is True


def test_assigned_model_timeout_is_named_and_restart_bound(monkeypatch):
    registry.declared_env_defaults.cache_clear()
    monkeypatch.delenv("LES_MODEL_CONNECTION_TIMEOUT_SEC", raising=False)

    factor = registry._factor("LES_MODEL_CONNECTION_TIMEOUT_SEC", {})

    assert factor["effective_value"] == "300.0"
    assert factor["label"] == "Таймаут ответа модели, сек"
    assert factor["mutable"] is True
    assert factor["restart_required"] is True


def test_context_factors_are_registered_with_effective_source() -> None:
    rows = registry.runtime_factor_rows(
        {
            "model_preset": {
                "requested": "qwen3.5:9b",
                "effective": "qwen-9b-restrictive",
                "source": "workflow_invariants > factory_preset",
                "restart_required": False,
            },
            "context_input_tokens": {
                "requested": 8253,
                "effective": 6000,
                "source": "observed_backend_capacity > factory_preset",
                "restart_required": False,
            },
            "generation_reserve": {
                "requested": None,
                "effective": 1200,
                "source": "factory_preset",
                "restart_required": False,
            },
            "safety_reserve": {
                "requested": None,
                "effective": 512,
                "source": "workflow_invariants",
                "restart_required": False,
            },
            "reasoning": {
                "requested": False,
                "effective": False,
                "source": "workflow_invariants",
                "restart_required": False,
            },
        }
    )

    assert {row["id"] for row in rows} == {
        "model_preset",
        "context_input_tokens",
        "generation_reserve",
        "safety_reserve",
        "reasoning",
    }
    assert all("effective" in row and "source" in row for row in rows)
    assert all(row["mutable"] is False for row in rows)
    assert next(row for row in rows if row["id"] == "model_preset")["operator_action"] == "profile_clone"


def test_registry_requires_exact_danger_confirmation(isolated_registry):
    with pytest.raises(registry.RuntimeConfigRegistryError, match="DANGER_CONFIRMATION_REQUIRED"):
        registry.update_factors({"LES_EXTERNAL_ALLOW_ANY": "1"})

    result = registry.update_factors(
        {"LES_EXTERNAL_ALLOW_ANY": "1"},
        danger_confirmations={"LES_EXTERNAL_ALLOW_ANY"},
    )
    assert result["updated"][0]["key"] == "LES_EXTERNAL_ALLOW_ANY"
    assert registry._dotenv_values(isolated_registry)["LES_EXTERNAL_ALLOW_ANY"] == "1"


def test_registry_roundtrip_handles_unicode_spaces_and_quotes(isolated_registry):
    value = 'C:\\Проекты\\ИЦ "Рабочая документация"'
    result = registry.update_factors({"UNICODE_PATH_SETTING": value})

    assert result["status"] == "saved"
    assert registry._dotenv_values(isolated_registry)["UNICODE_PATH_SETTING"] == value


def test_registry_rejects_read_only_unknown_and_multiline(isolated_registry):
    with pytest.raises(registry.RuntimeConfigRegistryError, match="READ_ONLY"):
        registry.update_factors({"LES_RUNTIME_HOME": "C:\\wrong"})
    with pytest.raises(registry.RuntimeConfigRegistryError, match="UNREGISTERED"):
        registry.update_factors({"NOT_IN_CODE": "1"})
    with pytest.raises(registry.RuntimeConfigRegistryError, match="INVALID_VALUE"):
        registry.update_factors({"RAG_TOP_K": "1\nEVIL=1"})


def test_registry_rejects_invalid_qdrant_url(isolated_registry, monkeypatch):
    declared = registry.declared_env_keys()
    monkeypatch.setattr(
        registry,
        "declared_env_keys",
        lambda: frozenset({*declared, "QDRANT_URL"}),
    )
    with pytest.raises(registry.RuntimeConfigRegistryError, match="INVALID_VALUE"):
        registry.update_factors({"QDRANT_URL": "qdrant.local:6333"})


def test_gui_and_api_expose_registry_and_advanced_rag_controls():
    from pathlib import Path

    diag = Path("sovushka/pages/diag.py").read_text(encoding="utf-8")
    app = Path("proxy/app.py").read_text(encoding="utf-8")
    assert "Все параметры среды" in diag
    assert "Danger" in diag
    assert "/api/settings/runtime-registry" in diag
    assert "Фактический контекст модели" in diag
    assert "Запрошено:" in diag and "действует:" in diag
    assert "Только чтение" in diag
    assert 'factor.get("label")' in diag
    assert 'factor.get("help_text")' in diag
    assert "RAPTOR и ColBERT" in diag
    assert "/api/rag/advanced" in diag
    assert "include_router(rag_advanced_router)" in app
