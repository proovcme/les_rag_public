import os
import time
import psutil
import sqlite3
import asyncio
import requests
from datetime import datetime, timezone

DB_PATH = "./data/les_metrics.db"
OLLAMA_HOST = os.getenv("OLLAMA_API_URL", "http://host.docker.internal:11434")

heartbeats = {"collector": 0, "sse_emitter": 0, "folder_watcher": 0}

def init_db():
    os.makedirs("./data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            cpu REAL,
            ram_used REAL,
            ram_total REAL,
            swap_used REAL,
            disk_used REAL,
            disk_total REAL,
            ollama_ram REAL,
            network_ok INTEGER,
            heartbeat_collector REAL,
            heartbeat_sse REAL
        )
    """)
    conn.commit()
    conn.close()

def get_ollama_ram():
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/ps", timeout=2)
        if r.status_code == 200:
            return sum(m.get("size", 0) for m in r.json().get("models", [])) / (1024**3)
    except Exception:
        pass
    return 0.0

def get_network_status():
    targets = ["10.195.146.98", "10.195.146.176"]
    ok = 0
    for ip in targets:
        try:
            r = requests.get(f"http://{ip}:8050/api/health", timeout=1)
            if r.status_code == 200: ok += 1
        except Exception:
            pass
    return ok

def collect():
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    disk = psutil.disk_usage("./data")
    ollama_gb = get_ollama_ram()
    net_ok = get_network_status()
    
    now = datetime.now(timezone.utc).isoformat()
    heartbeats["collector"] = time.time()
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO metrics (timestamp, cpu, ram_used, ram_total, swap_used, disk_used, disk_total, ollama_ram, network_ok, heartbeat_collector, heartbeat_sse)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now, psutil.cpu_percent(), vm.used/1e9, vm.total/1e9, sw.used/1e9,
        disk.used/1e9, disk.total/1e9, ollama_gb, net_ok,
        heartbeats["collector"], heartbeats["sse_emitter"]
    ))
    conn.commit()
    conn.close()

async def metrics_loop():
    init_db()
    while True:
        await asyncio.to_thread(collect)
        await asyncio.sleep(3)
