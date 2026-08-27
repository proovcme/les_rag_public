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

## Проверено на foundation checkpoint

- Focused Agent Foundation suite: `181 passed`.
- Канонический current behavior gate: `681 passed` с workspace-local
  `--basetemp` на Windows.
- `make architecture-gate` и `make verify`: зелёные; verify собрал 681 тест.
- Task 5 прошёл независимое повторное review без Critical/Important.
- Это offline structural/behavior evidence; живое качество 9B и release
  promotion им не подменяются.

## Запланировано, но ещё не реализовано

- ContextGovernor, typed memory projection и presets Qwen 9B/35B;
- versioned workbook artifacts и paired live 9B acceptance.

`make architecture-gate` является только структурным доказательством. Он не
доказывает качество ответа модели, корректность профессионального решения или
готовность релиза. Эти свойства закрываются behavior-тестами, реальным paired
9B workflow и release gates из канонической спецификации.
