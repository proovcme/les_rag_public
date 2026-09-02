from proxy import app
from backend import qdrant_adapter


def test_catalog_self_heal_can_be_disabled_for_isolated_runtime(monkeypatch):
    monkeypatch.setenv("LES_RAG_CATALOG_SELF_HEAL", "false")
    assert app.catalog_self_heal_enabled() is False

    monkeypatch.setenv("LES_RAG_CATALOG_SELF_HEAL", "true")
    assert app.catalog_self_heal_enabled() is True


def test_model_warmup_can_be_disabled_for_bounded_acceptance(monkeypatch):
    monkeypatch.setenv("LES_STARTUP_MODEL_WARMUP", "false")
    assert app.startup_model_warmup_enabled() is False

    monkeypatch.setenv("LES_STARTUP_MODEL_WARMUP", "true")
    assert app.startup_model_warmup_enabled() is True


def test_background_mutations_can_be_disabled_for_bounded_acceptance(monkeypatch):
    monkeypatch.setenv("LES_STARTUP_BACKGROUND_MUTATIONS", "false")
    assert app.startup_background_mutations_enabled() is False

    monkeypatch.setenv("LES_STARTUP_BACKGROUND_MUTATIONS", "true")
    assert app.startup_background_mutations_enabled() is True


def test_payload_index_ensure_can_be_disabled_for_read_only_acceptance(monkeypatch):
    monkeypatch.setenv("LES_RAG_PAYLOAD_INDEX_ENSURE", "false")
    assert qdrant_adapter.payload_index_ensure_enabled() is False

    monkeypatch.setenv("LES_RAG_PAYLOAD_INDEX_ENSURE", "true")
    assert qdrant_adapter.payload_index_ensure_enabled() is True
