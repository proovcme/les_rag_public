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

## Запланировано, но ещё не реализовано

- Trusted Executor и approval boundary;
- `legacy | shadow | active` ordinary-chat route;
- ContextGovernor, typed memory projection и presets Qwen 9B/35B;
- versioned workbook artifacts и paired live 9B acceptance.

`make architecture-gate` является только структурным доказательством. Он не
доказывает качество ответа модели, корректность профессионального решения или
готовность релиза. Эти свойства закрываются behavior-тестами, реальным paired
9B workflow и release gates из канонической спецификации.
