"""
С.О.В.У.Ш.К.А. v5.0 — Конфигурация
"""
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(".")
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH, override=False)

PROXY_URL = "http://localhost:8050"
MLX_URL   = "http://127.0.0.1:8080"   # именно 127.0.0.1, не localhost!
UI_PORT   = 8051
TRUSTED_NETWORKS = tuple(
    item.strip()
    for item in os.getenv(
        "TRUSTED_NETWORKS",
        "127.0.0.0/8,::1/128",
    ).split(",")
    if item.strip()
)
TRUSTED_NETWORK_ROLE = os.getenv("TRUSTED_NETWORK_ROLE", "admin")
TRUSTED_PROXY_NETWORKS = tuple(
    item.strip()
    for item in os.getenv("TRUSTED_PROXY_NETWORKS", "127.0.0.0/8,::1/128").split(",")
    if item.strip()
)
TRUSTED_PROXY_HEADER = os.getenv("TRUSTED_PROXY_HEADER", "x-les-trusted-network")
STORAGE_SECRET = os.getenv("SOVUSHKA_STORAGE_SECRET", "les_secret_883")
