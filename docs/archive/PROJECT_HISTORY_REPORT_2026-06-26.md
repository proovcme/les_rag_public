# История проекта ЛЕС из git/GitHub

Дата аудита: 2026-06-26.

Источник: локальный git `/Users/ovc/Projects/LES_v2`, remote `origin` (`proovcme/les_rag`),
remote `public` (`proovcme/les_rag_public`), `gh repo view`, `git log`, `git tag`,
канонические и исторические документы репозитория.

---

## 1. Короткий вывод

ЛЕС начался как локальный RAG-runtime для строительных документов:

```text
FastAPI + Qdrant + Ollama + SQLite + UI
```

За полтора месяца он прошёл четыре больших превращения:

```text
1. self-hosted RAG appliance
2. MLX/Core ML локальный runtime с индексом, UI, доступом и смоуками
3. строительная ИИ-СОД: нормы + проект + таблицы + почта + CAD/BIM + формы
4. evidence-harness: вопрос → scope → источники → расчёт кодом → blockers → проверяемый ответ
```

Главная траектория здравая: проект не просто "RAG", а локальный строительный evidence-harness.
Но рост был очень быстрым: за 47 дней история выросла до 560 коммитов, 963 tracked files,
503 Python-файлов, 138 markdown-документов и 208 test-файлов. Из-за этого накопился главный долг:
много полезных слоёв стали блокирующими гейтами и keyword-перехватчиками. То есть ломалось не потому,
что ядро поиска слабое, а потому что вокруг него стало слишком много неаддитивной логики.

---

## 2. Текущее состояние refs

Private GitHub:

```text
repo: proovcme/les_rag
created: 2026-05-10
private: true
default branch: main
origin/main: 98278ea
origin/feat/les3-p1: 98278ea
```

Local dev:

```text
branch: feat/les3-p1
local HEAD: 98278ea
origin/feat/les3-p1...HEAD: 0 0
```

Public GitHub:

```text
repo: proovcme/les_rag_public
created: 2026-06-05
public/main: 41aaf01
description: public snapshot for engineering RAG, CAD/BIM JSON exporters and ATLAS viewer
```

Public release tags:

```text
v0.1.0-public-cad-bim-rag
v0.1.1-public-atlas
v0.1.2-public-boxed-install
v0.1.3-rc1-windows-light
v0.1.4-public-installers
```

Private tags:

```text
v0.1.0
v0.1.1-dev
```

---

## 3. Рост проекта

Срезы по commit:

| Срез | Дата | Смысл | Files | Python | Markdown |
|---|---:|---|---:|---:|---:|
| `1b8d1f8` | 2026-05-10 | Initial LES v2 core | 16 | 6 | 5 |
| `b34c69a` | 2026-06-01 | local consistency baseline | 279 | 195 | 30 |
| `cc869e9` | 2026-06-07 | ARTEL/Revit closeout | 523 | 219 | 73 |
| `1e98be6` | 2026-06-14 | LES3 brain/ARTEL wave | 623 | 292 | 92 |
| `11418b3` | 2026-06-23 | retrieval perf + table answers | 885 | 444 | 127 |
| `98278ea` | 2026-06-26 | GitHub/local current | 967 | 506 | 139 |

Активность по датам показывает несколько взрывных сессий:

```text
2026-06-06: 41 commit
2026-06-14: 53 commit
2026-06-23: 53 commit
2026-06-24: 47 commit
2026-06-26: 40 commit
```

Это важно: проект развивался не линейно, а рывками. Многие решения принимались правильно,
но одновременно. Поэтому часть старых документов стала исторической, а часть кода получила
несколько параллельных маршрутов для похожей задачи.

---

## 4. Этапы развития

### Этап 0. До git-канона: LES 1.5

Документ `ROADMAP_LES_v2.0.md` хранит до-git контекст:

```text
К.О.Т. v1.1: Speckle GraphQL
С.У.Х.А.Р.И.К. v1.0: бэкапы MySQL/ES в MinIO
В.О.Л.К.: RBAC/JWT
Е.Ж.И.К.: OCR/Tesseract
RAGFLOW_API_URL
```

Это была более тяжёлая, внешне-инфраструктурная архитектура:

```text
RAGFlow / Elasticsearch / MySQL / MinIO / Redis / Celery
```

Вывод: ЛЕС v2 не возник на пустом месте. Он был реакцией на тяжёлый стек v1.5.

### Этап 1. 2026-05-10 — LES v2.0 Core

Первый commit:

```text
1b8d1f8 Initial commit: LES v2.0 Core (FastAPI+Qdrant+Ollama)
```

Смысл:

```text
отказ от RAGFlow/ES/MySQL/MinIO/Redis/Celery
переход на FastAPI + Qdrant + SQLite + LlamaIndex
локальный runtime без Docker как основного способа жизни
Ollama-модели qwen3/qwen2.5-coder/bge-m3
```

Архитектурно это был правильный резкий упрощатель: меньше внешней инфраструктуры,
больше локального контроля.

### Этап 2. 2026-05-12 — поворот к MLX

Ключевой commit:

```text
34a1041 Feat: Integrate MLX adapter and Qwen3 diagnostic tools. Transition to native MLX backend.
```

За 2 дня проект ушёл от Ollama-first к Apple Silicon / MLX-first. Затем:

```text
968b2ff completely drop Ollama support in favor of MLX
eaa4050 v2.5 stabilization — CRAG, VOLK, security
5a806dd v2.6 — модели, память, реранкер, watchdog
856543f v2.7 — SafeRAG, concentration, history, design
5d580f7 v2.8 — deploy/pauk, VPS sync, ZeroTier
```

Смысл:

```text
локальная модель становится не экспериментом, а runtime-ядром
появляется MLX-host :8080
появляется В.О.Л.К./П.А.У.К./ZeroTier/external contour
появляются первые реальные safety/auth/smoke задачи
```

Что пошло не туда:

```text
быстрый переход MLX-first создал сильную зависимость от памяти, Metal, TTL-выгрузки и launchd
часть старых Ollama/legacy assumptions потом приходилось чистить
```

### Этап 3. 2026-05-21 — 2026-05-24: runtime hardening

Ключевые commits:

```text
9f405bd Stabilize proxy auth boundary
99e8a30 Add post-deploy runtime smoke
29b4e62 Add Sovushka browser smoke
d64578b Stabilize Sovushka chat and refresh docs
76e6d08 Stabilize host runtime and indexing control
7772a0d Stabilize indexing and NTD dataset routing
```

Смысл:

```text
проект стал не просто кодом, а живым сервисом
появились runtime_smoke и browser_smoke
началась реальная эксплуатационная дисциплина
```

Что пошло правильно:

```text
smoke-инструменты появились рано
auth boundary тестировался
UI разделился на внешний чат и админку
```

Что пошло не до конца:

```text
smoke остались необязательными ручными командами, а не продуктовым gate
позже это вылезло как "всё зелёное, но руками элементарное лезет"
```

### Этап 4. 2026-05-26 — 2026-06-01: индексация, почта, consistency baseline

Ключевые commits:

```text
5dd340b Add Sovushka Lite chat shell
85198ae Add memory-first Sovushka Lite admin
95ae1b5 Add guarded dataset reindex tool
7ce866b Add local mail ingest for EZHIK
da0e354 Add IMAP ingest for EZHIK
33df8b8 Finalize LES Core ML runtime closeout
64aaa96 Harden FIRE and HVAC domain retrieval
9f6ee02 integrate MarkItDown, LangExtract, GLM-OCR
b34c69a Close LES local consistency baseline
```

Фактический baseline 2026-06-01:

```text
1211/1212 files indexed
0 pending / 0 errors
~142k SQLite chunks and Qdrant points aligned
FIRE/HVAC golden 16/16
357 pytest passed
```

Смысл:

```text
ЛЕС стал настоящим локальным RAG-appliance
появились офисные парсеры, OCR, structured_rules, почта, guarded reindex
появилась доменная приёмка FIRE/HVAC, а не только "работает endpoint"
```

Что пошло не туда:

```text
много ingestion/format веток появилось быстро
часть парсеров и диспетчеров форматов позже разошлась
structured_rules был code-ready, но не стал заполненным production-слоем
```

### Этап 5. 2026-06-02 — 2026-06-07: CAD/BIM, public snapshot, ATLAS, ARTEL

Ключевые commits:

```text
8c1a592 Add Speckle CAD BIM profiles and provider settings
49ed79b Make CAD BIM ingestion JSON first
fcc34b6 Add CAD BIM JSON exporters and OBC viewer
8621159 Add offline CAD BIM viewer package
e3dbf64 Add VIZOR ask LES action
89c35ca Add boxed installers and release artifacts
f77fbc0 Add ATLAS and ARTEL product surfaces
e62338e Add ARTEL Revit loop and Windows light runtime
cc869e9 Document ARTEL Revit loop closeout
```

Публичный репозиторий создан 2026-06-05:

```text
proovcme/les_rag_public
public ATLAS/CAD-BIM snapshot
```

Смысл:

```text
ЛЕС вышел из "поиск по документам" в CAD/BIM и продуктовые поверхности
ATLAS/VIZOR стал отдельной визуальной веткой
ARTEL стал отдельным Revit/RFA направлением
появилась упаковка: standalone, installers, public snapshot
```

Что пошло правильно:

```text
CAD/BIM переведён в JSON-first — правильное решение для надёжности
public snapshot отделён от private core
ARTEL вынесен в products/, а не смешан полностью с ядром
```

Что пошло не туда:

```text
Speckle self-hosted оказался несовместим с ожиданиями V3 connectors
часть CAD/BIM/ARTEL задач расширила продукт быстрее, чем был стабилизирован базовый RAG UX
```

### Этап 6. 2026-06-09 — 2026-06-14: LES3 как программа взросления

Ключевые commits:

```text
dfe896b add CODE_MAP.md
737981a add make verify gate
fb1d9de add AGENTS.md, CLAUDE.md, AGENT_NOTES.md
de0aed2 LES3 plan — ADR, waves W0-W14
1356dca CI offline verify
39119ed cross-encoder reranker
0a5496a BM25/IDF sparse sidecar
1594ec8 local/cloud P0/P1/P2 routing
67e1b33 SSE streaming
3723afb /api/live push
e942c83 single NiceGUI UI
4bffa54 remove external Speckle connector
444d058 object dossier
8770ae9 domain ontology
1ed27f0 decision layer
5566276 aggregate BIM chunks + OЖР
```

Главные ADR:

```text
эволюция, не переписывание
OpenAI-compatible protocol as LLM bus
cross-encoder reranker, not LLM reranking
token chunking
LLM минимализм: LLM последней
облако только OpenRouter/OpenAI и только по sensitivity policy
GUI-first: функция должна иметь кнопку, не только curl
```

Смысл:

```text
ЛЕС перестал быть просто RAG-сервисом и стал программой "ИИ-СОД для стройки"
появились волны работ, ADR, CODE_MAP, AGENTS, gates
качество retrieval стало измеряться golden-наборами
```

Что пошло правильно:

```text
dense+sparse+rerank дал доменный gate 16/16
BM25/IDF sparse выбран вместо BGE-M3 learned-sparse после замера 9ч vs 36с
LLM-ступень weak retry не внедрили без выгоды — редкая дисциплина
```

Что пошло не туда:

```text
14 июня было слишком много параллельных продуктовых направлений
UI, brain, ARTEL, forms, graph, stream, install, BIM — всё росло одновременно
часть live-приёмок была "за оператором", а код уже двигался дальше
```

### Этап 7. 2026-06-15 — 2026-06-23: строительная предметность

Ключевые commits:

```text
37b4bbb W20.4 входной контроль
4739287 W20.1 парсер смет
b27eb78 deterministic SUM по полному Parquet
ccf98ea external folder indexing in-place
4fc5371 reconcile ВОР↔КС-2↔смета↔ИД
f7df5ea specification form 9 → BOR works
cf4ca6a MCP-server LES
8868672 asbuilt mounted volume from scans
616c845 LES.md folder-context
f3d8e53 smeta pricing + deterministic chat channels
53d1b9d full GESN-2022 import from FGIS
fba969a local FGIS price base
0f03247 object estimate end-to-end
6651e5f Outlook mail push
2468f4e layout-aware PDF extraction
d8f84a0 tool catalog + constrained router
cb8fdaf answer layer synthesizes from found sources
45c12c2 validator additive
11418b3 Qdrant payload-index perf
```

Смысл:

```text
проект наконец получил строительную "плоть":
сметы, ГЭСН, ФГИС ЦС, КАЦ, ВОР, КС-2, ИД, ОЖР, входной контроль, Outlook, формы
```

Это очень важный этап: ЛЕС перестал быть "RAG по нормам" и стал рабочим контуром:

```text
документ → таблица/источник → расчёт кодом → форма/реестр/смета → действие
```

Что пошло правильно:

```text
числа начали считаться по Parquet/SQL/openpyxl, а не top-k RAG
появились ALGO-доки для 0 LLM ядер
MCP открыл инструменты наружу
```

Что пошло не туда:

```text
параллельно с доменной глубиной росло число детерминированных каналов-перехватчиков
keyword routes начали конкурировать с RAG и друг с другом
простые вопросы могли уходить в не тот канал
```

Ключевой аудит 2026-06-23 сформулировал проблему:

```text
ядро retrieval корректное
но вокруг него 5+ quality/verification gates и 3 router layers
они не аддитивны, а блокируют базовый путь
```

### Этап 8. 2026-06-24 — 2026-06-26: Unified Construction Harness и расплата за сложность

Ключевые commits:

```text
4cbb930 harness v0.7 operational live chat path
242b041 v0.8 operational hardening
c4d41b9 v0.9 real source adapters
b3634c4 v0.10 async adapters
01c2ea4 v0.11 real-data acceptance
0ad16ee v0.12 file_body + EML + markdown-table
9b84bc2 v0.13 document body extraction
977e791 v0.14 sidecar write policy
fbb93fe v0.15 approved runtime sidecar write
1e9e76c v0.16 sidecar operations
30283f4 v0.17 runtime alignment + registry fix + honest .xls
5ded539 v0.18 DeterministicFinalPolicy
b956039 v0.19 version_service
a6c0f81 v0.20 deploy stamp
11b4ba3 v0.21 scope model
ef7b71a v0.22 scope clarification
ab7bdd5 v0.23 harness version
7608b77 inversion: LLM-router primary, keyword cascade legacy
70da896 module audit
706835f VOLK P0 security defaults fixed
01c9430 SUHARIK restore
98e48d7 SAMOVAR MetaDB↔Qdrant reconcile
c36866e diagnostics raw_status
a0638ce PROXY_URL configurable
bb7abe8 background index-external
98278ea current GitHub/local basic smoke gate
```

Смысл:

```text
это уже не "добавляем фичи"
это попытка сделать систему взрослой:
видимая версия, deploy stamp, runtime alignment, scope contract,
source operations, failure ledger, module audit, operational trust
```

Что пошло правильно:

```text
появился канон AGENTS.md
доки разделены на current truth и historical context
deploy stamp признан источником правды runtime, а не git рантайм-клона
release roadmap до v1 стал evidence/operational oriented
```

Что всё ещё не закрыто:

```text
basic product smoke ещё не реализован как make smoke-basic
source drawer/open source/stop generation ещё не v1-ready
real dataset acceptance требует системной матрицы
health runtime degraded из-за pending index state
часть operational P0 только что закрыта или требует smoke-доказательства
```

---

## 5. Как менялась архитектурная идея

### Было: "локальный RAG"

```text
загрузить документы
нарезать
положить в Qdrant
спросить LLM с retrieved context
```

### Стало: "ИИ-СОД / строительный центр данных"

```text
нормы + проект + BIM/CAD + сметы + почта + формы + граф + задачи + память
```

### Сейчас формируется: "evidence-harness"

```text
dataset/project/scope
  → question
  → workflow/tool selection
  → retrieved/computed evidence
  → source refs
  → blockers/missing/conflicts
  → answer
  → user can inspect/copy/open/act
```

Именно это написано в текущем AGENTS.md:

```text
RAG — один из слоёв, не продукт.
Модель связывает, код считает.
Число без происхождения — не результат.
```

---

## 6. Главные развилки

### Развилка 1. RAGFlow → local FastAPI/Qdrant

Вердикт: правильно.

Причина:

```text
меньше внешней инфраструктуры
контроль над pipeline
локальность и приватность
```

Цена:

```text
всё пришлось строить самим: auth, jobs, diagnostics, deploy, restore, smoke
```

### Развилка 2. Ollama → MLX/Core ML

Вердикт: правильно для Apple Silicon, но дорого по операционной сложности.

Цена:

```text
память, Metal, TTL, warmup, model unloading, validator/main conflicts
```

### Развилка 3. Speckle connector → CAD/BIM JSON-first

Вердикт: правильно.

Причина:

```text
self-hosted Speckle/V3 connector limitations
JSON-first даёт воспроизводимость и offline path
```

### Развилка 4. More deterministic channels → LLM-router / evidence harness

Вердикт: вынужденный разворот.

Детерминированные каналы нужны, но они стали keyword-перехватчиками. Текущий правильный путь:

```text
инструменты остаются детерминированными
но выбор инструмента должен идти через явный intent/scope/profile contract
а не через случайный substring
```

### Развилка 5. Feature-first → gate-first

Вердикт: сейчас проект наконец туда повернул.

Новые gates:

```text
operational trust
clickable sources/citation drawer
real dataset acceptance
retrieval/citation quality
estimate workflow hardening
basic product smoke
```

---

## 7. Где пошло не туда

### 1. Слишком много параллельных истин

Исторические `README`, `ROADMAP`, `SESSION_SUMMARY`, `LES3_PLAN`, `SKILL`, `CODE_MAP`
часто описывали разные эпохи. Это уже частично исправлено в `AGENTS.md`, где задан порядок чтения.

### 2. Детерминизм превратился в перехват

Нужная идея:

```text
числа и действия считает код
```

Плохая реализация, которая возникла местами:

```text
keyword/substring решает, что хотел пользователь
```

Итог: "расскажи про котельную" мог уходить в ОЖР/help/glossary.

### 3. Гейты были неаддитивными

Quality/CRAG/validator/strict retry/scope могли занулить ответ при наличии релевантных источников.
Правильная модель:

```text
нашли релевантное → ответить с цитатами
сомневаемся → пометить weak/unvalidated
нет данных → MISSING/BLOCKED
```

### 4. UI отставал от backend

Backend уже умел source/evidence/sidecar/version, но UI не всегда давал:

```text
открыть источник
понять MISSING/BLOCKED
остановить генерацию
увидеть честный degraded
скопировать без сюрпризов
```

### 5. Runtime truth долго путалась с git truth

Рантайм-клон исторически divergent. Правильный фикс:

```text
deploy stamp + runtime_alignment
```

### 6. Базовый smoke не стал обязательным достаточно рано

`make verify` хорош, но он не ловит "пользователь открыл UI и кнопка не работает".
Нужен `make smoke-basic`.

---

## 8. Где проект сейчас

На 2026-06-26 проект находится между `h0.23` и v1.

Готовое ядро:

```text
FastAPI proxy
MLX-host
Qdrant + SQLite MetaDB
NiceGUI Совушка
scope model
version/deploy stamp
source operations
deterministic calculation services
mail/CAD/BIM/smeta/form/action layers
large offline test inventory
```

Взрослые признаки:

```text
AGENTS.md canon
CODE_MAP
ALGO docs for 0 LLM kernels
failure ledger
release roadmap
module audit
runtime stamp
manual gates
```

Невзрослые признаки:

```text
часть gates ещё ручные
basic product smoke не автоматизирован
часть UI evidence функций не v1-ready
runtime health degraded из-за pending index
некоторые module fixes требуют proof-smoke
```

---

## 9. Куда идёт

Текущий `ROADMAP_TO_V1.md` правильно задаёт порядок:

```text
v0.23A — Operational Trust Hardening
v0.23B — Clickable Sources + Citation Drawer
v0.23C — Real Dataset Acceptance
v0.24  — Retrieval and Citation Quality
v0.25  — Estimate Workflow Hardening
v0.90  — Release Candidate
v1.0   — Local Evidence Assistant
```

Правильная v1-формула:

```text
локальный строительный evidence-assistant
для одного пользователя
с реальными источниками
с расчётами кодом
с честным MISSING/BLOCKED
с проверяемыми цитатами
с UI, где источник можно открыть, ответ скопировать, генерацию остановить
```

---

## 10. Рекомендация

Не добавлять новых крупных доменных модулей до закрытия трёх вещей:

```text
1. make smoke-basic
2. source/citation drawer end-to-end
3. operational trust smoke: auth, restore, MetaDB↔Qdrant, diagnostics truth
```

После этого можно идти в:

```text
real dataset acceptance 3-5 комплектов
retrieval/citation quality
estimate workflow hardening
RC freeze
```

Главная мысль: проект уже достаточно сильный. Ему сейчас меньше нужны новые органы,
и больше нужна нервная система: единый contract, smoke gates, truthful diagnostics,
и пользовательский evidence-loop без фейковых кнопок.
