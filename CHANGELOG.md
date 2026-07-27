# Changelog

## 0.24.45 — 2026-07-23

- Public repository стал полным safe tracked team source для сборки и PR-review.
- Восстановлены активные algorithm/architecture/runbook docs из private без
  runtime data, credentials и закрытых operator runbooks.
- Добавлены индексы алгоритмов/skills и `make docs-check` в обязательный
  `make verify`.
- Public demo contract приведён к фактическому потоку:
  landing → key login → local или OpenRouter/OpenAI BYOK provider setup.

## 0.24.0.405 — 2026-07-13

- Выпущен Windows-установщик с разделением заменяемого кода и постоянных пользовательских
  данных в `%LOCALAPPDATA%\LES`; обновление сохраняет документы, индексы, настройки и результаты.
- Основной путь поиска закреплён как `dense + bm25_sparse → RRF → переранжирование →
  восстановление родительского контекста`.
- В настройках добавлены отдельные ручные действия «Проверить обновление» и «Обновить»;
  фоновой проверки и автоматической установки нет. Установщик принимается только после
  проверки SHA-256.
- В интерфейсе источников данных доступно публичное обновление ФГИС ЦС; отсутствующие цены
  не подменяются нулём.
- README обновлён: архитектура RAG, Л.И.С.Т., ФГИС ЦС, сметный контур и правила хранения
  данных описаны по-русски.

## 0.1.1.dev0 - unreleased

- Development version after the first boxed install stress release.
- Next patch target: Linux Docker smoke, Windows smoke, demo corpus/index flow,
  and release automation.

### 2026-06-17 — ИИ-СОД, табличная агрегация, типизированный ретрив, внешняя индексация

- **Позиционирование:** README переписан под «Единый центр информации о строительном
  проекте» — ИИ-СОД + агент-помощник РП и ГИП.
- **ADR-12 — типизированный двухстадийный ретрив** (`proxy/services/doc_router.py`): стадия-1 —
  LLM-роутер по каталогу документов + самонаращиваемый кэш (`doc_router_cache`); стадия-2 —
  `doc_filter` в `qdrant_adapter.retrieve/retrieve_sparse` (scope по документу). За флагом
  `LES_TYPED_RETRIEVAL`. Поверхностный поиск не мостит «серверная→СП 486» — это работа LLM.
  Док: `docs/ADR-12-typed-retrieval.md`.
- **Табличная агрегация — детерминированная SUM по полному Parquet** (а не top-k чанкам;
  ADR-11: числа считает код, не LLM). Кабель 3х1,5 по ВОР = 15 030,72 м, бит-в-бит.
- **Старые .xls читаются** (`xlrd` в deps + конвертация .xls→.xlsx в `parquet_writer`): сметы/
  ВОР/КС-2 индексируются в Parquet, а не как чанк-ошибка. Дренаж очереди индексации +
  `RAG_PARSE_MIN_FREE_GB` под 9B-модель.
- **Индексация внешней папки по ссылке** (`POST /api/rag/index-external`, `LES_EXTERNAL_SOURCE_ROOTS`):
  in-place, без копирования исходников; security — allowlist + resolve(strict) + per-file
  anti-traversal. Проверено: ИД ЭОМ → 87 файлов, 0 копий.
- **Облако через proxyapi.ru** (OpenAI-совместимый; из РФ Cloudflare/OpenRouter режется);
  локальная модель — Qwen3.5-9B-MLX-4bit (4B залипал в повторы). Чистка лишних локальных моделей.

## 0.1.0 - 2026-06-06

- First private boxed LES release.
- Published GitHub release `v0.1.0` for `proovcme/les_rag`.
- Attached boxed artifacts for:
  - macOS native;
  - Linux Docker;
  - Linux systemd;
  - Windows Docker;
  - Windows lite.
- Completed destructive macOS reinstall stress test from fresh clone.
- Fixed clean-clone launchd plist root rendering.
- Fixed missing `proxy/storage` package in clean clones.
- Fixed Sovushka startup without a pre-existing `static/` directory.
- Made MLX tokenizer preload lazy by default so health endpoints open before
  model/tokenizer warmup.
- Added empty-dataset retrieval short-circuit so fresh installs return fast
  empty search responses.
- Documented reinstall stress results in `docs/MAC_REINSTALL_STRESS.md`.

Known release scope:

- macOS native was hardware-smoked on Apple Silicon.
- Linux and Windows artifacts were packaged but not hardware-smoked.
- Fresh install starts empty; operators must add/index their own corpus.
