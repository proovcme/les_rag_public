"""
metrics_collector.py — сбор системных метрик в SQLite.

Проблемы оригинала:
  - requests.get синхронный внутри asyncio → блокирует event loop
  - get_network_status пингует ZeroTier IP хардкодом
  - metrics таблица не чистится → растёт вечно
  - init_db вызывается дважды (startup + metrics_loop)
"""
import asyncio
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone

import httpx
import psutil

logger = logging.getLogger(__name__)

DB_PATH      = "./data/les_metrics.db"
OLLAMA_HOST  = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
# Сколько строк хранить — ~3 суток при интервале 3с
MAX_METRICS_ROWS = 86400

heartbeats: dict = {"collector": 0.0, "sse_emitter": 0.0, "folder_watcher": 0.0}

_db_initialized = False


def init_db():
    global _db_initialized
    if _db_initialized:
        return
    os.makedirs("./data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp        TEXT,
            cpu              REAL,
            ram_used         REAL,
            ram_total        REAL,
            swap_used        REAL,
            disk_used        REAL,
            disk_total       REAL,
            ollama_ram       REAL,
            network_ok       INTEGER,
            heartbeat_collector REAL,
            heartbeat_sse    REAL
        )
    """)
    conn.commit()
    conn.close()
    _db_initialized = True
    logger.info("[METRICS] DB инициализирована")


async def _get_ollama_ram() -> float:
    """Асинхронно запрашивает RAM занятый Ollama/MLX моделями."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{OLLAMA_HOST}/api/ps")
            if r.status_code == 200:
                return sum(
                    m.get("size", 0) for m in r.json().get("models", [])
                ) / (1024 ** 3)
    except Exception:
        pass
    return 0.0


async def _get_network_ok() -> int:
    """Проверяет доступность прокси — только localhost, без хардкода ZeroTier."""
    try:
        async with httpx.AsyncClient(timeout=1.0) as c:
            r = await c.get("http://localhost:8050/api/health")
            return 1 if r.status_code == 200 else 0
    except Exception:
        return 0


def _write_metrics(row: tuple):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO metrics
          (timestamp, cpu, ram_used, ram_total, swap_used,
           disk_used, disk_total, ollama_ram, network_ok,
           heartbeat_collector, heartbeat_sse)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, row)
    # Чистим старые строки
    conn.execute(f"""
        DELETE FROM metrics WHERE id NOT IN (
            SELECT id FROM metrics ORDER BY id DESC LIMIT {MAX_METRICS_ROWS}
        )
    """)
    conn.commit()
    conn.close()


async def metrics_loop():
    """Основной цикл сбора метрик. Запускается как asyncio task."""
    init_db()
    while True:
        try:
            vm   = psutil.virtual_memory()
            sw   = psutil.swap_memory()
            disk = psutil.disk_usage("/")
            cpu  = psutil.cpu_percent()

            ollama_ram = await _get_ollama_ram()
            network_ok = await _get_network_ok()

            heartbeats["collector"] = time.time()
            now = datetime.now(timezone.utc).isoformat()

            row = (
                now, cpu,
                vm.used / 1e9, vm.total / 1e9,
                sw.used / 1e9,
                disk.used / 1e9, disk.total / 1e9,
                ollama_ram, network_ok,
                heartbeats["collector"],
                heartbeats["sse_emitter"],
            )
            await asyncio.to_thread(_write_metrics, row)

        except Exception as e:
            logger.warning(f"[METRICS] Ошибка сбора: {e}")

        await asyncio.sleep(3)
