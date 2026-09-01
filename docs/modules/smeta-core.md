# Smeta Core — исторический/экспериментальный контур

> **Текущий production-путь находится не здесь.** Активный чат использует
> `chat_evidence_application_service.py`: вложение + выбранный датасет → модель
> формулирует все запросы → общий RAG → та же модель выдаёт `answer + rows` →
> код после model result рассчитывает и упаковывает XLSX. Описанный ниже
> `document_workflow.py` сохранён как история экспериментов и совместимость; его
> catalog/search/read/confirm loops не являются продуктовой архитектурой.

## Retrieval-only acceptance (v0.27.73)

Активный паспорт чистой ФСНБ использует тот же embedding space, что и его
опубликованный Qdrant-индекс: `bge-m3`; Windows installer направляет embeddings
в Ollama. `tools/smeta_retrieval_recall_probe.py` проверяет top-k отдельно от
Big Qwen, reranker, catalog routing и document workflow. Строгие кейсы содержат
только подтверждённые пары; бытовые неоднозначные перефразировки считаются
stress-наблюдением, а не ложным профессиональным golden.

## FreeToken one-row transport (v0.27.72)

Legion FreeToken/Big Qwen runs the existing document workflow with `batch_size=1`:
one immutable source row enters each model batch, and every accepted row is written
to the existing durable attachment checkpoint before the next row. FreeToken does
not support constrained `response_format`, so the same model serializes its decision
through the forced terminal function `submit_estimate_mapping`. No second model,
card phase or smeta-specific reranker is introduced. On failure the exact chat
attachment remains available for resume; code validates identity/provenance and does
not replace the model's professional choice.

FreeToken's KV budget includes both the prompt and reserved generation. Ordinary
agent tool turns therefore reserve at most 1024 output tokens: compact tool
arguments remain complete, while later turns are not rejected merely because a
4096-token generation allowance consumed the remaining context window.

Context is managed as a transport projection, not by rewriting the model's
decision. The durable checkpoint retains the full conversation/audit. Each
FreeToken inference frame keeps the immutable system/source prefix, latest
assistant/tool exchange, current `smeta_norm_agent_working_memory_v1`, and any
terminal instruction. The working-memory contract is already authoritative in
the document workflow; historical tool turns remain available for audit/resume
without consuming every later KV frame.

Reproducible live transport gate (no dataset, checkpoint or smeta run):

```powershell
uv run python tools/freetoken_context_probe.py --input-tokens 6200 --max-tokens 1024
```

The gate uses FreeToken's own `/v1/messages/count_tokens`, then performs exactly
one forced `report_probe` tool-call. It proves transport capacity separately
from professional norm selection and the multi-turn document workflow.

## Fast local catalog transport (v0.27.60)

Windows stability profile (`config/local/windows-cuda.env`): `MAX_TOOL_TURNS=10`,
`TEMPERATURE=0.2`, `TOP_P=0.9`, repair=1, local global review off, batch_size=1.
Self-contradicting `exact` binds return the model to tools with
`smeta_exact_deny_broaden_v1` (broaden/unbound) instead of burning schema repair
on the same norm. `model_batch_candidate` binds do not publish
`route_evidence_cache`. Rows left without a terminal decision become
`model_batch_open` and still produce Excel — code never invents a rate.

## Fast local catalog transport (v0.27.59)

`MappingValidationExhausted` after one bounded schema repair no longer raises
through the document batch loop as a hard «ЛСР не собрана». The stuck batch is
skipped (`batch_skipped_after_mapping_failure`); later rows continue; a partial
LSR is finalized from accepted decisions with uncovered rows left open.

## Fast local catalog transport (v0.27.57)

Soft incomplete `unbound` becomes `model_batch_candidate` only after the row has
real tool evidence (at least one `search_norms_batch` or opened card). Catalog-only
unbound with zero searches is rejected again so demo rows are not closed empty.

## Fast local catalog transport (v0.27.56)

Local Ollama/Qwen document LSR defaults: `max_turns=8`, evidence-repair `1`,
and `require_global_review=false` (override with `LES_SMETA_LOCAL_GLOBAL_REVIEW=1`).
An honest `unbound` with a reason and incomplete evidence is accepted immediately
as `model_batch_candidate` — no second structured mapping retry that burned
5–40s/row on demo runs.

## Fast local catalog transport (v0.27.55)

`selection_kind=exact` binds whose own `reason` denies applicability
(«не применима», «не соответствует», «не совпадает», «не подходит») are
rejected as incomplete bind evidence and are never draft-promoted. Code does
not pick another norm; the model must unbound or broaden.

## Fast local catalog transport (v0.27.54)

Conflict-group global review no longer aborts a completed document LSR when
structured mapping fails after bounded schema repair (`incomplete bind
evidence`). The packet keeps the initial row-mapping decisions, and draft-eligible
incomplete binds can be promoted to `model_batch_candidate` before a hard
RuntimeError. Row quality remains model-owned; code only preserves terminal
mapping instead of destroying it.

## Fast local catalog transport (v0.27.53)

`route_evidence_cache` is published only after a successful bind — never on
mere table select. Unbound and `broaden_norm_catalog` drop routes sourced by
that work. `_completed_route_cache` exposes only bind-proven tables so a wrong
first table cannot poison every later VOR row via reuse.

`norm_evidence` tools are search/read/`broaden_norm_catalog` (still no
reuse/browse). After opened typed cards, the model gets one free turn to bind
or broaden; structured mapping is forced on the second evidence turn.

## Fast local catalog transport (v0.27.52)

Identical catalog tool retries no longer force unbound mapping unless the row
already has search/read evidence. Ollama tool-call XML HTTP 500 retries once
with `seed+1` and a short nudge; a second failure soft-degrades to an empty
tool turn with recovery instead of aborting the whole VOR batch. Mapping
exchange also retries once on XML 500.

## Fast local catalog transport (v0.27.51)

`norm_evidence` never exposes `reuse_norm_catalog_route` / browse. When any
active work already has opened typed cards, the agent forces structured mapping
on the next turn so the first LSR row appears instead of a reuse spin loop.

## Fast local catalog transport (v0.27.50)

When the model reaches `norm_search` with a selected table, LES executes one
scoped `search_norms_batch` from the VOR title (two lexical queries) before the
next model turn — same spirit as auto root browse. Flat
`reuse_norm_catalog_route` args are normalized to `items[]`. Reuse-first
working-memory text is limited to early catalog phases so Qwen does not spin
reuse after the table is already chosen.

## Fast local catalog transport (v0.27.49)

After catalog `unbound`, `norm_evidence` exposes only search/read (no browse) and
the accepted unbound row sets `force_mapping_serialization` so the agent does not
burn identical `browse_norm_catalog` retries. An identical failed tool call also
forces mapping immediately (conversation reset removed). Unbound while still on
a family/collection node is rejected as premature — model must `broaden` to
`catalog:root` before closing the route.

## Fast local catalog transport (v0.27.48)

`family_select` keeps Ollama-safe `continue_norm_catalog` with `items[]` and
minimal required fields (`work_id`, `selected_node_id`, `confidence`). A flat
top-level schema caused Ollama HTTP 500 (`parameter` closed by `</function>`).
Menu-echo of passport cards into `items[]` is still rejected with an `items[]`
example; flat decision args remain accepted only as transport normalization.

Hybrid Qwen calls (`items[]` + top-level `selected_node_id`, evidence only for
rejected siblings) merge the top-level selection into the item and draft
passport evidence for the model-chosen child so catalog can advance. The chosen
node is dropped from `rejected_nodes` when both are set. After three identical
catalog rejects (`catalog_stalled`) or an identical duplicate tool call while
stalled, the agent forces mapping/unbound serialization instead of burning more
`model_wait` turns. Native Ollama document exchange retries once on tool-call
XML syntax HTTP 500.

At wide table menus, more than six `rejected_nodes` are truncated (not rejected).
Local Ollama/Qwen also defaults `LES_SMETA_NORM_RERANK=false` when unset.

Typed family→collection / section→table menus proceed when shortlist cards exist,
even if the cross-encoder is missing (`fallback_input_order`). Empty shortlist
remains a hard reject. Evidence that cites `catalog:root`/parent while selecting
a visible child is remapped to that child when the field exists there.

Chat `run_smeta_document_application` always passes `require_scoped_search=True`
(same contract as RIM / `smeta_document_local_run`). Phase tools expose
`continue_norm_catalog` with `selected_node_id` enum; legacy
`browse_norm_catalog(decision=continue)` without a node is not the chat path.

On non-cloud Ollama+Qwen (and `qwen_agent`), document LSR defaults to
`batch_size=1`, `LES_SMETA_DOCUMENT_MAX_TOOL_TURNS=12`, search/read budgets `3`,
and `LES_SMETA_MAPPING_EVIDENCE_REPAIR_TURNS=2` unless the operator already set
those env vars. `batch_size>1` stays off for local Qwen JSON stability.

When `route_evidence_cache` is non-empty, working memory sets `route_reuse_first`
and asks the model to call `reuse_norm_catalog_route` before browsing from
`catalog:root`. Reuse transfers verified scope only; search/read and the model's
norm choice remain mandatory. Source-batch progress reports `rows_done`,
`elapsed_sec` and `sec_per_row`.

Document LSR requires a server-owned `read_*` attachment. PDF attached as chat
«Таблица» (`quick`) is promoted to `read_*`; without `attachment_id` the smeta
path returns an explicit mode error instead of estimate-harness with 0 rows.

## PR #8 accepted with production corrections (v0.27.35)

The useful local-Qwen transport and document-output work from public PR #8 is
ported on top of the current tree rather than merged wholesale. Mapping JSON
accepts trailing commas and schema output placed in Ollama's `thinking` field;
a length retry uses compact context while preserving the model-owned decision.
Typographic dashes and display aliases are transport-normalized only against an
already opened typed card. Code still does not choose or replace a norm.

Filled KS-2/KS-3 exports from LSR are always marked
`draft_from_lsr_not_execution_fact`; KS-6а reads only confirmed journal rows of
the explicit project. Low-coverage LSR workbooks label their total as the cost
of the bound part. Global newest-artifact fallback and code-owned demotion of a
model decision from the prototype are intentionally excluded.

## Candidate-draft boundary (v0.27.34)

Qwen receives one bounded repair turn when its selected opened typed card
contradicts its own applicability audit. If the same model still submits a
professionally questionable but structurally valid choice, LES preserves that
choice as `model_batch_candidate`, calculates the visible draft, and attaches
`model_candidate_mapping` with the exact validation reasons. Missing/unopened
typed references, incompatible units, malformed evidence and invalid work
links remain hard failures. `LES_SMETA_CANDIDATE_DRAFT_MODE=off` restores the
strict rejection loop; `LES_SMETA_FLEXIBLE_RESOLVER_MODE=legacy` remains the
separate Gemini-compatible rollback for transport interpretation.

The same visible-candidate boundary applies to a repeated honest `unbound`
whose search trace is incomplete: LES stores no invented queries, marks the
row `model_batch_candidate`, adds `model_candidate_unbound`, and keeps it
ineligible for Memory. A positive reference to an opened card, an invalid
cross-row link, or fabricated evidence still remains a hard contradiction.

Post-budget evidence repair (`LES_SMETA_MAPPING_EVIDENCE_REPAIR_TURNS`) is
granted once. Re-arming it on every failed unbound submit prevented the
candidate-draft second serialization on local Ollama and ended in
`RuntimeError: … after bounded repair`. If the finite loop still ends with only
`invalid unbound_evidence` after one reject, LES performs one terminal re-submit
to promote the visible candidate without inventing queries.

> Единый человеко-машинный паспорт всего модуля —
> [SMETA_MODULE_EXPLAINED.md](../SMETA_MODULE_EXPLAINED.md): архитектура, skill, полный active prompt,
> Qwen row-loop, ФСНБ/ФГИС, расчёт, UI, настройки, тесты и ограничения.

> **Статус 2026-08-02: ✅ СМЕТНЫЙ МОДУЛЬ ПРИЗНАН СТАБИЛЬНЫМ v0.3 (v0.27.29).** Канонический PDF→ЛСР путь —
> model-owned evidence loop, immutable построчный mapping, обязательная глобальная модельная ревизия,
> автoчерновик и отдельный пользовательский lock перед финальным расчётом.
> Архитектурное решение и судьба экспериментальных веток зафиксированы в
> [ADR-13](../ADR-13-smeta-session-workflow.md).

## Архитектурная граница

```text
исходник / ВОР / спецификация
  → source_intake: строки, количества, единицы, координаты
  → SmetaAgentRunner: native | Qwen-Agent | Google ADK
  → модель + skills/smeta/references/document-mapping-agent.md
  → browse_norm_catalog: typed-карта семейство → сборник → официальная таблица
  → smeta_scope_plan_v1: scoped(base_types/collections) | global, всегда выбран моделью
  → search_norms_batch: ScopePlan → RRF/FTS + rerank либо полный listing выбранной таблицы
  → read_norms_batch: фактические карточки Typed SQLite
  → submit_lsr_mapping: завершённое решение той же модели по активной строке/пакету
  → smeta_row: готовая строка сразу появляется в живой таблице чата
  → professional_conflict_v1: детерминированные противоречия без выбора ответа
  → global_review: та же модель проверяет связанные группы конфликтов; остальные решения переносятся дословно
  → calculator: единицы, ресурсы, цены, РИМ, НР/СП, НДС
  → priced_draft XLSX → пользовательский mapping_locked → отдельный финальный расчёт
```

Модель выбирает работы, декомпозицию, запросы, нормы, аналоги, coverage и ресурсные действия
`add|replace|exclude|reuse`. Код не выбирает и не переписывает решение модели. Он проверяет машинную
адресацию и выявляет доказуемые профессиональные противоречия; они передаются той же модели в
обязательную cross-row ревизию, но не содержат готовой замены. Непрочитанная карточка и несовместимая
единица сохраняются в модельной ревизии как построчные расчётные blockers. Неполный
`technology_check` возвращается той же модели как ошибка terminal-полноты; код не оценивает её
профессиональный вывод. Python не содержит второго профессионального
prompt: фазовый контракт находится внутри canonical skill package и содержит только правила mapping,
а не нерелевантные этой фазе РИМ/ФГИС/НР/СП и оформление ответа.

`SmetaNormToolSession` хранит показанные карточки, принятые строки и trajectory. Все runner'ы
исполняют один и тот же контракт; встроенные RAG, MCP, Google Search и code interpreter выключены.
`native` остаётся default до живого профессионального гейта. `qwen_agent` использует локальный
Ollama; Qwen-Agent управляет loop, но на актуальном Ollama включает raw function serialization,
так как Nous text wrapper возвращает серверный `500 EOF`. `google_adk` — прямой Google API только
после `LES_CLOUD_CONSENT=true`; отсутствие ключа или
согласия является явной ошибкой без fallback.

Если Qwen-Agent завершил исследование обычным текстом без `submit_lsr_mapping`, runner повторно
предъявляет **той же модели и той же истории** только требование terminal serialization. Это один
ограниченный recovery-этап, а не fallback и не выбор кода. Для `unbound` session сверяет перечисленные
запросы и открытые коды с фактической tool trajectory; при расхождении возвращает модели
`allowed_evidence`, чтобы она сама исправила provenance. Для существующего `bind` recovery требует
полный `technology_check`. Пустой или выдуманный evidence не создаёт `row_ready`.
Если structured terminal показывает, что для собственного решения модели физически не открыты
карточки или не выполнены поиски, JSON-починка недостаточна: та же Qwen один раз возвращается в LES
tool-loop с точным validation feedback, сама выбирает evidence и затем повторяет terminal. Для ошибок
только формы исследование не возобновляется.

В локальном контуре ВОР остаётся одной задачей, а phase scheduler собирает все строки, находящиеся
на одинаковой минимальной фазе `family→collection→section→table→search→read`, в один model turn и
один batch tool call. Следующая строка получает исходные поля, соседний контекст и компактный
`task_state` со всеми уже принятыми моделью решениями. Этот журнал нужен для coverage и поиска
дублей; Python его не редактирует и не выбирает решение. После успешного
`submit_lsr_mapping` session публикует `row_ready`, application переводит его в SSE `smeta_row`, а
Совушка обновляет таблицу внутри текущего сообщения. Черновые кандидаты в таблицу не выводятся.
Каждая валидная строка сохраняется отдельным durable checkpoint непосредственно при принятии,
до проверки следующей строки того же JSON-пакета. Повторный запуск продолжает только оставшиеся
`work_id`; готовые модельные решения не генерируются заново. Structured mapping сериализуется порциями до
`LES_SMETA_DOCUMENT_MAPPING_CHUNK` строк (default 8). Timeout останавливает идентичный
детерминированный запрос после первой попытки и сохраняет уже принятые строки. Для локальной
диагностики тот же контракт доступен через `tools/smeta_document_local_run.py`.

При document-level resume внутренний `tool_session` применяется к первой незавершённой строке
только при точном совпадении её `work_fingerprint`. Если checkpoint уже завершил предыдущую строку,
её immutable selection сохраняется, а следующая строка начинает чистый tool-session. Live benchmark
можно продолжить в том же каталоге через `--resume-run <run_root>`; source SHA, профиль модели и весь
fixed contract проверяются до продолжения.

Отдельных обязательных resource-review, impact-review, dominant-review и `finish_norm_selection` нет.
После построчного mapping conflict-validator строит связанные компоненты по общим `work_id`.
Модель получает только эти группы пакетами до `LES_SMETA_GLOBAL_REVIEW_ROWS` строк (default 8);
решения строк без конфликтов переносятся в новую immutable revision дословно. Её расчёт имеет
статус `priced_draft`; endpoint `/api/smeta-mappings/{revision_id}/lock` создаёт пользовательскую
immutable lock-ревизию и только затем отдельный финальный расчёт.
Одинаковая норма у похожих строк того же раздела/измерителя создаёт
`possible_duplicate_norm_binding`: validator ничего не меняет, а требует у global review или
пользователя явной проверки coverage и двойного учёта. Неразрешённый warning остаётся в draft.

Conflict-only global review возвращает полный terminal mapping вместе с согласованным
`valid_model_rows`; техническая граница документа не может трактовать сохранённые model-owned
решения как ноль валидных строк. Счётчик вычисляется только из ключей уже принятого mapping и не
выбирает, не исправляет и не удаляет профессиональные решения модели.

## Точки входа

- `proxy.smeta_core.application` — единственная публичная application-граница смет: model-first
  workflow, расчёт уже принятых решений, immutable revision и finality.
- `proxy.smeta_core.document_workflow.run_vor_pdf_workflow` — zero-state PDF→ЛСР.
- `proxy.smeta_core.document_workflow._run_batch_norm_agent` — тонкий tool-loop модели.
- `proxy.smeta_core.document_workflow.SmetaNormToolSession` — единое состояние и исполнение LES tools.
- `proxy.smeta_core.professional_review` — typed mapping revisions, evidence budgets, conflict-validator
  и quality metrics; профессиональных решений не принимает.
- `proxy.services.smeta_agent_runner_service` — общий интерфейс и адаптеры Qwen-Agent/Google ADK.
- `tools/smeta_agent_benchmark.py` — изолированный quick/full гейт исходной ВОР; его проверки не
  импортируются production workflow.
  Последовательный quick-тест запускается так:
  `uv run python tools/smeta_agent_benchmark.py <путь-к-ВОР.xlsx> --engine qwen_agent --phase quick --batch-size 1`.
- `tools/smeta_model_quality_benchmark.py` — воспроизводимый live A/B двух локальных Ollama-моделей
  на полном каноническом XLSX/PDF→ЛСР workflow. Профили получают один request/system skill, corpus,
  tools, seed, context/token limits, `batch_size=1`, scoped search и global review. Harness проверяет
  реальный durable resume через одинаковое cooperative-прерывание, сохраняет по каждому профилю
  `result.xlsx`, полный `workflow.json`, `analysis.json` и `tool-events.jsonl`. Формальная целостность
  нормы/единицы/объёма/provenance отделена от профессиональной правильности: без явного
  `les.smeta.qrels.v1` с совпадающим полным `source_sha256` последняя остаётся
  `not_adjudicated`, а не угадывается кодом или моделью. Manifest фиксирует SHA-256 фактического
  system prompt и полного tool contract, digests моделей и активные Qdrant aliases/point counts.
  Запуск: `uv run python tools/smeta_model_quality_benchmark.py <ВОР.xlsx>`; продолжение сохранённого
  прогона: та же команда и параметры плюс `--resume-run <run_root>`.
- `proxy.services.smeta_chat_application_service` — application flows ordinary smeta и PDF→ЛСР:
  безопасно открывает одноразовое вложение, координирует RAG/model/progress, сохраняет artifact/trace
  и возвращает response envelope. Профессиональных решений не принимает.
- `proxy.services.smeta_chat_adapter_service` — smeta transport/RAG adapters, prompts и parsers:
  runtime провайдера, document exchange, evidence packet, model-owned lookup/choice и numeric audit.
  Router этих реализаций не содержит и не собирает их вручную.
  Модель документа задаётся отдельно от модели обычного чата (`LES_SMETA_DOCUMENT_MODEL`). Для
  чистого сравнения резерв можно отключить пустым `LES_SMETA_DOCUMENT_FALLBACK_MODEL`.
  Для Ollama используется нативный `/api/chat`, потому что совместимый `/v1/chat/completions` теряет
  tool-calls `gemma4:12b`; tool results переводятся в нативное поле `tool_name`, а OpenAI-поля
  `name/tool_call_id` не передаются как будто это тот же протокол. Это transport-различие, а не
  отдельная логика выбора норм.
  Облачная модель по умолчанию получает всю ВОР одним разговором. Локальный native runner
  получает транспортные пакеты до 5 строк с общим контекстом соседних строк: это защищает `work_id`
  и tool JSON от смешивания/обрыва, но не выбирает нормы и не дробит общую immutable-ревизию.
  Оба document exchange используют `temperature=0`; локальный повторяемый профиль дополнительно
  передаёт `LES_SMETA_DOCUMENT_SEED` (default `0`) и сохраняет seed в trace. Нормализованные
  model-authored запросы и пакетные tool-вызовы сортируются перед retrieval без изменения scope.
  Qwen-Agent получает одинаковую текущую фазу сразу для нескольких строк и накопленный
  `task_state` общей задачи.
  Ordinary-text завершение получает ограниченный same-model terminal recovery; отсутствие или
  расхождение `unbound_evidence` с tool trace отклоняет только transport-пакет, не решение модели.
  Полный список чужих `work_id` в пакет не копируется: для проверки coverage используются только
  `neighbor_context` текущих строк, иначе локальная модель ошибочно вызывает tools по всей ВОР.
  `LES_SMETA_DOCUMENT_BATCH_SIZE=0` явно возвращает один разговор; положительное значение меняет
  только размер транспортного пакета. Значение `1` включает накопленный последовательный контекст
  только для `qwen_agent`; профессиональные решения остаются модельными.
  Если модель без изменения содержания вложила `work_id` внутрь `technology_check`, transport
  переносит только этот идентификатор на верхний уровень. Норма, applicability, ограничения,
  resource actions и профессиональная аргументация остаются буквально модельными. Аналогично,
  одиночный `norm_code` в `read_norms_batch` принимается как одноэлементный `norm_codes`; значение
  кода не исправляется и не подменяется. Python не дополняет профессиональное решение. Отсутствующая
  обязательная анкета возвращается модели как ошибка transport-полноты; непрочитанная карточка или
  несовместимая единица сохраняют решение, но расчётный слой
  проверяет возможность вычисления построчно: несовместимая строка остаётся в ревизии модели и
  получает blocker, а остальные строки продолжают считаться.
- `proxy.smeta_core.norm_browser.browse_norm_catalog` — актуальная typed-навигация по семействам,
  сборникам и таблицам без статического списка в prompt.
- `proxy.smeta_core.norm_browser.browse_norms_many` — пакетный scoped RRF/FTS + configured reranker;
  выбранные моделью `table_codes` возвращаются полным официальным меню без ranking.
- `proxy.smeta_core.calculator.calculate_visible_rows_revision` — один расчёт решения модели.
- `proxy.services.smeta_user_message_service` — человеческое сообщение из готовой summary.
- Прежние `etm_price_service` и `/api/prices/etm/*` удалены в 0.30.21 как
  неиспользуемый альтернативный price island. Живой точный источник —
  `fgis_price_service`; КАЦ остаётся model-owned через свои evidence sources.
- `proxy.routers.chat` — request context, вызов application flow и общий history/response contract.

`estimate_harness_service` временно исполняет старый tool-loop только за
`smeta_core.application`; это implementation adapter, а не самостоятельная точка входа.
`construction_harness_service` и `unified_construction_harness_service` помечены
`LEGACY_PRIVATE`, остаются feature-off для старых evidence-fixtures и не входят в сметный маршрут.
Их старый `gesn_expand` больше не выбирает первый candidate кодом: он останавливается на
model-visible candidate list.

## Инструменты модели

### `browse_norm_catalog`

Возвращает текущую карту `family → collection → table` typed-каталога. Семейство, сборник и таблицу
выбирает модель. Повтор одной страницы возвращает короткий `already_seen`. Каталог является
навигацией, а не решением о применимости нормы.

### `search_norms_batch`

Принимает любое число независимых `work_id`, поисковые формулировки с обязательным `search_intent`
и выбранные моделью `base_types`/`collections`/`table_codes`. Обычный shortlist проходит configured
cross-encoder даже в batch из пяти и более строк; transport failure виден как `rerank_status`.
Выбранная таблица возвращается полностью по коду, без top-k и rerank: код не скрывает selector-range
и не выбирает строку. Кандидат сразу показывает `source_ref` и краткий
состав работ, а также `norm_key`, редакцию, семейство/сборник, совместимость измерителя, количество и
виды ресурсов, ресурсный preview и `matched_query`. Поля объясняют происхождение кандидата, но не
содержат code-side решения о применимости.
Одинаковые запросы
дедуплицируются, embedding/retrieval выполняются пакетно. Результаты не смешиваются между строками.
Score и порядок кандидатов не являются выбором нормы.
Если модель случайно переносит каталожный `limit=100` в ranked search, одна страница ограничивается
настроенным `candidate_limit`; `requested_limit`, фактический `page_size` и `has_more` остаются видимы,
а продолжение доступно явным `page`. Это защита model-context, не скрытый top-1.

### `read_norms_batch`

Открывает выбранные карточки из Typed SQLite: идентичность, измеритель, состав работ, ресурсы и
источники. Норму нельзя связать со строкой, пока модель её не открыла. По умолчанию ответ не повторяет
весь длинный список ресурсов для каждой нормы: модель видит их количество/виды и полный состав работ.
Если состав ресурсов влияет на решение или нужны `resource_actions`, сама модель повторяет чтение с
`include_resources=true` и получает все ресурсы без лимита. Полная карточка всё время остаётся в
расчётном контуре; это экономия model-context, а не удаление evidence.

Оба evidence tools доступны модели на каждом ходу. Python не назначает следующий tool. Если модель
завершила ход обычным текстом, нативный Ollama agent loop закончен и та же модель получает отдельный
вызов `format: JSON Schema`, который только сериализует её mapping. `tools` и `format` не смешиваются
в одном запросе.
Если модель подряд повторила полностью идентичный детерминированный tool-call, workflow также
останавливается сразу: повтор не меняет evidence и не должен превращаться в многоминутный цикл.
Профессиональная полнота evidence определяется skill и моделью, а не Python-gate.
Локальные native Ollama/Qwen и FreeToken/Big Qwen обрабатывают исходник по одной строке на
transport-пакет; общий
контекст сохраняется через `neighbor_context`, а обязательная глобальная модельная ревизия не
отключается. Если reasoning-модель исчерпала лимит до видимого structured JSON, transport один раз
повторяет только сериализацию с `think=false`; после отклонённого JSON допускается ещё один
ограниченный schema-repair той же модели. Поиск и открытие карточек при этом не синтезируются кодом.
Если Ollama-модель дважды сериализовала `items`/`rows` как JSON-строку внутри аргументов,
transport рекурсивно распаковывает только контейнеры JSON/Python literal. Все `work_id`, коды и
решения остаются дословными; исполняемый `eval` не используется.
Batch-level `page`/`limit`, которые Qwen кладёт рядом с `items`, применяются к элементам без своих
значений; это сохраняет выбранную моделью страницу вместо молчаливого возврата page 0.

### Structured model mapping

Передаёт завершённую модельную ревизию по исходным строкам через provider-enforced JSON Schema:

- `bind` — выбранная открытая норма, явные exact/analog и applicability, модельный
  `candidate_evaluations` и полный `technology_check`
  (совпавшие/отсутствующие/лишние операции, посторонние ресурсы, условия, пересечения и их разрешение)
  и массив ресурсных действий;
- `covered_by` — доказанное покрытие другой исходной строкой;
- `unbound` — модель осознанно оставила работу открытой и передала `unbound_evidence`: минимум две
  реально выполненные поисковые формулировки, открытые карточки, причины неприменимости и проверку
  coverage/decomposition.

Эти требования находятся в runtime skill. Python возвращает неполную обязательную анкету той же
модели на transport-исправление, но не меняет её норму или вывод. Неоткрытая карточка и несовместимый
измеритель сохраняют решение модели, а расчётный слой помечает невычислимую строку blocker-ом и
продолжает остальные. Каждое
`add|replace|exclude|reuse` по skill требует причины и `basis_ref`; неполное ресурсное действие также
становится построчным расчётным blocker, а не причиной переписывать mapping. Runtime skill требует от модели
не считать частичное технологическое совпадение exact и сверять выбранные нормы между строками, чтобы
подготовительные операции и слои не оплачивались дважды.
JSON Schema является transport-контрактом, а не профессиональным validator: значения полей создаёт
та же модель из собственной conversation history; Python их не дописывает и не меняет.
Для `unbound` поля `queries_used` и `opened_norm_codes` нормализуются только по фактической tool
trajectory: выдуманные ссылки отбрасываются, а реально выполненные запросы и чтения могут быть
восстановлены из trace. Причины отказа и вывод о coverage код не сочиняет; если их нет, mapping
остаётся невалидным и возвращается той же модели.

`candidate_evaluations` фиксирует оценку выбранной карточки по операции, объекту, измерителю, области
и чужим ресурсам. Если search показал несколько карточек, transport требует открыть и сравнить выбранную хотя
бы с одной реально открытой отклонённой/спорной альтернативой. Код проверяет ссылки и полноту,
но не оценивает причины и не меняет `selected|rejected|uncertain`.

Кандидатные меню и рабочая память используют короткие карточки с точными selectable ids; полная
typed-карточка появляется только через `read_norms_batch` перед model-owned bind. Когда модель
явно считает ранее пройденный маршрут применимым к другой строке, она вызывает
`reuse_norm_catalog_route` с `cache_id` и собственной причиной. Код переносит только проверенный
family/collection/section/table scope, но не норму и не вывод о применимости; search/read остаются
обязательными. Глобальная ревизия получает bounded-карту карточек: идентичность, до 12 операций,
агрегат ресурсов и до 8 примеров вместо полного ресурсного списка. Для спорной строки полная
карточка повторно открывается тем же `read_norms_batch`; typed evidence не заменяется summary.

Число строк и поисковых ходов не зашито под один тестовый объект. Транспорт поддерживает минимум
50 строк тем же контрактом. Локальный task имеет до 10 модельных ходов и независимые технические
лимиты: четыре search-вызова, четыре read-вызова, 12 открытых карточек и 180 секунд. На границе та же
модель фиксирует решение по уже собранным доказательствам. Это предел латентности, а не число
кандидатов или code-side выбор нормы. Terminal `submit_lsr_mapping` всегда разрешён после исчерпания
evidence budget: лимит обязан остановить дальнейший поиск, но не может отклонить уже принятое
моделью решение. Cloud сохраняет 64 модельных хода.

## Нормативное хранилище и retrieval

Typed SQLite — расчётная истина. `norm_key = base_type:bare_code` отделяет одинаковые цифровые коды
разных семейств. Qdrant является навигационным sibling-индексом. Поиск использует dense+sparse и RRF;
при несовпадении fingerprint/контракта dense не маскируется как исправный.

Структура базы, формула количества и источники РИМ описаны в
[`skills/smeta/references/gesn-storage.md`](../../skills/smeta/references/gesn-storage.md).

## Количества и деньги

```text
norm_quantity = source_quantity × unit_conversion_factor
resource_quantity = norm_quantity × per_unit × quantity_coefficient
```

Исходное количество входит в расчёт один раз. `quantity_multiplier` в tool-контракте отсутствует.
Альтернативные представления одного трудового ресурса дедуплицируются до денег.

Missing price хранится как `null`, не как бесплатный ресурс. В частичной ЛСР показывается известная
рассчитанная часть, а в редактируемом XLSX ячейки цены и стоимости такого ресурса остаются пустыми.
Строка работы показывает официальное название нормы и через `/` фактическое описание исходной работы;
шапка явно называет ресурсно-индексный метод (РИМ). НДС задаётся параметром расчёта; для текущего
сценария используется 22%.

## Артефакт и история

Формульный XLSX, trace и download contract сохраняются вместе с сообщением. При открытии истории
Совушка должна восстановить карточку того же файла без повторного расчёта и без вызова модели.
Внешний ответ формируется отдельно от машинного JSON и не показывает служебные имена полей.

## Clean-install baseline и гейты

Windows release не строит нормативную базу из случайного локального parquet. `make patch-release`
создаёт `LES-smeta-baseline.zip` из canonical typed source/SQLite/manifest/integrity и ФСЭМ,
проверяет SHA и нижние границы 40 000 норм / 1 500 машин, передаёт архив на Legion и встраивает в EXE.
Bootstrap разворачивает его только в пустой persistent state. `build_smeta_structured_base` до замены
канонического файла проверяет `minimum_norms`, поэтому результат 171 или 14 570 норм не может затереть
живую базу. Все проверочные SQLite-соединения закрываются до `replace`, поэтому тот же атомарный
контракт работает на Windows, где открытый файл нельзя переименовать. Clean-install smoke повторно
проверяет фактические SQLite после установки.
Это гейт норм/ресурсов и ФСЭМ, а не ценовой гейт: региональная Сплит-форма выбирается по субъекту,
ценовой зоне и периоду после установки. Без неё точные цены остаются `MISSING`.

Операторское полное обновление ФГИС имеет отдельный persistent status contract. Он различает запуск,
получение каталога, загрузку Сплит-форм, загрузку ГЭСН и локальные стадии unify/SQLite/RAG; возвращает
heartbeat, текущий регион/период или сборник/отдел, completed/total/remaining, скачанные байты,
среднюю скорость и ETA. Живой PID без свежего heartbeat объясняется как ожидание ответа ФГИС или
длительная локальная операция; исчезнувший PID при `status=running` маркируется как прерванный job.

Гейты:

- `tests/test_smeta_core.py` — catalog/table/search/read, model-owned выбор, полный technology/resource evidence,
  50 строк, единицы и один расчёт.
- `tests/test_smeta_norm_browser.py`, `tests/test_smeta_rerank_ab_probe.py` — batch rerank,
  явный transport status, полный table listing и контракт живого A/B smoke.
- `tests/test_rim_trace_xlsx.py` — форма РИМ, официальное наименование и пустая missing price.
- `tests/test_smeta_prompt_freedom.py` — отсутствие объектных якорей и скрытого selector.
- `tests/test_prompt_registry_service.py` — загрузка полного canonical skill и prompt registry.
- `tests/test_specification_to_bor_contract.py` — model-owned декомпозиция и quantity trace.
- `tests/test_smeta_release_baseline.py` — SHA/count/integrity, clean provision и запрет overwrite.
- `tests/test_installer_windows.py` — baseline в bootstrap и обязательная Windows-smoke проверка.
- `tools/smeta_document_live_smoke.py` — реальная ВОР, выбранная модель, отключённый fallback и
  обязательный ненулевой XLSX; `--only-row` оставлен для диагностики tool-контракта.
- `make verify`, `make test-unit`, `make test-integration` и `make test` — офлайн-гейты;
  `make smoke-active-artifacts` проверяет active base, `make smoke-smeta-rerank` — живую
  цепочку active base → Qdrant/RRF → cross-encoder.

## Открытые долги

- Доказать полноту всех семейств/редакций сверх общего floor и закрыть полный ценовой контур ФГИС/КАЦ.
- Повторять live zero-state ВОР→XLSX для каждой production-модели перед выпуском и отдельно
  оценивать профессиональное качество выбранных норм; зелёный transport не равен экспертизе.
- Завершить clean dense+sparse reindex общего RAG и только после гейтов переключить alias.

Эти долги влияют на качество/полноту денег, но не дают права возвращать кодовый выбор норм или
многоступенчатый оркестратор.
