# Аудит документации public/team-контура

Дата: 2026-07-23

## Вердикт

Исходный public-репозиторий не был достаточным для командной работы: в нём
отсутствовали 14 активных описаний алгоритмов и связанные architecture/runbook
документы из private, несколько живых ссылок были битыми, README и lock расходились
с `config/version.json`, reinstall-инструкция клонировала private repo, а
операторский skill описывал устаревший статический public-host.

В этой ветке восстановлен безопасный tracked documentation set, добавлены единые
индексы алгоритмов и skills и введён `make docs-check`. Исторические документы
сохранены в `docs/archive` и учитываются в inventory, но их старые команды и ссылки
не принимаются за текущую эксплуатационную истину.

## Проверенный охват

- Канон: `AGENTS.md`, root `SKILL.md`, module/code/test maps, roadmap, release
  ledger, versions, install/packaging/platform/publication runbooks.
- Все 27 `docs/ALGO-*`.
- Все 4 LES skills и ARTEL skills в pinned Agnostis source.
- 181 git-visible Markdown-файл: H1, локальные ссылки и public/private boundary
  (151 living, 30 historical/generated).
- Version contract: `config/version.json`, Python package, `uv.lock`, Tauri/Cargo,
  software passport и README badge.
- Публичный clone path и отсутствие действующей инструкции на private remote.

## Исправлено

1. Возвращены безопасные активные документы из private, включая недостающие
   ALGO-доки, guardrails, architecture и archive index.
2. Добавлены `ALGORITHM_INDEX.md` и `SKILL_INDEX.md` с явным статусом
   active/canonical/MVP/tombstone/decision record.
3. `make verify` теперь начинает с `make docs-check`.
4. Public install/reinstall использует
   `https://github.com/proovcme/les_rag_public.git` и `--recurse-submodules`.
5. Public repo описан как полный safe tracked team source, а не showcase.
6. Root skill приведён к фактическому demo-flow:
   landing → key login → provider setup → local MLX или OpenRouter/OpenAI BYOK.
7. Синхронизированы version contract и package/desktop manifests.

Проверки: `make docs-check` — 181/27/4 без замечаний; focused
documentation/publication tests — 4 passed; `make verify` — 3086 collected.

## Семантическая проверка алгоритмов

- RAG-доки согласованы с единым named-vector contract и запрещают unnamed vectors,
  sparse sidecar, копирование legacy dense и dataset-specific boosts.
- Сметные доки и skill сохраняют model-owned mapping; Python не выбирает и не
  «улучшает» нормы/аналоги/resource actions.
- Нормоконтроль разделяет computed checks и model-led инженерное замечание;
  неполная область остаётся `needs_more_evidence/not_checked`.
- Табличные и ЛСР-алгоритмы считают по typed rows/Parquet/SQLite, не по top-k
  фрагментам модели.
- `ALGO-object-estimate` оставлен только как явно помеченный tombstone;
  `ALGO-vl-lora` — как decision record, а не активная инструкция.

## Открытые границы

- Документальный gate доказывает структуру, ссылки и version consistency, но не
  заменяет профильные тесты и живые Windows/Revit проверки.
- Runtime datasets, нормативные корпуса, клиентские документы, credentials,
  индексы и caches намеренно не переносятся в public.
- ARTEL product docs и release contract принадлежат Agnostis; LES фиксирует только
  проверяемый gitlink и integration boundary.
