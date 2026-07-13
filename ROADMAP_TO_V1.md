# ROADMAP_TO_V1.md

# ЛЕС v1.0 — дорожная карта до стабильной локальной версии

Статус: рабочий roadmap после ветки `feat/les3-p1`; актуализирован 2026-07-04 после runtime
`0.24.0.230` и `docs/RELEASE_LEDGER.md`.

Цель документа — перестать идти «по наитию» и зафиксировать, что именно считается версией 1.0, какие этапы ведут к ней, что блокирует релиз и какие вещи сознательно остаются после v1.

Текущий исполнимый порядок работы evidence-контура и его живой статус ведутся отдельно в
[docs/PLAN_EVIDENCE_CORE.md](docs/PLAN_EVIDENCE_CORE.md). Этот файл уточняет текущие
retrieval/evidence gates, но не заменяет roadmap v1 или release ledger.

---

## 0. Актуализация 2026-07-04

Фактический runtime дошёл до `0.24.0.230`. Старый milestone-план ниже остаётся полезным как
история, но текущая траектория v1 изменилась: кроме evidence UI и normcontrol появился новый
рабочий центр тяжести — корпусная навигация, controlled tool-harness, системный слой PDF/XLS и
CAD/DWG projections. Актуальная правда по версии и деплою — `docs/RELEASE_LEDGER.md`.

### Что уже фактически закрыто

```text
version/deploy stamp есть
main = feat/les3-p1 = deployed_commit
ProfileResolver появился как единый контракт маршрутизации
scope_model и scope_clarification работают
DeterministicFinalPolicy закрывает старые hijack-баги
sidecar/source operations частично выведены в API/UI
copy у ответа есть
Operational Trust Hardening закрыт как gate 0.23A
SPDS doc-review baseline работает через чат/API/GUI с JSON/HTML/XLSX отчётом
typed dataset memory вырос в notebook/source-guide слой: file cards, source graph, topic/section map
Document Explorer показывает датасеты, документы, chunks, поиск и CAD inventory
controlled tool-harness даёт model-selected read/search tools без автономного agent loop
PDF/P7M/XLS/XLSX/XLSM parse вынесен в killable subprocess
большие Excel/CSV индексируются как navigation projections, а не row-chunk flood
raw CAD/BIM больше не становится ложным INDEXED 0; DWG/DXF идут через canonical JSON projection
CAD/DWG drawn tables извлекаются из line/polyline grids и попадают в RAG до element noise
target-file CAD smoke на `drawn_table_1 first positions` закрыт на runtime `0.24.0.230`
dev `0.24.0.353`: integrity-first RAG core, fail-closed index contract, отдельный `test-rag-core`,
безопасный Qwen sibling-canary, типизированные системные датасеты и начатое единое smeta-core;
текущая normative SQLite в quarantine до semantic integrity report
```

### Что не считать закрытым

```text
Evidence UI не закрыт целиком: "Открыть", preview, source drawer и Stop ещё не v1-ready
Real Dataset Acceptance не закрыт как системная матрица 3–5 датасетов
Retrieval/Citation Quality не закрыт: used/found/rejected, preview, weak/strong ещё требуют прохода
активная Qdrant-коллекция имеет смешанные embedding fingerprints и не может быть усыновлена новым
manifest; нужен sibling canary index для BAI/ПД ИЦ/FIRE/смет
Estimate Workflow Hardening не закрыт как release gate
загрузка сметных документов не прозрачна для пользователя как отдельный intake-workflow
document_router устарел как владелец dataset routing: для `+ папка` граница датасета задаётся
оператором/LES.md, а router должен давать только file-role/parse-pipeline hints
PDF/XLS system layer ещё не равен полноценному пользовательскому reader/tool workflow
CAD tables beyond simple grids остаются риском: сложные merged cells, multi-sheet specs, rotated/fragmented grids
latency локальной генерации остаётся продуктовым риском
чистые source-verified retrieval goldens ещё не пересобраны; прежний debug-based FIRE/HVAC baseline аннулирован
runtime divergence остаётся дисциплиной: dev-правка не равна runtime, деплой только через `make ship`
```

### Стабилизационный вектор сессии 2026-06-27

Все функции, поднятые в сессии 0.23.6.x, должны идти по контракту “взрослой” функции:
работает в GUI, управляется оператором явно, документирована, даёт понятную ошибку вместо падения
workflow, не выдаёт число без логики/source/assumption/MISSING/BLOCKED и имеет regression test на
happy path плюс управляемый fail path там, где возможен плохой ввод. Формальный чек-лист перенесён в
`docs/GUARDRAILS.md#5-контракт-стабильной-функции`; для смет это означает: мутное ТЗ допускает только
ориентир с явными ASSUME/коэффициентами, а честная смета строится по файлам/датасетам/ВОР с evidence.

### Новый порядок до v1

До новых больших функций действует правило:

```text
Сначала доверие и воспроизводимость.
Потом прозрачный intake документов: пользователь должен видеть, что именно загружено, прочитано,
проиндексировано, приложено к вопросу или заблокировано.
Потом кликабельный evidence и строгий target-file/source workflow.
Потом довести PDF/XLS/CAD readers до пользовательских инструментов, а не только index internals.
Потом retrieval quality и сметный workflow.
Потом RC.
```

Новые pre-RC gates:

```text
v0.23A — Operational Trust Hardening                         ✅ closed
v0.23B — Clickable Sources + Citation Drawer                  🟡 partial
v0.23C — Real Dataset Acceptance                              🟡 partial, needs matrix
v0.24  — SPDS Documentation Normcontrol: ГОСТ Р 21.101-2026   ✅ baseline, deeper profile open
v0.24D — Transparent Smeta Document Intake                    📋 next
v0.24E — PDF/XLS Reader Tools + System Table Layer            🟡 PDF source-map + ES/EOM/ОВ/ВК/rooms done; next exact XLS/PDF reader APIs
v0.24F — CAD/DWG Table Hardening                              📋 next
v0.25  — Retrieval and Citation Quality                       📋
v0.26  — Estimate Workflow Hardening                          🟡 Phase 0/1 started; [TODO](docs/TODO_SMETA_CORE.md)
v0.90  — Release Candidate                                    📋
v1.0   — Local Evidence Assistant                             📋
```

Источник текущего состояния — `docs/RELEASE_LEDGER.md`; источник P0 для v0.23A —
`docs/MODULE_AUDIT_2026-06-26.md`.

---

## 1. Короткое определение v1.0

**ЛЕС v1.0** — это локальный строительный evidence-assistant для одного пользователя, который в обычном чате умеет работать по реальным проектным источникам, нормам, таблицам, почте и сметным данным, не выдумывает факты и числа, показывает происхождение ответа и даёт пользователю проверить источники.

Целевой production-профиль v1 — **Legion/Windows**: Tauri, Ollama и Qdrant Docker. Mac используется для разработки, сравнительных прогонов и локального reference-runtime, но не задаёт production defaults.

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

### 3.7. Runtime 0.24 core: navigation, tools, PDF/XLS, CAD/DWG

После старого плана v0.24 стал не только normcontrol-веткой. В runtime уже появились новые ядра,
которые теперь считаются частью дороги к v1:

```text
typed dataset memory / notebook_v1:
  file cards, source layers, source graph, topic map, section map, dataset brief for model

Document Explorer:
  no-AI обзор датасетов/документов/chunks, поиск, topic/section map, "Спросить по теме"

controlled tool-harness:
  dataset_map, indexed source search/read, PDF/Excel indexed readers, read-only filesystem tools

PDF/XLS parse safety:
  killable subprocess for risky conversions, spreadsheet_navigation_projection,
  table_navigation_projection вместо тысячи row chunks

CAD/DWG pipeline:
  DWG -> DXF -> canonical JSON -> CAD_BIM projection -> CAD_BIM_Index
  drawn CAD tables from LINE/LWPOLYLINE + TEXT/MTEXT
  first positions/logical positions anchors
  first_ordinal rank pin survives chat rerank and context expansion
```

Живой smoke на `0.24.0.230` доказал узкий сценарий: вопрос по target-file
`drawn_table_1 first positions` получает начало нужной drawn table, а не соседние таблицы.
Это не означает, что весь CAD/DWG table layer закрыт: сложные сетки, merged cells, повернутые
таблицы и многостраничные спецификации остаются отдельной стабилизацией.

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
полноценный BIM graph / CAD modeller
автоматическое удаление мусорных документов
полную поддержку всех legacy .xls вариантов
автоматическое распознавание любых чертёжных таблиц без ручного контроля
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

## v0.23A — Operational Trust Hardening

Цель: закрыть P0 из `docs/MODULE_AUDIT_2026-06-26.md`, чтобы v1 не был только "умным",
но хрупким. Это gate перед RC и перед расширением больших функций.

### Сделать

```text
auth/trust hardening:
  no predictable admin/JWT defaults
  trusted proxy only from trusted proxy networks
  X-Forwarded-For не даёт spoof trusted client
  proxy/security.py и sovushka/trust.py не расходятся по логике

backup/restore:
  restore для SQLite + Qdrant
  checksum/manifest
  свежий backup smoke
  launchd/права не молчат

index consistency:
  MetaDB ↔ Qdrant consistency check
  repair/reconcile path
  partial upsert не оставляет файл "INDEXED" без точек
  health показывает рассинхрон как FAIL/WARN

diagnostics truth:
  API не нормализует FAIL в OK ради красивого UI
  Docker/MLX/Qdrant checks честно говорят unavailable/error
  dead diagnostics modules помечены или удалены после отдельного решения
```

### Acceptance

```text
auth/trust smoke green
backup restore smoke green
MetaDB↔Qdrant consistency smoke green
doctor/diagnostics не прячут реальные ошибки
MODULE_AUDIT P0 закрыты или явно marked infrastructure-blocked
```

### Статус 2026-06-26 — фактически закрыт

```text
auth/trust:   admin123/JWT-дефолты убраны (random+warn, не предсказуемы); XFF-спуф проверен — не
              проходит; proxy/security.py ↔ sovushka/trust.py сведены в backend/trust_core.py
              (11 тестов + спуф-реверификация зелёные)
backup/restore: tools/restore_runtime.sh (Qdrant snapshot-upload + SQLite stop/start), смоук-цикл
              зелёный; /api/backup/{archives,restore} + кнопка в diag; бэкап-фолбэк (launchd оживлён,
              доказан — писал 3.3G локально при TCC на /Volumes/Data)
index:        reconcile_dataset + /datasets/{id}/reconcile (детект+лечение рассинхрона); upsert
              wait=True durable + raise→cleanup → INDEXED только при успехе; live-рассинхрон = 0
diagnostics:  _normalize_diag_payload хранит raw_status (MLX/CRAG err→warn не стирают правду);
              Docker-матч сужен; мёртвый backend/diagnostics.py помечен DEPRECATED
basic smoke:  tools/basic_function_smoke.py + make smoke-basic + tests/test_basic_function_smoke.py
              (live: 8 pass / 1 warn / 0 fail)
```

### Стабилизация 2026-06-27 — 0.23.6.2

```text
auth/trust:   дефолты TRUSTED_NETWORKS/TRUSTED_PROXY_NETWORKS сужены с 127.0.0.0/8 до
              127.0.0.1/32, env может явно расширить ZeroTier; regression на 127.1.2.3 spoof.
backup/restore: backup_runtime.sh пишет SHA256SUMS.txt; restore_runtime.sh проверяет checksum
              до dry-run/restore и останавливается на mismatch.
index:        RAG_VERIFY_POINTS_EVERY default = 1; mismatch Qdrant-count → ERROR + cleanup, не INDEXED.
KOT:          term matching только от границы слова; "кац" не ловится внутри "спецификация";
              "противопожар" добавлен явно, чтобы качество пожарного домена не просело.
```

Источник: `docs/MODULE_AUDIT_2026-06-26.md` (P0/P1 закрыты), ветка `feat/les3-p1`.

### UI/сметная стабилизация 2026-06-27 — 0.23.6.3

```text
chat attachments: скрепка получила read-mode (текст файла → контекст следующего запроса);
              quick/index-вложения реально попадают в payload как dataset_ids; чип вложения снимаемый.
chat scope:    в composer добавлены прямые кнопки выбора проекта/датасета и открытия папок/файлов
              рядом со скрепкой (не только верхний ScopeSelector).
smeta:         object_estimate разделён на два честных режима: мутное ТЗ → прикидка целого
              объекта (ГЭСН-конструктив + явные ASSUME-разделы + price_level_k + НДС);
              много данных/вложений → детальная смета должна считаться по ВОР/Ф9/КС-2/датасету.
              Ориентир остаётся final_total_allowed=false, потому что допущения придуманы явно.
```

### UI/сметная стабилизация 2026-06-27 — 0.23.6.4

```text
theme:          чат и админка стартуют в светлой теме; тёмная остаётся ручным переключателем.
artifacts:      правая панель "Артефакты" по умолчанию скрыта; открывается по явному чипу,
                файлу/форме или verification-artifact, закрывается кнопкой.
cloud model:    OpenAI-compatible/proxyapi больше не показывает "модель не задана":
                дефолт `OPENAI_MODEL=gpt-4.1`, runtime/status/UI показывают фактическую модель.
smeta evidence: объектная прикидка несёт RAG-подвал: логика расчёта, ссылки на шаблон/код/ALGO,
                ГЭСН-коды, `sources`, `retrieval_trace`, `evidence_summary`.
```

### Стабилизационный контракт 2026-06-27 — 0.23.6.5

```text
attachments:     режим "Прочитать" ловит сбой конвертера и отдаёт управляемый 422 с подсказкой,
                 без падения workflow и без записи в датасет.
artifacts GUI:   при скрытой по умолчанию панели у оператора есть отдельная кнопка "Показать
                 артефакты" в composer actions; закрытие остаётся в самой панели.
docs:            Guardrails получил формальный контракт стабильной функции: GUI-контроль,
                 fail-path как результат, evidence/provenance, тест, документация, gate.
```

---

## v0.23B — Clickable Sources + Citation Drawer

Цель: убрать фейковую интерактивность. Любой источник, который выглядит кликабельным,
обязан открываться. Если открыть нельзя — он disabled и объясняет почему.

### Сделать

```text
SourceRefUI normalization:
  answer.sources
  evidence_blocks
  retrieval_trace
  artifacts
  table source cells

SourceChip:
  clickable / disabled / weak / warning states
  file + locator + kind + tooltip

Citation drawer:
  file/source_kind/location/snippet
  copy source_ref
  copy citation
  no full mail body leaks

Artifact "Цитаты":
  used sources
  snippets
  warning for incomplete source_ref

Open behavior:
  file preview when available
  extracted paragraph/page/row/cell locator when available
  clear unavailable reason when not available
```

### Acceptance

```text
source chip открывает drawer                         ✅ 0.23.6.6
"Открыть" работает или disabled с причиной
source без source_ref не рисуется как fake button     ✅ 0.23.6.6
mail citation snippet-only                            ✅ 0.23.6.6
котельная/live answer можно проверить глазами
```

### Частично закрыто 2026-06-27 — 0.23.6.6

```text
source drawer:   source chip с реальным source_ref открывает карточку цитаты в панели "Артефакты".
open behavior:   file-like source_ref получает ссылку raw-file; weak/vector/missing-ref показывают
                 причину недоступности вместо фейкового открытия.
copy:            в drawer есть копирование source_ref и текстовой цитаты.
mail safety:     citation payload остаётся snippet-only, полное тело письма не попадает в artifact.
```

### Latency hotfix 2026-06-27 — 0.23.6.7

```text
router primary:  LES_ROUTER_PRIMARY больше не включается по умолчанию. Без явного opt-in чат
                 не ждёт 12 секунд LLM-router timeout перед deterministic fallback.
smoke symptom:   до фикса deterministic smoke-ответы имели router_unavailable_cascade_fallback
                 и занимали ~12s даже без LLM generation.
```

### Attachment/router stabilization 2026-06-27 — 0.23.6.8

```text
chat attach:     дефолт скрепки стал "В чат": файл виден в composer/user bubble и уходит модели
                 как attachment_context следующего запроса с именем файла; после отправки вложение
                 снимается, чтобы не протекать в следующий вопрос.
read attach:     auto-путь с attachment_context пропускает ранний keyword/clarification-каскад:
                 "прочитай/суммируй этот файл" идёт в LLM/RAG, а не в glossary/scope ловушку.
plain read:      если у запроса нет project/dataset scope, read-вложение обрабатывается attachment-only
                 LLM route без глобального RAG, чтобы не подтягивать случайные источники корпуса.
LLM fallback:    direct LLM/attachment/free path и router-primary без облачного ключа используют
                 локальный MLX; router-primary имеет LES_ROUTER_TIMEOUT=2s fail-fast вместо 12s ожидания.
```

### Defense-contract stabilization 2026-06-27 — 0.23.6.9

```text
system:          evidence_contract расширен до DefensePack/DefenseClaim: claim → source/formula/input
                 → assumptions/gaps/actions → defensibility.
smeta object:    объектная прикидка показывает не только итог, но и защиту строк: формула объёма,
                 physical qty, прямые/НР/СП, покрытие цен ресурсов, missing-price examples.
normcontrol:     doc_review JSON отдаёт такой же defense-contract для proposed remarks; финал по-прежнему
                 ставит инженер, не движок.
ops:             make ship стал полным check→deploy→post-smoke; make ship-check оставлен для проверки
                 без деплоя.
```

### Attachment UX / ship cadence 2026-06-27 — 0.23.6.10

```text
attach UX:       после галочки upload файл виден прямо в чате системным сообщением и в composer-плашке:
                 оператор понимает, что файл уйдёт со следующим запросом.
ship cadence:    make ship = быстрый итерационный gate; make ship-full = полный pytest gate версии.
post smoke:      post-deploy smoke делает retry после restart proxy, а не падает на коротком startup gap.
```

### Normcontrol defense report 2026-06-27 — 0.23.6.11

```text
doc-review chat: ответ стал отчётом для человека: verdict машины, evidence/action таблицы, защита решения.
leak fix:        рабочая память/LES.md больше не примешивается в doc-review answer.
payload:         chat payload отдаёт top-level defense для UI/экспорта без парсинга markdown.
sheet format:    D4-001 проверяет PDF-геометрию листов по ГОСТ 2.301 кодом; нестандартный лист даёт
                 computed_issue с source_ref страницы.
layout next:     размещение рамки/основной надписи и заполнение граф — отдельный layout-tool; не выдаём
                 это за текущую уверенность модели.
```

### Service sources / layout v1 2026-06-27 — 0.23.6.12

```text
service sources: config/service_sources.yaml + /api/service-sources показывают, какие служебные
                 источники нужны ЛЕСу: ГЭСН, ФГИС ЦС, коэффициенты/шаблоны, СПДС rulepack,
                 нормативный RAG и layout-reference.
admin GUI:       Инструменты получили блок "Служебные источники данных" со статусом OK/НУЖЕН/БЛОК.
layout v1:       D4-002 проверяет текстовые блоки PDF: сигнатуры основной надписи должны быть в
                 ожидаемой нижней правой зоне листа; вне зоны = computed_issue.
safe self-write: ЛЕС может вести реестр источников/подсказки/missing-actions, но расчётные ядра и
                 rulepack меняются только через версию, тесты и ledger.
```

---

## v0.23C — Real Dataset Acceptance

Цель: уйти от fixture-confidence к реальной приёмке.

### Прогнать 3–5 реальных датасетов

Минимальные типы:

```text
norm-like dataset
mail-like .eml dataset
project-like dataset
SPDS ПД/РД dataset for normcontrol
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

## v0.24 — SPDS Documentation Normcontrol: ГОСТ Р 21.101-2026

Цель: первым доменным workflow сделать нормоконтроль комплекта документации на соответствие
СПДС и требованиям нормоконтроля. Первый стандарт в фокусе — ГОСТ Р 21.101-2026.

Это не падение в чистую детерминацию и не обычный одиночный RAG-вопрос. Workflow — RAG-led review:

```text
комплект ПД/РД
  → RAG находит применимые требования СПДС/ГОСТ
  → отдельный profile сверяет состав ПД по ПП РФ №87
  → RAG находит evidence в комплекте
  → код проверяет только формализуемые вещи
  → модель объясняет и связывает evidence
  → инженер подтверждает/отклоняет замечание
  → normalized remarks
  → XLSX/JSON/HTML отчёт, затем DOCX/PDF renderer
```

Статус стандарта на 2026-06-26:

```text
ГОСТ Р 21.101-2026
Система проектной документации для строительства.
Основные требования к проектной и рабочей документации.
Утверждён приказом Росстандарта от 12.02.2026 № 129-ст.
Дата введения: 01.04.2026.
Взамен ГОСТ Р 21.101-2020.
```

### Сделать

```text
rulepack config/normcontrol/gost_r_21_101_2026.yaml как карта review, не как полный rule engine и не "ГОСТ в YAML"
doc-review service поверх текущего normcontrol v1 и RAG retrieval
SPDS applicability: ПД/РД/unknown, комплект, раздел, марка, дисциплина
document set model: файл ↔ лист ↔ ведомость ↔ штамп ↔ обозначение
ПП 87 composition profile для состава ПД
RAG search по требованиям ГОСТ Р 21.101-2026 и related СПДС
RAG search по комплекту: ведомости, штампы, пояснения, листы, изменения
computed checks: состав комплекта, ведомости, обозначения, листы, изменения
title block/stamp extraction: уверенно или manual_required
evidence model: requirement, document_evidence, computed_check, model_note, human_decision
normalized remark JSON: общий выход для doc-review/formal-checker/checklist/cross-checker
отчёт XLSX/JSON/HTML
UI "Проверка документации" в Инструментах
```

Принципы:

```text
полный текст ГОСТ не коммитить
rulepack хранит карту review: что искать, какие evidence нужны, какие checks возможны
RAG ищет требования и доказательства, rulepack не заменяет retrieval
окончательный status только для computed checks или подтверждённых человеком замечаний
если extraction/layout не уверен — manual_required, не fake pass
LLM формулирует вывод и вопросы к evidence, но не ставит финальное решение без evidence/human decision
computed checks являются evidence-слоем внутри RAG-led review, а не заменой retrieval
```

### Первый набор проверок

```text
RAG: найти применимые требования ГОСТ Р 21.101-2026 по комплекту
RAG: найти evidence в документах комплекта под каждое требование
version gate: выбран ГОСТ Р 21.101-2026, не устаревший 2020
применимость СПДС: комплект относится к ПД/РД или требует ручного выбора
computed: согласованность базового шифра комплекта
computed: ведомость рабочих чертежей / состав документации ↔ фактические файлы
computed/layout: обозначение документа: имя файла ↔ ведомость ↔ извлечённый штамп
computed: формат листа и текстовый слой
RAG/layout: основная надпись/штамп: evidence found / potential issue / manual_required
RAG/layout: изменения/revisions: evidence found / potential issue / not_applicable
```

### Acceptance

```text
synthetic РД clean → no confirmed error, requirements/evidence trace есть, silent pass нет
synthetic РД missing sheet → computed issue с rule_id/clause/source_ref
bad designation → potential/confirmed issue с target
synthetic ПД без обязательного раздела ПП 87 → computed/potential issue, не общий verdict
PDF без текста → OCR/manual_required, не crash
штамп не найден → manual_required или potential_issue, не pass
ГОСТ Р 21.101-2020 в корпусе при rulepack 2026 → warning
реальный комплект РД от оператора → top-10 RAG/computed замечаний вручную сверены
отчёт XLSX/JSON создаётся
JSON remarks пригоден для чек-листа БУП/ГИП и будущего DOCX/PDF отчёта
UI показывает retrieved requirements / computed checks / review needed / confirmed отдельно
```

Подробный план: `docs/DOC_REVIEW_GOST_R_21_101_2026_PLAN.md`.

### Статус 2026-06-27 — 0.24.0.0

```text
doc-review:      RAG-led ГОСТ Р 21.101-2026 workflow работает через чат, API и Инструменты.
reports:         JSON/HTML/XLSX доступны; XLSX содержит лист normalized_remarks.
evidence:        каждый пункт отдаёт items + defense_contract_v1 + normalized_remarks; финал остаётся за инженером.
layout:          D4-001 формат листа и D4-002 зона основной надписи проверяются кодом.
service sources: оператор видит, какие базы/датасеты нужны для смет и нормоконтроля.
public-ready:    README/LICENSE/SECURITY/PUBLICATION_CHECKLIST + make public-check.
```

Не закрыто и вынесено в v0.24+:

```text
ПП РФ №87 composition profile
импорт чек-листа БУП/ГИП как template
DOCX/PDF renderer отчёта
deeper layout-tool для заполнения всех граф основной надписи
```

---

## v0.24+ — Checklist Review ПД (профиль БУП/ГИП поверх Doc Review)

Цель: прикладной чек-лист входного контроля ПД ГИП/БУП **как профиль поверх v0.24**, НЕ отдельный
rule-engine и НЕ замена нормоконтролю. RAG-led checklist review: чек-лист задаёт карту требований,
RAG ищет evidence, код проверяет формализуемое, модель связывает/объясняет, инженер подтверждает.

Полная спецификация: **`docs/CHECKLIST_REVIEW_PD_TASK.md`** (13 разделов: классы пунктов, data model,
API, UI, report, проверки, tests, acceptance, 5-фазный roadmap). Сверена с `les final build spec.pdf`.

```text
вход:     Чек_лист_входного_контроля_ПД_ГИПы_БУП.xlsx (12 листов, 10 разделов, ~400 пунктов;
          дисциплины Общее/СПОЗУ/АР/КР/ЭОМ/ЭН/ВК_НВК/ОВиК/СС/ПБ2) + Приложение 1 PDF (печатный образ)
классы:   presence · calculation · spds_formal · cross_section · tz_vendor · layout · manual_required
сервисы:  checklist_template_importer · checklist_review_service · checklist_report_service +
          router checklist_review (опц. checklist_item_classifier)
переиспользовать: doc_review_service / normcontrol_service (computed) / RAG retrieval / ПП87 composition /
          normalized remark JSON (общий выход doc-review/formal/normative/consistency)
фазы:     P0 Doc Review alignment → P1 template import → P2 evidence review → P3 report+UI →
          P3b normcontrol DOCX/PDF → P4 РД extension → P5 Cross-Checker ПД↔РД
```

Инвариант: `suggested yes/no` запрещён без `evidence.source_ref`; `human_answer` сильнее предложенного;
никакого общего verdict «ПД соответствует» без human decision; полный текст ГОСТ/ПП87 не коммитить;
исходные XLSX/PDF оператора не коммитить (только нормализованный template/config). Для v1 — XLSX/JSON/
HTML отчёт; importer достаточно универсален, чтобы позже принять РД workbook (28 листов, ~793 пункта)
без переписывания архитектуры. Зависит от v0.24 (общий Doc Review / ГОСТ Р 21.101-2026 review-map).

---

## v0.24D — Transparent Smeta Document Intake

Цель: загрузка сметных документов должна быть прозрачной для пользователя. Оператор должен видеть не
только "файл загружен", а весь статус: куда файл попал, как будет использован, прочитан ли текст,
нужен ли parse/index, приложен ли он к следующему вопросу, и почему workflow заблокирован, если
документ пока непригоден.

Фокус — два разных входа, которые нельзя смешивать:

```text
служебный сметный датасет:
  постоянная база ЛЕС для смет — нормы, цены, индексы, формы, методики, шаблоны
  оператор кладёт файлы в служебный датасет и нажимает Play
  Play проверяет состав, форматы, parse/readiness, строит паспорт и показывает MISSING/BLOCKED

проектный сметный intake:
  ВОР, Ф9, ЛСР, спецификация, ТЗ, КП и ресурсные ведомости конкретного объекта
  файл идёт в проектный датасет или как одноразовое вложение к вопросу
  вопрос "по этому файлу" должен работать строго по этому файлу или явно блокироваться
```

### Какие документы нужны

```text
служебный датасет SMETA_SERVICE:
  нормы: ГЭСН/ФЕР/ТЕР, ресурсные части, локальные norm cards
    preferred: parquet/json/sqlite
    accepted raw: xlsx/csv/pdf/docx

  цены: ФГИС ЦС сплит-формы, ресурсные ведомости, КП/КАЦ, индексы Минстроя
    preferred: parquet/xlsx/csv
    accepted raw: pdf/docx для писем/КП с обязательным parse-status

  методика: 421/пр, НР/СП, правила РИМ, коэффициенты, КАЦ, локальные регламенты
    preferred: md/yaml/json для rule/config layer
    accepted raw: pdf/docx как source layer, не как исполняемый rule engine

  формы: ЛСР РИМ, ВОР, КАЦ, КС-2/КС-3, шаблоны экспорта
    preferred: xlsx

проектный intake:
  ВОР / Ф9 / ЛСР / ресурсная ведомость / спецификация / ТЗ / КП
    preferred: xlsx/xlsm/csv/docx
    accepted: pdf with text layer
    blocked/actionable: scanned pdf -> OCR/manual_required, corrupt/encrypted -> blocked
```

### Router refactor

Текущий `document_router` оставить на refactor: он устарел для основного GUI-пути `+ папка`.
Пользовательская папка/датасет/`LES.md` задают ownership и scope; router не должен перекладывать
проектные документы в глобальные `DOCS_OTHER_Index`, `NTD_ELECTRICAL_Index` и т.п. по своим
эвристикам. Его новая роль — классифицировать файл внутри выбранной области:

```text
dataset ownership:
  источник истины — выбранный оператором dataset/project/folder + LES.md
  `+ папка` создаёт/обновляет этот dataset, не отдавая boundary на эвристики имени файла
  sync-smart остаётся служебным/legacy/import инструментом, не основным проектным intake

file classification:
  document_role: ВОР / ЛСР / спецификация / КП / ТЗ / РД / НТД / unknown
  content_type: text / table / drawing / scan / mixed
  parse_pipeline: markdown / table_projection / pdf_reader / cad_projection / manual_required
  warnings: scanned_pdf / encrypted / no_text_layer / huge_file / likely_revision

trace contract:
  сохранять route hints в metadata документа
  показывать оператору, что router решил и что можно override
  не менять dataset_id без явного operator action
```

### Сделать

```text
service dataset Play:
  отдельный SMETA_SERVICE dataset/type или профиль служебного источника
  кнопка Play запускает bounded validation/parse, не полный reindex всего RAG_Content
  показывает manifest: found/ready/partial/missing/blocked по каждому классу источников
  строит/обновляет service notebook/passport для smeta prompt/tool shortlist
  не смешивает служебные источники с проектными доказательствами конкретного объекта

composer upload strip:
  файл виден сразу после выбора/загрузки
  режим виден явно: "в чат" / "прочитать" / "индексировать" / "сметный intake"
  есть remove/change mode до отправки

intake status card:
  original filename, size, type, target dataset/session
  parse state: not_needed / pending / running / ready / blocked / failed
  text/table layer: available / partial / missing / OCR/manual required
  next action: ask with attachment / prepare to search / open document / open artifact

smeta classification:
  ВОР / ЛСР / спецификация / КП / ресурсная ведомость / ТЗ / unknown
  classification is a hint, not final professional answer
  user can override type before asking
  classification must not move project files to another dataset

required-docs guidance:
  UI показывает, какие служебные документы нужны для РИМ/ГЭСН/КАЦ/индексов/форм
  для отсутствующего класса есть понятное MISSING: "нужна сплит-форма ФГИС ЦС" / "нужен шаблон ЛСР"
  для сырого PDF/XLSX есть status: raw / parsed / table-ready / indexed / manual_required

trace and evidence:
  chat payload records attachment ids, parse ids, doc ids and source_refs
  answer explains whether it used attachment text, indexed chunks, table reader, or only filename
  no silent fallback to neighboring dataset/source when uploaded document is unreadable

fail path:
  legacy .xls, scanned PDF, encrypted/corrupt files and parser timeout produce actionable message
  no workflow crash; no fake "indexed" document with zero usable text
```

### Acceptance

```text
Оператор видит SMETA_SERVICE, кладёт туда нормы/цены/формы/методики и нажимает Play.
После Play есть отчёт: какие классы источников готовы, какие partial, какие MISSING/BLOCKED.
Служебный датасет подмешивается в сметный workflow как база/навигация, но не как evidence объекта.
Пользователь загружает ВОР/XLSX и до вопроса видит, что файл готов как табличный источник.
Пользователь загружает PDF-ЛСР без текста и видит "нужен OCR/manual", а не пустой ответ.
Вопрос "сделай смету по этому файлу" использует именно этот файл или явно говорит, почему нет.
В composer/user bubble есть видимый статус вложения; после отправки одноразовое вложение снимается.
Trace/source_refs позволяют открыть исходник или сметный artifact.
`+ папка` сохраняет проектную границу датасета; router даёт metadata/hints, но не уводит файлы
в соседние глобальные индексы без явного действия оператора.
Regression test покрывает service Play, happy upload path, parser fail path и "не ушло в соседний датасет".
```

### Статус 2026-07-04 — 0.24.0.231

```text
SMETA_SERVICE: добавлен как служебный источник в config/service_sources.yaml.
required docs: Play показывает manifest по классам norms/prices/methodology/forms.
formats: для каждого класса указаны preferred и accepted raw форматы.
UI: в «Инструменты» появился раскрываемый блок «Какие документы нужны».
API: /api/service-sources* отдаёт required_documents, /process возвращает Play summary.
router refactor: добавлен в roadmap как precondition transparent project intake.
external intake plan: `+ папка` перед Play показывает project/dataset, accepted/skipped, maps,
discipline hints и missing для сметы; `00_dataset_map.md` создаётся до регистрации файлов.
open: проектный upload/intake ВОР/ЛСР/КП с видимым статусом в composer ещё не реализован.
```

### Не делать в этом блоке

```text
не строить новую сметную математику
не выбирать работы/нормы кодом
не делать широкий OCR pipeline
не запускать полный reindex без явного действия оператора
```

---

## v0.24E — PDF/XLS Reader Tools + System Table Layer

Цель: довести уже сделанную parse/index защиту до пользовательского workflow. Большие таблицы и PDF
должны быть не только безопасно проиндексированы, но и читаемы инструментом по листу/строке/таблице,
чтобы модель могла выбирать источник, а код доставал точные строки и считал.

Текущее состояние: Л.И.С.Т. уже строит bounded project PDF source-map, читает
ЭС/ЭОМ, ОВ ХВС, ВК water balance и экспликации помещений, честно различает
`ok/partial/failed/empty` и не выдаёт слабые слова из технических руководств за
кабельную таблицу или ВОР. Открытый остаток этапа — точные XLS/PDF reader API
по диапазону/строке/таблице и `manual_required` для сканов, а не новые
эвристические категории.

### Сделать

```text
Excel reader:
  list sheets / columns / table profiles
  read rows by filter/range
  aggregate numeric columns with source refs
  preserve full Parquet/source file path outside semantic chunks

PDF reader:
  page/table locator
  extracted text/table status
  page preview/open where available
  manual_required for scanned/ambiguous pages

tool-harness integration:
  model sees available readers from shortlist
  tool result returns source_refs, missing, warnings, trace
  final answer stays model-written; code only reads/counts
```

### Acceptance

```text
Большой XLSX не засоряет RAG, но конкретная строка/сумма доступна reader tool.
PDF с таблицей даёт page/table source_ref или честный manual_required.
Сметный workflow может ссылаться на строки ВОР/ЛСР без угадывания из markdown excerpt.
```

---

## v0.24F — CAD/DWG Table Hardening

Цель: расширить доказанный smoke `drawn_table_1 first positions` до устойчивого CAD-table workflow.
Не нужно обещать "любой DWG"; нужно закрыть самые частые инженерные таблицы без ухода в соседние
projection-и и без сотен графических примитивов в prompt.

### Сделать

```text
drawn table variants:
  merged cells / multi-line cell text / split text by columns
  repeated headers / multi-page continuation
  rotated or shifted grids where safely detectable

projection quality:
  table summary before element noise
  first positions, logical positions, compact rows, source_row/source_cell refs
  weak/minimal import status visible in CAD inventory

retrieval quality:
  target_file/doc_filter stays strict
  first ordinal pins survive rerank, source concentration and context expansion
  neighboring tables remain visible as alternatives, not as replacement evidence
```

### Acceptance

```text
3-5 real DWG/DXF specs: first positions, middle position and named equipment answer from target table.
Weak/minimal drawings do not pretend to be complete.
CAD inventory points to projection and chat target_file without manual path copying.
```

---

## v0.25 — Retrieval and Citation Quality

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

## v0.26 — Estimate Workflow Hardening

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

## v0.26+ — Источник: индексы изменения сметной стоимости (Минстрой ИФ/09)

Цель: завести **официальные индексы изменения сметной стоимости Минстроя** как локальный источник для
перевода базовых цен в текущие (`price_base × индекс` — графы 8-10 РИМ-трассы, режим `fgis_base_index`).
Сейчас индекс берётся из ФГИС ЦС; письма Минстроя — официальный рекомендованный источник (особ. для
базисно-индексного метода) и нужны, когда ФГИС ЦС не покрывает субъект/квартал.

```text
источник:  https://minstroyrf.gov.ru/trades/tsenoobrazovanie/indeksy-izmeneniya-smetnoy-stoimosti/
формат:    ежемесячные/квартальные «Письма Минстроя России … № NNNNN-ИФ/09 О рекомендуемой величине
           индексов изменения сметной стоимости …» → страница /docs/<id>/ + PDF /upload/iblock/…
           (свежие: 22.06.2026 №37404-ИФ/09, 03.06.2026 №33771-ИФ/09, 22.05.2026 №31091-ИФ/09, …)
содержание PDF: индексы по субъектам РФ × видам строительства/работ × элементам прямых затрат
           (СМР, ОЗП, ЭМ, материалы) — таблицы внутри письма (часто приложением)
egress:    minstroyrf.gov.ru РЕЖЕТ не-РФ IP (WebFetch/рантайм-сеть таймаутят) → тянуть через РФ-VPS
           `box` (ZeroTier 10.195.146.136 / public 185.185.71.196), как ГЭСН-добор (LES_FGIS_VIA_SSH)
```

Принцип (см. R6 и [[local-bases-untrusted-channel]]): **локаль-первый** — PDF/индексы кэшировать в
parquet локально, канал (Минстрой) только для квартального обновления по запросу; query-time без сети.
Шаги: (1) скачать последнее письмо через `box`; (2) распарсить таблицу индексов (PDF → строки:
субъект×вид×элемент→коэф.); (3) сложить в `data/indices/minstroy_if09.parquet`; (4) сервис
`index_lookup` (субъект+квартал+вид → индекс) → стык с `fgis_price_service`/РИМ-трассой. Релиз —
post-v1 (как Price DB/FGIS в §4), но добор уже возможен ручным шагом из рантайма.

---

## v0.90 — Release Candidate

После v0.26 перестать добавлять крупные функции.

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
проверять комплект документации на соответствие СПДС / ГОСТ Р 21.101-2026
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
19. Auth/trust допускает предсказуемый admin/JWT default или X-Forwarded-For spoof.
20. Нет проверенного restore для SQLite + Qdrant.
21. MetaDB↔Qdrant рассинхрон не виден в health/doctor.
22. Diagnostics/doctor нормализуют реальные FAIL в OK/WARN без raw_status.
23. Нормоконтроль СПДС ставит pass/fail без source_ref или при layout uncertainty.
24. Проверка ГОСТ Р 21.101-2026 молча использует/цитирует устаревший ГОСТ Р 21.101-2020.
25. Загруженный сметный документ исчезает из UI или используется неочевидно.
26. Вопрос "по этому файлу" отвечает по соседнему датасету/таблице без явного blocker.
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
загрузи ВОР/XLSX → файл виден → "сделай смету по этому файлу" использует именно его
загрузи PDF без текстового слоя → виден blocker OCR/manual_required
```

### SPDS normcontrol smoke

```text
ГОСТ Р 21.101-2026 rulepack загружается
clean synthetic РД → 0 error
missing sheet synthetic РД → error с rule_id/clause/source_ref
bad designation → warning/error
stamp unknown → manual_required
outdated ГОСТ Р 21.101-2020 source при rulepack 2026 → warning
отчёт XLSX/JSON создаётся
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

### Operational trust smoke

```text
auth/trust: public client без ключа → 401
auth/trust: trusted ZeroTier/loopback → ожидаемая роль
auth/trust: spoofed X-Forwarded-For от недоверенного peer не даёт trusted
backup: сделать backup + restore на копии SQLite/Qdrant
index: MetaDB↔Qdrant consistency check green
diagnostics: искусственно выключенный сервис виден как FAIL/UNREACHABLE, не OK
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
SPDS normcontrol
estimate workflow
smoke/ledger
```

Каждый коммит должен отвечать на вопрос:

```text
Это приближает v1 или просто добавляет ветку сложности?
```

---

## 11. Открытые риски

Важно: пункты ниже — не приговор архитектуре, а проверяемые риск-гипотезы. Их нельзя чинить
"потому что так написано в аудите". Каждый риск должен закрываться трассой, smoke/golden-тестом
или измерением. Если проверка показывает, что риск не воспроизводится или уже закрыт другим
механизмом, пункт снимается или понижается.

### R0. Architecture risk hypotheses

Текущие гипотезы риска:

```text
quality/CRAG/validator/strict-retry могут быть неаддитивными и блокировать ответ при найденных источниках
keyword/substring routing может перехватывать вопрос раньше intent/scope contract
несколько роутеров могут конкурировать за один простой запрос
UI evidence может отставать от backend evidence
ingestion/format contracts могут расходиться между конвертером, smart_index, router и sidecar
make verify не ловит базовый пользовательский путь
```

Как доказывать или снимать:

```text
trace показывает, какой слой принял/отклонил решение
golden/smoke воспроизводит проблему до фикса и зелёный после
negative smoke доказывает, что анти-галлюцинация не ослаблена
basic product smoke доказывает UI-путь глазами пользователя
если риск не воспроизводится на real dataset matrix — снять/понизить, не чинить вслепую
```

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

### R8. Upload transparency

Сметный файл может быть технически загружен, но пользователь не понимает, попал ли он в следующий
запрос, прочитан ли текст/таблицы, нужен ли parse/index/OCR и почему ответ ушёл не туда. Это v1-риск,
потому что "по этому файлу" является базовым пользовательским контрактом.

### R9. Tool-loop stability

Общий model-selected tool loop уже стал ядром для чтения источников, но `tool_loop NameError` и похожие
ошибки должны закрываться отдельными regression tests. Инструментальный слой не должен падать молча
и не должен заменять модельный финальный ответ кодовой заглушкой.

### R10. Local generation latency

Локальная генерация остаётся продуктовым риском: даже правильный workflow не v1-ready, если пользователь
не видит понятного progress/status и не может остановить долгий ответ.

---

## 12. Definition of Done for v1.0

v1.0 можно выпускать, если:

```text
[ ] версия и commit видны в UI
[ ] /api/version работает
[ ] runtime alignment виден
[ ] route smoke green
[ ] evidence smoke green
[ ] SPDS normcontrol ГОСТ Р 21.101-2026 smoke green
[ ] estimate smoke green
[ ] transparent smeta upload smoke green
[ ] resource workbook smoke green
[ ] sidecar workflow smoke green
[ ] UI smoke green
[ ] operational trust smoke green
[ ] backup restore smoke green
[ ] MetaDB↔Qdrant consistency smoke green
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
v0.23A — Operational Trust Hardening
v0.23B — Clickable Sources + Citation Drawer
v0.23C — Real Dataset Acceptance
v0.24 — SPDS Documentation Normcontrol: ГОСТ Р 21.101-2026
v0.24+ — Checklist Review ПД (профиль БУП/ГИП поверх Doc Review) → docs/CHECKLIST_REVIEW_PD_TASK.md
v0.24D — Transparent Smeta Document Intake
v0.24E — PDF/XLS Reader Tools + System Table Layer
v0.24F — CAD/DWG Table Hardening
v0.25 — Retrieval and Citation Quality
v0.26 — Estimate Workflow Hardening
v0.26+ — Источник: индексы изменения сметной стоимости (Минстрой ИФ/09, локаль-первый, egress через РФ-VPS)
v0.90 — Release Candidate
v1.0  — Local Evidence Assistant
```

После v0.26 — feature freeze. Дальше только стабилизация.

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
прозрачно показывает, что случилось с загруженным документом,
даёт открыть и скопировать доказательства,
и позволяет понять, какая версия сейчас запущена.
```
