# HANDOFF — Л.Е.С. (состояние и бэклог на 2026-06-18)

Снимок после большой сессии «ИИ-СОД». Что работает, что НЕ сделано, и как продолжить.
Ветка: `feat/les3-p1` (запушена в public `proovcme/les_rag`, pre-release `v0.1.1-dev`).
Детали решений — `docs/ADR-12-typed-retrieval.md`, ADR-таблица в `docs/LES3_PLAN.md`.

## Что живёт и проверено

- **Позиционирование:** «Единый центр информации о строительном проекте» — ИИ-СОД + агент РП/ГИП (README).
- **Детерминированная агрегация по сметам/ВОР:** SQL по полному Parquet, не LLM. Кабель 3х1,5 = 15 030,72 м (бит-в-бит). `proxy/services/table_query_service.py`.
- **.xls читаются:** xlrd + конвертация в `parquet_writer`; дренаж индексатора; `RAG_PARSE_MIN_FREE_GB=4` под 9B.
- **Типизированный ретрив (ADR-12, флаг `LES_TYPED_RETRIEVAL=true`):** LLM-роутер по каталогу + кэш `doc_router_cache`. `proxy/services/doc_router.py`.
- **Индексация внешней папки по ссылке:** `POST /api/rag/index-external` + `LES_EXTERNAL_SOURCE_ROOTS`. ИД ЭОМ → 87 файлов, 0 копий.
- **Облако:** proxyapi.ru (Cloudflare/OpenRouter из РФ режутся). **Локаль:** Qwen3.5-9B-MLX-4bit.

## Сессия 2026-06-18 — сделано (код в репо, `make verify` зелёный, 5 коммитов)

Все пункты бэклога **кроме АРТЕЛИ** закрыты на уровне кода (детерминированные ядра, 0 LLM где обещано; 43 новых офлайн-теста). Осталось деплой/данные/мерж — см. «остатки» ниже.

1. ✅ **Сверка ВОР↔КС-2↔смета↔ИД** — `proxy/services/reconcile_service.py` (qty-приоритет + data-aware fallback по полям объёма, кластеризация позиций по ед.+наименованию, флаги match/mismatch/gap/single, допуск 1%). Роутер `/api/bor/reconcile` (preview/generate/download). 16 тестов. *Остаток: проиндексировать реальные КС-2/ЛС + распарсить ИД (87 файлов, parse=False) — это данные, не код.*
2. ✅ **GUI-вид сверки + Сводный ВОР** — карта «СВЕРКА» на странице Инструменты (`sovushka/pages/instrumenty.py`): мультивыбор датасетов, динамические колонки по источникам, цветной статус. ВОР-таблица уже была. *Остаток: живой скриншот (нужен порт в рантайм + рестарт sovushka + данные).*
3. ✅ **Мультикласс через диалог** — `proxy/services/class_router_service.py` (детектор классов норматив/смета/письмо/проект + suggestions). Чипы «Посмотреть как …» в чате (стрим+нестрим). ADR-12: «через диалог, не авто-fan-out». 10 тестов.
4. ⏸ **АРТЕЛЬ — MEP-коннекторы** (`task_91f89b7d`) — НЕ трогали по просьбе; туда применить полученные знания (W10.3 three-layer, контракты).
5. ✅ **Формирование ответа по интенту** — `proxy/services/answer_form_service.py` (value/enum/full/brief/default → каркас + потолок токенов, аддитивно к sys_normal). 9 тестов.
6. ✅ **OCR сканов → gemma4:12b** — `OllamaVisualOCRParser` + фабрика `make_ocr_parser` (RAG_OCR_BACKEND=ollama|mlx), converter переключён, MLX-путь сохранён. 8 тестов.

## Остатки (деплой/данные/мерж — НЕ код)

- **Данные:** индексировать КС-2 + ЛС(смета), распарсить ИД (87 файлов `parse=False`) → тогда сверка/мультикласс получают живой кросс-классовый контент и скриншот.
- **Деплой в рантайм:** порт изменений в `/Users/ovc/LES` + рестарт sovushka/proxy (gemma4:12b в ollama должен быть подтянут для OCR) — только осознанно.
- **#7 Влить `feat/les3-p1` → main** + настоящий релиз — когда контур стабилизируется (полный `make test` на живых сервисах + доменный golden 16/16).

## Известный долг / наблюдать

- **Валидатор Т.О.С.К.А. (coreml NLI):** точность golden ~25%, fail-open (ответ виден, штамп VERIFIED не доверять). Тюнить пороги/режимы.
- **Локальный 9B:** ~73с/ответ на M4 (холодный старт + декод). Облако (proxyapi) — быстрый primary; 9B — приватный fallback.
- **Naming-долг АРТЕЛЬ:** `Agnostis`/`MyVeras` → `ARTEL` (ренейм после стабилизации контрактов).
- **Whisper (голосовые заметки):** модель оставлена, фича не сделана (W8.2).
- **table_query поле:** работает на кабеле; на новых датасетах проверять выбор qty/amount (qty-приоритет + data-aware fallback).

## Как продолжить

- Рантайм: `/Users/ovc/LES` (live, launchd: mlx/proxy/qdrant/sovushka). Репо: `/Users/ovc/Projects/LES_v2`.
- Правки рантайма → порт в репо → `make verify` → commit. Гейт: `make verify` (офлайн).
- Память агента: `MEMORY.md` + `les3-rag-intake-state` (бэклог), `cloudflare-blocked-use-openai-direct`, `mlx-model-choice-m4`, `legion-build-workflow`, `artel-*`.
- Тесты сессии: `tests/test_table_query_service.py`, `tests/test_external_index.py` (15/15 зелёные).
