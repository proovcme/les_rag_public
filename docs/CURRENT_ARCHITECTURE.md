# CURRENT_ARCHITECTURE — canonical 0.29 implementation state

Каноническое решение зафиксировано в
[Canonical Tool, Context, Memory and Artifact Update](superpowers/specs/2026-08-26-canonical-tool-context-memory-update-design.md).
Этот документ показывает только фактическое состояние реализации; при
расхождении план не выдаётся за работающий код.

## Реализовано

- `tools/architecture_contract_gate.py` и `make architecture-gate` проверяют
  структурные границы новой архитектуры без запуска сервисов и чтения runtime
  data/secrets.
- Gate запрещает параллельные `estimate_*` workbook contracts, code-owned
  language/regex forcing, неявную активацию профиля, новые literal direct model
  HTTP callsites вне точного migration baseline/ContextGovernor и фиктивную
  live acceptance.
- Публичные канонические имена workbook tools остаются
  `build_lsr_workbook` и `build_vor_workbook`.
- `tool_contract_service.py` и `tool_registry_service.py` реализуют immutable
  provider-neutral contracts/registrations и один canonical registry.
- Все существующие read-only handlers подключены к registry ровно один раз;
  `ToolHarness` сохранён как совместимый facade без копирования обработчиков.
- `CapabilityBroker` формирует bounded shortlist только из profile/scope/phase/
  runtime/preset/budget policy. Он не получает текст вопроса и не выполняет
  профессиональный intent routing.
- `TrustedExecutor` является общей границей для legacy/API вызовов: валидирует
  JSON Schema, dataset scope, actor role, deadline, idempotency и result schema/
  budget; commit/external/destructive требуют exact revision-bound approval.
- Клиент не задаёт authorization scope и не подписывает approval сам: Executor
  читает receipt и атомарный idempotency state из trusted SQLite store;
  concurrent/ambiguous privileged execution fail-closed.
- Authoritative resolution косвенного `doc_id` входит в scope check; один
  approval receipt можно связать только с одной operation identity.
- Ordinary chat default `shadow` сохраняет legacy visible answer и выполняет
  максимум один canonical candidate call; trace redacted, persistence запрещён.
- До `TOOL_WOULD_EXECUTE` проверяются deadline и dataset scope; косвенный
  `doc_id` разрешается read-only SQLite-запросом без schema migration.
- Dataset/source/web и model-backed handlers в shadow validate-only; обычный
  notebook остаётся активен в legacy path, но shadow его не перестраивает.
- `active` без exact passing promotion receipt эффективно остаётся `shadow`;
  публикация профиля не активирует и не перепривязывает существующий session.
- `shadow` не исполняет draft/commit/external/destructive handlers, а overflow
  сохраняет целый результат за cursor без обрезания JSON.
- `qwen-9b-restrictive` и `qwen-35b-extended` разрешаются из наблюдаемой
  ёмкости backend. Профиль и оператор могут только сужать factory limits;
  LES не меняет физический KV и не перезапускает provider.
- Фактические tool-decision и answer packets общего чата собирает один
  `ContextGovernor`: обязательные объекты проверяются до model call, остальные
  включаются целиком в каноническом порядке и получают cursor при omission.
- Существующая notebook/session/project memory продолжает жить в прежних
  хранилищах. Typed projection только даёт ей bounded представление
  `advisory_state`; память не становится evidence и не выбирает решение.
- 9B и 35B используют одинаковые реальные tool contracts, effect/approval
  policy, порядок typed context и одну typed advisory-memory projection. 35B
  получает только более широкие числовые лимиты shortlist/batch/context/
  parallel reads.
- Совушка показывает effective preset, input limit, generation/safety reserves,
  reasoning, источник значения и необходимость restart. Эти строки read-only;
  допустимые изменения делаются через копию профиля.
- `tools/live_workbook_acceptance.py` — отдельный opt-in runner реального
  ordinary-chat маршрута: `/api/chat/attachments` upload → `/api/version`
  binding → `/api/chat/stream` SSE → metadata /
  download immutable revisions 1 и 2. Он fail-closed проверяет identity,
  attachment/provenance/checkpoint lineage, hash download, missing/blockers и
  elapsed/deadline time; он требует readable XLSX с visible meaningful sheet,
  checkpoint-bound monotonic SSE progress и runtime commit/build. JSON receipt
  redacted и имеет только exact typed allowlisted fields с
  `evidence_kind=live_runtime`.
  В receipt сохраняются только счётчики `missing`/`blockers`, не их свободный
  runtime-текст.
- Отдельный `candidate_acceptance=true` допускает pre-promotion executor только
  для root-admin в process CWD, который точно равен read-only Danger bootstrap
  factor `LES_CANONICAL_ACCEPTANCE_STATE_ROOT`. Он сохраняет публичное route
  decision `shadow`, не создаёт promotion receipt и явно отмечается в trace;
  обычный shadow остаётся неперсистентным. Candidate upload проходит тот же
  root/isolation guard до temporary-file и idempotency writes; все effective
  attachment/meta/idempotency/workbook artifact paths должны оставаться под
  isolated CWD. Fake contract transport выдаёт только non-persistent
  `contract_test`, никогда не `live_runtime` receipt.

## Проверено на context checkpoint

- Focused Agent Foundation suite: `181 passed`.
- Канонический current behavior gate: `717 passed` с workspace-local
  `--basetemp` на Windows.
- `make architecture-gate` и `make verify`: зелёные; verify собрал 717 тестов.
- Governed-chat и UI checkpoints прошли независимое повторное review без
  Critical/Important.
- Это offline structural/behavior evidence; живое качество 9B и release
  promotion им не подменяются.

## Ожидает owner-run evidence

- **PENDING: live user-owned input/model acceptance.** Offline tests этого
  runner-а не являются evidence качества модели и не повышают маршрут до
  `active`. Обязателен owner-authorized запуск на реальном документе и
  configured Qwen 3.5 9B; 35B запускается дополнительно только если настроен.

`make architecture-gate` является только структурным доказательством. Он не
доказывает качество ответа модели, корректность профессионального решения или
готовность релиза. Эти свойства закрываются behavior-тестами, реальным paired
9B workflow и release gates из канонической спецификации.
