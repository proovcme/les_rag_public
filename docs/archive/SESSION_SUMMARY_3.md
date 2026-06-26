# Состояние системы Л.Е.С. (16.05.2026 — финал сессии)

Авторы правок: Claude (Клодыч), Qwen (Кен), Gemini (Панорамыч).

---

## Архитектура стека

```
Mac Mini M4 / 24 GB
├── Docker
│   ├── les-proxy   (FastAPI, порт 8050)
│   └── les-qdrant  (Qdrant, порт 6333)
├── MLX Native Host (FastAPI, порт 8080) — uv run python3 mlx_host.py
│   ├── Qwen3-14B-4bit   (main, TTL 300с, lazy load)
│   ├── Qwen3-4B-4bit    (val,  TTL 120с)
│   └── bge-m3           (embed, всегда)
└── С.О.В.У.Ш.К.А. (NiceGUI, порт 8051)
    автозапуск: ~/Library/LaunchAgents/com.les.sovushka.plist (KeepAlive=true)
```

curl на MLX — всегда 127.0.0.1:8080 (не localhost — Docker занимает IPv6).
После правки .env или docker-compose.yml — docker compose down && docker compose up -d.

---

## .env (текущий)

```env
LLM_MODEL=mlx-community/Qwen3-14B-4bit
EMBED_MODEL=bge-m3
OLLAMA_URL=http://host.docker.internal:8080
MLX_MODEL=mlx-community/Qwen3-14B-4bit
MLX_VAL_MODEL=mlx-community/Qwen3-4B-4bit
QDRANT_URL=http://qdrant:6333
JWT_SECRET=les_v2_secret_key_change_in_prod
ADMIN_PASSWORD=admin123
```

docker-compose.yml исправлен: OLLAMA_URL=http://host.docker.internal:8080 (было 11434 хардкодом).

---

## Что сделано за сессию 16.05

### sovushka_ng.py — v4.1

Системное решение крэшей NiceGUI 3.6.1 — таймеры не отменяются при disconnect:
- make_client_guard(element) + guarded(is_alive_fn, coro_fn)
- _sentinel = ui.label("").style("display:none;") — первый элемент в main_page
- Все 8 таймеров обёрнуты в _alive() проверку

Остальные фиксы: add_log try/except, bg_loop try/except, _sync_row без ui.notify,
SYNC ALL вместо ручного ввода, _now_local() для времени, api_post возвращает
{__error__, status, detail}, KPI диагностики inline (forward ref bug убран),
full_refresh не создаёт UI элементы.

### proxy_server.py — v2.2

- /api/chat: 504/503/502 с деталями вместо голого 500
- list_sources + sync_folder: rglob вместо iterdir (подпапки)
- finished_at + chunk_count в job message

### backend/qdrant_adapter.py — v2.1

- chunk_count реальный (SQLite)
- Дельта-синк: только PENDING файлы
- Дедупликация в Qdrant перед upsert
- indexed_files = только INDEXED документы
- OllamaEmbedding → OpenAIEmbedding → MLX /v1/embeddings

### mlx_host.py — v3.1

- /api/embeddings принимает prompt ИЛИ input (Ollama-совместимость)
- /v1/embeddings: безопасный tolist() + логирование
- Одиночный запрос → {"embedding": [...]} напрямую

---

## Быстрые команды

```bash
# Проверка эмбеддингов
curl -s -X POST http://127.0.0.1:8080/api/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"bge-m3","prompt":"тест"}' | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('OK dim:', len(d.get('embedding',[])))"

# Проверка чата
curl -s -X POST http://localhost:8050/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Ширина путей эвакуации"}' | python3 -m json.tool

# Пересборка прокси
docker compose build proxy && docker compose up -d

# Диагностика
curl -s http://localhost:8050/api/diag | python3 -c \
  "import sys,json; d=json.load(sys.stdin); [print(f\"{r['status'].upper():6} {r['name']:30} {r['value']}\") for r in d['checks']]"
```

---

## Бэклог

| Приоритет | Задача |
|---|---|
| 🔴 | Проверить чат после деплоя mlx_host + qdrant_adapter |
| 🔴 | SYNC ALL → проверить chunk_count и индексацию NTD |
| 🔴 | Aider: pip3 install huggingface-hub==0.30.2 pillow==11.2.1 tokenizers==0.21.1 markupsafe==3.0.2 typing-inspection==0.4.0 pydantic==2.11.4 |
| 🟠 | Е.Ж.И.К.: вкладка настройки IMAP в Совушке |
| 🟠 | Датасет LES_Docs — документация системы в RAG |
| 🟠 | Caddy VPS + les.ovc.me + SSL |
| 🟡 | В.О.Л.К. v2: ключи доступа (admin/user, SQLite) |
| 🟡 | Parquet пайплайн XLSX/CSV |
| 🟡 | Folder Watcher |
| ⚪ | Рефакторинг прокси по Кену |
| ⚪ | VLM пайплайн Gemma 4 для PDF чертежей |
