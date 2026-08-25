# Release cut after 0.28.1

Согласованная нарезка поверх публичного Windows `0.28.1` / build `588`.
План коллеги по слоям верный: сначала неубиваемый установщик, потом Agent Foundation,
потом действия. Живой Legion добавляет обязательный сметный слой **до** 0.29.

## Номера

| Версия | Build | Что | Статус |
|---|---:|---|---|
| `0.28.1` | 588 | Публичный GitHub EXE | выпущен |
| `0.28.2` | 589 | Срочный hotfix установщика и лимитов профиля | **зарезервирован** за коллегой |
| `0.28.3` | 590 | Файловые ЛСР/ВОР tools + живой SSE + анти-503 стрима | этот PR, candidate |
| `0.29.0` | — | Agent Foundation | harness-референс, не wholesale-port |
| `0.29.1` | — | compute / draft / approval / receipts / MCP parity | после 0.29.0 |

Локальные Python-копии на Legion кратко назывались `0.28.2–0.28.4` / `589–591`.
Это **не** GitHub-теги. Повторять эти номера в релизе нельзя.

Если установщик `0.28.2` вмержится первым — этот PR просто ребейзится и остаётся `0.28.3`.
Если этот PR вмержится первым — установщик всё равно занимает `0.28.2` только пока `0.28.3`
ещё не в `main`; после этого установщик становится `0.28.4`. Предпочтительный порядок:
сначала `0.28.2` установщика, затем `0.28.3`.

Не смешивать с грязной веткой качества `0.27.93` и не переносить wholesale дерево harness `0.29.1`.

## 0.28.2 — установщик и профили (план коллеги, берём)

Уже подтверждено живым сбоем tray «Перезапустить службы»:

- Docker и Qdrant не блокируют LES Core;
- lock-bound marker готового venv;
- повторный `uv sync --locked --offline` только при смене lock/runtime или порче окружения;
- `requires-python = ">=3.12,<3.14"` (иначе резолвер лезет в split `python >= 3.14`, `google-adk` нет в offline cache);
- двойной последовательный offline-install test;
- отдельные сообщения для Docker, Qdrant и venv вместо одного `bundled_runtime_unavailable` / «переустановите ЛЕС»;
- пользовательский skill ≤ 8 000 символов, prompt ≤ 16 000; счётчики и серверный отказ сохранить превышение;
- 8k/16k ограничивают редактируемые поля профиля, не общий prompt packet модели.

### Обязательные дополнения с Legion

1. `LES_TAURI_ACTION=restart` не должен заново разворачивать Python. Сначала marker, потом `stop-light` + `start-light`.
2. Не копировать `pyproject.toml` в установленный runtime без того же `uv.lock`. Версия продукта — только `config/version.json`.
3. В dual offline-install test явно: tray restart без сети на уже готовом venv.
4. Factory skill сметчика + короткий appendix tools должен влезать в 8k.
5. Health `files=0` при опубликованных нормах в Qdrant — не поломка установщика.

Этот PR **не** реализует 0.28.2. Он только резервирует номер и фиксирует живые баги.

## 0.28.3 — этот PR (estimator file tools)

Профиль «Сметчик» в 0.28.1 ходит в ordinary native-RRF evidence flow и **не** вызывает
скрытый chat-route intercept. Без файловых tools готового xlsx нет.

Контракт:

- модель выбирает инструмент; код пишет файл;
- `build_lsr_workbook` оборачивает существующий `run_smeta_document_application` (модель не передаёт цены/строки);
- `build_vor_workbook` пишет количества из intake / spec→ВОР без расценки;
- `document_workflow` не переписывается;
- `dataset_ids is None` (scope «весь RAG») — пустой список, не падение tool-loop;
- LSR-tool исполняется на asyncio-цикле FastAPI с `token_sink`, чтобы шли `smeta_row` / `smeta_step`;
- режим `estimator` в сценарии прогресса, не «Формирую ответ»;
- read-timeout стрима минуты, не 300 с тишины;
- после живого прогресса клиент **не** ретраит `/api/chat` (это давало `503 ram_free_gb < 2.0`);
- гард 2 ГБ RAM оставить; плашка во время сборки — норма.

35B на Legion — не `ollama pull` плотной модели. Это FreeToken
`Qwen3.6-35B-A3B-NVFP4` на `127.0.0.1:1919/v1`, эмбеддинги остаются Ollama `bge-m3`.
9B и 35B одновременно не держать. Для 0.28.3 default генерации остаётся `qwen3.5:9b`.

## 0.29.0 — Agent Foundation (план коллеги, берём как архитектуру)

Канонический Tool Registry, адаптеры Qwen/FreeToken/MCP/API, Capability Broker,
Trusted Executor, ContextGovernor, общая Memory projection, отдельные пресеты
Qwen 9B и Qwen 35B, миграция read-only tools, наблюдаемость токенов / compaction / overflow.

Не блокировать 0.28.2/0.28.3 этим слоем. Не переписывать `document_workflow`.
Пресет 35B на 16 ГБ — fail-closed по VRAM; ODS Coder и тяжёлый LES-Ollama вместе запрещены.
LSR/VOR в 0.29 становятся capability-tools с Trusted Executor, а не свободным artifact.

## 0.29.1 — действия

compute-tools, автоматические draft-tools, approval для commit/external/destructive,
idempotency и action receipts, полная MCP↔️internal parity.

Локальная ЛСР-xlsx уже черновой write-tool без approval. Для денег достаточно
предупреждения «долго и жрёт RAM», не тот же gate, что у destructive/external.
Полная MCP-parity не должна блокировать выдачу LSR/VOR.

## Живые баги, которые ещё могут всплыть

- Первая ЛСР по PDF-ВОР: десятки минут до первой строки → нужен heartbeat SSE.
- Старый чат держит snapshot профиля без новых tools → «применить активную версию» или однократный migrate.
- Вложение съедается после успеха; после 503 файл в UI может быть сброшен.
- Повтор «собери ЛСР» должен resume checkpoint, а не вторую полную сессию.
- Нормы в Qdrant есть, проектного корпуса нет — модель снова нарисует markdown-таблицу, если tool не вызовется.
