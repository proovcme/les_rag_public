"""
С.О.В.У.Ш.К.А. v5.0 — Конфигурация
"""
import os

PROXY_URL = "http://localhost:8050"
MLX_URL   = "http://127.0.0.1:8080"   # именно 127.0.0.1, не localhost!
UI_PORT   = 8051
TRUSTED_NETWORKS = tuple(
    item.strip()
    for item in os.getenv(
        "TRUSTED_NETWORKS",
        "127.0.0.0/8,::1/128,10.195.146.0/24",
    ).split(",")
    if item.strip()
)
TRUSTED_NETWORK_ROLE = os.getenv("TRUSTED_NETWORK_ROLE", "admin")
STORAGE_SECRET = os.getenv("SOVUSHKA_STORAGE_SECRET", "les_secret_883")
