"""Typed-ish runtime settings for LES Proxy v3."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(".")
DATA_DIR = ROOT / "data"
META_DB_PATH = DATA_DIR / "les_meta.db"
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH, override=False)

PUBLIC_ROLE = "public"
USER_ROLE = "user"
ADMIN_ROLE = "admin"

ALLOWED_SETTINGS = {
    "LLM_MODEL",
    "EMBED_MODEL",
    "EMBEDDING_MODEL",
    "LES_EMBED_PROFILE",
    "MLX_URL",
    "RAG_COLLECTION_NAME",
    "RAG_VECTOR_SIZE",
}
DEFAULT_RAG_UPLOAD_SUFFIXES = (
    ".pdf",
    ".docx",
    ".doc",
    ".eml",
    ".msg",
    ".xlsx",
    ".xls",
    ".csv",
    ".json",
    ".jsonl",
    ".md",
    ".txt",
)

TRUSTED_NETWORKS = tuple(
    item.strip()
    for item in os.getenv(
        "TRUSTED_NETWORKS",
        "127.0.0.0/8,::1/128,10.195.146.0/24",
    ).split(",")
    if item.strip()
)
TRUSTED_NETWORK_ROLE = os.getenv("TRUSTED_NETWORK_ROLE", ADMIN_ROLE)

TRUSTED_PROXY_NETWORKS = tuple(
    item.strip()
    for item in os.getenv("TRUSTED_PROXY_NETWORKS", "127.0.0.0/8,::1/128").split(",")
    if item.strip()
)

CORS_ALLOWED_ORIGINS = tuple(
    item.strip()
    for item in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080,"
        "http://localhost:8050,http://127.0.0.1:8050",
    ).split(",")
    if item.strip()
)


def docker_control_enabled() -> bool:
    return os.getenv("LES_ENABLE_DOCKER_CONTROL", "false").lower() in {"1", "true", "yes", "on"}


def rag_upload_suffixes() -> set[str]:
    raw = os.getenv("RAG_UPLOAD_SUFFIXES", ",".join(DEFAULT_RAG_UPLOAD_SUFFIXES))
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def max_upload_bytes() -> int:
    return int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024


def max_pst_upload_bytes() -> int:
    return int(os.getenv("MAX_PST_UPLOAD_MB", "2048")) * 1024 * 1024


def mlx_url() -> str:
    return os.getenv("MLX_URL", "http://127.0.0.1:8080").rstrip("/")


def qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")


def llm_model() -> str:
    return os.getenv("LLM_MODEL", "mlx-community/Qwen3-14B-4bit")


def embed_model() -> str:
    return os.getenv("EMBED_MODEL", "bge-m3:latest")
