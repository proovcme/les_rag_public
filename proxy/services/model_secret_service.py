"""Write-only environment-backed secret references for model connections."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile
from typing import MutableMapping


class ModelSecretError(ValueError):
    """A secret reference or value violates the storage contract."""


_CONNECTION_REF = re.compile(r"^LES_MODEL_CONNECTION_[A-Z0-9_]+_API_KEY$")
_MIGRATION_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_KEY",
        "LEMONADE_API_KEY",
        "FREETOKEN_API_KEY",
    }
)


@dataclass(frozen=True)
class SecretValue:
    _value: str = field(repr=False)

    def reveal(self) -> str:
        return self._value


@dataclass(frozen=True)
class SecretWriteReceipt:
    secret_ref: str
    status: str
    actor: str
    updated_at: str


def _secret_key(secret_ref: str) -> str:
    normalized = str(secret_ref or "").strip()
    if not normalized.startswith("env:"):
        raise ModelSecretError("SECRET_REF_NOT_ALLOWED")
    key = normalized.removeprefix("env:")
    if key not in _MIGRATION_KEYS and _CONNECTION_REF.fullmatch(key) is None:
        raise ModelSecretError("SECRET_REF_NOT_ALLOWED")
    return key


class EnvironmentSecretStore:
    def __init__(
        self,
        env_path: str | Path,
        *,
        environ: MutableMapping[str, str] | None = None,
    ):
        self.env_path = Path(env_path)
        self.environ = os.environ if environ is None else environ

    def _file_value(self, key: str) -> str:
        if not self.env_path.exists():
            return ""
        for line in self.env_path.read_text(encoding="utf-8").splitlines():
            raw_key, separator, raw_value = line.partition("=")
            if separator and raw_key.strip() == key:
                return raw_value.strip()
        return ""

    def status(self, secret_ref: str | None) -> str:
        if secret_ref is None:
            return "not_required"
        key = _secret_key(secret_ref)
        value = str(self.environ.get(key) or "").strip() or self._file_value(key)
        return "configured" if value else "missing"

    def resolve(self, secret_ref: str | None) -> SecretValue | None:
        if secret_ref is None:
            return None
        key = _secret_key(secret_ref)
        value = str(self.environ.get(key) or "").strip() or self._file_value(key)
        if not value:
            raise ModelSecretError("SECRET_MISSING")
        return SecretValue(value)

    def replace(self, secret_ref: str, value: str, *, actor: str) -> SecretWriteReceipt:
        key = _secret_key(secret_ref)
        secret = str(value or "")
        if not secret.strip() or "\n" in secret or "\r" in secret or len(secret) > 4096:
            raise ModelSecretError("SECRET_VALUE_INVALID")
        normalized_actor = str(actor or "").strip()
        if not normalized_actor:
            raise ModelSecretError("SECRET_ACTOR_REQUIRED")

        lines = self.env_path.read_text(encoding="utf-8").splitlines() if self.env_path.exists() else []
        output: list[str] = []
        replaced = False
        for line in lines:
            raw_key, separator, _raw_value = line.partition("=")
            if separator and raw_key.strip() == key:
                if not replaced:
                    output.append(f"{key}={secret}")
                    replaced = True
                continue
            output.append(line)
        if not replaced:
            output.append(f"{key}={secret}")

        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"{self.env_path.name}.",
            suffix=".tmp",
            dir=self.env_path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(output) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.env_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        self.environ[key] = secret
        return SecretWriteReceipt(
            secret_ref=f"env:{key}",
            status="configured",
            actor=normalized_actor,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
