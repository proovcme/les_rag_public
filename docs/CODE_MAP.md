# CODE_MAP — карта кода Л.Е.С. (LES_v2)

Навигатор по коду для агентов и людей: где что лежит и как связано. Архитектура/инфраструктура подробно — в [INFRASTRUCTURE_v2.0.md](../INFRASTRUCTURE_v2.0.md), [PROXY_ARCHITECTURE.md](../PROXY_ARCHITECTURE.md), [LES_MASTER_DOC_v2_1.md](../LES_MASTER_DOC_v2_1.md), [RAG_MODERNIZATION_PLAN.md](../RAG_MODERNIZATION_PLAN.md), [MLX_GUIDE.md](../MLX_GUIDE.md), термины — в [DICTIONARY_LES_v2.0.md](../DICTIONARY_LES_v2.0.md). Рантайм-операции и доступы — в корневом [SKILL.md](../SKILL.md). Здесь — структура и связи кода.

## Стек

Python **3.12**, менеджер **uv** (`uv.lock`), сборка hatchling. Локальная экспертная RAG-система: **FastAPI** (proxy + MLX-host) + **NiceGUI** (UI «Совушка») + **Qdrant** (вектора) + **llama-index** + **MLX/Core ML** (инференс и эмбеддинги на Apple Silicon). Запуск как набор сервисов (launchd-плисты / docker-compose).

## Рантайм-топология (три яруса + UI)

```
Браузер / les.ovc.me (через P.A.U.K. SSH-туннель, V.O.L.K. ключи)
   │
   ▼
Совушка UI  :8051  (NiceGUI)  ── /classic (чат), /les/classic (админ), /m5, /login
   │  ├─ Qdrant-визуализатор :8066 (iframe, three.js)
   ▼
Proxy       :8050  (FastAPI)  ── /api/chat, /api/datasets, /api/runtime, /api/cad-bim …
   ├──────────────► MLX-host :8080 (FastAPI)  ── /v1/embeddings, /v1/chat/completions, /api/validate
   └──────────────► Qdrant   :6333            ── коллекции les_rag_*, MAIL_Index
```
Доверенные сети (ZeroTier `10.195.146.0/24` + loopback) → доступ без ключа, роль admin. Точные порты/доступы — [SKILL.md](../SKILL.md).

## Точки входа

| Файл | Порт | Роль |
|---|---|---|
| [proxy_server.py](../proxy_server.py) | 8050 | API-шлюз: `from proxy.app import create_app()` |
| [sovushka_ng.py](../sovushka_ng.py) | 8051 | NiceGUI-приложение (UI/админка), монтирует static, поднимает визуализатор |
| [mlx_host.py](../mlx_host.py) | 8080 | Инференс: main/validator движки + эмбеддер (Core ML / sentence-transformers), TTL-выгрузка, memory-guard |
| Консольные ([pyproject.toml](../pyproject.toml)) | — | `lesctl` / `les-runtime` / `les-install` → `tools/` |

## Поток запроса (чат) и индексации

**Запрос:** `POST /api/chat` → `runtime_admission` (очередь/режим) → `query_router` (mail/table/clause/generic) → `retrieval_service` (semantic_cache → Qdrant) → `saferag_service` (C-RAG: контекст + валидация фактов через MLX `/api/validate`) → `runtime_dispatcher` (MLX `/v1/chat/completions`, стрим) → ответ + источники + статус валидации.

**Индексация:** `POST /api/datasets/{id}/upload` → `document_router.route_document()` → `converter.convert_to_markdown()` (pdf/docx/xlsx/eml/dxf/ifc) → `StructureAwareSplitter` (бережёт нумерованные пункты ГОСТ/СП) → батч-эмбеддинг через MLX `/v1/embeddings` → `upsert` в Qdrant → метаданные в SQLite (`data/les_meta_qwen.db`).

## Пакеты

### `proxy/` — API-шлюз и оркестрация
- [proxy/app.py](../proxy/app.py) — `create_app()`, CORS, регистрация роутеров, инъекция общего состояния в роутеры на старте.
- **routers/** (~15): `chat`, `datasets` (CRUD/upload/reindex), `runtime` (health/metrics/mode), `auth`, `mail`, `speckle` (CAD/BIM-роутер: `/api/cad-bim/*`, вьювер/граф/импорт-из-JSON; внешний Speckle-коннектор удалён 2026-06-14), `rerank`, `bor` (ВОР из спецификаций, W11), `diff` (ревизии моделей/документов, W12), `normcontrol` (формальный нормоконтроль, W13), `filemap` (карта файлового архива, W15), `tasks` (задачник, W16), `field` (журнал полевых объёмов: CRUD/свод/xlsx, W8), `diagnostics`, `jobs`, `logs`, `settings`, `chat_history`, `status_page`, `projects` (W17.1: объекты+привязки+двойной режим+досье `/api/projects/{id}/dossier` W17.5), `edges` (W17.2: типизированные рёбра графа знаний+backfill), `ontology` (W17.3: `/api/ontology/*` — хребет Floor→System→Category, обход `elements`, состояния CDE контейнеров, LBS-захватки), `decisions` (W17.4: `/api/decisions/*` — решения проекта DecisionRecord + типизированные рёбра + бэклинки по типу), `forms` (W11.3/W19: `/api/forms/*` — типовые формы, поля из объекта, генерация docx/xlsx/html, download), `files` (W18.1: отдача файлов/структуры RAG_Content, path-guard). Связка вьювер↔чат: `cad-bim` отдаёт `GET/POST /api/cad-bim/highlight` (последняя подсветка, W6.7). Чат: `/api/chat`+SSE `/api/chat/stream` (W5.1, цитаты-фрагменты в ответе W18.6), облачный фолбэк по цепочке моделей (W: `cloud_fallback_models`).
- **services/** (~21): `retrieval_service`, `saferag_service` (C-RAG), `semantic_cache`, `runtime_dispatcher`/`runtime_admission` (очередь к MLX), `query_router`, `table_query_service` (Parquet/Excel), `bor_service` (ВОР: Parquet→свод→xlsx, без LLM), `plan_fact_service` (W11.2: план/факт — ВОР↔журнал объёмов, сопоставление по наименованию×единице, разница/остаток/%готовности, xlsx, без LLM), `diff_service` (дифф CAD-графов по source_id + текстов по пунктам, без LLM), `normcontrol_service` (NK-01…NK-04: форматы ГОСТ 2.301, сканы, шифры, ведомость↔состав, без LLM), `file_map_service` (краулер-карта архива: метаданные+шифры, инкрементальный rescan, выборочная индексация из карты, без LLM), `task_service` (задачник: regex-команды чата + SQL, без LLM), `field_intake_service` (W8.1/W8.4: журнал полевых объёмов — CRUD + regex-команда «запиши объём…» + SQL-агрегации по периоду/захватке + xlsx, числа считает SQL не LLM), `memory_service` (заметки «запомни:…» + лексический recall по заметкам/истории в контекст чата, без LLM), `cad_bim_highlight` (W6.7: регэксп-извлечение `Source ID` из CAD/BIM-чанков + in-process снимок «последняя подсветка» с `seq` для вьювера, без LLM), `mail_query_service`, `clause_lookup_service`, `clarification_service`, `context_expander_service`, `rerank`, `resource_governor`, `job_service`, `cad_bim_graph` (CAD/BIM JSON→markdown), `project_service` (W17.1/17.5: объекты `les_projects`/`les_project_links`, `project_dataset_ids` для двойного режима, `build_dossier` КАРТА ОБЪЕКТА, без LLM), `edge_service` (W17.2: `les_edges` + детерм. экстракторы НТД/`[[вики]]`/Source ID + `derive_edges_from_text`, write-time в заметках/задачах, без LLM), `ontology_service` (W17.3: классификационный хребет Floor→System→Category поверх `cad_bim_elements` + `derive_system` словарь, обход `elements_in`; состояния CDE `les_containers` конечный автомат + `supersede`→ребро; LBS-захватки из журнала объёмов, без LLM), `decision_service` (W17.4: `les_decisions` — решения RFI-стиль, партиц. по объекту Q3 + веер типизированных рёбер justified_by/concerns/at/references/supersedes в граф, бэклинки по типу, чат-команды «реши:…», без LLM), `forms_service` (W11.3/W19: типовые формы — дескриптор `config/forms/*.yaml` + детерм. резолв полей из объекта (project/field/edges/manual/date) + рендереры docx (python-docx, образец `{{поле}}` или template-less)/xlsx/html, ИИ при заполнении не участвует).
- **storage/** (file_storage), **workers/** (фоновая индексация), **clients/**, **repositories/**, [proxy/config.py](../proxy/config.py), [proxy/security.py](../proxy/security.py).

### `backend/` — RAG-движок и конвертация (~21 модуль)
- **Ядро RAG:** [backend/qdrant_adapter.py](../backend/qdrant_adapter.py) (`QdrantLlamaIndexAdapter`, `EmbedClient`→MLX, `MetaDB` SQLite, `StructureAwareSplitter`), [backend/rag_config.py](../backend/rag_config.py) (профили эмбеддингов), [backend/interface.py](../backend/interface.py) (`RAGBackend`, `Chunk`), [backend/reranker.py](../backend/reranker.py) (кросс-энкодер через MLX), [backend/mlx_adapter.py](../backend/mlx_adapter.py) (`MLXMemoryManager`: TTL-выгрузка, metal-семафор).
- **Конвертация:** `converter.py` (MarkItDown: pdf/docx/xlsx/email), `document_router.py`, `ocr_parser.py` (MLX VLM OCR), `parquet_writer.py` (таблицы→Parquet).
- **Почта (Е.Ж.И.К.):** `mail_ingest.py` (IMAP/Apple Mail), `mail_threads.py`, `mail_profile.py`, `mail_emlx.py`, `pst_reader.py`.
- **Прочее:** `smart_index.py` (план индексации), `metrics_collector.py`, `diagnostics.py`, `rules_extractor.py`, `auth.py`/`auth_login_route.py` (В.О.Л.К.).
- **`backend/inference/` (W3.1/W2.4/W3.3):** `providers.py` (протоколы ChatProvider/EmbedProvider/ValidatorProvider/RerankProvider/OCRProvider), `validator.py` (общий rules-валидатор, каскад rules→LLM), `bm25_sparse.py` (BM25/IDF sparse для гибрида, W2.4), `sparse_embed.py` (BGE-M3 learned-sparse — задел, не в активном пути), `routing.py` (W3.3: политика локал/облако по чувствительности P0/P1/P2 — `decide_provider`/`memory_aware_provider`/`estimate_cost_usd`, pure-функции; гейт в `chat.py` — P0 не уходит в облако).

### `sovushka/` — UI (NiceGUI) + статика
- Ядро: `config.py`, `state.py`, `auth.py`, `trust.py` (доверенные сети), `safe_markup.py` (санитайз SVG), `styles.py`.
- **pages/**: `overview` (ОБЗОР), `samovar` (С.А.М.О.В.А.Р. — датасеты), `prorab, zadachi (задачник+заметки, W16), instrumenty (ВОР/нормоконтроль/дифф в GUI, W11.2), obyomy (журнал полевых объёмов, W8)` (П.Р.О.Р.А.Б. — метрики), `chat` (AI ЧАТ; drawer «Задачи и объёмы» — просмотр /api/tasks+/api/field прямо в чат-шелле, ввод командами чата), `history`, `volk` (auth), `diag`. **components/**: `header`, `charts`, `logterm`.
- Единственный UI — NiceGUI: `/classic` чат, `/les/classic` админка (W5.4/5.5). HTML-шеллы lite_chat/lite_admin удалены; `/`, `/les`, `/les/lite` редиректят в NiceGUI.
- `lite_bridge.py` (`register_lite_bridge_routes`): мост `/lite-api/*`→proxy (контур les.ovc.me/M5/smoke 12/12/вьювер), `/lite-runtime/*` (рестарты сервисов, loopback/trusted), статика+страница вьювера CAD/BIM, редиректы шеллов. `m5_display.py` (экран Wokyis M5) — отдельно.
- Чат: нестриминговый `POST /api/chat` + SSE `POST /api/chat/stream` (W5.1, токены по мере генерации); push-канал `GET /api/live` (W5.2, метрики/статус/индексация одним SSE).
- Статика: [frontend/](../frontend/) (legacy `sovushka.html`; `cad_bim_viewer/` — TS+Vite+three.js+web-ifc), [qdrant_visualizer/](../qdrant_visualizer/) (three.js + клиентский PCA), `static/fonts/`.

### `tools/` (~48) — установка, сборка, ML, smoke, индексация
Группы: рантайм-контроль (`install_les`, `les_runtime_control`, `lesctl`, `les_doctor` — W7.2 health-отчёт: порты/RAM/диск/GPU/инференс/провайдеры/коллекции, офлайн-безопасный, переиспользует `les_runtime_control`) · релизы (`build_*_release`, `build_release_artifacts`, `check_*_budget`) · CAD/BIM экстракторы (`cad_bim_extract_dxf/ifc`) · Core ML/эмбеддинги (`coreml_*`) · smoke (`browser_smoke`, `chat_format_smoke`, `clean_install_smoke`, `runtime_smoke`) · индексация/eval (`build_lexical_index`, `reindex_*_guarded`, `rag_golden_set`, `rag_eval_report`, `measure_weak_retry` — W2.7: доля weak, закрываемой словарём, на golden → go/no-go по LLM-ступени) · сиды (`seed_artel_*`).

## Данные и конфиг

- **Env:** [env.example](../env.example) (~190 ключей) — модели (`MLX_MODEL`, `LES_EMBED_PROFILE`, `EMBEDDING_MODEL`), Qdrant (`QDRANT_URL`, `RAG_COLLECTION_NAME`, `RAG_VECTOR_SIZE`), чанкинг (`RAG_CHUNK_SIZE/OVERLAP/BATCH`), Core ML (`COREML_*`), почта (`MAIL_*`), безопасность (`JWT_SECRET`, `ADMIN_PASSWORD`, `TRUSTED_NETWORKS`). Профили эмбеддингов: `qwen|legacy|fast|quality` → разные коллекции/размерности.
- **config/** — профили развёртывания (`profiles/*.yaml`), `kot_terms.yaml`. **schema/** — JSON-схемы (artel learning case).
- **SQLite-метабаза** (`data/les_meta_qwen.db`): `datasets`, `documents` (статусы PENDING/INDEXED), `structured_rules` (извлечённые нормы). **Qdrant-коллекции:** `les_rag_*`, `MAIL_Index`.
- **golden/** — эталонные наборы для тестов/eval (validator/domain/ntd sets). **exporters/** — CAD/BIM-экспортеры (.NET артефакты, тяжёлые). **products/** (artel, atlas), **examples/**.

## Сборка / деплой / тесты / гейт

- **Гейт:** `make verify` → `compileall` (синтаксис) + `pytest --collect-only` (импорт-смоук всех 455 тестов, офлайн, без сервисов). Полная сюита: `make test` (часть тестов требует живых Qdrant/MLX).
- **Тесты:** [tests/](../tests/) — 75 файлов / 455 тестов, `pytest-asyncio`; ~25 требуют живых сервисов/сети. Конфиг [pytest.ini](../pytest.ini) (`testpaths=tests`).
- **Сборка/деплой:** hatchling (wheel: backend/proxy/sovushka/tools), [docker-compose.yml](../docker-compose.yml) (Qdrant+Proxy), [Dockerfile.proxy](../Dockerfile.proxy), `installers/{macos,linux,windows}/`, `deploy/pauk/`, `standalone/cad_bim_viewer/`.
- **CI:** нет (намеренно — локальная система).

## Сквозные механизмы

- **Доступ/доверенные сети:** `sovushka/trust.py` + `proxy/security.py` — loopback/ZeroTier → роль admin без ключа; публичные клиенты → API-ключ (V.O.L.K.). Внешний вход через P.A.U.K. (reverse SSH).
- **Управление памятью MLX:** `backend/mlx_adapter.py` — TTL-выгрузка моделей, metal-семафор (один движок к Metal), RAM-гарды.
- **Сервисы (launchd):** `*_launchd.plist` (qdrant/mlx/proxy/sovushka/pauk/qwen-index) + `*.command`. **Агент НЕ должен рестартить сервисы без явной нужды.**

## «Где искать что»

| Хочу… | Смотреть |
|---|---|
| Поток чата/ответа | `proxy/routers/chat.py` → services (`retrieval`, `saferag`, `runtime_dispatcher`) |
| Индексацию/эмбеддинги | `backend/qdrant_adapter.py` + `backend/rag_config.py` (профили) |
| Память/выгрузку моделей | `backend/mlx_adapter.py`, `mlx_host.py` |
| UI/страницы | `sovushka/pages/*` + `sovushka_ng.py` (роуты) |
| Доступ/доверие/ключи | `sovushka/trust.py`, `proxy/security.py`, [SKILL.md](../SKILL.md) |
| Запуск/рестарт сервисов | `tools/les_runtime_control.py`, `lesctl.py`, `*_launchd.plist` (осторожно) |
| Конфиг/модели/коллекции | [env.example](../env.example), `config/`, [MLX_GUIDE.md](../MLX_GUIDE.md) |
| Проверить перед готовностью | `make verify` |

> Карта собрана из кода (5 параллельных read-only проходов) и отражает состояние на момент написания. Источник истины — код; обновляйте карту при крупных структурных правках.
