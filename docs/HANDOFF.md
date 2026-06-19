# HANDOFF — Л.Е.С. (снимок на 2026-06-19)

Состояние после большой сессии RAG-функционала СОД. Что работает, что открыто, как продолжить.

- **Репо (dev):** `/Users/ovc/Projects/LES_v2`. **Рантайм (live):** `/Users/ovc/LES` (launchd: qdrant/mlx/proxy/sovushka; origin клона — `LES_v2_reinstall_stress`, диверговый).
- **Деплой:** правка в репо → `cp`/точечный Edit изменённых файлов в `/Users/ovc/LES` → `launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy` (и `com.les.sovushka`). НЕ `git pull` (история расходится). Файлы из dirty-set (`chat.py`/`datasets.py`/`parquet_writer.py`/`samovar.py`) — патчить Edit'ом, не overwrite.
- **Гейт:** `make verify` (офлайн). Полная сюита — `make test` (нужны живые Qdrant/MLX). Доменный golden — `tools/rag_golden_set.py` 16/16.
- **Git:** ветка `feat/les3-p1` запушена в приват `proovcme/les_rag` + **PR [#1](https://github.com/proovcme/les_rag/pull/1)** (→ main, на ревью). Публ. snapshot `proovcme/les_rag_public` — обновлён только README (внутренние/заказчиковые доки туда НЕ льются). `main` не тронут.

## Что живёт и проверено (ядро)

- **Числа считает код, не LLM** (ADR-11). Кабель 3х1,5 = 15 030,72 м бит-в-бит (`table_query_service`, `docs/ALGO-table-query.md`).
- Типизированный ретрив ADR-12 (`LES_TYPED_RETRIEVAL=true`), гибрид+реранк, валидатор Т.О.С.К.А.
- Облако — proxyapi.ru (primary); локаль — `Qwen3.5-9B-MLX-4bit` (fallback). OCR скан-PDF — **ollama `gemma4:12b`** (`RAG_OCR_BACKEND=ollama`, GLM-OCR удалён).

## Сделано в сессии (W11.4–11.17, ~50 офлайн-тестов, всё задеплоено и проверено вживую)

- **Сверка** ВОР↔КС-2↔смета↔ИД (`reconcile_service` + чат-канал `reconcile_chat_service`, ось `by=dataset`): `/api/bor/reconcile`, GUI-карта, чат «сверь…». Флаги match/mismatch/gap/single, фильтр шума, чистые ярлыки. Живо нашло: **Коробка Batibox ВОР 395 vs Акт/ИД 68 (Δ 82.8%)**.
- **ВОР из спецификации (форма 9)** — `spec_to_bor_service` (`docs/ALGO-spec-to-bor.md`), `/api/bor/{id}/from-spec`, GUI-переключатель, чат «сделай ВОР из спецификации». Фикс парсинга `Наименование…материалов`→name.
- **Типовые формы** по стандартам (docx/xlsx/html): `spec_gost21110` (ГОСТ 21.110 ф.1), `vor`, `smeta_lsr` (ЛСР 421/пр), `aosr`. `forms_service` расширен под табличные формы (`columns`+`table`).
- **Сводка проекта** (стадия/ТЭП/состав) — `project_summary_service`, чат «дай сводку проекта». Каркас.
- **Чат:** intent→форма ответа (`answer_form_service`), мультикласс через диалог (`class_router_service`), **память диалога** (`session_memory`) + **авто-заметки** фактов (`maybe_autonote`), усиленный тон.
- **/-команды** (`command_service`): `/спецификация //вор //смета //акт //сверка //сводка //мсп //команды`; `GET /api/commands`; GUI «/»-палитра.
- **Почта/Outlook:** IMAP из GUI (Самовар, пресеты M365/Outlook.com); архивы `import-archive` — `.olm` (Mac, stdlib `olm_reader`), `.pst` (Windows, **libpff установлен**), `.msg`. Скрепка чата (`/api/rag/attach`), браузер папок (`/api/rag/browse-external`).
- **MCP-сервер** — `tools/les_mcp_server.py` (FastMCP/stdio, 6 инструментов наружу). **Доказано end-to-end** (внешний клиент вызвал `les_reconcile`).
- **Доки:** README причёсан (зачем/сильные стороны/функции/Mermaid), `ALGO-table-query`, `ALGO-spec-to-bor`, блог про LLM-арифметику.

## Открыто / следующее

1. **Данные (приоритет под кейс ГИП/котельной):**
   - ИД распарсены **17/87** (`M74_ID_EOM_Index`) — догнать 70 при свободной RAM (сканы пойдут через gemma-OCR). В корпусе **нет настоящих КС-2/ЛС** — нужен реальный КС-2/смета от Олега для содержательной сверки.
   - **ТЭП-якоря `project_summary` калибровать на реальной котельной** (сейчас на ВОР ТЭП пусто — ожидаемо).
2. **Fuzzy-match наименований** (артикул/типоразмер как ключ) — чтобы сверка ловила одинаковые позиции с разным написанием (сейчас «Кабель ППГнг 3х1,5» ≠ «Кабель 3х1,5 ВВГнг» → gap, и это верно для РАЗНЫХ кабелей).
3. **Автозаполнение форм** из данных объекта (спецификация ← оборудование, ВОР ← bor, смета). Сейчас формы — бланк по ГОСТ.
4. **#7 Мерж PR #1 → main + релиз** — после стабилизации (полный `make test` + golden 16/16). Придержано Олегом.
5. **MCP-клиент** — точечно, под внешние действия (напр. MS Project), вне детерминированного ядра.
6. **АРТЕЛЬ** — MEP-коннекторы (`task_91f89b7d`), туда применить W10.3 three-layer/контракты.

## Известный долг / наблюдать

- **Валидатор Т.О.С.К.А. (coreml NLI):** golden ~25%, fail-open (штамп VERIFIED не доверять). Текущий дефолт — `rules`.
- **9B:** ~73с/ответ на M4 (холодный старт). Облако — быстрый primary.
- **Runtime extras:** `libpff-python` (.pst) и `mcp` поставлены `uv pip install` (не в `--extra mac-mlx`) → любой `uv sync` их уберёт; переставить или синкать `--extra mac-mlx --extra mail-pst --extra mcp`.
- Naming-долг АРТЕЛЬ (`Agnostis`/`MyVeras`→`ARTEL`); Whisper (голос) не сделан.

## Память агента

`MEMORY.md` + `les3-rag-intake-state` (бэклог/состояние), `sovushka-tone-and-memory` (тон/память/авто-заметки), `les-mcp-server-plan` (MCP готов), `mlx-model-choice-m4`, `cloudflare-blocked-use-openai-direct`, `runtime-uv-sync-mlx-extra`, `artel-*`, `forms-architecture`.
