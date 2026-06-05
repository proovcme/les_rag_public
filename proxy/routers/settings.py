"""Settings routes for LES Proxy."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from proxy.config import docker_control_enabled
from proxy.security import require_admin, require_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

ENV_PATH = Path(".env")


class SettingsRequest(BaseModel):
    llm_model: Optional[str] = None
    embed_model: Optional[str] = None
    mlx_url: Optional[str] = None
    speckle_enabled: Optional[bool] = None
    speckle_base_url: Optional[str] = None
    speckle_graphql_url: Optional[str] = None
    speckle_api_token: Optional[str] = None
    speckle_api_token_clear: Optional[bool] = None
    speckle_wake_timeout_sec: Optional[float] = None
    openrouter_base_url: Optional[str] = None
    openrouter_model: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openrouter_api_key_clear: Optional[bool] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_api_key_clear: Optional[bool] = None
    mail_imap_host: Optional[str] = None
    mail_imap_port: Optional[int] = None
    mail_imap_ssl: Optional[bool] = None
    mail_imap_login: Optional[str] = None
    mail_imap_password: Optional[str] = None
    mail_imap_folders: Optional[str] = None
    mail_imap_checkpoint_dir: Optional[str] = None
    mail_imap_storage_root: Optional[str] = None
    mail_attachment_ocr_enabled: Optional[bool] = None
    mail_tesseract_bin: Optional[str] = None
    mail_ocr_lang: Optional[str] = None
    mail_attachment_vlm_enabled: Optional[bool] = None
    mail_vlm_url: Optional[str] = None
    mail_vlm_model: Optional[str] = None


@router.get("")
async def get_settings(_user=Depends(require_user)):
    try:
        mlx_url = os.getenv("MLX_URL", "http://127.0.0.1:8080")
        available = []
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{mlx_url}/api/tags")
                if r.status_code == 200:
                    available = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass

        return {
            "llm_model": os.getenv("LLM_MODEL", "qwen3:14b"),
            "embed_model": os.getenv("EMBED_MODEL", "bge-m3:latest"),
            "mlx_url": mlx_url,
            "available_models": available,
            "speckle": _speckle_settings_payload(),
            "providers": _provider_settings_payload(),
            "mail": _mail_settings_payload(),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("")
async def save_settings(req: SettingsRequest, restart: bool = False, _admin=Depends(require_admin)):
    env_lines = []
    if ENV_PATH.exists():
        env_lines = ENV_PATH.read_text().splitlines()

    updates = {}
    if req.llm_model:
        updates["LLM_MODEL"] = req.llm_model
    if req.embed_model:
        updates["EMBED_MODEL"] = req.embed_model
    if req.mlx_url:
        updates["MLX_URL"] = req.mlx_url
    updates.update(_speckle_updates(req))
    updates.update(_provider_updates(req))
    updates.update(_mail_updates(req))

    for key, val in updates.items():
        if "\n" in str(val) or "\r" in str(val):
            raise HTTPException(400, f"Недопустимое значение {key}")
    if req.mlx_url and not req.mlx_url.startswith(("http://", "https://")):
        raise HTTPException(400, "MLX_URL должен начинаться с http:// или https://")
    for field, env_key in (
        (req.speckle_base_url, "SPECKLE_BASE_URL"),
        (req.speckle_graphql_url, "SPECKLE_GRAPHQL_URL"),
        (req.openrouter_base_url, "OPENROUTER_BASE_URL"),
        (req.openai_base_url, "OPENAI_BASE_URL"),
    ):
        if field and not field.startswith(("http://", "https://")):
            raise HTTPException(400, f"{env_key} должен начинаться с http:// или https://")
    if "MAIL_VLM_URL" in updates and updates["MAIL_VLM_URL"]:
        if not updates["MAIL_VLM_URL"].startswith(("http://", "https://")):
            raise HTTPException(400, "MAIL_VLM_URL должен начинаться с http:// или https://")
    if restart and not docker_control_enabled():
        raise HTTPException(403, "Docker control disabled")

    new_lines = []
    updated_keys = set()
    for line in env_lines:
        key = line.split("=")[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n")
    public_updates = _redact_sensitive_updates(updates)
    logger.info("[SETTINGS] Updated: %s", public_updates)

    for key, val in updates.items():
        os.environ[key] = val

    if restart:
        async def _restart():
            await asyncio.sleep(1)
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "compose", "restart", "proxy"],
                    cwd="/app",
                    capture_output=True,
                    timeout=30,
                )
            except Exception as e:
                logger.warning("[SETTINGS] Restart failed: %s", e)

        asyncio.create_task(_restart())

    return {"status": "saved", "updated": public_updates, "restarting": restart}


def _redact_sensitive_updates(updates: dict[str, str]) -> dict[str, str]:
    return {
        key: ("***" if key.endswith(("PASSWORD", "API_KEY", "TOKEN", "SECRET")) else value)
        for key, value in updates.items()
    }


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _speckle_default_base_url() -> str:
    return os.getenv("SPECKLE_BASE_URL", "https://speckle.example.com").rstrip("/")


def _speckle_default_graphql_url(base_url: str | None = None) -> str:
    explicit = os.getenv("SPECKLE_GRAPHQL_URL", "").strip()
    if explicit:
        return explicit
    return f"{(base_url or _speckle_default_base_url()).rstrip('/')}/graphql"


def _speckle_settings_payload() -> dict[str, object]:
    base_url = _speckle_default_base_url()
    return {
        "enabled": _env_bool("SPECKLE_ENABLED", "true"),
        "base_url": base_url,
        "graphql_url": _speckle_default_graphql_url(base_url),
        "api_token_set": bool(os.getenv("SPECKLE_API_TOKEN", "")),
        "wake_timeout_sec": float(os.getenv("SPECKLE_WAKE_TIMEOUT_SEC", "5") or "5"),
        "supported_formats": ["json", "jsonl", "dwg", "dxf", "rvt", "ifc"],
    }


def _provider_settings_payload() -> dict[str, object]:
    return {
        "openrouter": {
            "base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            "model": os.getenv("OPENROUTER_MODEL", ""),
            "api_key_set": bool(os.getenv("OPENROUTER_API_KEY", "")),
        },
        "openai_compatible": {
            "base_url": os.getenv("OPENAI_BASE_URL", ""),
            "model": os.getenv("OPENAI_MODEL", ""),
            "api_key_set": bool(os.getenv("OPENAI_API_KEY", "")),
        },
    }


def _mail_settings_payload() -> dict[str, object]:
    password_set = bool(os.getenv("MAIL_IMAP_PASSWORD", ""))
    return {
        "imap_host": os.getenv("MAIL_IMAP_HOST", ""),
        "imap_port": int(os.getenv("MAIL_IMAP_PORT", "993") or "993"),
        "imap_ssl": os.getenv("MAIL_IMAP_SSL", "true").strip().lower() in {"1", "true", "yes", "on"},
        "imap_login": os.getenv("MAIL_IMAP_LOGIN", ""),
        "imap_password_set": password_set,
        "imap_folders": os.getenv("MAIL_IMAP_FOLDERS", "INBOX"),
        "imap_checkpoint_dir": os.getenv("MAIL_IMAP_CHECKPOINT_DIR", "data/mail_imap_checkpoints"),
        "imap_storage_root": os.getenv("MAIL_IMAP_STORAGE_ROOT", "RAG_Content/MAIL/IMAP"),
        "attachment_ocr_enabled": os.getenv("MAIL_ATTACHMENT_OCR_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
        "tesseract_bin": os.getenv("MAIL_TESSERACT_BIN", "tesseract"),
        "ocr_lang": os.getenv("MAIL_OCR_LANG", "rus+eng"),
        "attachment_vlm_enabled": os.getenv("MAIL_ATTACHMENT_VLM_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        "vlm_url": os.getenv("MAIL_VLM_URL", ""),
        "vlm_model": os.getenv("MAIL_VLM_MODEL", ""),
    }


def _speckle_updates(req: SettingsRequest) -> dict[str, str]:
    fields = req.model_fields_set
    updates: dict[str, str] = {}
    if "speckle_enabled" in fields:
        updates["SPECKLE_ENABLED"] = "true" if bool(req.speckle_enabled) else "false"
    if "speckle_base_url" in fields:
        updates["SPECKLE_BASE_URL"] = str(req.speckle_base_url or "").strip().rstrip("/")
    if "speckle_graphql_url" in fields:
        updates["SPECKLE_GRAPHQL_URL"] = str(req.speckle_graphql_url or "").strip()
    if "speckle_api_token" in fields and req.speckle_api_token:
        updates["SPECKLE_API_TOKEN"] = req.speckle_api_token.strip()
    if req.speckle_api_token_clear:
        updates["SPECKLE_API_TOKEN"] = ""
    if "speckle_wake_timeout_sec" in fields:
        timeout = float(req.speckle_wake_timeout_sec or 0)
        if timeout < 0.5 or timeout > 60:
            raise HTTPException(400, "SPECKLE_WAKE_TIMEOUT_SEC должен быть от 0.5 до 60")
        updates["SPECKLE_WAKE_TIMEOUT_SEC"] = str(timeout)
    return updates


def _provider_updates(req: SettingsRequest) -> dict[str, str]:
    fields = req.model_fields_set
    updates: dict[str, str] = {}
    string_map = {
        "openrouter_base_url": "OPENROUTER_BASE_URL",
        "openrouter_model": "OPENROUTER_MODEL",
        "openai_base_url": "OPENAI_BASE_URL",
        "openai_model": "OPENAI_MODEL",
    }
    for field, env_key in string_map.items():
        if field in fields:
            updates[env_key] = str(getattr(req, field) or "").strip()

    if "openrouter_api_key" in fields and req.openrouter_api_key:
        updates["OPENROUTER_API_KEY"] = req.openrouter_api_key.strip()
    if req.openrouter_api_key_clear:
        updates["OPENROUTER_API_KEY"] = ""

    if "openai_api_key" in fields and req.openai_api_key:
        updates["OPENAI_API_KEY"] = req.openai_api_key.strip()
    if req.openai_api_key_clear:
        updates["OPENAI_API_KEY"] = ""

    return updates


def _mail_updates(req: SettingsRequest) -> dict[str, str]:
    fields = req.model_fields_set
    updates: dict[str, str] = {}
    string_map = {
        "mail_imap_host": "MAIL_IMAP_HOST",
        "mail_imap_login": "MAIL_IMAP_LOGIN",
        "mail_imap_folders": "MAIL_IMAP_FOLDERS",
        "mail_imap_checkpoint_dir": "MAIL_IMAP_CHECKPOINT_DIR",
        "mail_imap_storage_root": "MAIL_IMAP_STORAGE_ROOT",
        "mail_tesseract_bin": "MAIL_TESSERACT_BIN",
        "mail_ocr_lang": "MAIL_OCR_LANG",
        "mail_vlm_url": "MAIL_VLM_URL",
        "mail_vlm_model": "MAIL_VLM_MODEL",
    }
    for field, env_key in string_map.items():
        if field in fields:
            updates[env_key] = str(getattr(req, field) or "").strip()

    if "mail_imap_password" in fields and req.mail_imap_password:
        updates["MAIL_IMAP_PASSWORD"] = req.mail_imap_password

    if "mail_imap_port" in fields:
        port = int(req.mail_imap_port or 0)
        if port < 1 or port > 65535:
            raise HTTPException(400, "MAIL_IMAP_PORT должен быть от 1 до 65535")
        updates["MAIL_IMAP_PORT"] = str(port)

    bool_map = {
        "mail_imap_ssl": "MAIL_IMAP_SSL",
        "mail_attachment_ocr_enabled": "MAIL_ATTACHMENT_OCR_ENABLED",
        "mail_attachment_vlm_enabled": "MAIL_ATTACHMENT_VLM_ENABLED",
    }
    for field, env_key in bool_map.items():
        if field in fields:
            updates[env_key] = "true" if bool(getattr(req, field)) else "false"

    return updates
