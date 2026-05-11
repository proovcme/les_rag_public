# Задание для Aider: правки proxy_server.py

Путь к Aider: `/Users/ovc/Library/Python/3.9/bin/aider`  
Рабочая директория: `~/Projects/LES_v2`  
После каждой задачи: `docker compose restart proxy && curl -s http://localhost:8050/api/health`

---

## Задача 1 — Удалить дублирующий import time

Самая простая. Один файл, одна строка.

```bash
cd ~/Projects/LES_v2 && \
/Users/ovc/Library/Python/3.9/bin/aider \
  --model ollama_chat/qwen2.5-coder:14b \
  --openai-api-base http://localhost:11434/v1 \
  --yes-always \
  proxy_server.py \
  --message "Remove the duplicate 'import time' statement. There are two: one at the top of the file with other stdlib imports, and one around line 44 after 'job_tracker = {}'. Keep only the first one at the top. Do not change anything else."
```

---

## Задача 2 — Объединить два startup-обработчика

Два файла: прокси и коллектор (чтобы Aider видел сигнатуру `init_db` и `metrics_loop`).

```bash
cd ~/Projects/LES_v2 && \
/Users/ovc/Library/Python/3.9/bin/aider \
  --model ollama_chat/qwen2.5-coder:14b \
  --openai-api-base http://localhost:11434/v1 \
  --yes-always \
  proxy_server.py backend/metrics_collector.py \
  --message "In proxy_server.py there are two @app.on_event('startup') handlers: 'startup' and 'startup_event'. Merge them into a single async function named 'startup'. The merged function must: first call init_db(), then initialize rag_backend (existing logic from the original 'startup' function), then create tasks for both metrics_collector_loop() and metrics_loop(). Keep global rag_backend declaration. Do not change backend/metrics_collector.py. Do not change anything else in proxy_server.py."
```

---

## Задача 3 — Очищать /tmp после загрузки файла

Один файл, точечная правка в `upload_file`.

```bash
cd ~/Projects/LES_v2 && \
/Users/ovc/Library/Python/3.9/bin/aider \
  --model ollama_chat/qwen2.5-coder:14b \
  --openai-api-base http://localhost:11434/v1 \
  --yes-always \
  proxy_server.py \
  --message "In the upload_file endpoint, the _parse inner async function does not clean up the temp file after parsing. Wrap the existing body of _parse in a try/finally block and add 'temp_path.unlink(missing_ok=True)' in the finally clause. Do not change anything else."
```

---

## Задача 4 — Счётчики new/changed в sync_folder

Один файл, правка внутри `sync_folder`.

```bash
cd ~/Projects/LES_v2 && \
/Users/ovc/Library/Python/3.9/bin/aider \
  --model ollama_chat/qwen2.5-coder:14b \
  --openai-api-base http://localhost:11434/v1 \
  --yes-always \
  proxy_server.py \
  --message "In sync_folder, add a changed_count variable (initialized to 0). In the file loop, distinguish between new files (dest does not exist) and changed files (dest exists but size or mtime differs). Increment new_count for new files, changed_count for changed files, skip_count for unchanged. Update the job completion message to include changed_count. Add changed_files to the return dict. Do not change anything else."
```

---

## Задача 5 — Записывать latency и CRAG в chat_metrics

Самая объёмная. Три файла в контекст: прокси, адаптер и интерфейс — чтобы Aider знал что возвращает `retrieve()`.

```bash
cd ~/Projects/LES_v2 && \
/Users/ovc/Library/Python/3.9/bin/aider \
  --model ollama_chat/qwen2.5-coder:14b \
  --openai-api-base http://localhost:11434/v1 \
  --yes-always \
  proxy_server.py backend/qdrant_adapter.py backend/interface.py \
  --message "In the chat endpoint, measure and record latency and CRAG results into chat_metrics. Specifically: (1) measure time for retrieve() call and store in latency_search list; (2) measure time for Ollama generate call and store in latency_gen list; (3) on NO_DATA path increment chat_metrics['crag_fail'] and append 0 to latency_gen; (4) on VERIFIED path increment chat_metrics['crag_pass'] and append eval_count from Ollama response to tokens list; (5) after each append, trim all three lists (latency_search, latency_gen, tokens) to last 100 elements. Use time.time() for measurements. Do not change backend files. Do not change anything else in proxy_server.py."
```

---

## Диагностика после всех задач

```bash
# Перезапуск
docker compose restart proxy

# Health
curl -s http://localhost:8050/api/health | python3 -m json.tool

# Проверить что метрики пишутся (после одного чат-запроса)
curl -s http://localhost:8050/api/metrics | python3 -c "
import sys, json
d = json.load(sys.stdin)
p = d.get('pipeline', {})
print('latency_search:', p.get('latency_search'))
print('latency_gen:   ', p.get('latency_gen'))
print('crag_pass_rate:', p.get('crag_pass_rate'))
"

# Проверить sync возвращает changed_files
curl -s -X POST http://localhost:8050/api/rag/sync/NTD | python3 -m json.tool
```

---

## Если Aider пошёл не туда

```bash
# Посмотреть что изменилось
git diff proxy_server.py

# Откатить конкретный файл
git checkout HEAD -- proxy_server.py

# Откатить к конкретному коммиту
git log --oneline -5
git checkout <hash> -- proxy_server.py
```

---

## Порядок выполнения

1 → 2 → 3 → 4 → 5  
После каждой задачи — restart + health check.  
Если задача 2 (startup merge) дала ошибку при старте — откатить и разобрать логи перед продолжением.
