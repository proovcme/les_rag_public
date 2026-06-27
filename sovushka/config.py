"""
С.О.В.У.Ш.К.А. v5.0 — Конфигурация
"""
import os
from pathlib import Path

from dotenv import load_dotenv


# Корень рантайма ОТ ФАЙЛА, не от CWD: иначе UI-сервис (другой WorkingDirectory) не находил .env
# и TRUSTED_NETWORKS падал в дефолт (только loopback) → ZeroTier/доверенные сети бились в логин ВОЛК.
ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH, override=False)

PROXY_URL = os.getenv("PROXY_URL", "http://localhost:8050")
MLX_URL   = os.getenv("MLX_URL", "http://127.0.0.1:8080")   # именно 127.0.0.1, не localhost!
UI_PORT   = int(os.getenv("SOVUSHKA_UI_PORT", "8051"))
QDRANT_VISUALIZER_PORT = int(os.getenv("QDRANT_VISUALIZER_PORT", "8066"))
TRUSTED_NETWORKS = tuple(
    item.strip()
    for item in os.getenv(
        "TRUSTED_NETWORKS",
        "127.0.0.1/32,::1/128",
    ).split(",")
    if item.strip()
)
TRUSTED_NETWORK_ROLE = os.getenv("TRUSTED_NETWORK_ROLE", "admin")
TRUSTED_PROXY_NETWORKS = tuple(
    item.strip()
    for item in os.getenv("TRUSTED_PROXY_NETWORKS", "127.0.0.1/32,::1/128").split(",")
    if item.strip()
)
TRUSTED_PROXY_HEADER = os.getenv("TRUSTED_PROXY_HEADER", "x-les-trusted-network")
def _storage_secret() -> str:
    # БЕЗОПАСНОСТЬ: НЕ дефолтить предсказуемым «les_secret_883» (им подписываются куки сессий →
    # подделка). Нет env → персистим случайный в data/.storage_secret (стабилен между рестартами,
    # сессии не мрут). chmod 600.
    env = (os.getenv("SOVUSHKA_STORAGE_SECRET") or "").strip()
    if env:
        return env
    import secrets as _secrets
    path = ROOT / "data" / ".storage_secret"
    try:
        if path.exists():
            saved = path.read_text(encoding="utf-8").strip()
            if saved:
                return saved
        path.parent.mkdir(parents=True, exist_ok=True)
        val = _secrets.token_hex(32)
        path.write_text(val, encoding="utf-8")
        path.chmod(0o600)
        return val
    except Exception:
        return _secrets.token_hex(32)  # fallback: не персистится (сессии умрут на рестарте), но НЕ предсказуем


STORAGE_SECRET = _storage_secret()
