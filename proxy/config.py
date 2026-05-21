"""Typed-ish runtime settings for LES Proxy v3."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(".")
DATA_DIR = ROOT / "data"
META_DB_PATH = DATA_DIR / "les_meta.db"
ENV_PATH = ROOT / ".env"

PUBLIC_ROLE = "public"
USER_ROLE = "user"
ADMIN_ROLE = "admin"

ALLOWED_SETTINGS = {"LLM_MODEL", "EMBED_MODEL", "MLX_URL"}

TRUSTED_NETWORKS = tuple(
    item.strip()
    for item in os.getenv(
        "TRUSTED_NETWORKS",
        "127.0.0.0/8,::1/128,10.195.146.0/24",
    ).split(",")
    if item.strip()
)
TRUSTED_NETWORK_ROLE = os.getenv("TRUSTED_NETWORK_ROLE", ADMIN_ROLE)


def mlx_url() -> str:
    return os.getenv("MLX_URL", "http://host.docker.internal:8080").rstrip("/")


def qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/")


def llm_model() -> str:
    return os.getenv("LLM_MODEL", "mlx-community/Qwen3-14B-4bit")


def embed_model() -> str:
    return os.getenv("EMBED_MODEL", "bge-m3:latest")
