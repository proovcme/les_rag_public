"""Ephemeral per-user LLM provider selection for the public demo.

The NiceGUI user storage keeps only non-secret metadata and an opaque reference.
Cloud API keys live in this process memory and expire automatically.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any

from nicegui import app


_SESSION_TTL_SECONDS = 12 * 60 * 60
_PROFILE_KEY = "llm_provider_profile"
_SECRET_REF_KEY = "llm_provider_secret_ref"


@dataclass(frozen=True)
class _SecretEntry:
    api_key: str
    expires_at: float


class EphemeralProviderVault:
    """Small in-memory vault; intentionally not persisted across restarts."""

    def __init__(self, ttl_seconds: int = _SESSION_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, _SecretEntry] = {}
        self._lock = RLock()

    def put(self, api_key: str, *, now: float | None = None) -> str:
        created_at = time.time() if now is None else now
        reference = secrets.token_urlsafe(32)
        with self._lock:
            self._purge_locked(created_at)
            self._entries[reference] = _SecretEntry(
                api_key=api_key,
                expires_at=created_at + self.ttl_seconds,
            )
        return reference

    def get(self, reference: str, *, now: float | None = None) -> str | None:
        checked_at = time.time() if now is None else now
        with self._lock:
            self._purge_locked(checked_at)
            entry = self._entries.get(reference)
            if entry is None:
                return None
            return entry.api_key

    def discard(self, reference: str) -> None:
        with self._lock:
            self._entries.pop(reference, None)

    def _purge_locked(self, now: float) -> None:
        expired = [ref for ref, entry in self._entries.items() if entry.expires_at <= now]
        for ref in expired:
            self._entries.pop(ref, None)


_VAULT = EphemeralProviderVault()


def _storage() -> Any:
    return app.storage.user


def clear_provider_config() -> None:
    """Remove the current provider selection and its in-memory secret."""
    storage = _storage()
    reference = str(storage.get(_SECRET_REF_KEY) or "")
    if reference:
        _VAULT.discard(reference)
    storage.pop(_PROFILE_KEY, None)
    storage.pop(_SECRET_REF_KEY, None)


def save_provider_config(provider: str, model: str = "", api_key: str = "") -> dict[str, str]:
    """Validate and save one session-scoped provider selection."""
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip()
    normalized_key = str(api_key or "").strip()

    if normalized_provider not in {"mlx", "openrouter", "openai"}:
        raise ValueError("Выберите поддерживаемого провайдера")
    if normalized_provider != "mlx":
        if not normalized_model:
            raise ValueError("Укажите модель")
        if len(normalized_model) > 200:
            raise ValueError("Название модели слишком длинное")
        if len(normalized_key) < 8:
            raise ValueError("Введите API-ключ провайдера")
        if len(normalized_key) > 4096:
            raise ValueError("API-ключ слишком длинный")

    clear_provider_config()
    profile = {
        "provider": normalized_provider,
        "model": normalized_model if normalized_provider != "mlx" else "",
    }
    storage = _storage()
    storage[_PROFILE_KEY] = profile
    if normalized_provider != "mlx":
        storage[_SECRET_REF_KEY] = _VAULT.put(normalized_key)
    return profile


def provider_request_config() -> dict[str, str] | None:
    """Return a proxy request payload, resolving the secret only in server memory."""
    storage = _storage()
    profile = storage.get(_PROFILE_KEY)
    if not isinstance(profile, dict):
        return None
    provider = str(profile.get("provider") or "").strip().lower()
    if provider == "mlx":
        return {"provider": "mlx"}
    if provider not in {"openrouter", "openai"}:
        return None
    reference = str(storage.get(_SECRET_REF_KEY) or "")
    api_key = _VAULT.get(reference) if reference else None
    if not api_key:
        return None
    return {
        "provider": provider,
        "model": str(profile.get("model") or "").strip(),
        "api_key": api_key,
    }


def provider_setup_complete() -> bool:
    return provider_request_config() is not None


def provider_public_profile() -> dict[str, str]:
    """Return non-secret metadata suitable for rendering."""
    profile = _storage().get(_PROFILE_KEY)
    return dict(profile) if isinstance(profile, dict) else {}
