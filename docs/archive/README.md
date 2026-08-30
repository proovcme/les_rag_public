# Архив доков — историческое (контекст «почему так», НЕ текущая правда)

Сюда сведены **датированные** саммари/хендоффы/репорты и **заменённые** планы. Они полезны для
понимания «почему так сложилось», но версии/решения в них могут быть устаревшими. **Текущая правда:**

- Бэклог/дорожная карта до v1 → [`../../ROADMAP_TO_V1.md`](../../ROADMAP_TO_V1.md)
- Карта кода → [`../CODE_MAP.md`](../CODE_MAP.md) · Инструкции агентам → [`../../AGENTS.md`](../../AGENTS.md)
- Что реально запущено/задеплоено → `GET /api/version` + `git log`
- Алгоритм-каноны (0 LLM ядра) → `../ALGO-*.md`

## Что здесь

### Прежние корневые документы

| Прежний путь | Почему в архиве | Текущая замена |
|---|---|---|
| `ARTICLE_INDEXING_LESSONS.md` | статья о конкретном этапе развития индексации | `docs/ALGO-rag-best-practices.md`, `docs/unified_harness_failure_ledger.md` |
| `ARTICLE_SAFERAG.md` | историческое объяснение отдельного safety-слоя | `docs/ALGO-rag-best-practices.md`, `ROADMAP_TO_V1.md` |
| `DICTIONARY_LES_v2.0.md` | словарь прежней архитектуры v2 | `README.md`, `ROADMAP_TO_V1.md`, `docs/MODULE_INDEX.md` |
| `LES_SIMPLE_OVERVIEW.md` | параллельный обзор продукта | `README.md`, `docs/index.md` |
| `LES_SYSTEM_BUSINESS_NOVEL.md` | продуктовый нарратив, а не текущий контракт | `README.md`, `ROADMAP_TO_V1.md` |
| `PROGRAMMA_ISPYTANIY_v2.0.md` | программа испытаний прежнего поколения | `docs/TEST_INVENTORY.md`, `Makefile` |
| `RAG_MODERNIZATION_PLAN.md` | заменённый план нескольких поколений RAG | `docs/ALGO-rag-best-practices.md`, `ROADMAP_TO_V1.md` |

Файлы сохранены в `docs/archive/root-legacy/` через `git mv`.

### Завершённые планы

| Прежний путь | Почему в архиве | Текущая замена |
|---|---|---|
| `docs/PLAN_DODELKA.md` | общий список доработок прежней эпохи | `ROADMAP_TO_V1.md`, `docs/MODULE_INDEX.md` |
| `docs/UI_IMPROVEMENT_PLAN.md` | завершённый UI-план до единого UIKit | `docs/modules/sovushka-uikit.md`, `docs/MODULE_INDEX.md` |

Файлы сохранены в `docs/archive/plans/`.

### Завершённые аудиты и хендоффы

| Прежний путь | Почему в архиве | Текущая замена |
|---|---|---|
| `docs/ACCESSIBILITY_AUDIT.md` | выводы внесены в UIKit и типографику 0.30.1 | `docs/modules/sovushka-uikit.md` |
| `docs/MODULE_AUDIT_2026-06-26.md` | датированный снимок старой модульной карты | `docs/MODULE_INDEX.md` |
| `docs/SMETA_MODULE_BASE_AUDIT_2026-07-09.md` | датированный аудит сметной базы | `docs/SMETA_MECHANICS.md`, `docs/MODULE_INDEX.md` |
| `docs/SMETA_RIM_MODULE_HANDOFF_CLAUDE.md` | хендофф конкретной сессии | `docs/ALGO-smeta.md`, `docs/ALGO-fgis-price.md` |

Файлы сохранены в `docs/archive/audits/`.

### Старые release notes

Восемь файлов `docs/RELEASE_NOTES_0.24*.md` перенесены в `docs/archive/releases/`.
Текущая версия и хронология находятся в `docs/RELEASE_LEDGER.md`, а пользовательские документы
выпусков — в `docs/public/releases/`.

## Оставлены активными до ручного решения

Эти документы выглядят историческими, но имеют действующие backlinks или содержат незакрытый
контракт. Их нельзя переносить только по названию.

| Активный файл | Почему пока остаётся |
|---|---|
| `docs/BASIC_FUNCTIONS_AUTOTEST_PLAN.md` | на него ссылается `tools/basic_function_smoke.py` |
| `docs/DOC_REVIEW_GOST_R_21_101_2026_PLAN.md` | ссылки из сервисов нормоконтроля, config, CODE_MAP и MODULE_INDEX |
| `docs/LES3_PLAN.md` | содержит ADR-ссылки и используется `INSTALLERS_MULTIPLATFORM_PLAN.md` |
| `docs/PLAN_EVIDENCE_CORE.md`, `docs/TODO_EVIDENCE_CORE.md` | связаны с corpus-inventory и RAG quality backlog в MODULE_INDEX |
| `docs/RAG_TEST_PROGRAM_AUDIT.md` | указан как действующая quality-ссылка в MODULE_INDEX и TEST_INVENTORY |
| `docs/TODO_SMETA_CORE.md`, `docs/SMETA_REQUIRED_SOURCE_AUDIT_2026-07-11.md` | описывают защищённый сметный долг; перенос требует отдельного benchmark-аудита |
| `docs/TODO_LOCAL_INFERENCE_BENCHMARK.md`, `docs/LOCAL_INFERENCE_OPTIQ_MTP_M4_2026-07-13.md` | используются текущим MLX-контрактом и MODULE_INDEX |
| `docs/MAC_REINSTALL_STRESS.md` | на него ссылаются installer docs и живой тест установщика |
| `docs/ANSWER_LIMIT_AUDIT.md` | MODULE_INDEX использует его как источник текущих лимитов |
| `docs/TEST_ARCHITECTURE_AUDIT_2026-07-14.md` | ссылки из TEST_INVENTORY и исторического release ledger требуют отдельного сведения |
| `docs/TODO_WINDOWS_PRODUCTION.md` | содержит оставшийся production/signing долг; статус надо проверить вручную |

Следующий аудит должен либо заменить каждый backlink текущим module/algorithm contract и перенести
файл, либо явно подтвердить его как рабочий документ. До этого они не считаются каноном.

| Файл | Что это |
|---|---|
| `SESSION_SUMMARY*.md` (×12) | датированные саммари сессий (06-19); хронология, не текущее состояние |
| `SESSION_HANDOFF_2026-07-06_PD_RD_RAG.md` | хендофф по ветке `feat/les3-p1`: PD/RD source-map, drawing manifest MVP, ГОСТ Р 21.101-2026 в live RAG, что продолжать |
| `SESSION_HANDOFF_2026-06-27.md`, `HANDOFF.md` | хендоффы конкретных сессий — заменены ROADMAP_TO_V1 + git-историей |
| `DOCS_SESSIONS_AUDIT_REPORT_2026-06-25.md` | аудит доков/сессий на дату |
| `PROJECT_HISTORY_REPORT_2026-06-26.md` | исторический отчёт по проекту |
| `ROADMAP_LES_v2.0.md` | **заменён** актуальным `ROADMAP_TO_V1.md` |
| `QWEN_TASKS.md`, `QWEN_DIAGNOSTICS.md` | старые листы задач/диагностики по qwen |
| `README_v2.0.md` | устаревший дубль роли `README.md` (4B/GLM-OCR/Aider) — актуален корневой `README.md` |
| `LES_MASTER_DOC_v2_1.md` | мастер-док «v4.0», дубль-секции, вапор-стек (GLM-OCR/LangExtract) — историческое |
| `INFRASTRUCTURE_v2.0.md` | инфра-док: ≥40% мёртвое (Speckle/GLM-OCR/Qwen3.5-4B/lite-shell). Актуальная инфра → `../CODE_MAP.md` (топология) + `../../PROXY_ARCHITECTURE.md` |
| `AUDIT_RAG_FUNCTIONAL.md` | аудит RAG (06-23); план в основном исполнен. **Живой долг вынесен:** авто-индексация pending-документов (`proxy/workers/` пуст) — добавить self-healing планировщик |

> Ничего не удалено — перемещено (git хранит и историю файлов). Если что-то понадобится в каноне —
> вернуть `git mv docs/archive/<файл> <место>`.
> Аудиты **AUDIT_DETERMINISM** и **AUDIT_CORE** оставлены в `docs/` (на них ссылается КОД), но получили
> статус-баннер «исполнено/закрыто» — это история решений, не текущая инструкция.
