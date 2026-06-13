# Session Summary 8 — LES3: вьювер↔чат, реранкер, журнал объёмов, Волна 3, sparse-гибрид

Workspace: `/Users/ovc/Projects/LES_v2` · Runtime clone: `/Users/ovc/Projects/LES_v2_reinstall_stress`
Дата закрытия: `2026-06-14` · Ветка: `feat/les3-p1` (синхронна с origin, HEAD `644dbb7`)

---

## 🔜 ПРОМТ-ХЕНДОФФ (вставить в следующую сессию)

> Продолжаем LES3 по `docs/LES3_PLAN.md`. Прочитай `AGENTS.md`, `docs/CODE_MAP.md`, `SKILL.md` и память.
> Принципы: **LLM-минимализм** (ADR-11), **облако только OpenRouter+OpenAI** (ADR-9), **GUI-first** —
> любая функция обязана иметь кнопку в Совушке, не только API.
> После каждого шага: обновляй документацию + SKILL + CODE_MAP + план, `make verify`, git commit+push,
> деплой в рантайм-клон (`git pull /Users/ovc/Projects/LES_v2 feat/les3-p1` + сборка вьювера при нужде +
> `launchctl kickstart`). Если GitHub SSH таймаутит — деплой идёт через локальный pull, пуш догнать позже
> (есть паттерн retry-loop в фоне).
>
> Прогресс: **30/65 карт закрыто**. Бери, что не упирается в сеть/реиндекс:
> 1. **W2.7-остаток** — замер доли weak-ретраев, закрываемой словарём (на golden) → go/no-go по LLM-расширению.
> 2. **W3.3-остаток** — политика маршрутизации P0/P1/P2 (чувствительность датасета) + учёт расходов токенов/$
>    в `/api/metrics` + memory-aware fallback (ollama рядом с MLX выедает RAM — диспетчер обязан смотреть память).
> 3. **W5 — зрелость UI** (5 карт): SSE-стриминг чата end-to-end, quick wins (tail-логи, TTL-кэш api_get,
>    индикатор «proxy недоступен»), чистка лайт-шеллов (W5.4/5.5), причёсывание САМОВАРа (W5.6-остаток).
> 4. **Полевая вертикаль:** W11.2 план/факт (ВОР↔журнал объёмов — журнал уже готов), W8.2/W8.3 (фото→VLM→подтверждение).

---

## Что сделано в этой сессии (огромный объём)

### W6.7 — Вьювер ↔ чат: двусторонняя подсветка CAD/BIM — ЗАКРЫТА
- `proxy/services/cad_bim_highlight.py` (регэксп `Source ID` из чанков, 0 LLM) + снимок «последняя подсветка» с `seq`.
- `chat.py` кладёт `source_ids`/`cad_bim` в ответ + `GET/POST /api/cad-bim/highlight`.
- АТЛАС-вьювер: `applyHighlight()` (live-перекраска по `userData.elementId`), подсветка из встроенного чата + поллинг.
- Проверено: extract на живых чанках → 11 source_id, совпадают с element.id вьювера. Остаток `[live]`: глазами в АТЛАСе.

### W2.2/W2.3 — Cross-encoder реранкер — ЗАКРЫТЫ
- `bge-reranker-v2-m3` дотянут **с зеркала hf-mirror.com** (оригинальный HF cdn-lfs заблокирован). `/v1/rerank`.
- Тёплая латентность ~60 мс/8 док, домен-гейт **16/16** (fire_truck_access починен, был 15/16), 3 живых кейса OK.
- `retrieval_trace.mode == hybrid+rerank`.

### W8.1/W8.4 — Журнал полевых объёмов + GUI — ЗАКРЫТЫ (разблокировал W11.2)
- `field_intake_service.py` (таблица `les_field_entries`, CRUD + regex-команда чата + SQL-агрегации + xlsx, 0 LLM),
  роутер `/api/field`, канал `field` в query_router. **GUI: вкладка ОБЪЁМЫ**.
- E2E на рантайме: «запиши объём 50 м3…» → запись, «сколько… за июнь?» → SQL-свод без LLM, xlsx.

### W7.2 — lesctl doctor — ЗАКРЫТА
- `tools/les_doctor.py`: one-shot health (порты/RAM/диск/GPU/инференс/провайдеры/коллекции), называет причину при падении.

### Волна 3 — слой инференса — W3.1/W3.2/W3.4 ЗАКРЫТЫ
- `backend/inference/`: `providers.py` (протоколы) + `validator.py` (общий rules-валидатор, DRY).
- W3.4: каскад rules→LLM в proxy — облако получило детерминированный числовой guard до LLM.
- W3.2: диспетчер `_llm_runtime` уже маршрутизирует 5 провайдеров (mlx/openrouter/openai/ollama/lemonade).

### W2.4 — Sparse-вектора (Qdrant-native гибрид) — ЗАКРЫТА
- **Путь:** доказал BGE-M3 learned-sparse без FlagEmbedding (`sparse_embed.py`) → выяснил, что на 169k реальных
  чанков (~450 токенов) это **~9 ч MPS** → по решению оператора перешёл на **BM25/IDF** (`bm25_sparse.py`:
  токены+стем как FTS → TF, IDF считает Qdrant `modifier=Idf`).
- **Sparse-сайдкар** `les_rag_qwen3_06b_sparse` (sparse-only, те же point id; основная коллекция НЕ тронута).
  `retrieve_sparse` фьюзит dense+sparse RRF за флагом `RAG_SPARSE_ENABLED`.
- Реиндекс 169k за **36 секунд** на CPU (vs 9 ч). Домен-гейт **16/16**, `mode=hybrid+sparse+rerank`. Активирован.

### Операционное — диск
- Освобождено **~10 ГБ** (14→24 свободно): удалены неиспользуемые модели `Qwen3.5-9B`, `Qwen3.5-4B-MLX`, `bge-m3`.

## Runtime state (на момент закрытия)
- Все 4 сервиса слушают, proxy `health=ok`. Домен-гейт 16/16 на hybrid+sparse+rerank.
- Активная LLM: `Qwen3.5-4B-OptiQ-4bit`. Реранкер `bge-reranker-v2-m3` живой. `RAG_SPARSE_ENABLED=true` в клоне.
- Qdrant: 2 коллекции (`les_rag_qwen3_06b` dense 169701 + `les_rag_qwen3_06b_sparse` BM25 169546).
- Метабаза: добавлена `les_field_entries`. 602 теста / 92 файла, `make verify` зелёный.

## Блокеры / незавершённое
- **Диск 95% (24 ГБ свободно)** — отпустило, но следить. `local_private_archive` 8.9 ГБ можно перенести на
  `/Volumes/Data` (647 ГБ свободно) — ждёт решения оператора. Swap под давлением (84%).
- **GitHub SSH периодически рвётся** — пуш через retry-loop в фоне; деплой через локальный pull надёжен.
- **`[live]`-приёмки ждут оператора:** W6.7 подсветка глазами в АТЛАСе; реальные CAD/BIM-модели и полевые фото.
- **BGE-M3-путь** (`sparse_embed.py`) дормантный — модель удалена с диска; код бросит понятную ошибку, если
  понадобится (re-download с зеркала). BM25-путь активен и не зависит от неё.

## Принципы / решения
- LLM-минимализм (ADR-11), облако только OpenRouter+OpenAI (ADR-9), GUI-first.
- **W2.4: BM25/IDF вместо BGE-M3 learned-sparse** — на этом железе BGE-M3 на 169k = ~9ч, BM25 = 36с при той же
  архитектурной цели (Qdrant-native гибрид). Sparse — апгрейд лексики, не фикс (гибрид и так был 16/16).
- **Загрузка моделей** при заблокированном HF cdn-lfs — через `hf-mirror.com` (рецепт в SKILL).
