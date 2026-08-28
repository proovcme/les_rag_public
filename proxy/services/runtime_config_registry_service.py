"""GUI-first inventory and guarded mutation of LES runtime factors."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from proxy.services.llm_transport_profile_service import (
    effective_model_execution_diagnostics,
)


REGISTRY_SCHEMA = "les.runtime-config-registry.v1"
_EFFECTIVE_FACTOR_LABELS = {
    "model_preset": "Пресет модели",
    "context_input_tokens": "Лимит входного контекста",
    "generation_reserve": "Резерв ответа",
    "safety_reserve": "Страховой резерв",
    "reasoning": "Рассуждение модели",
}
_ROOT = Path(__file__).resolve().parents[2]
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_SECRET_MARKERS = (
    "PASSWORD", "SECRET", "TOKEN", "API_KEY", "PRIVATE_KEY", "CREDENTIAL",
    "JWT", "COOKIE", "SESSION", "_KEY",
)
_DANGER_KEYS = {
    "LES_CANONICAL_ACCEPTANCE_STATE_ROOT",
    "LES_CANONICAL_AGENT_ROUTE_MODE",
    "LES_DEMO_PROVIDER_OVERRIDE_ENABLED",
    "LES_ALLOW_RUNTIME_SIDECAR_WRITE",
    "LES_EXTERNAL_ALLOW_ANY",
    "DOCKER_CONTROL_ENABLED",
    "LES_CLOUD_CONSENT",
    "TRUSTED_NETWORKS",
    "TRUSTED_NETWORK_ROLE",
    "VALIDATOR_BACKEND",
    "RAG_PARSE_MAX_ATTEMPTS",
    "RAG_BOUNDED_REPAIR_MAX_FILES",
}
_READ_ONLY_KEYS = {
    "LES_CANONICAL_ACCEPTANCE_STATE_ROOT",
    "LES_RUNTIME_HOME", "LES_REPO_ROOT", "LES_ENV_PATH", "LOCALAPPDATA",
    "USERPROFILE", "PATH", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT",
}
_RESTART_PREFIXES = (
    "RAG_", "EMBED_", "QDRANT_", "LES_RUNTIME_", "LES_REPO_", "LES_ENV_",
    "SOVUSHKA_", "PROXY_", "MLX_", "OLLAMA_", "LEMONADE_", "FREETOKEN_",
)
_RESTART_KEYS = {
    "LES_CANONICAL_ACCEPTANCE_STATE_ROOT",
    "LES_CANONICAL_AGENT_ROUTE_MODE",
    "LES_DEMO_PROVIDER_OVERRIDE_ENABLED",
}
_SKIP_PARTS = {
    ".git", ".venv", ".test-tmp", "data", "logs", "storage", "dist",
    "docs", "local_private_archive", "node_modules", "target", "build",
}


class RuntimeConfigRegistryError(ValueError):
    pass


def env_path() -> Path:
    return Path(os.getenv("LES_ENV_PATH", ".env")).expanduser()


def _is_secret(key: str) -> bool:
    # FreeToken is a product/provider name, not a credential marker.
    scan_key = key.removeprefix("FREETOKEN_")
    return any(marker in scan_key for marker in _SECRET_MARKERS)


def _is_danger(key: str) -> bool:
    return key in _DANGER_KEYS or any(
        marker in key for marker in ("DELETE", "WIPE", "RESET", "ALLOW_ANY", "DISABLE_GUARD")
    )


def _literal_env_key(call: ast.Call) -> str:
    if not call.args:
        return ""
    arg = call.args[0]
    return str(arg.value) if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else ""


@lru_cache(maxsize=1)
def declared_env_defaults() -> dict[str, str]:
    defaults: dict[str, str] = {}
    source_paths: list[Path] = []
    for root, directories, files in os.walk(_ROOT):
        directories[:] = [
            name for name in directories
            if name not in _SKIP_PARTS and not name.startswith(".")
        ]
        source_paths.extend(Path(root) / name for name in files if name.endswith(".py"))
    for path in source_paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_getenv = isinstance(func, ast.Attribute) and func.attr == "getenv"
            is_environ_get = (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ"
            )
            if is_getenv or is_environ_get:
                key = _literal_env_key(node)
                if _KEY_RE.fullmatch(key):
                    default = ""
                    if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                        raw_default = node.args[1].value
                        if raw_default is not None and isinstance(raw_default, (str, int, float, bool)):
                            default = str(raw_default)
                    if key not in defaults or (not defaults[key] and default):
                        defaults[key] = default
    return defaults


@lru_cache(maxsize=1)
def declared_env_keys() -> frozenset[str]:
    return frozenset(declared_env_defaults())


def _dotenv_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    from dotenv import dotenv_values

    parsed = dotenv_values(path, encoding="utf-8-sig")
    return {
        str(key): str(value or "")
        for key, value in parsed.items()
        if key and _KEY_RE.fullmatch(str(key))
    }


def _serialize_value(value: str) -> str:
    """dotenv-compatible quoted UTF-8; protects spaces, #, quotes and backslashes."""
    return json.dumps(value, ensure_ascii=False)


def _factor(key: str, dotenv: dict[str, str]) -> dict[str, Any]:
    secret = _is_secret(key)
    in_process = key in os.environ
    in_dotenv = key in dotenv
    declared_default = declared_env_defaults().get(key, "")
    value = os.environ.get(key, dotenv.get(key, declared_default))
    source = "process" if in_process else ("dotenv" if in_dotenv else "default")
    read_only = key in _READ_ONLY_KEYS
    danger = _is_danger(key)
    return {
        "key": key,
        "category": key.split("_", 1)[0].lower(),
        "source": source,
        "declared_default": None if secret else declared_default,
        "set": bool(value),
        "effective_value": None if secret else value,
        "display_value": "••••••" if secret and value else ("не задан" if secret else value),
        "secret": secret,
        "danger": danger,
        "danger_label": "Danger" if danger else "",
        "mutable": not read_only,
        "restart_required": key in _RESTART_KEYS or key.startswith(_RESTART_PREFIXES),
        "registry_state": "explicit" if key in _DANGER_KEYS or key in _READ_ONLY_KEYS else "auto",
    }


def runtime_factor_rows(
    effective_payload: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Normalize read-only requested/effective model facts for API and GUI."""
    payload = effective_payload if isinstance(effective_payload, Mapping) else {}
    rows: list[dict[str, Any]] = []
    for factor_id, label in _EFFECTIVE_FACTOR_LABELS.items():
        raw = payload.get(factor_id)
        values = raw if isinstance(raw, Mapping) else {}
        rows.append(
            {
                "id": factor_id,
                "label": label,
                "requested": values.get("requested"),
                "effective": values.get("effective"),
                "source": str(values.get("source") or "unavailable"),
                "restart_required": bool(values.get("restart_required", False)),
                "mutable": False,
                "operator_action": (
                    "profile_clone"
                    if factor_id in {"model_preset", "context_input_tokens"}
                    else "read_only"
                ),
            }
        )
    return rows


def registry_snapshot() -> dict[str, Any]:
    dotenv = _dotenv_values(env_path())
    keys = sorted(set(declared_env_keys()) | set(dotenv) | {
        key for key in os.environ if key.startswith(("LES_", "RAG_", "EMBED_", "QDRANT_", "MAIL_"))
    })
    factors = [_factor(key, dotenv) for key in keys]
    effective_factors = runtime_factor_rows(effective_model_execution_diagnostics())
    return {
        "schema": REGISTRY_SCHEMA,
        "factors": factors,
        "effective_factors": effective_factors,
        "counts": {
            "total": len(factors),
            "danger": sum(bool(item["danger"]) for item in factors),
            "secrets": sum(bool(item["secret"]) for item in factors),
            "read_only": sum(not bool(item["mutable"]) for item in factors),
            "unregistered": 0,
            "effective": len(effective_factors),
        },
        "unregistered_runtime_factors": [],
    }


def _backup_env(path: Path) -> Path | None:
    if not path.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path("storage/recovery/runtime-config") / f"env-{stamp}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    return backup


def _write_dotenv(path: Path, updates: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else []
    output: list[str] = []
    seen: set[str] = set()
    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            output.append(f"{key}={_serialize_value(updates[key])}")
            seen.add(key)
        else:
            output.append(line)
    output.extend(
        f"{key}={_serialize_value(value)}"
        for key, value in updates.items() if key not in seen
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write("\n".join(output) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def update_factors(
    updates: dict[str, Any], *, danger_confirmations: set[str] | None = None
) -> dict[str, Any]:
    danger_confirmations = danger_confirmations or set()
    declared = set(declared_env_keys()) | set(_dotenv_values(env_path()))
    normalized: dict[str, str] = {}
    for key, raw_value in updates.items():
        if not _KEY_RE.fullmatch(key) or key not in declared:
            raise RuntimeConfigRegistryError(f"UNREGISTERED_RUNTIME_FACTOR: {key}")
        if key in _READ_ONLY_KEYS:
            raise RuntimeConfigRegistryError(f"RUNTIME_FACTOR_READ_ONLY: {key}")
        if _is_danger(key) and key not in danger_confirmations:
            raise RuntimeConfigRegistryError(f"DANGER_CONFIRMATION_REQUIRED: {key}")
        value = str(raw_value)
        if "\n" in value or "\r" in value or "\x00" in value:
            raise RuntimeConfigRegistryError(f"RUNTIME_FACTOR_INVALID_VALUE: {key}")
        normalized[key] = value
    backup = _backup_env(env_path())
    _write_dotenv(env_path(), normalized)
    for key, value in normalized.items():
        os.environ[key] = value
    return {
        "status": "saved",
        "updated": [
            {
                "key": key,
                "value": "***" if _is_secret(key) else value,
                "restart_required": key.startswith(_RESTART_PREFIXES),
            }
            for key, value in sorted(normalized.items())
        ],
        "rollback_available": backup is not None,
        "rollback_path": str(backup) if backup else "",
        "registry": registry_snapshot(),
    }
