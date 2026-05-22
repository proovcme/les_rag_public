import re

FILE = "proxy_server.py"
with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Глобальные переменные (после job_tracker)
if "error_counts = defaultdict(int)" not in content:
    content = content.replace(
        "job_tracker = {}",
        """job_tracker = {}
import time
from collections import defaultdict

error_counts = defaultdict(int)
llm_queue_size = 0
chat_metrics = {
    "latency_search": [], 
    "latency_gen": [], 
    "tokens": [], 
    "crag_pass": 0, 
    "crag_fail": 0
}"""
    )

# 2. Middleware (перед первым роутом)
if "@app.middleware" not in content:
    content = content.replace(
        '@app.get("/api/health")',
        """@app.middleware("http")
async def track_errors(request: Request, call_next):
    response = await call_next(request)
    if response.status_code >= 400:
        error_counts[response.status_code] += 1
    return response

@app.get("/api/health")"""
    )

# 3. Семафор (замена строки и добавление функции)
if "async def acquire_sem():" not in content:
    content = content.replace(
        "index_semaphore = asyncio.Semaphore(2)",
        """index_semaphore = asyncio.Semaphore(2)

async def acquire_sem():
    global llm_queue_size
    llm_queue_size += 1
    await index_semaphore.acquire()
    llm_queue_size -= 1"""
    )
    # Заменяем использование семафора в индексации
    content = content.replace(
        "await index_semaphore.acquire()",
        "await acquire_sem()"
    )

# 4. Инструментация чата (поиск и генерация)
if "t_search = time.time() - t0" not in content:
    # Обёртка поиска
    content = re.sub(
        r'(chunks = await retriever\.aretrieve\(query\))',
        r't0 = time.time()\n    \1\n    t_search = time.time() - t0',
        content
    )
    # Обёртка генерации
    content = re.sub(
        r'(response = await llm\.acomplete\(prompt\))',
        r't1 = time.time()\n    \1\n    t_gen = time.time() - t1\n\n    tokens = response.raw.get("prompt_eval_count", 0) + response.raw.get("eval_count", 0)\n\n    chat_metrics["latency_search"].append(t_search)\n    chat_metrics["latency_gen"].append(t_gen)\n    chat_metrics["tokens"].append(tokens)\n    \n    if crag_status == "VERIFIED": \n        chat_metrics["crag_pass"] += 1\n    else: \n        chat_metrics["crag_fail"] += 1',
        content
    )

# 5. Обновление /api/metrics
if '"pipeline": {' not in content:
    # Находим функцию get_metrics и заменяем return
    old_return = re.search(r'(@app\.get\("/api/metrics"\).*?return \{.*?\})', content, re.DOTALL)
    if old_return:
        new_return = """@app.get("/api/metrics")
async def get_metrics():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM metrics ORDER BY id DESC LIMIT 60").fetchall()
    conn.close()
    
    return {
        "system": {
            "cpu": rows[0]["cpu"] if rows else 0,
            "ram_used": rows[0]["ram_used"] if rows else 0,
            "ram_total": rows[0]["ram_total"] if rows else 0,
            "swap_used": rows[0]["swap_used"] if rows else 0,
            "disk_used": rows[0]["disk_used"] if rows else 0,
            "disk_total": rows[0]["disk_total"] if rows else 0,
            "ollama_ram": rows[0]["ollama_ram"] if rows else 0,
            "network_ok": rows[0]["network_ok"] if rows else 0
        },
        "pipeline": {
            "latency_search": chat_metrics["latency_search"][-10:],
            "latency_gen": chat_metrics["latency_gen"][-10:],
            "tokens": chat_metrics["tokens"][-10:],
            "crag_pass_rate": chat_metrics["crag_pass"] / max(1, chat_metrics["crag_pass"] + chat_metrics["crag_fail"])
        },
        "queue": {"llm_waiting": llm_queue_size},
        "errors": dict(error_counts),
        "heartbeats": heartbeats
    }"""
        content = content.replace(old_return.group(1), new_return)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("✅ proxy_server.py успешно обновлён")
