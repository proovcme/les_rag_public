# Состояние системы Л.Е.С. (31.05.2026 — Закрытие сессии интеграции VLM и структурирования)

## Итог

В этом релизе Л.Е.С. получил две технологии распознавания и структурирования нормативных данных: нативный VLM-конвейер **GLM-OCR (0.9B)** на базе MLX, и извлекатель **Google LangExtract** для создания реляционной базы правил `structured_rules` в SQLite параллельно с векторной базой Qdrant.

Актуализация 02.06.2026: контур уже не находится в спящем режиме. Qdrant, proxy, MLX Host и UI подняты; локальная consistency закрыта после CAD/BIM импорта. Текущий health: `1212` files, `1212 indexed`, `0 pending`, `0 errors`, `143150` SQLite chunks, `143150` Qdrant points, `points_match_sqlite_chunks=true`, local `/api/health` = `ok`. Closeout включал SQLite/Qdrant backup, удаление stale Qdrant points, fix duplicate-basename pending selection и индексирование Speckle CAD/BIM projection. FIRE/HVAC acceptance остаётся зелёным (`16/16`), full pytest проходит `365` тестов.

---

## 🛠 Выполненные архитектурные изменения и модули

### 1. Нативный MLX-Native GLM-OCR конвейер (Визуальный RAG):
* **Новый модуль [backend/ocr_parser.py](file:///Users/ovc/Projects/LES_v2/backend/ocr_parser.py)**:
  * Создан класс `MLXVisualOCRParser` с поддержкой легковесной мультимодальной VLM-модели `mlx-community/GLM-OCR-4bit` (всего ~600-800 МБ RSS на GPU).
  * Интегрирован механизм **принудительного освобождения памяти**: принудительный запуск сборщика мусора Python и очистка кэша Metal GPU (`mlx.core.metal.clear_cache()`) сразу по завершении разбора пакета страниц, высвобождая Unified Memory для чат-сервера.
  * Рендеринг PDF-страниц в высокоточные PIL Images на лету через `pypdfium2` (без записи промежуточных картинок на диск).
* **Специфический Fallback в [converter.py](file:///Users/ovc/Projects/LES_v2/backend/converter.py)**:
  * Если `route.pipeline == "markdown_needs_ocr"` (сканы без текстового слоя) или если стандартные текстовые экстракторы (`pymupdf4llm`/`fitz`) возвращают пустую или слишком короткую строку (менее 100 символов мусора) — система на лету переключается на OCR-конвейер.
  * Конфигурация вынесена в `.env`: `RAG_OCR_ENABLED=true`, `RAG_OCR_MODEL=mlx-community/GLM-OCR-4bit`, `RAG_OCR_DPI=150`.
* **Скрипт проверки**: Создан инструмент [test_mlx_ocr.py](file:///Users/ovc/Projects/LES_v2/scratch/test_mlx_ocr.py) для изолированного тестирования OCR на любой странице PDF с замером потребления RAM до/во время/после выгрузки модели.

### 2. Универсальный конвертер Microsoft MarkItDown:
* **Интеграция в [converter.py](file:///Users/ovc/Projects/LES_v2/backend/converter.py)**:
  * Добавлена поддержка презентаций **PowerPoint (`.pptx`)**.
  * Метод `_parse_with_markitdown` выполняет автоматическую конвертацию DOCX, XLSX, PPTX, XML силами `MarkItDown`.
  * Реализован **отказоустойчивый конвейер с fallback**: если библиотека не установлена или дает сбой, конвертер плавно перенаправляет поток на классические локальные парсеры (`mammoth` и `pandas`), гарантируя 100% стабильность.
* **Скрипт проверки**: Создан инструмент [test_markitdown.py](file:///Users/ovc/Projects/LES_v2/scratch/test_markitdown.py), тестирующий конвертацию офисных документов.

### 3. Реляционная база нормативных требований Google LangExtract:
* **SQLite таблица `structured_rules`**:
  * В метабазу SQLite интегрирована таблица правил `structured_rules` с реляционными индексами по `document_id` и `file_key`.
  * Описана строгая Pydantic-схема `EngineeringRule` (субъект, параметр, оператор, численное значение, единица измерения, дополнительные условия).
  * Добавлены DB-методы пакетной вставки, извлечения и очистки правил в классе `MetaDB` в [qdrant_adapter.py](file:///Users/ovc/Projects/LES_v2/backend/qdrant_adapter.py).
  * На 01.06.2026 активная база `data/les_meta_qwen.db` содержит `0` строк в `structured_rules`; это ожидаемо до targeted reindex `NORMATIVE`/`SPEC` документов с включенным извлечением правил.
* **Модуль структурирования [rules_extractor.py](file:///Users/ovc/Projects/LES_v2/backend/rules_extractor.py)**:
  * Создан класс `StructuredRulesExtractor` с ленивым импортом `google/langextract` и поддержкой как локальных моделей (Qwen), так и облачного Gemini API (через `GEMINI_API_KEY`) для пиковой точности.
* **Интеграция в пайплайн индексации [qdrant_adapter.py](file:///Users/ovc/Projects/LES_v2/backend/qdrant_adapter.py)**:
  * Во время синхронного парсинга `_sync_parse` система сбрасывает старые правила. Если документ относится к типу `NORMATIVE` или `SPEC` (нормативные и проектные акты), система пропускает его текстовые чанки через `StructuredRulesExtractor` и записывает все извлеченные правила в SQLite параллельно с векторной базой Qdrant, связывая их с точными символьными координатами (`char_start`, `char_end`) в тексте чанка (Source Grounding).
* **Скрипт проверки**: Создан инструмент [test_langextract_synthetic.py](file:///Users/ovc/Projects/LES_v2/scratch/test_langextract_synthetic.py), который скармливает VLM нормативный пункт о ширине выхода на русском языке и проверяет правильность извлечения по схеме.

---

## 📋 Состояние контура и зависимости

* **Зависимости в [pyproject.toml](file:///Users/ovc/Projects/LES_v2/pyproject.toml)**:
  * Успешно добавлены `mlx-vlm>=0.3.11` и `Pillow>=10.0.0`.
* **Документация**:
  * Обновлен статус и чек-листы в [README.md](file:///Users/ovc/Projects/LES_v2/README.md).
  * Внесены новые параметры closeout baseline и guardrails в [SKILL.md](file:///Users/ovc/Projects/LES_v2/SKILL.md).
* **Чек-лист задач**:
  * Все задачи внедрения и верификации полностью закрыты в [task.md](file:///Users/ovc/.gemini/antigravity/brain/3ed31134-d18c-41bc-a91a-9595f7b46ea4/task.md) и [walkthrough.md](file:///Users/ovc/.gemini/antigravity/brain/3ed31134-d18c-41bc-a91a-9595f7b46ea4/walkthrough.md).

---

## 🚀 Инструкции по дальнейшему запуску и проверке

После старта RAG-машины вы можете безопасно запустить проверку двумя простыми шагами:

1. **Синхронизировать зависимости в вашем окружении**:
   ```bash
   uv sync
   ```
2. **Запустить синтетический тест MarkItDown**:
   ```bash
   python scratch/test_markitdown.py
   ```
3. **Запустить синтетический тест Google LangExtract**:
   ```bash
   python scratch/test_langextract_synthetic.py
   ```
4. **Запустить изолированный тест OCR на отсканированном PDF**:
   ```bash
   python scratch/test_mlx_ocr.py <путь_к_скану.pdf>
   ```

После верификации тестов можно смело переводить систему в режим индексации и запускать фоновую кампанию для датасета `NTD_FIRE`!

## Live Notes 01.06.2026

- Active validator default: deterministic `rules`; Core ML MiniLM package установлен, но не загружен как live default.
- Core ML embedder: `Qwen/Qwen3-Embedding-0.6B`, package `qwen3_embedding_06b_b1_s512_static`, `compute_units=all`, ANE/GPU eligible.
- Core ML embedder выдержал guarded indexing closeout без worker failures/fallback; в конце может быть unloaded/idle, что не является failure.
- Full pytest green after modernization fixes: `357 passed` (2 SWIG deprecation warnings). Закрыты исторические 7 падений: test doubles для `structured_rules`, env isolation для memory admission, retrieval top-k/PP87 expectations.
- Внешний `les.ovc.me` поднят через П.А.У.К. reverse SSH tunnel. VPS Caddy оставлен без перезапуска и правок; соседний tunnel `127.0.0.1:22020` не тронут. Public smoke: `12/12`, live RAG question через внешний контур: `VERIFIED`, `sources=3`.

## Live Notes 02.06.2026

- Добавлен Speckle BIM/CAD bridge для DWG/RVT/IFC: `SPECKLE_BASE_URL=https://speckle.ovc.me`, `SPECKLE_GRAPHQL_URL=https://speckle.ovc.me/graphql`, `SPECKLE_ENABLED=true`, `SPECKLE_WAKE_TIMEOUT_SEC=5`.
- `/api/settings` и Lite/Classical GUI управляют Speckle endpoint/token; token маскируется как `api_token_set`/`***`.
- `/api/speckle/status` выполняет легкий probe и классифицирует `502/503/504` как `sleeping`, если BIM/CAD сервер снова уснет. Live check 02.06.2026 после token setup: `https://speckle.ovc.me` отвечает `200`, LES status route возвращает `status=ok`, `http_status=200`, `api_token_set=true`.
- Upload boundary расширен под `.dwg`, `.rvt`, `.ifc`, `.ifczip`; полноценная модельная конвертация остается на стороне Speckle/connectors.
- Добавлен профильный CAD/BIM pipeline: `/api/speckle/import` принимает inline payload, latest/local `RAG_Content/CAD_BIM/Speckle/*.json|*.jsonl` или Speckle `stream_id+object_id`, нормализует объектный граф в `data/cad_bim_graph.db`, свойства/параметры в `cad_bim_properties`, пишет markdown projection в `RAG_Content/CAD_BIM/exports/`, а `SYNC CAD/BIM` регистрирует projections в `CAD_BIM_Index` без автоматического heavy parse.
- CAD/BIM ingestion переведен в JSON-first модель: preferred inbox `RAG_Content/CAD_BIM/JSON/`, preferred endpoint `/api/cad-bim/import`, projection `cad_bim_json_<id>.md`, JSON contract `dev/CAD_BIM_JSON_CONTRACT.md`. Speckle остается optional/legacy source через `/api/speckle/import`.
- Добавлены Autodesk-side JSON exporters как следующий основной путь: AutoCAD `.NET` plugin `exporters/autocad/LES.AutoCAD.JsonExport` с ribbon tab `LES` и командами `LESJSONEXPORT`/`LESJSONPUSH`/`LESJSONCONFIG`, Revit addin `exporters/revit/LES.Revit.JsonExport` с ribbon tab `LES` и кнопками `Export JSON`/`Push to LES`. Direct upload пробует Mac ZeroTier `http://10.195.146.98:8050`, затем `https://les.ovc.me`, при отказе сохраняет fallback JSON; DXF extractor остается fallback.
- Добавлен Lite Admin `CAD/BIM Viewer` и read-only endpoint `/api/cad-bim/source`: viewer читает latest или указанный `cad_bim_graph.json`, рисует 2D preview по CAD geometry/bbox и fallback graph view по relations. Формат не Speckle-only; Speckle остается только optional source.
- Lite Admin `IMPORT JSON GRAPH` управляет source profile из GUI: `AUTO`, `AutoCAD/DWG`, `Revit/RVT`, `IFC`, `Excel/Power BI`, `Generic`. Это покрывает уже извлеченные Speckle object graph/plugin payloads: DWG/RVT/IFC модельные объекты и Excel/Power BI табличные rows/properties индексируются как единая CAD/BIM проекция.
- Speckle private project `36`, model `шпалерная 36_отсоединено_oleg`, object `8b6c73a095776fcd872f7f5f3bfbbf80` импортирован как `432aa0b18f2a`: `956` graph elements, `955` relations, `44` properties. Projection `RAG_Content/CAD_BIM/exports/cad_bim_speckle_432aa0b18f2a.md` проиндексирован в `CAD_BIM_Index`: `957` chunks, retrieval-debug возвращает chunks из этого projection.
- Speckle server на Lenovo Legion обновлен до `2.31.5/custom` с backup Postgres `C:\SPKL\backups\speckle-pre-2.31.5-20260602101617.dump`. Для текущего AutoCAD DUI/connector `3.22.0` добавлен compatibility shim: `Workspace.logoUrl`, `ModelPermissionChecks.canCreateIngestion`, `WorkspacePermissionChecks.canAccessHelpCenter`, а disabled workspaces возвращают пустой `activeUser.workspaces` collection вместо ошибки. Проверено через внешний `https://speckle.ovc.me/graphql`: introspection видит `canAccessHelpCenter`, replay `WorkspaceListQuery` возвращает `errors=null`. Повторный AutoCAD Publish 02.06.2026 не создал object/blob/version/commit traffic; клиентские логи содержат только DUI bridge init и Desktop Service `/ping`. Root cause: V3 connectors require workspace-based projects, а community self-hosted Speckle не имеет workspace module без лицензии (`FF_WORKSPACES_MODULE_ENABLED=true` приводит к `InvalidLicenseError`). Direct presigned upload route через ingress исправлен и принимает PUT, но self-hosted file importer rejects DWG/DXF as unsupported; рабочий путь для LES сейчас IFC или уже извлеченный Speckle object graph.
- ZeroTier GUI trusted access проверен для subnet `10.195.146.0/24`: `/lite-api/settings`, `/lite-api/speckle/status`, `/lite-api/runtime/dispatcher/status`, `/lite-runtime/status` отвечают `200` без ключа. Исправлен edge-case stale browser key: trusted ZeroTier request с невалидным `X-API-Key` fallback-ится в `trusted-network`, public request с тем же ключом остается `401`.
- Verification: latest full pytest `377 passed` (2 SWIG warnings), local health `ok`, `1212 indexed / 0 pending / 0 errors`, Qdrant points match SQLite chunks (`143150 / 143150`), `les.ovc.me` `/` и `/api/health` возвращают `200`.

## Live Notes 04.06.2026 Closeout

- Speckle V3 снят с критического пути CAD/BIM: canonical format остается `cad_bim_graph.json`, Speckle только optional source.
- Собраны AutoCAD/Revit JSON exporter sources and Windows installer flow under `exporters/`. AutoCAD plugin exposes ribbon tab `LES` and commands `LESJSONEXPORT`/`LESJSONPUSH`/`LESJSONCONFIG`; Revit addin exposes ribbon tab `LES` with `Export JSON` and `Push to LES`.
- Исправлен Autodesk exporter dependency issue: Revit/AutoCAD JSON serialization moved away from `System.Text.Json` runtime dependency into local `LesJsonWriter`; ribbon icons generated in code. Последний Windows artifact: `exporters/artifacts/LES_CAD_BIM_exporters_NO_STJ_ICONS_20260604.zip` locally and on Legion Downloads. AutoCAD DLL replacement requires AutoCAD closed if old DLL is locked.
- Добавлен standalone OBC/WebGL CAD/BIM JSON viewer under `frontend/cad_bim_viewer` and mounted in Sovushka at `/les/cad-bim-viewer`; Lite Admin button `OPEN OBC VIEWER` opens it for latest or selected `source_path`.
- Viewer reads `/lite-api/cad-bim/source`, renders line/polyline/arc/text/bbox geometry in meters, shows layers/stats/selected properties and supports `source_path`, `source`, `highlight`, `focus`, and `debug_scene` query parameters. Black-screen OBC issue was fixed by rebuilding stale `dist`, enforcing `bim-viewport`/canvas dimensions, using sane grid units and removing extreme camera clip planes.
- DWG sample `Узлы установки оросителей розеткой вниз` was copied to `RAG_Content/CAD_BIM/JSON/uzly_orositelei_rozetkoi_vniz.cad_bim_graph.json` after removing UTF-8 BOM. Round-trip result: `2534` elements, `2457` drawable objects, `2534` relations; two sprinkler nodes render back in OBC viewer. Blog/demo screenshots are local under `outputs/cad_bim_viewer/blog/`, including `orositelei_one_node_with_panel.png`.
- Added source QA tests for `/api/cad-bim/source`, Lite Admin viewer route/static assets, and exporter contract/installers. Focused verification: `uv run pytest -q tests/test_sovushka_lite_admin.py tests/test_static_assets.py` -> `6 passed`; `git diff --check` clean.
- Gemma 4 12B is recorded only as a future benchmark candidate for local multimodal CAD/BIM visual QA and OCR/schema comparison; it does not replace current Qwen/GLM-OCR production RAG.
- Next session priority: IFC. Target: IFC -> `cad_bim_graph.json` with products/classes/storeys/property sets/materials/bounding boxes and lightweight viewer previews; preserve spatial/system/connectivity relations for RAG source highlighting.

## Live Notes 05.06.2026 CAD/BIM Viewer Standalone

- Revit exporter now writes lightweight per-element display meshes into `geometry.mesh`; inline import persists pushed JSON source files while skipping heavy geometry arrays in RAG/SQLite projections.
- OBC/WebGL CAD/BIM viewer gained a Russian working UI with model registry, add-file flow, federated model controls, structure tree, layers, selected-object actions, clipping and basic distance measurement.
- The viewer can run both mounted in LES at `/les/cad-bim-viewer` and as an offline-ready standalone package under `standalone/cad_bim_viewer/`.
- Standalone package contents are intentionally minimal: `index.html`, bundled `assets/index.js/css`, `fragments/worker.mjs`, browser `web-ifc.wasm`, `serve.sh`, `serve.ps1`, and `models/demo.cad_bim_graph.json`. It does not require `npm install`, LES backend, or internet access on the target machine.
- Windows offline smoke path: `powershell -ExecutionPolicy Bypass -File .\serve.ps1 -Port 8095`, open `http://127.0.0.1:8095/`, load `models/demo.cad_bim_graph.json`.
- Verification: standalone browser smoke on `http://127.0.0.1:8095/?source=models/demo.cad_bim_graph.json` loaded `2` demo elements with canvas and no UI errors; focused CAD/BIM pytest remained green.

## Live Notes 05.06.2026 Universal Autodesk Destinations

- AutoCAD/Revit exporters now share a universal destination config:
  `%APPDATA%\LES\cad_bim_exporter_settings.json`.
- Config fields: `les_urls` for LES base addresses, `custom_urls` for exact or
  base POST addresses, `local_output_dir` for offline/fallback JSON drops,
  `api_key` for public LES admin auth and `timeout_sec`.
- AutoCAD `LESJSONCONFIG` edits LES URLs, custom URLs and local folder from the
  command line. Revit gained a `Config` ribbon button that creates/opens the
  same JSON config.
- Added first Navisworks exporter project
  `exporters/navisworks/LES.Navisworks.JsonExport`: metadata-first tree
  traversal, item properties, instance GUIDs where available and bbox preview
  geometry into canonical `cad_bim_graph.json`.
- Windows installer/build flow now includes AutoCAD, Revit and Navisworks DLLs;
  Navisworks installs under
  `%APPDATA%\Autodesk Navisworks Manage <year>\Plugins\LES.Navisworks.JsonExport\`.
