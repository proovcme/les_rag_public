# Состояние системы Л.Е.С. (17.05.2026 — финал сессии)

Авторы правок: Claude (Клодыч), Qwen (Кен), Gemini (Панорамыч).

---

## Архитектура стека

```
Mac Mini M4 / 24 GB
├── Docker
│   ├── les-proxy   (FastAPI, порт 8050)
│   └── les-qdrant  (Qdrant, порт 6333)
├── MLX Native Host (FastAPI, порт 8080) — uv run python3 mlx_host.py
│   ├── Qwen3-14B-4bit   (main, TTL 300с, lazy weights)
│   ├── Qwen3-4B-4bit    (val,  TTL 120с, lazy weights)
│   └── BGE-M3           (sentence-transformers + MPS, lazy)
└── С.О.В.У.Ш.К.А. (NiceGUI, порт 8051) — python3 sovushka_ng.py
    автозапуск: ~/Library/LaunchAgents/com.les.sovushka.plist
```

curl на MLX — всегда **127.0.0.1:8080** (не localhost — Docker занимает IPv6).

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

---

## Что сделано за сессию 17.05

### Архитектурная стабилизация — полный аудит и правка всех файлов

#### `pyproject.toml` — новый (вместо requirements.txt)
- `uv sync` создаёт `.venv` в папке проекта
- `mlx-embedding-models` выброшен (сломан в transformers>=4.40)
- `sentence-transformers` для BGE-M3 (MPS на Apple Silicon)
- Нет warnings, нет `python =` в `[tool.uv]`

#### `backend/mlx_adapter.py` — переписан
- Токенизатор грузится в `start()` один раз (без весов, ~1с)
- `apply_chat_template()` — правильный ChatML для Qwen3
- `metal_semaphore = Semaphore(1)` — один движок на Metal одновременно
- Stop-токены обрезаются из ответа
- `force_unload` vs `_unload_model` — раздельно (токенизатор остаётся)
- `reload_tokenizer()` после `switch_model`

#### `mlx_host.py` — переписан
- BGE-M3 через `sentence-transformers` (не mlx_embedding_models)
- `_messages_to_prompt` → `engine.apply_chat_template()` — нет дублирования
- `/api/validate` использует chat template для Qwen3-4B
- `switch_model` перезагружает токенизатор
- FutureWarning `get_sentence_embedding_dimension` исправлен

#### `proxy_server.py` — пропатчен (8 правок)
- Промпт через `system + user messages` — правильный ChatML
- Лимит контекста 12k символов — защита от overflow
- Таймаут валидации 90s (было 15s)
- Двойное копирование файлов убрано
- `job_tracker` чистится (старше 24ч)
- `llm_queue_size` реальный счётчик
- Диагностика правильно парсит `{path, loaded}` из health
- Ollama fallback тоже получает нормальный промпт

#### `backend/qdrant_adapter.py` — переписан
- **Батч-эмбеддинги**: 32 чанка за запрос вместо по одному → в 10-30x быстрее индексация
- **EmbedClient**: прямой httpx к MLX /v1/embeddings, без llama-index OpenAIEmbedding
- `retrieve` async через httpx (не блокирует event loop)
- `_ensure_collection` с asyncio.Lock (race condition при startup)
- WAL + NORMAL synchronous для SQLite
- Индекс на `documents(dataset_id)`
- Пустые чанки < 20 символов не индексируются
- Upsert батчами по 100 точек

#### `backend/converter.py` — переписан
- Добавлен `.txt`
- Лимит 500k символов на файл
- PDF fallback постраничный
- CSV автодетект кодировки (cp1251 для русских файлов)
- JSON стриминг лимит 2000 записей
- Рекурсивный `_extract_json_text` глубина 2

#### `backend/metrics_collector.py` — переписан
- `requests` → `httpx` async (не блокирует event loop)
- Убран хардкод ZeroTier IP
- Таблица чистится автоматически (хранит 3 суток)
- `init_db` не вызывается дважды

#### `sovushka_ng.py` — MLX_URL исправлен на 127.0.0.1

---

## Быстрые команды

```bash
# Полный деплой
cd ~/Projects/LES_v2
./stop_mlx.command && ./start_mlx.command
docker compose build proxy && docker compose up -d
python3 sovushka_ng.py

# Проверка стека
curl -s http://127.0.0.1:8080/api/health | python3 -m json.tool
curl -s http://localhost:8050/api/health
curl -s http://localhost:8050/api/diag | python3 -c \
  "import sys,json; d=json.load(sys.stdin); [print(f\"{r['status'].upper():6} {r['name']:30} {r['value']}\") for r in d['checks']]"

# Тест эмбеддингов
curl -s -X POST http://127.0.0.1:8080/api/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"bge-m3","prompt":"тест"}' | python3 -c \
  "import sys,json; d=json.load(sys.stdin); e=d.get('embedding',[]); print('OK dim:', len(e))"

# Тест чата
curl -s -X POST http://localhost:8050/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Ширина путей эвакуации"}' | python3 -m json.tool

# SYNC датасетов
curl -s -X POST http://localhost:8050/api/rag/sync/NTD | python3 -m json.tool
curl -s -X POST http://localhost:8050/api/rag/sync/CLAUDE | python3 -m json.tool
```

---

## Бэклог

| Приоритет | Задача |
|---|---|
| 🔴 | Живые тесты: SYNC NTD → тестовый запрос по нормативам |
| 🔴 | Проверить качество ответов (нет ли дублирования после chat template) |
| 🔴 | Aider: `pip3 install huggingface-hub==0.30.2 pillow==11.2.1 tokenizers==0.21.1 markupsafe==3.0.2 typing-inspection==0.4.0 pydantic==2.11.4` |
| 🟠 | Е.Ж.И.К.: вкладка настройки IMAP в Совушке + тест на реальных письмах |
| 🟠 | Caddy VPS + les.ovc.me + SSL |
| 🟡 | Датасет LES_Docs — документация системы в RAG |
| 🟡 | В.О.Л.К. v2: ключи доступа (admin/user, SQLite) |
| 🟡 | Parquet пайплайн XLSX/CSV (сметы, спецификации) |
| 🟡 | Folder Watcher — автосинк |
| ⚪ | VLM пайплайн Gemma 4 для PDF чертежей |
| ⚪ | Реранкер Qwen3-4B как cross-encoder (при индексе > 5000 чанков) |

---

## Файлы проекта (актуальное состояние)

| Файл | Версия | Статус |
|---|---|---|
| `mlx_host.py` | v3.2 | ✅ переписан |
| `backend/mlx_adapter.py` | v2.0 | ✅ переписан |
| `backend/qdrant_adapter.py` | v3.0 | ✅ переписан |
| `backend/converter.py` | v2.0 | ✅ переписан |
| `backend/metrics_collector.py` | v2.0 | ✅ переписан |
| `backend/interface.py` | v1.1 | ✅ чисто |
| `proxy_server.py` | v2.3 | ✅ пропатчен |
| `sovushka_ng.py` | v4.1 | ✅ MLX URL исправлен |
| `pyproject.toml` | v1.0 | ✅ новый |
| `start_mlx.command` | v2.0 | ✅ через uv sync |
| `stop_mlx.command` | v1.0 | ✅ создан |
