# Что было сделано за сессию (11.05.2026)

Контекст: работали с Claude (Клодыч). Все изменения применены и проверены в production.

---

## Файлы которые изменились

### `proxy_server.py`

1. Дублирующий `import time` удалён, `from collections import defaultdict` перенесён наверх
2. Два `@app.on_event("startup")` объединены в один. Порядок: `init_db()` — инит `rag_backend` — `metrics_collector_loop()` — `metrics_loop()`
3. В `/api/chat` добавлено измерение latency и запись в `chat_metrics`
4. В `upload_file` добавлен `finally: temp_path.unlink(missing_ok=True)`
5. В `sync_folder` добавлен `changed_count`, в ответе теперь `changed_files`
6. Добавлен `current_mode = {"mode": "rag", "model": "qwen3:14b"}`
7. Добавлены модели `ModeRequest`, `SettingsRequest`
8. Новые эндпоинты: `/api/mode` (GET/POST), `/api/status`, `/api/settings` (GET/POST), `DELETE /api/rag/datasets/{id}`, `DELETE /api/rag/datasets`
9. Автодетект формата LLM в `/api/chat`: порт 11434 — Ollama (`/api/generate`), любой другой — OpenAI (`/v1/chat/completions`). Нужно для MLX на порту 8080.

### `frontend/sovushka.html` — v3.1

- Вкладка С.А.М.О.В.А.Р. с деревом датасетов, KPI, историей jobs, кнопкой SYNC
- В П.Р.О.Р.А.Б.: карточки Ollama активные модели + Docker контейнеры
- Хедер: кнопка режима РАГ/КОД + кнопка настроек
- Модальное окно настроек: LLM/embed модель, URL сервера, сброс датасетов

### `backend/metrics_collector.py`

Не трогали. Файл хороший, написан Квеном ранее.

### `Dockerfile.proxy`

Добавлен `docker-ce-cli`. Убран `--reload` из CMD.

### `docker-compose.yml`

Добавлен volume: `/var/run/docker.sock:/var/run/docker.sock`

### `mode_code.sh` / `mode_rag.sh`

Лежат в корне проекта. Переключают модели Ollama вручную через SSH.

---

## Текущее состояние

```
Health:      ok / qdrant_llama
Контейнеры:  les-proxy UP, les-qdrant UP
Ollama:      qwen3:14b + bge-m3
NTD:         сброшен и запущен заново, 801 файл, идёт PARSING
Датасеты:    QWEN_Index (1), CLAUDE_Index (4), NTD_Index (в процессе)
```

---

## Известные проблемы

**Чанков в С.А.М.О.В.А.Р. показывает 0.** Схема SQLite таблицы `datasets` — только `(id, name, status)`, колонки `chunk_count` нет. Чанки правильно отображаются в `/api/metrics` из Qdrant напрямую. Нужно либо добавить колонку, либо в `fetchSamovar()` брать чанки из `/api/metrics`.

**Чанки не удаляются из Qdrant по фильтру.** LlamaIndex не проставляет `dataset_id` как payload. Поэтому `DELETE /api/rag/datasets` удаляет всю коллекцию `les_rag` целиком.

**list_sources() и sync_folder() не рекурсивные.** `folder.iterdir()` — только первый уровень. Для подпапок нужен `rglob('*')`.

---

## Как подключить MLX + Gemma

```bash
pip install mlx-lm

mlx_lm.server \
  --model mlx-community/gemma-3-12b-it-4bit \
  --port 8080 \
  --host 0.0.0.0
```

В совушке нажать, поменять URL на `http://host.docker.internal:8080`, вписать модель вручную, сохранить. Прокси сам переключится на OpenAI-формат по порту.

Варианты моделей: `gemma-3-4b-it-4bit` (~2.5 GB), `gemma-3-12b-it-4bit` (~7 GB), `gemma-3-27b-it-4bit` (~16 GB).

---

## Бэклог

- `chunk_count` в С.А.М.О.В.А.Р. всегда 0 — нужно добавить колонку в SQLite или брать из Qdrant
- Рекурсивный обход: заменить `iterdir()` на `rglob('*')` в `list_sources()` и `sync_folder()`
- Кнопка режима в UI переключает только `/api/mode` — реальную загрузку модели делают скрипты вручную
- Убрать кротовуху из чата (статичный демо-диалог в HTML)

---

## Полный список API

| Endpoint | Метод | Что делает |
|---|---|---|
| `/api/health` | GET | Статус бэкенда |
| `/api/mode` | GET/POST | Текущий режим / переключить |
| `/api/status` | GET | Ollama модели + Docker контейнеры |
| `/api/settings` | GET | Настройки + список моделей Ollama |
| `/api/settings` | POST | Сохранить в .env + restart прокси |
| `/api/metrics` | GET | CPU/RAM/disk/latency/CRAG |
| `/api/rag/sources` | GET | Папки RAG_Content с маппингом |
| `/api/rag/datasets` | GET/POST | Список/создание датасетов |
| `/api/rag/datasets/{id}` | DELETE | Удалить один датасет |
| `/api/rag/datasets` | DELETE | Сбросить все + Qdrant коллекцию |
| `/api/rag/sync/{folder}` | POST | Синк папки в индекс |
| `/api/rag/upload/{id}` | POST | Загрузка файла |
| `/api/jobs` | GET | История jobs |
| `/api/chat` | POST | RAG-чат, поле `question`, автодетект Ollama/OpenAI |
| `/api/logs/stream` | GET | SSE логи |

## .env

```env
LLM_MODEL=qwen3:14b
EMBED_MODEL=bge-m3:latest
OLLAMA_URL=http://host.docker.internal:11434
QDRANT_URL=http://qdrant:6333
JWT_SECRET=les_v2_secret_key_change_in_prod
ADMIN_PASSWORD=admin123
```

Логика автодетекта: если порт в `OLLAMA_URL` не 11434 — прокси использует OpenAI-формат. Менять код не нужно.
