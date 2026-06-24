# ROADMAP_TO_V1.md

# ЛЕС v1.0 — дорожная карта до стабильной локальной версии

Статус: рабочий roadmap после ветки `feat/les3-p1` и серии `Unified Construction Harness v0.3–v0.18`.

Цель документа — перестать идти «по наитию» и зафиксировать, что именно считается версией 1.0, какие этапы ведут к ней, что блокирует релиз и какие вещи сознательно остаются после v1.

---

## 1. Короткое определение v1.0

**ЛЕС v1.0** — это локальный строительный evidence-assistant для одного пользователя, который в обычном чате умеет работать по реальным проектным источникам, нормам, таблицам, почте и сметным данным, не выдумывает факты и числа, показывает происхождение ответа и даёт пользователю проверить источники.

Формула v1:

```text
выбран проект / датасет
  → пользователь задаёт строительный вопрос
  → ЛЕС выбирает правильный контур
  → ищет в документах / нормах / почте / таблицах
  → считает только кодом
  → показывает evidence
  → даёт цитаты
  → умеет сказать “не хватает” / “заблокировано”
  → UI позволяет открыть источник, скопировать ответ и остановить генерацию
```

v1.0 — это не «идеальный строительный ИИ» и не production SaaS. Это стабильная локальная система, которая не теряет источники, не ломает маршруты, честно блокирует слабые результаты и даёт проверяемый ответ.

---

## 2. Главные принципы ЛЕС v1.0

### 2.1. Evidence-first

Каждый содержательный фрагмент ответа должен относиться к одному из типов:

```text
RETRIEVED — найдено в источнике
COMPUTED  — вычислено кодом
ASSUMED   — принято как допущение
MISSING   — данных не хватает
BLOCKED   — продолжать нельзя
CONFLICT  — источники противоречат друг другу
```

Правило:

```text
Факт без источника — не факт.
Число без происхождения — не инженерный результат.
```

### 2.2. Модель связывает, код считает

Модель может:

```text
понять вопрос
выбрать формулировку ответа
связать найденные источники
предложить структуру
```

Модель не должна:

```text
выдумывать норму
выдумывать цену
выдумывать факт монтажа
выдумывать проектный факт
выдавать число без source/formula/provenance
игнорировать blockers
```

### 2.3. Детерминизм живёт в инструментах и гейтах

Детерминированными должны быть:

```text
расчёты
единицы измерения
нормо-единицы
проверка применимости норм
source_refs
final_total blocking
извлечение таблиц
реестр файлов
статусы sidecar/extraction
```

Детерминированные автоответы по широким словам запрещены.

Разрешён deterministic final только для:

```text
явной команды
явного режима
точного термина в явном term-query
точного кода / расценки
system/status/help
```

### 2.4. Source-scope важнее термина

Запрос вида:

```text
найди <X> в <Y>
```

маршрутизируется по источнику `Y`, а не по догадке о значении `X`.

Примеры:

```text
найди ОЗК в актах              → поиск в актах / исполнительной
найди КДУ в спецификации       → поиск в спецификации
найди ШУ-1 в исполнительной    → поиск в исполнительной
найди ОЗК в почте              → поиск по письмам
правила расстановки ОЗК        → norm/document QA
что такое ОЖР                  → glossary
```

### 2.5. Честный отказ лучше красивой ошибки

Если источника нет, индекс пуст, sidecar не создан, почта не подключена, норма не применима или итог заблокирован — ЛЕС должен объяснить это явно.

Плохой отказ:

```text
Не найдено.
```

Хороший отказ:

```text
В выбранном датасете есть PDF/DOCX, но текстовый слой не подготовлен.
Запустите “Подготовить к поиску”. Оригиналы документов не изменяются.
```

---

## 3. Что уже сделано до roadmap

### 3.1. Harness / исполнительный контур

Сделан unified construction harness:

```text
intent routing
source-scoped search
evidence blocks
typed tools
sidecar extraction
resource workbook validation
live _run_chat integration
adapter statuses
failure ledger
```

### 3.2. Сметный harness Gate 1–4

Закрыты:

```text
Gate 1 — unit contract
Gate 2 — norm applicability
Gate 3 — candidate ranking
Gate 4 — slot requirements / clarification loop
```

### 3.3. Resource workbook

Реальный XLSX `ПРИМЕР_обсчета_24_06.xlsx` валидирован кодом:

```text
direct costs:      4 333 793.60 ₽
FOT:               3 960 420.87 ₽
НР:                3 683 191.41 ₽
СП:                2 455 460.94 ₽
position total:   10 472 445.95 ₽
ТЦ/КАЦ:            6 354 837.24 ₽
grand total:      16 827 283.19 ₽
```

`line_diffs = 0`, source refs идут до листа/строки/ячейки.

### 3.4. Real dataset source adapters

Поддержаны:

```text
parquet rows
metadata / filenames
.md / .txt file_body
.eml read-only mail source
markdown tables → ВОР
PDF/DOCX/XLSX → sidecar extracted_body
lexical adapter
async vector/mail adapters with honest unavailable status
real workbook source
```

### 3.5. Runtime sidecar loop

Доказан operator-safe процесс:

```text
dry-run
approved write
manifest
staleness
extracted_body smoke
originals byte-identical
```

Извлечены реальные датасеты:

```text
844a2b53 — 27 sidecar, 23 930 paragraphs
e19cc409 — 22 sidecar, 20 054 paragraphs
```

### 3.6. DeterministicFinalPolicy

Закрыт класс hijack-багов:

```text
“Расскажи про котельную на лесном 64?” больше не уходит в ОЖР.
“что такое ОЖР/КАЦ/ЛСР” продолжает работать.
“реестр документации” не должен уходить в global “реестр проектов”.
```

Но policy должна оставаться release blocker до v1.

---

## 4. Что НЕ входит в v1.0

Чтобы не расползтись, v1.0 сознательно НЕ включает:

```text
полный OCR pipeline
идеальное сметное качество по любому объекту
Gate 5 для всех объектов
production price DB / полный ФГИС workflow
multi-user режим
облачную эксплуатацию
полный WorkflowRuntime/ProfileRegistry
идеальный Qdrant ranking
полноценный BIM graph
автоматическое удаление мусорных документов
полную поддержку всех legacy .xls вариантов
```

Если что-то из этого начато раньше v1, оно не должно блокировать v1, если не является критическим для уже заявленных сценариев.

---

## 5. Roadmap milestones

## v0.19 — Version Stamp + Diagnostics

Цель: перестать гадать, что запущено.

### Сделать

```text
/api/version
version badge рядом с [0_0] Л.Е.С.
app version
harness version
evidence schema version
extraction schema version
resource calc version
git commit / branch / build time
feature flags
runtime alignment
version_info в каждом ответе
copy diagnostics
CHANGELOG / releases doc
```

### Acceptance

```text
Версия видна в UI.
По клику видно commit, branch, flags, runtime alignment.
Каждый ответ несёт version_info.
Runtime divergence не скрывается.
/api/version не раскрывает секреты.
```

### Release blocker

```text
Нельзя идти к v1 без видимой версии и commit.
```

---

## v0.20 — Evidence UI

Цель: интерфейс должен показывать силу backend-а, а не terminal dump.

### Сделать

```text
кнопка “Стоп”
кнопка “Копировать” у ответа
рабочая кнопка “Открыть”
source drawer
citation artifacts
source chips
evidence renderer
MISSING/BLOCKED/CONFLICT blocks
artifact cards вместо тесной таблицы справа
expanded table view
CSV/JSON exports сохранить
trace summary
examples menu вместо старых inline prompt chips
task selector as hint, not fake mode
```

### Naming rule

Не использовать в UI термин:

```text
“Извлечь тело”
```

Пользовательские названия:

```text
Подготовить к поиску
Подготовить документы
Создать текстовый слой
Предварительная проверка
```

Технические термины `extract_body`, `sidecar`, `extracted_body` допустимы только в коде/diagnostics.

### Acceptance

```text
“Открыть” открывает источник или объясняет, почему preview unavailable.
Ответ можно скопировать.
Во время генерации есть “Стоп”.
Цитаты доступны как artifact.
MISSING/BLOCKED видны без прокрутки до конца.
Правая панель не дублирует сжатую таблицу.
```

---

## v0.21 — Route Safety Freeze

Цель: закрыть старые deterministic hijack’и как класс.

### Аудит deterministic final handlers

Проверить:

```text
glossary
registry
table shortcuts
smeta shortcuts
memory/tasks
keyword cascade
command service
les_md / ontology handlers
```

Каждый handler классифицировать:

```text
FINAL_ALLOWED
TOOL_ONLY
HINT_ONLY
DEPRECATED
```

### Release regressions

Обязательные вопросы:

```text
Расскажи про котельную на лесном 64?
что такое ОЖР
что такое КАЦ
составь реестр документации котельной
реестр проектов ЛЕС
найди ОЗК в актах смонтированного оборудования
найди КДУ в спецификации
собери ЛСР по Ф9
проверь пример обсчёта
```

### Acceptance

```text
Проектные/descriptive вопросы не уходят в glossary.
Source-scoped вопросы не уходят в norm/glossary.
Глобальный project registry работает только на exact intent.
Explicit term queries работают.
Trace показывает rejected deterministic candidates.
```

---

## v0.22 — Source Operations

Цель: extraction / sidecar / index health становятся понятной операцией.

### Сделать

```text
GUI action “Подготовить к поиску”
dry-run report
approved write with env+confirm gate
manifest / staleness
index health visible
extraction state messages
sidecar status in registry
legacy .xls actionable unsupported
```

### Acceptance

```text
Пользователь видит, подготовлены ли документы к поиску.
Dry-run не пишет.
Write требует подтверждения.
Оригиналы не мутируются.
Sidecar stale виден.
Scanned PDF → OCR required outside hot path.
```

---

## v0.23 — Real Dataset Acceptance

Цель: уйти от fixture-confidence к реальной приёмке.

### Прогнать 3–5 реальных датасетов

Минимальные типы:

```text
norm-like dataset
mail-like .eml dataset
project-like dataset
xlsx/docx/pdf dataset
resource workbook dataset
```

### Для каждого сохранить

```text
smoke output
failure ledger
index health
source support
route results
MISSING/BLOCKED reasons
```

### Acceptance

```text
Smoke не падает целиком.
Failure ledger типизирован.
Top-5 локальных провалов закрыты или marked infrastructure-blocked.
```

---

## v0.24 — Retrieval and Citation Quality

Цель: улучшить качество источников и доверие к ответу.

### Сделать

```text
dedup источников
used vs found vs rejected sources
citation snippets
source preview
search within selected source
exclude source
pin source
weak/strong source marker
filename-only vs body-hit distinction
vector semantic-only != exact occurrence
```

### Acceptance

```text
Пользователь понимает, какие источники реально использованы.
Можно открыть/скопировать цитату.
Можно отличить body-hit от filename-only.
Система не называет mounted то, что найдено только в spec.
```

---

## v0.25 — Estimate Workflow Hardening

Цель: сделать стабильным не “идеальную смету”, а предварительный сметный workflow.

### Сделать

```text
Ф9/ВОР → ЛСР stable
markdown/xlsx/docx table rows → WorkLines
unknown family → BLOCKED
unit conversion regression pack
norm applicability regression pack
partial/final total semantics
resource workbook integrated
clear blockers
no final_total with blockers
```

### Не делать

```text
Не пытаться закрыть все объекты строительства.
Не начинать широкий Gate 5 без отдельного решения.
```

### Acceptance

```text
Если источник ВОР есть — система извлекает работы.
Если норма/цена/семья не подтверждены — BLOCKED/MISSING.
Итог показывается только при complete.
```

---

## v0.90 — Release Candidate

После v0.25 перестать добавлять крупные функции.

Разрешено:

```text
bugfix
UI polish
performance
route regressions
docs
smoke
packaging
```

Запрещено без отдельного решения:

```text
новые большие контуры
Gate 5
OCR pipeline
полный price DB
full WorkflowRuntime
новые режимы
```

### RC критерии

```text
7 дней активного использования без P0-регрессий
release smoke green
нет dead UI buttons
version visible
route bugs закрыты
source_refs есть
evidence visible
final_total не нарушает blockers
```

---

## v1.0 — Local Evidence Assistant

Формулировка релиза:

```text
ЛЕС v1.0 — локальный строительный evidence-assistant для одного пользователя.
```

v1.0 должен стабильно уметь:

```text
отвечать по документам и нормам с source_refs
описывать проект и давать чистый реестр документов
искать произвольные термины в заданных источниках
искать по .eml как read-only mail source
извлекать ВОР из parquet/markdown/xlsx/docx tables
собирать предварительную ЛСР с blockers
валидировать resource workbook
подготавливать документы к поиску через sidecar workflow
показывать evidence в UI
останавливать генерацию
копировать ответ
открывать цитаты
показывать версию/commit/runtime alignment
```

---

## 6. Release blockers для v1

v1 блокируется, если есть хотя бы один пункт:

```text
1. Нет видимой версии/commit.
2. /api/version отсутствует или декоративный.
3. Runtime diverges from repo without warning.
4. “Расскажи про котельную” уходит в glossary/ОЖР.
5. “Реестр документации” отдаёт global project registry.
6. “Найди X в актах” уходит в norm/glossary.
7. “Открыть” ничего не делает.
8. Нет копирования ответа.
9. Нет citation/source drawer.
10. MISSING/BLOCKED скрыты в тексте.
11. final_total показывается при blockers.
12. RETRIEVED evidence без source_ref.
13. Mail body попадает целиком в trace/citation.
14. Sidecar write возможен без operator gate.
15. Chat OFF behavior ломается.
16. Version info отсутствует в ответе.
17. Legacy .xls крашит extraction вместо actionable unsupported.
18. Deterministic handler может вернуть термин, отсутствующий в запросе.
```

---

## 7. Release smoke matrix

Перед v1.0 обязательно прогонять:

### Route smoke

```text
Расскажи про котельную на лесном 64?
что такое ОЖР
что такое КАЦ
составь реестр документации котельной
реестр проектов ЛЕС
найди ОЗК в актах смонтированного оборудования
найди КДУ в спецификации
найди ШУ-1 в исполнительной
```

### Evidence smoke

```text
что по нормам для серверной
правила расстановки ОЗК
опиши проект котельная
выведи не мусорные документы
найди ОЗК в письмах
```

### Estimate smoke

```text
извлеки ВОР из Ф9
собери предварительную ЛСР по Ф9
почему итог partial/blocked
```

### Resource smoke

```text
проверь пример обсчёта
почему итог 16 827 283.19
что требует КАЦ
```

### Source operations smoke

```text
status документов
предварительная проверка подготовки к поиску
подготовить к поиску with blocked env
sidecar stale warning
```

### UI smoke

```text
версия видна
копировать ответ
открыть источник
цитаты открываются
таблица раскрывается
стоп генерации
MISSING/BLOCKED видны
```

---

## 8. Test and artifact policy

Каждый milestone обязан иметь:

```text
unit tests
integration tests where possible
live smoke or script smoke
failure ledger update if source-related
report with honest limitations
```

Artifacts:

```text
artifacts/unified_vXX_smoke.json
artifacts/extract_vXX_report.json
artifacts/runtime_dataset_inventory_vXX.json
docs/unified_harness_failure_ledger.md
docs/releases.md
```

---

## 9. Naming rules for UI

Запрещённые пользовательские формулировки:

```text
Извлечь тело
body extraction
write sidecar
raw evidence dump
```

Пользовательские названия:

```text
Подготовить к поиску
Подготовить документы
Создать текстовый слой
Предварительная проверка
Текстовый слой создан
Текстовый слой устарел
Документ найден, но текст ещё не подготовлен для поиска
PDF без текстового слоя — нужен OCR
```

Технические термины допустимы в коде/trace/dev diagnostics:

```text
extract_body
extracted_body
sidecar
manifest
stale
```

---

## 10. Commit discipline

Не делать один огромный коммит, если изменение можно разделить.

Рекомендуемые группы:

```text
versioning
route safety
source operations
UI renderer
citations
stop generation
sidecar operations
estimate workflow
smoke/ledger
```

Каждый коммит должен отвечать на вопрос:

```text
Это приближает v1 или просто добавляет ветку сложности?
```

---

## 11. Открытые риски

### R1. Legacy deterministic hijack

Статус: частично закрыт DeterministicFinalPolicy.

Риск остаётся, пока все deterministic handlers не классифицированы.

### R2. Runtime/repo divergence

Статус: надо закрывать через version endpoint + runtime alignment.

### R3. UI отстаёт от backend

Статус: главный UX-долг.

### R4. Real datasets heterogeneous

Данные могут быть:

```text
.md
.eml
PDF
DOCX
XLSX
legacy XLS
сканы
битые таблицы
reference шум
```

### R5. Scanned PDFs

OCR не входит в v1, но должен быть честно обозначен.

### R6. Price DB / FGIS

Production price DB deferred after v1.

### R7. Source quality

Дубли, битые таблицы, Revit/API шум требуют post-v1 курирования.

---

## 12. Definition of Done for v1.0

v1.0 можно выпускать, если:

```text
[ ] версия и commit видны в UI
[ ] /api/version работает
[ ] runtime alignment виден
[ ] route smoke green
[ ] evidence smoke green
[ ] estimate smoke green
[ ] resource workbook smoke green
[ ] sidecar workflow smoke green
[ ] UI smoke green
[ ] no release blockers
[ ] failure ledger не содержит P0 open
[ ] chat OFF behavior stable
[ ] operator can rollback by commit/version
[ ] docs/ROADMAP_TO_V1.md актуален
[ ] docs/releases.md актуален
```

---

## 13. Короткая версия плана

```text
v0.19 — Version Stamp + Diagnostics
v0.20 — Evidence UI
v0.21 — Route Safety Freeze
v0.22 — Source Operations
v0.23 — Real Dataset Acceptance
v0.24 — Retrieval and Citation Quality
v0.25 — Estimate Workflow Hardening
v0.90 — Release Candidate
v1.0  — Local Evidence Assistant
```

После v0.25 — feature freeze. Дальше только стабилизация.

---

## 14. Главная мысль

До сих пор ЛЕС рос правильно: через реальные провалы. Но дальше нужен release-план.

v1.0 — это не момент, когда ЛЕС умеет всё.

v1.0 — это момент, когда ЛЕС:

```text
не врёт,
не теряет источник,
не ломает маршрут,
не показывает числа без происхождения,
не прячет MISSING/BLOCKED,
даёт открыть и скопировать доказательства,
и позволяет понять, какая версия сейчас запущена.
```
