"""The effective evidence character ceiling is visible and editable in the GUI registry."""
import pytest

from proxy.services import runtime_config_registry_service as registry


@pytest.fixture
def isolated_factor_registry(tmp_path, monkeypatch):
    path = tmp_path / "настройки с пробелом" / "diagnostic.env"
    monkeypatch.setattr(registry, "env_path", lambda: path)
    monkeypatch.setattr(registry, "effective_model_execution_diagnostics", lambda: {})
    # Register an undo even if the key was initially absent: update_factors
    # writes os.environ, not monkeypatch's proxy.
    monkeypatch.setenv("RAG_MODEL_CONTEXT_CHARS", "")
    monkeypatch.delenv("RAG_MODEL_CONTEXT_CHARS")
    registry.declared_env_defaults.cache_clear()
    registry.declared_env_keys.cache_clear()
    yield path
    registry.declared_env_defaults.cache_clear()
    registry.declared_env_keys.cache_clear()


def test_default_evidence_ceiling_is_in_the_visible_registry(isolated_factor_registry):
    rows = {row["key"]: row for row in registry.registry_snapshot()["factors"]}
    factor = rows["RAG_MODEL_CONTEXT_CHARS"]
    assert factor["effective_value"] == factor["declared_default"] == "120000"
    assert factor["source"] == "default"
    assert factor["mutable"] and not factor["secret"]
    assert factor["restart_required"] is False


@pytest.mark.parametrize("value,expected", [("150000", 150000)])
def test_gui_saved_ceiling_reaches_the_actual_next_request_budget(isolated_factor_registry, value, expected):
    from proxy.routers.chat import _local_context_budget

    saved = registry.update_factors({"RAG_MODEL_CONTEXT_CHARS": value})
    assert saved["updated"] == [{"key": "RAG_MODEL_CONTEXT_CHARS", "value": value,
                                 "restart_required": False}]
    assert _local_context_budget(local_big=False, big_context=False,
                                 provider="openai_compatible")["context_chars_limit"] == expected
    assert f'RAG_MODEL_CONTEXT_CHARS="{value}"' in isolated_factor_registry.read_text(encoding="utf-8")


@pytest.mark.parametrize("value", ["0", "-1", "bad", "1.2", "", "１２"])
def test_invalid_evidence_ceiling_is_rejected_before_write(isolated_factor_registry, value):
    with pytest.raises(registry.RuntimeConfigRegistryError, match="INVALID_VALUE"):
        registry.update_factors({"RAG_MODEL_CONTEXT_CHARS": value})
    assert not isolated_factor_registry.exists()
