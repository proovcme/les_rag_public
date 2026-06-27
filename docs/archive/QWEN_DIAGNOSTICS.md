# Диагностика: реальное состояние системы Л.Е.С.

Задача: собрать факты о том, что реально происходит в системе прямо сейчас.
Ничего не менять. Только читать и докладывать.

---

## 1. Контейнеры

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Ожидаем: `les-qdrant` и `les-proxy` в статусе `Up`. Если `Restarting` — сразу сообщить.

```bash
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

Показывает реальное потребление RAM контейнерами прямо сейчас.

---

## 2. Логи прокси — последние 100 строк

```bash
docker logs les-proxy --tail 100
```

Искать:
- `[INIT] Backend initialized` — бэкенд поднялся нормально
- `ERROR` / `Exception` — что-то сломано
- `[PARSE]` / `[CONVERT]` — идёт или шла индексация
- циклические рестарты (одна и та же ошибка повторяется)

```bash
docker logs les-proxy --tail 50 2>&1 | grep -E "ERROR|Exception|WARNING|INIT"
```

---

## 3. Ollama

```bash
ollama ps
```

Показывает какие модели загружены в RAM прямо сейчас и сколько занимают.

```bash
ollama list
```

Показывает все установленные модели. Проверить что есть: `qwen3:14b`, `bge-m3:latest`.

```bash
curl -s http://localhost:11434/api/tags | python3 -m json.tool | grep name
```

То же самое через API — полезно если `ollama` не в PATH.

---

## 4. API health и метрики

```bash
curl -s http://localhost:8050/api/health | python3 -m json.tool
```

Ожидаем: `{"status": "ok", "backend": "qdrant_llama"}`.  
Если `"starting"` — прокси ещё не готов. Если `"error"` — Qdrant недоступен.

```bash
curl -s http://localhost:8050/api/metrics | python3 -m json.tool
```

Смотреть на:
- `system.cpu`, `system.ram_used`, `system.ram_total` — нагрузка узла
- `system.disk_used`, `system.disk_total` — если оба 0, коллектор метрик не пишет диск
- `system.ollama_ram` — если 0, коллектор не видит Ollama
- `rag.files`, `rag.chunks`, `rag.status` — состояние индекса
- `pipeline.latency_search`, `pipeline.latency_gen` — если оба пустые списки `[]`, задача 3 из QWEN_TASKS ещё не сделана
- `pipeline.crag_pass_rate` — если ровно 0.0 или 1.0 при нулевых счётчиках, тоже не пишется

---

## 5. Датасеты и источники

```bash
curl -s http://localhost:8050/api/rag/datasets | python3 -m json.tool
```

Список датасетов: id, name, status, doc_count, chunk_count.  
Если `chunk_count` везде 0 — либо поле не заполняется из Qdrant, либо чанки есть только в коллекции `les_rag`, но не привязаны к датасетам.

```bash
curl -s http://localhost:8050/api/rag/sources | python3 -m json.tool
```

Список папок RAG_Content с маппингом на датасеты.  
Смотреть на: `source_files` vs `indexed_files` — есть ли pending.

---

## 6. Что реально в Qdrant

```bash
curl -s http://localhost:6333/collections | python3 -m json.tool
```

Список коллекций. Должна быть `les_rag`.

```bash
curl -s http://localhost:6333/collections/les_rag | python3 -m json.tool
```

Смотреть на `points_count` — это реальное количество чанков в векторной базе.  
Сравнить с тем что возвращает `/api/metrics` → `rag.chunks`. Должно совпадать.

---

## 7. SQLite — что в базах

```bash
sqlite3 ./data/les_meta.db "SELECT COUNT(*) as datasets FROM datasets;"
sqlite3 ./data/les_meta.db "SELECT COUNT(*) as documents FROM documents;"
sqlite3 ./data/les_meta.db "SELECT name, status, doc_count, chunk_count FROM datasets LIMIT 20;"
```

```bash
sqlite3 ./data/les_metrics.db "SELECT COUNT(*) FROM metrics;"
sqlite3 ./data/les_metrics.db "SELECT * FROM metrics ORDER BY id DESC LIMIT 3;"
```

Последняя строка показывает последнюю запись метрик.  
Проверить: есть ли там `disk_used`, `disk_total`, `ollama_ram` — или они NULL / 0.  
Если NULL — коллектор метрик их не пишет, отсюда пустой gauge на фронте.

---

## 8. Файловая структура хранилища

```bash
du -sh ./RAG_Content/*/
```

Размер каждой папки-источника.

```bash
du -sh ./storage/datasets/*/
```

Размер каждого датасета в хранилище (скопированные файлы).

```bash
ls ./RAG_Content/ | wc -l
find ./RAG_Content -type f | wc -l
```

Количество папок и файлов в источниках.

```bash
find ./storage/datasets -type f | wc -l
```

Количество файлов реально скопированных в хранилище.  
Сравнить с `indexed_files` из `/api/rag/sources` — должно совпадать (или быть больше если были ручные загрузки).

---

## 9. Активные jobs

```bash
curl -s http://localhost:8050/api/jobs | python3 -m json.tool
```

Если пусто `{}` — jobs не было с момента последнего старта прокси (они in-memory).  
Если есть записи — смотреть на `status`: `COMPLETED` / `FAILED` / `PARSING`.

---

## 10. Системные ресурсы Mac Mini

```bash
# RAM
vm_stat | awk '/Pages active|Pages wired|Pages free/ {print $0}'

# Диск
df -h /

# Температура и нагрузка (если установлен iStatMenus или powermetrics)
sudo powermetrics --samplers cpu_power -n 1 2>/dev/null | grep "CPU die temperature" || echo "powermetrics недоступен"
```

---

## Что доложить в итоге

После всех команд — собрать сводку:

```
КОНТЕЙНЕРЫ:    les-proxy [Up/Down], les-qdrant [Up/Down]
OLLAMA:        qwen3:14b [загружена/нет], bge-m3 [загружена/нет]
HEALTH:        status = [ok/error/starting]
ИНДЕКС:        [N] файлов, [N] чанков в Qdrant
PENDING:       [N] файлов не проиндексировано
МЕТРИКИ:       disk_used=[значение или NULL], ollama_ram=[значение или NULL]
LATENCY:       latency_search=[], latency_gen=[] → задача 3 нужна / уже сделана
ОШИБКИ:        [есть/нет, что именно]
JOBS:          [пусто / N записей, статусы]
```

Если что-то недоступно (команда не работает, файл не найден) — написать явно, не пропускать.
