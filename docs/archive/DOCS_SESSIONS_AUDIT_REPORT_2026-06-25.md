# Отчет по документации, аудитам и историям сессий

Дата: 2026-06-25
Фокус: ЛЕС как RAG-harness для стройки, архитектура, функциональная готовность, честные разрывы.

## 1. Что просмотрено

Канонические входы:

- `AGENTS.md`, `SKILL.md`, `docs/CODE_MAP.md`.
- Архитектурные документы: `PROXY_ARCHITECTURE.md`, `INFRASTRUCTURE_v2.0.md`, `LES_MASTER_DOC_v2_1.md`, `RAG_MODERNIZATION_PLAN.md`, `RUNTIME_MEMORY_PROFILES.md`, `docs/ARCHITECTURE_les_algorithm.md`.
- Аудиты: `docs/AUDIT_CORE.md`, `docs/AUDIT_RAG_ARCHITECTURE.md`, `docs/AUDIT_RAG_FUNCTIONAL.md`, `docs/AUDIT_DETERMINISM.md`.
- Roadmap и планы: `ROADMAP_TO_V1.md`, `docs/PLAN_DODELKA.md`, `docs/LES3_PLAN.md`, `docs/TEST_INVENTORY.md`, `docs/unified_harness_failure_ledger.md`, `docs/HANDOFF.md`.
- Алгоритмические доки по строительному ядру: `docs/ALGO-table-query.md`, `docs/ALGO-spec-to-bor.md`, `docs/ALGO-gesn.md`, `docs/ALGO-fgis-price.md`, `docs/ALGO-kac.md`, `docs/ALGO-lsr-assembly.md`, `docs/ALGO-object-estimate.md`, `docs/ALGO-mail-intake.md`, `docs/ALGO-asbuilt-intake.md`, `docs/ALGO-pdf-layout.md`, `docs/ALGO-vl-lora.md`.
- Истории сессий: `SESSION_SUMMARY.md`, `SESSION_SUMMARY_3.md` ... `SESSION_SUMMARY_12.md`, `docs/HANDOFF.md`, `docs/STORY_les_dispatcher.md`.
- Ранний агентский лог: `.aider.chat.history.md` просмотрен выборочно как исторический след раннего monolith/proxy-этапа.
- Локальный WebArchive: `/Users/ovc/Downloads/ЛЕС алгоритм архитектура.webarchive` — 16 сообщений из чата "ЛЕС алгоритм архитектура": исходная архитектура, внешний разнос, отчеты кодера v0.15/v0.17/v0.18/v0.20/v0.22 и prompt на v0.23 Clickable Sources.

Не трогал по правилам безопасности: `.env`, секреты, `data/`, `logs/`, `.venv/`, `local_private_archive/`, тяжелые артефакты, `docs/AGENT_NOTES.md`, сборочные `dist/`.

Внешняя ссылка `https://chatgpt.com/share/6a3c5596-128c-83eb-963a-910ee8303140` через fetch отдала только оболочку ChatGPT без текста беседы, но локальный `.webarchive` разобран как Apple binary plist и использован как источник.

## 2. Короткий вывод

ЛЕС уже не просто RAG над строительными документами. По документам и сессиям видно движение к локальному строительному evidence-assistant: проектный контекст, нормы, таблицы, почта, ВОР/ЛСР, ГЭСН, КАЦ, исполнительная, sidecar-подготовка документов, project graph, UI Совушки, runtime-диагностика.

Скелет сильный: локальный RAG, Qdrant, SQLite/FTS, CoreML/MLX, гибрид dense+sparse+rerank, deterministic tools, source_refs, sidecar extraction, failure ledger. Главная проблема сейчас не в отсутствии функций. Проблема в том, что функций стало больше, чем единой архитектурной рамки: несколько маршрутизаторов, несколько поколений документов, dev/runtime divergence, часть возможностей доказана смоуками, а часть пока существует как backend-контур без нормальной UI/live-приемки.

Если формулировать жестко: ЛЕС дорос до правильной идеи, но еще не стал стабильным v1-продуктом. Ему нужен не новый слой возможностей, а фиксация harness-контракта, route safety freeze, evidence UI и реальная приемка на 3-5 строительных датасетах.

## 3. Как система эволюционировала

### 3.1. Ранний этап: proxy/RAG и индексация

По `.aider.chat.history.md` и ранним session summary видно, что старт был прагматичным: FastAPI proxy, upload, chat, jobs, Qdrant, Ollama/MLX, простые метрики. Фокус был на том, чтобы поднять локальную RAG-систему, загрузить корпус и получить ответы.

Ключевые ранние проблемы были инфраструктурные: индексация больших документов, скорость эмбеддинга и поиска, health/runtime, перенос от BGE/Ollama-образа к Qwen/CoreML/MLX, стабилизация Qdrant/SQLite.

История про диспетчер из `docs/STORY_les_dispatcher.md` хорошо фиксирует поворот: keyword/regex-каналы дали быстрые демо, но начали имитировать понимание. Система стала уходить в "Excel with chat", где слово-триггер решает больше, чем смысл.

### 3.2. Второй этап: строительные инструменты

Дальше ЛЕС начал обрастать строительными детерминированными ядрами:

- `table_query`: суммы по табличным данным и Parquet.
- `spec_to_bor`: спецификация формы 9 -> ВОР.
- `bor`, `lsr`, `gesn`, `fgis_price`, `kac`, `stesnennost`: сметный контур.
- `asbuilt_intake`: извлечение смонтированного объема из исполнительной.
- `field`, `plan_fact`, `worklog`, `forms`: полевой и исполнительный слой.
- `mail_intake`: почта/Outlook как источник и триггер.
- `project graph`, typed edges, dossier, ontology, decisions.

Это правильное направление для стройки: модель не считает числа и не выдумывает норму; она связывает, выбирает, формулирует. Числа, статусы, source_refs и blockers должны приходить из кода.

### 3.3. Третий этап: unified construction harness

Поздние документы (`ROADMAP_TO_V1.md`, `docs/unified_harness_failure_ledger.md`, `docs/TEST_INVENTORY.md`) фиксируют новый центр тяжести: не "ответить RAG-ом", а провести строительный вопрос через evidence pipeline.

Сильные признаки зрелости:

- типы evidence: `RETRIEVED`, `COMPUTED`, `ASSUMED`, `MISSING`, `BLOCKED`, `CONFLICT`;
- честные failure types вместо общего "не найдено";
- source-scope важнее термина;
- sidecar extraction как операторская операция, а не скрытая магия;
- deterministic final policy против hijack-багов;
- resource workbook с проверенным итогом;
- version/runtime alignment как release blocker.

Это уже правильная рамка для "раг-харнесса под стройку".

## 4. Функциональная карта на сейчас

### 4.1. RAG-ядро

По документам ядро включает Qdrant dense retrieval на Qwen3 embeddings, SQLite/FTS, BM25/IDF sparse sidecar, cross-encoder rerank, context windows, typed retrieval/doc_router, validation/TOSKA и FIRE/HVAC golden gate 16/16.

Оценка: базовый RAG-скелет здоров. Проблемы не в "поставить другую модель", а в маршрутизации, evidence-контракте, качестве корпуса, dedup/citations и UI-предъявлении источников.

### 4.2. Строительный deterministic layer

Судя по ALGO-докам и CODE_MAP, есть большой набор 0-LLM или LLM-last инструментов: таблицы, ВОР, ЛСР, ГЭСН, ФГИС ЦС, КАЦ, стесненность, объектная смета на шаблонах, сверка ВОР/КС-2/сметы/ИД, полевой журнал, ОЖР, forms, исполнительная, почта.

Оценка: направление правильное. Слабое место не сами расчетные ядра, а границы применимости. Там, где есть явный источник и схема, система сильная. Там, где нужен широкий объектный разбор, появляются допущения, шаблоны и risk of overclaim.

### 4.3. Runtime и эксплуатация

Фактическая эксплуатация сложнее, чем обычный dev-repo: dev workspace `/Users/ovc/Projects/LES_v2`, live runtime clone `/Users/ovc/LES`, launchd services, дивергентный runtime, пофайловый деплой, опасный `uv sync` без `--extra mac-mlx`, deploy stamp и `/api/version`.

Оценка: это главный операционный риск. Для RAG-harness это угроза воспроизводимости: любой отчет "в коде есть" не равен "в живой системе работает".

### 4.4. UI Совушки

UI движется в правильную сторону: GUI-first, вкладки инструментов, артефакты, CSV/xlsx, source panels, project/file viewer, CAD/BIM viewer. Но roadmap честно говорит, что v1 невозможен без Evidence UI: открыть источник, цитаты, copy, stop generation, видимые `MISSING/BLOCKED/CONFLICT`, source chips, artifact cards, trace summary без terminal dump.

Оценка: backend сильнее UI. Для строительного ассистента это критично: если пользователь не видит evidence, он не может доверять результату.

## 5. Где пошло не туда

### 5.1. Тройная маршрутизация расползлась

В документах повторяется один и тот же корневой долг: explicit modes, command/regex handlers, keyword cascade, LLM agent-router, deterministic final handlers, RAG fallback.

Каждый слой был разумным локальным решением, но вместе они создают риск hijack: проектный вопрос улетает в glossary, source-scoped вопрос улетает в нормы, "реестр документации" путается с global registry.

Правильное направление уже зафиксировано: единый контракт `ProfileResolution`, где разные механизмы могут быть источниками решения, но наружу выходит один профиль `{workflow, tools, prompt/role, model/escalation, confidence, reasons, missing_slots}`.

### 5.2. Детерминизм местами стал отвечать вместо помогать

`docs/AUDIT_DETERMINISM.md` и `ROADMAP_TO_V1.md` прямо говорят: deterministic tools должны быть инструментами и гейтами, а не широкими автоответчиками по словам.

Плохой паттерн:

```text
слово найдено -> детерминированный final -> RAG не дошел до источников
```

Правильный паттерн:

```text
router/profile -> tool calls -> evidence -> answer synthesis -> visible blockers
```

### 5.3. Runtime/repo divergence бьет по доверию

`docs/AUDIT_CORE.md`, `SKILL.md`, `ROADMAP_TO_V1.md` сходятся в одном: живой ЛЕС и dev repo могут расходиться. Были реальные инциденты: plist drift ломал MLX/эмбеддер, runtime clone имеет незакоммиченные live-only правки, `uv sync` может снести MLX-зависимости, deploy был ручным `cp`/patch.

Это не просто DevOps-долг. Для RAG-harness это угроза воспроизводимости: тест зеленый в dev не доказывает, что операторский runtime отвечает тем же кодом.

### 5.4. Документация многослойная и местами историческая

В репо много сильных документов, но они разных эпох: старые v2.0/master docs описывают раннюю инфраструктуру, LES3 docs описывают волны фич, `ROADMAP_TO_V1.md` описывает текущую релизную рамку, `SKILL.md` содержит живой операторский runtime, `CODE_MAP.md` содержит актуальную карту кода.

Риск: новый агент может прочитать старый документ и принять его за текущую правду. Канон надо явно маркировать:

1. `AGENTS.md` — правила работы.
2. `SKILL.md` — живой runtime/operator truth.
3. `docs/CODE_MAP.md` — куда смотреть в коде.
4. `ROADMAP_TO_V1.md` — что считается v1.
5. `docs/unified_harness_failure_ledger.md` — что реально доказано/не доказано.

Остальное нужно помечать как historical/reference или привязать к версии.

### 5.5. "Фича готова" часто значит "backend готов", а не "оператор принял"

В сессиях много формулировок "закрыто", но рядом часто стоит: нужна live-приемка глазами, браузерная приемка pending, runtime флаг не включался, GUI не проверялся, не прогонялось на чистой машине, реальный датасет требует оператора, sidecar write не делался без разрешения.

Это честно записано, но в суммарной картине может потеряться. Для v1 надо различать статусы: `implemented`, `unit-tested`, `offline-smoked`, `runtime-smoked`, `operator-accepted`.

### 5.6. Сметный/строительный harness еще не доказан как end-to-end продукт

Есть сильные куски: resource workbook validated, ГЭСН база импортирована, ВОР/ЛСР контуры есть, sidecar extraction доказан на датасетах, route smoke и failure ledger есть.

Но до v1 остаются настоящие продуктовые проверки: 3-5 реальных датасетов разных типов, end-to-end "проект -> вопрос -> источники -> расчет -> blockers -> UI evidence", сметный workflow с partial/final semantics, no final_total when blockers, явные source/citation artifacts, open source/preview из UI.

### 5.7. Что добавил внешний чат

WebArchive подтвердил и усилил несколько выводов.

Первое: "один router" не должен означать "одна LLM решает все". Правильная сущность — `ProfileResolver` / `ProfileResolution`: explicit mode, command, deterministic recognizer, keyword/classifier и LLM-router могут быть разными источниками одного решения, но наружу должен выходить единый контракт.

Второе: routing должен выбирать не атомарный инструмент, а workflow. Пользовательский запрос обычно не равен `table_agg` или `glossary`; он равен задаче: "проверить проект", "найти в актах", "собрать ЛСР", "объяснить норму", "подготовить документы к поиску". Инструменты — внутренние шаги workflow.

Третье: "числа считает код" недостаточно. Если объектная модель, состав работ или геометрия взяты из шаблона/допущения, итог не становится инженерно строгим только потому, что арифметика строгая. Нужны классы чисел: `EXTRACTED_VALUE`, `COMPUTED_VALUE`, `ASSUMED_VALUE`, `ESTIMATED_VALUE`, `USER_PROVIDED_VALUE`, `UNSUPPORTED_VALUE`; каждое значимое число должно иметь basis, formula/inputs, assumptions и confidence.

Четвертое: LLM+RAG-декомпозиция сметы должна быть schema-first. Модель не "делает смету"; она предлагает кандидата объектной модели/ВОР в строгой схеме, а код валидирует полноту, единицы, применимость норм, недостающие слоты и blockers.

Пятое: UI-долг по источникам — не косметика, а доверие. Если source chip выглядит кликабельным, он обязан открываться. Иначе это фейковая интерактивность: evidence выглядит как доказательство, но не дает проверить источник.

## 6. Что хорошо

- Сильная инженерная честность в доках: проблемы названы прямо, включая plist drift, route hijack, no_lexical_index, mail backend, Qdrant/vector unavailable, UI lag.
- Принцип "LLM последний" выдержан в большинстве ALGO-доков.
- Failure ledger отличный: он превращает vague "не работает" в typed limitation или bug.
- Safety guardrails сильные: no secrets, no destructive data ops, sidecar write только с gate, mail read-only, P0 local-only.
- Доменный гейт FIRE/HVAC 16/16 дает хотя бы один стабильный quality anchor.
- Roadmap to v1 наконец сужает цель: не "строительный ИИ вообще", а локальный evidence assistant.

## 7. Что требует немедленного порядка

### P0 перед продолжением фич

1. Version/runtime alignment visible everywhere: `/api/version`, UI badge, response `version_info`, deploy stamp.
2. Route Safety Freeze: классифицировать handlers как `FINAL_ALLOWED`, `TOOL_ONLY`, `HINT_ONLY`, `DEPRECATED`.
3. Clickable Sources + Citation Drawer: все source chips и "Открыть" либо работают, либо явно disabled с warning; source без `source_ref` не выглядит как кнопка.
4. Реальная приемка v0.23: 3-5 датасетов, failure ledger per dataset.
5. Развести статусы готовности: implemented/tested/runtime/operator accepted.

### P1 после P0

1. Retrieval/citation quality: dedup, used/found/rejected, body-hit vs filename-only, weak/strong markers.
2. Estimate workflow hardening: unknown family -> blocked, unit conversion pack, no final_total with blockers.
3. Dataset registry/Qdrant health checks as release smoke.
4. Browser acceptance suite for Совушка.
5. Документационный канон и архивирование исторических планов.

## 8. Целевая архитектура v1

Минимальная правильная схема:

```text
User question + selected scope
  -> ProfileResolution
       route_source, workflow_id, tools, model policy, missing slots, reasons
  -> Source operations
       registry, sidecar state, lexical/vector/mail/table availability
  -> Tool execution
       retrieval tools, deterministic calculators, extractors, validators
  -> Evidence contract
       RETRIEVED / COMPUTED / ASSUMED / MISSING / BLOCKED / CONFLICT
  -> Numeric provenance
       EXTRACTED / COMPUTED / ASSUMED / ESTIMATED / USER_GIVEN / UNSUPPORTED
  -> Answer synthesis
       model may phrase and connect, but not invent numbers/facts
  -> UI evidence
       citations, source drawer, copy/open/export, trace summary
```

Главный принцип: RAG не должен быть одним из поздних fallback после эвристик. Для предметного вопроса RAG/evidence path должен быть базовым маршрутом, а детерминированные инструменты должны добавлять доказанные вычисления и blockers.

## 9. Итоговый вердикт

ЛЕС технически гораздо ближе к правильной системе, чем к игрушечному RAG. Главное достижение — не модель и не UI, а сформулированный контракт: факты из источников, числа из кода, модель связывает, `MISSING/BLOCKED` не прячутся.

Главный риск — продолжить добавлять ветки сложности до того, как будет заморожена маршрутизация и предъявление evidence. Тогда система будет уметь много, но оператор не сможет понять, почему она ответила именно так и какая версия вообще работала.

Практический курс:

1. Остановить расширение фич после текущего v0.22/v0.23 контура.
2. Дожать `ROADMAP_TO_V1.md` как операционный план.
3. Сделать visible version/runtime alignment.
4. Закрыть route safety.
5. Сделать кликабельные источники и citation drawer как отдельный P0.
6. Прогнать реальные строительные датасеты через failure ledger.
7. Только потом возвращаться к OCR, Gate 5, полному ФГИС/price DB, BIM graph и multi-user.

Если коротко: нужен не "еще один RAG", а строительный harness с доказательствами. В документах этот вектор уже есть. Теперь его надо зацементировать кодом, UI и приемкой.

## 10. Repo / GitHub / runtime audit

Дата первичной проверки: 2026-06-25. Повторная проверка после фикса deploy stamp: 2026-06-25. Актуализация после повторного аудита: 2026-06-26.

Проверенные факты:

- Dev-репо: `/Users/ovc/Projects/LES_v2`.
- Runtime-клон: `/Users/ovc/LES`.
- GitHub remote dev-репо: `git@github.com:proovcme/les_rag.git`.
- Текущая ветка dev-репо: `feat/les3-p1`.
- `git fetch --prune origin` прошел успешно.
- Dev HEAD: `98278ea`.
- `origin/feat/les3-p1`: `98278ea`.
- `origin/main`: `98278ea`.
- Dev branch vs upstream: `ahead=0`, `behind=0`.
- `origin/main...origin/feat/les3-p1`: `0 0`. Значит `main` и `feat/les3-p1` сейчас указывают на один commit.

Runtime:

- Git HEAD runtime-клона `/Users/ovc/LES`: `1e98be6`.
- Runtime remote: `/Users/ovc/Projects/LES_v2_reinstall_stress`, не GitHub.
- Runtime git dirty: 128 entries по `git status --porcelain`; это ожидаемо для divergent runtime-клона и не должно использоваться как источник правды о деплое.
- `/api/version` отвечает:
- `app_version=5.1.0`;
- `harness_version=0.23`;
- `git_commit=1e98be6`;
- `deployed_commit=00ddee2`;
- `deploy_stamp.status=ok`;
- `runtime_alignment.status=aligned`;
- `runtime_alignment.checked=12`.

Ключевая поправка к первичной проверке:

- Ранее live `/api/version` показывал `deployed_commit = ba2e8d3`, что отставало от dev/GitHub HEAD.
- На актуализации 2026-06-26 live `/api/version` показывает `deployed_commit = 00ddee2`, а dev/GitHub HEAD уже `98278ea`.
- `runtime_alignment=aligned` означает совпадение по 12 файлам deploy-stamp bundle, а не полное совпадение всего runtime-клона с dev HEAD.

Health:

- `GET /api/health` отвечает, но `status=degraded`.
- RAG totals на момент повторной проверки: 30 датасетов, 3133 файлов, 1651 indexed, 1482 pending, 0 error, 187642 chunks.
- Это не блокирует git/runtime-audit, но важно для операционного отчета: live runtime не полностью "green", он "degraded" из-за pending index state.

Audit-файл:

- `docs/DOCS_SESSIONS_AUDIT_REPORT_2026-06-25.md` уже отслеживается git и попал в историю через `b0c2d65`.
- После текущей актуализации файл снова изменен в рабочем дереве до нового commit.

Вывод:

- GitHub-ветка `feat/les3-p1` синхронна с dev-репо.
- `main` синхронен с `feat/les3-p1`.
- Runtime нельзя оценивать по git-клону; надо смотреть deploy stamp.
- Runtime реально задеплоен на `00ddee2`, а текущие `main` и `feat/les3-p1` уже на `98278ea`.
- По stamp-проверяемым файлам runtime aligned, но это ограниченная проверка; commit stamp сейчас не равен GitHub HEAD.
