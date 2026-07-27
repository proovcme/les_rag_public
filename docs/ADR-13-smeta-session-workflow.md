# ADR-13 — Один model-owned workflow сметы и транспортные профили

Статус: **принято** (2026-07-27).

Связано: [Smeta Core](modules/smeta-core.md), [сметный skill](../skills/smeta/SKILL.md),
[структура ГЭСН](../skills/smeta/references/gesn-storage.md).

## Контекст

Два экспериментальных контура решали разные проблемы:

- публичный PR доказал пользу стабильного порядка, `temperature=0`, сессии, прогресса и повторяемого
  транспорта, но смешал это с предметной ревизией и runtime defaults;
- локальный WIP доказал, что слабая модель способна сформировать JSON-черновик после заранее
  подготовленного evidence, но `simple_rag` начал сам угадывать семейство/сборник и создавать
  профессиональные решения.

Повторяемость выбранных норм сама по себе не доказывает их профессиональную правильность. При этом
отдельный «упрощённый сметный движок» неизбежно создаёт второй предметный канон.

## Решение

В LES существует один `SmetaSession` и один предметный workflow:

```text
source intake
  → model-owned ScopePlan
  → code executes catalog/search/read
  → immutable R1 row_mapping
  → deterministic conflicts
  → same-model immutable R2 global_review
  → priced_draft LSR
  → explicit user mapping_locked
  → separate priced_final calculation/XLSX
```

Сильная модель может сама вести function-call loop. Слабая локальная модель может работать
ступенчато через schema-constrained transport, но перед каждым code-exec поиском обязана передать
`smeta_scope_plan_v1`: `work_id`, собственные запросы и намерения, а также либо:

- `scope_mode=scoped` с выбранными моделью `base_types` и `collections`;
- `scope_mode=global` без скрытых фильтров.

Код проверяет форму плана и исполняет его буквально. Он не выводит сборник из текста работы, не
добавляет доменные boosts и не превращает ranking в выбор нормы. `browse_norm_catalog`,
`search_norms_batch`, `read_norms_batch` и `submit_lsr_mapping` остаются единым контрактом для всех
адаптеров.

R1 и R2 — append-only ревизии. R2 получает всю ВОР, открытые карточки и доказуемые конфликты. Если
модель меняет норму, новая ревизия строится из её нового terminal mapping; производные поля R1
(`technology_check`, НР/СП, ресурсные действия) не копируются кодом в новую норму. Спорную новую
карточку модель обязана открыть через `read_norms_batch`.

Автоматический результат R2 всегда черновой. Финальный расчёт создаётся только из отдельной
пользовательской `mapping_locked`-ревизии. Session/SSE/job/checkpoint/batching/seed — operational
layer; Ollama/CUDA/Qdrant — runtime profile.

## Запрещено

- отдельный `simple_rag` или другой второй сметный движок;
- `СКС → ГЭСНм10`, vocab→collection, auto-unbound и stall-auto-search/read в Python;
- скрытая замена нормы, coverage, ресурсов или коэффициентов conflict-validator'ом;
- копирование профессиональных полей старой нормы при смене нормы в R2;
- выдача transport failure за профессиональное решение «нормы нет»;
- финальный XLSX до явного пользовательского lock.

## Что переносится из экспериментов

- фильтры typed retrieval, которые исполняют model-selected scope;
- стабильный порядок меню, seed и арифметики;
- checkpoint/resume, batch size, heartbeat и прогресс;
- продуктовая рамка «черновик + flags + пользовательская фиксация»;
- runtime-настройки только как отдельные профили.

## Реализация 0.24.46

Operational-часть публичного PR перенесена поверх единого workflow без второго selector:

- локальный document profile по умолчанию использует `qwen3.5:9b`, `temperature=0`,
  `LES_SMETA_DOCUMENT_SEED=0` и транспортные пакеты по 5 строк;
- нормализованные model-authored запросы и пакетные tool-вызовы сортируются до retrieval, а seed
  записывается в model/agent trace;
- NiceGUI хранит текущий `session_id` в user storage, при открытии восстанавливает только историю
  этой сессии, а новый чат создаёт и сохраняет новый id;
- полезный recovered SSE-ответ сохраняется в history, а закрытие вкладки не отменяет серверное
  завершение уже запущенного document workflow.

Предметный self-check из PR не перенесён. Его роль выполняет существующий `global_review`: это
полноценный R2 tool-loop той же модели с новой immutable revision. При изменении нормы R2 должен
открыть новую карточку и вернуть новое terminal-решение; поля R1 кодом не наследуются.

## Судьба веток

- Публичный PR не сливается целиком. Полезные operational изменения переносятся отдельными
  минимальными диффами после проверки на этот ADR.
- Локальный WIP не ребейзится как продуктовая ветка. Он остаётся экспериментальным evidence;
  `simple_rag` и предметные эвристики не переносятся.
- Новые изменения делаются от актуального `main` и проверяются по одному workflow, а не сравнением
  двух параллельных движков.

## Критерии приёмки

1. Один и тот же tool/mapping contract используется локальным и облачным адаптером.
2. Trace показывает model-authored `smeta_scope_plan_v1`; код не добавляет предметный scope.
3. R1, R2 и user lock имеют разные immutable revision ids и `parent_revision_id`.
4. Смена нормы в R2 не наследует производные поля R1.
5. До lock результат имеет `priced_draft`; `priced_final` создаётся отдельным расчётом после lock.
6. Transport/stall не создаёт `unbound` без terminal решения модели.
