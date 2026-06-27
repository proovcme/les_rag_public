# Задание для Квена: правки proxy_server.py

Файл: `proxy_server.py`  
Запускать после правок: `docker compose restart proxy`

---

## Задача 1 — Объединить два startup-обработчика

**Проблема:** Два декоратора `@app.on_event("startup")` с разными именами функций — порядок выполнения не гарантирован.

**Что сделать:** Объединить в одну функцию `startup()`.

```python
# БЫЛО — два отдельных обработчика:
@app.on_event("startup")
async def startup(): ...          # инициализирует rag_backend

@app.on_event("startup")
async def startup_event(): ...    # init_db + metrics_loop

# НАДО — один:
@app.on_event("startup")
async def startup():
    global rag_backend
    init_db()
    try:
        rag_backend = QdrantLlamaIndexAdapter(...)
        await rag_backend.health()
        logger.info("[INIT] Backend initialized successfully")
        asyncio.create_task(metrics_collector_loop())
        asyncio.create_task(metrics_loop())
    except Exception as e:
        logger.error(f"[INIT] Backend initialization failed: {e}")
        raise
```

---

## Задача 2 — Удалить дублирующий import

**Проблема:** `import time` встречается дважды — на строке ~5 и снова на строке ~44 внутри модуля.

**Что сделать:** Удалить второй `import time` (тот что идёт после `job_tracker = {}`).

---

## Задача 3 — Записывать latency в chat_metrics

**Проблема:** `chat_metrics` объявлен, читается в `/api/metrics`, но нигде не пишется. Из-за этого графики latency и CRAG pass rate в дашборде всегда пустые / 0%.

**Что сделать:** В эндпоинте `/api/chat` добавить запись времени и результата.

```python
@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.question.strip(): raise HTTPException(400, "Empty question")
    
    t_search_start = time.time()
    try:
        chunks = await rag_backend.retrieve(req.question, dataset_ids=req.dataset_ids, top_k=5)
    except Exception as e: raise HTTPException(500, f"Retrieval failed: {e}")
    t_search = time.time() - t_search_start
    
    if not chunks:
        crag_stats["no_data"] += 1
        chat_metrics["crag_fail"] += 1                          # <- добавить
        chat_metrics["latency_search"].append(t_search)         # <- добавить
        chat_metrics["latency_gen"].append(0)                   # <- добавить
        return {"answer": "Нет данных в выбранных источниках.", "crag_status": "NO_DATA", "sources": []}
    
    context = "\n".join([f"[{c.doc_name}]: {c.content}" for c in chunks])
    prompt = f"Ты — инженер Л.Е.С. Ответь строго по контексту.\nКонтекст:\n{context}\n\nВопрос: {req.question}\nОтвет:"
    
    t_gen_start = time.time()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{os.getenv('OLLAMA_URL')}/api/generate",
                json={"model": os.getenv("LLM_MODEL", "qwen3:14b"), "prompt": prompt, "stream": False}
            )
            resp.raise_for_status()
            t_gen = time.time() - t_gen_start
            
            tokens = resp.json().get("eval_count", 0)           # <- добавить
            chat_metrics["latency_search"].append(t_search)     # <- добавить
            chat_metrics["latency_gen"].append(t_gen)           # <- добавить
            chat_metrics["tokens"].append(tokens)               # <- добавить
            chat_metrics["crag_pass"] += 1                      # <- добавить
            crag_stats["verified"] += 1
            
            return {"answer": resp.json().get("response"), "crag_status": "VERIFIED", "sources": list(set(c.doc_name for c in chunks))}
    except httpx.HTTPStatusError as e: raise HTTPException(502, f"LLM error: {e.response.text}")
    except Exception as e: raise HTTPException(500, str(e))
```

> Важно: списки `latency_search`, `latency_gen`, `tokens` растут бесконечно. Ограничить до последних 100 элементов. После `.append()` добавить:
> ```python
> if len(chat_metrics["latency_search"]) > 100:
>     chat_metrics["latency_search"] = chat_metrics["latency_search"][-100:]
>     chat_metrics["latency_gen"] = chat_metrics["latency_gen"][-100:]
>     chat_metrics["tokens"] = chat_metrics["tokens"][-100:]
> ```

---

## Задача 4 — Очищать временный файл после загрузки

**Проблема:** В `/api/rag/upload/{dataset_id}` файл пишется в `/tmp/{filename}` и никогда не удаляется.

**Что сделать:** Добавить удаление после парсинга.

```python
@app.post("/api/rag/upload/{dataset_id}")
async def upload_file(dataset_id: str, file: UploadFile = File(...)):
    temp_path = Path(f"/tmp/{file.filename}")
    content = await file.read()
    await asyncio.to_thread(temp_path.write_bytes, content)
    doc_id = await rag_backend.upload_file(dataset_id, temp_path)
    
    async def _parse():
        try:
            async with parse_semaphore:
                await rag_backend.parse_dataset(dataset_id)
        finally:
            temp_path.unlink(missing_ok=True)    # <- добавить
    
    asyncio.create_task(_parse())
    return {"doc_id": doc_id, "status": "queued"}
```

---

## Задача 5 — Вернуть счётчики new/changed из sync

**Проблема:** `/api/rag/sync/{folder}` считает `new_count` и `skip_count`, но не различает "новый" и "изменённый". Фронт хочет видеть оба.

**Что сделать:** Добавить счётчик `changed_count`, различать новые и изменённые файлы, вернуть оба в ответе.

```python
# В начале sync_folder:
new_count, skip_count, changed_count = 0, 0, 0

# В цикле по файлам — заменить логику:
is_new = not dest.exists()
is_changed = False
if not is_new:
    s_src, s_dst = f.stat(), dest.stat()
    if s_src.st_size != s_dst.st_size or abs(s_src.st_mtime - s_dst.st_mtime) > 1.0:
        is_changed = True

if is_new or is_changed:
    await asyncio.to_thread(shutil.copy2, f, dest)
    await rag_backend.upload_file(ds.id, f)
    if is_new: new_count += 1
    else: changed_count += 1
else:
    skip_count += 1

# В ответе return:
return {
    "status": "sync_started",
    "job_id": job_id,
    "dataset_id": ds.id,
    "new_files": new_count,
    "changed_files": changed_count,      # <- добавить
    "skipped_files": skip_count
}

# И в сообщении job после парсинга:
job_tracker[job_id]["message"] = f"Готово. Новых: {new_count}, изменённых: {changed_count}, пропущено: {skip_count}"
```

---

## Что НЕ трогать

- `metrics_cache` — не используется в `/api/metrics` (там идёт напрямую в SQLite), не удалять, но и не трогать
- `parse_semaphore = asyncio.Semaphore(2)` — оставить как есть
- `CORS allow_origins=["*"]` — локальная система, оставить
- `@app.on_event("startup")` — устаревший синтаксис, но менять на `lifespan` не нужно, сейчас не критично
- Логику `list_sources()` — не трогать, там `folder.iterdir()` только первый уровень, это сделано намеренно

---

## Порядок выполнения

1. Задача 2 (удалить строку) — 10 секунд
2. Задача 1 (объединить startup) — осторожно, не потерять `global rag_backend`
3. Задача 4 (очистка /tmp) — точечно
4. Задача 5 (new/changed счётчики) — точечно в sync_folder
5. Задача 3 (chat_metrics) — последней, самая объёмная

После каждой задачи — `docker compose restart proxy` и `curl http://localhost:8050/api/health`.
