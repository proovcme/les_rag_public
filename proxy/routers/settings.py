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


@router.get("")
async def get_settings(_user=Depends(require_user)):
    try:
        mlx_url = os.getenv("MLX_URL", "http://host.docker.internal:8080")
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

    for key, val in updates.items():
        if "\n" in val or "\r" in val:
            raise HTTPException(400, f"Недопустимое значение {key}")
    if req.mlx_url and not req.mlx_url.startswith(("http://", "https://")):
        raise HTTPException(400, "MLX_URL должен начинаться с http:// или https://")
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
    logger.info("[SETTINGS] Updated: %s", updates)

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

    return {"status": "saved", "updated": updates, "restarting": restart}
