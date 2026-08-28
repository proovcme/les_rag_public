"""Regression tests for the public demo's per-session provider chooser."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from proxy.routers import chat
from sovushka import provider_session


def test_provider_page_claims_full_nicegui_width() -> None:
    source = (provider_session.__file__.replace("provider_session.py", "provider_setup.py"))
    text = open(source, encoding="utf-8").read()

    assert ".nicegui-content {" in text
    assert "width:100% !important; min-width:100% !important;" in text
    assert "max-width:none !important;" in text


def test_ephemeral_vault_expires_secrets() -> None:
    vault = provider_session.EphemeralProviderVault(ttl_seconds=10)
    reference = vault.put("sk-private", now=100.0)

    assert vault.get(reference, now=109.0) == "sk-private"
    assert vault.get(reference, now=110.0) is None


def test_cloud_profile_keeps_plaintext_key_out_of_user_storage(monkeypatch) -> None:
    storage: dict = {}
    monkeypatch.setattr(provider_session, "_storage", lambda: storage)
    monkeypatch.setattr(provider_session, "_VAULT", provider_session.EphemeralProviderVault())

    provider_session.save_provider_config("openrouter", "openai/gpt-5.4", "sk-private-key")

    assert "sk-private-key" not in repr(storage)
    assert provider_session.provider_public_profile() == {
        "provider": "openrouter",
        "model": "openai/gpt-5.4",
    }
    assert provider_session.provider_request_config() == {
        "provider": "openrouter",
        "model": "openai/gpt-5.4",
        "api_key": "sk-private-key",
    }


def test_local_profile_needs_no_secret(monkeypatch) -> None:
    storage: dict = {}
    monkeypatch.setattr(provider_session, "_storage", lambda: storage)
    monkeypatch.setattr(provider_session, "_VAULT", provider_session.EphemeralProviderVault())

    provider_session.save_provider_config("mlx")

    assert provider_session.provider_request_config() == {"provider": "mlx"}
    assert "llm_provider_secret_ref" not in storage


def test_chat_provider_config_rejects_incomplete_cloud_choice() -> None:
    with pytest.raises(ValidationError):
        chat.ChatProviderConfig(provider="openai", model="gpt-5.4", api_key="short")
    with pytest.raises(ValidationError):
        chat.ChatProviderConfig(provider="unknown", model="x", api_key="sk-private-key")


@pytest.mark.asyncio
async def test_request_provider_is_context_scoped_and_secret_is_redacted(monkeypatch) -> None:
    monkeypatch.setenv("LES_DEMO_PROVIDER_OVERRIDE_ENABLED", "true")
    server_runtime = chat.LlmRuntime("mlx", "http://local", "http://local/v1/chat/completions", "local", "", True)
    monkeypatch.setattr(chat, "_mlx_runtime", lambda: server_runtime)

    observed = {}

    async def fake_run(req, token_sink=None):
        observed["runtime"] = chat._llm_runtime()
        observed["consent"] = chat._env_bool("LES_CLOUD_CONSENT", False)
        return {"answer": "ok"}

    monkeypatch.setattr(chat, "_run_chat", fake_run)
    request = chat.ChatRequest(
        question="test",
        provider_config={
            "provider": "openrouter",
            "model": "openai/gpt-5.4",
            "api_key": "sk-private-key",
        },
    )

    assert await chat._run_chat_with_provider(request) == {"answer": "ok"}
    assert observed["runtime"].provider == "openrouter"
    assert observed["runtime"].api_key == "sk-private-key"
    assert observed["consent"] is True
    assert chat._REQUEST_LLM_RUNTIME.get() is None
    assert "sk-private-key" not in repr(chat._idempotency_payload(request))
