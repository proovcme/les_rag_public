# RELEASE_LEDGER — где мы сейчас (единый источник состояния)

> **Единственный источник правды о версии/деплое.** Не «хер знает где мы»: здесь — что за версия, какой
> commit в dev, какой задеплоен на рантайм, что вошло. Сверяй с `GET /api/version` и `git log`.
> Модель — locia `SERVER_BUILD_LEDGER`. Канон-бэклог — [../ROADMAP_TO_V1.md](../ROADMAP_TO_V1.md).

## Текущее состояние (2026-06-28)

```
версия (схема 0.N.FEATURE.PATCH): 0.24.0.20  (в КОДЕ: LES_VERSION; в /api/version поле les_version)
ветка:                     feat/les3-p1
dev HEAD:                  HEAD  (см. git log -1)
задеплоено на рантайм:     0.24.0.20 smeta model-first route + object-composition removal
НЕ задеплоено:             —
рантайм /api/version:      0.24.0.20 · app 5.1.0 · h0.24 · runtime_alignment=aligned · checked=31
```

> 0.24.0.6 выкачен через `make ship`. Живой чат-прогон без semantic cache:
> FIRE `52.8s` (`generation=44.313s`, `source_map=5`, unknown citations `0`);
> HVAC `37.0s` (`generation=30.148s`, `source_map=4`, unknown citations `0`).
> 0.24.0.7 возвращает таблицы как нормальный формат строительной выдачи. Живой FIRE-прогон:
> `has_table=true`, `50.6s` (`generation=42.264s`), `source_map=5`, unknown citations `0`.
> 0.24.0.8 выкачен через `make ship`: операторский слой чата прячет внутренние KOT/CTX/CACHE
> за раскрывашку, добавляет видимый «Паспорт области» и принудительно обновляет пузырь на каждом
> SSE-токене.
> 0.24.0.9 — hotfix кнопки «Паспорт области»: диалог заранее создаётся в UI-slot NiceGUI, а клик
> только заполняет его после async-загрузки профилей.
> 0.24.0.10 добавляет видимый ход работы для tool/детерминированных веток (`progress` SSE)
> и явный `answer_contract`/`scenario` в payload ответа.
> 0.24.0.11 добавляет мягкую машинную проверку `answer_contract_check`: pass/warn,
> missing-поля и признаки таблиц/evidence без блокировки ответа.
> 0.24.0.12 чинит наблюдённые системные провалы smeta-чата: состояние параметров по истории
> текущей сессии, разговорные площадь/этажность, предупреждения по неподдержанным вариантам и
> фильтр кандидатов ГЭСН по реальному сборнику даже при префиксе `ГЭСН:`.
> 0.24.0.13 добавляет память tool-следов для smeta-продолжений: повторная реплика может
> использовать массу/ярусы из предыдущего `retrieval_trace`; mass-fallback показывает кандидатов
> ГЭСН, но не выдаёт их за ЛСР, и убирает внутренние refs ставок/yaml из видимого ответа.
> PDF-нормы ГЭСН/ФЕР/ТЕР классифицируются как нормативные строительные документы, а не `TABLE_SMETA`.
> 0.24.0.14 добавляет bounded analog fallback для объектной сметы: если точного шаблона нет,
> ЛЕС ищет ближайший локальный аналог в `object_templates.yaml`, помечает результат
> `rough_analog_object_assumed` и удерживает диалоговый сценарий каркасной дачи без скрытых подсказок.
> 0.24.0.15 чистит видимый ответ объектной сметы: вместо абзацев с внутренними терминами —
> короткие списки «Коротко / Что не покрыто точно / Итог / Ключевые допущения».
> 0.24.0.16 добавляет `composition_candidates`: спорные части объектной сметы ищут реальные
> ГЭСН-кандидаты в локальной базе, но эти нормы не включаются в сумму без ВОР/подтверждения.
> 0.24.0.17 делает паспорта датасетов измеримыми: quality-сигнал и no-reindex benchmark
> cold rebuild против warm cached read по каждому датасету.
> 0.24.0.18 добавляет общий `workflow_plan_v1`: smeta/normcontrol/RAG/table payload получают
> единый план workflow, required/missing inputs, evidence policy, claim/source summary, blockers/actions.
> 0.24.0.19 выводит `workflow_plan_v1` в операторский слой Совушки: статус/финальность видны в чипах,
> а workflow id, missing inputs и next actions доступны в технических деталях ответа.
> 0.24.0.20 переключает режим «Смета» на model-first tool-loop: модель сама раскладывает объект,
> харнесс только даёт инструменты и gates; старый объектный слой, его YAML-данные и mass-rate fallback
> удалены, а auto-router больше не имеет отдельного объектного инструмента.

> Деплоятся только code-правки (`proxy/`,`backend/`,`sovushka/`,`config/`). Доки на рантайм не катятся —
> поэтому dev HEAD ≠ deployed_commit это нормально, пока расходятся только доки.

## Три оси версий (почему путаница) — и целевая одна

Сейчас в коде/доках живут ТРИ несвязанные оси (отсюда «где мы»):

| Ось | Где | Значение | Назначение |
|---|---|---|---|
| **APP_VERSION** | `version_service.py:19` | `5.1.0` | пользовательская «маркетинговая» версия ЛЕС |
| **HARNESS_VERSION** | `version_service.py:20` | `0.23` | внутренний строительный контур (веха roadmap) |
| **package** | `pyproject.toml` | `0.1.1.dev0` | версия python-пакета (SemVer сборки) |

Старые доки добавляют 4-ю («v2.0/v4.0» в README_v2.0/MASTER_DOC/INFRASTRUCTURE) — историческое, в архив.

**Целевая схема (по запросу оператора): `0.MILESTONE.FEATURE.PATCH`**

| часть | смысл | пример |
|---|---|---|
| `0` | до релиза v1.0 | — |
| `MILESTONE` | веха roadmap (растёт к v0.24…v1.0) | `0.23` |
| `FEATURE` | фиче-инкремент внутри вехи (двигать КАЖДУЮ фичу) | `0.23.5` |
| `PATCH` | фикс/патч | `0.23.5.1` |

**Статус:** схема зафиксирована здесь и внедрена в код (`version_service` → 4-частная версия в
`/api/version` + deployed-версия рядом).
Дисциплина после: бамп версии + строка в этот леджер + строка в `releases.md` на каждую фичу; деплой —
через `make ship` (быстрый gate: verify→focused tests→smoke→deploy→retry-smoke) или `make ship-full`
(полная сюита на границе версии), откат — `git checkout <prev>` + redeploy
(код) / `tools/restore_runtime.sh` (данные). См. [GUARDRAILS.md](GUARDRAILS.md) (в очереди).

## Леджер (новое → старое)

| Версия | commit | дата | что | деплой |
|---|---|---|---|---|
| 0.24.0.21 | HEAD | 2026-06-28 | Smeta harness latency: режим «Смета» больше не гоняет многоходовую LLM-петлю по умолчанию; модель одним компактным JSON отдаёт схему объекта и works, после чего код пакетно выполняет `search_norm`/`add_position` по ГЭСН, показывает коды-кандидаты при неоднозначности и не добавляет их в сумму без уверенной применимости; LLM-вызов планировщика ограничен timeout | ✅ рантайм, full test + ship/smoke + live dacha 18s ✅ |
| 0.24.0.20 | HEAD | 2026-06-28 | Smeta model-first route: режим «Смета» идёт через `estimate_harness` (модель сама раскладывает объект; харнесс даёт `search_norm`/`add_position` и gates); старый объектный слой, его YAML-данные, mass-rate fallback и auto-router target удалены; служебные источники больше не требуют готовых объектных составов | ✅ рантайм, full test + ship/smoke; runtime old files removed ✅ |
| 0.24.0.19 | HEAD | 2026-06-28 | Workflow plan UI: Совушка сохраняет `workflow_plan_v1` в metadata сообщения, показывает статус/финальность workflow оператору и оставляет `workflow_id`, missing inputs, next actions в технических деталях без вывода router/debug полей в первый слой | ✅ рантайм, focused/verify + ship/smoke + live workflow UI ✅ |
| 0.24.0.18 | HEAD | 2026-06-27 | Workflow plan contract: ответы чата и JSON нормоконтроля получают общий `workflow_plan_v1` (workflow id, required/missing inputs, evidence policy, claim/source summary, blockers, next actions), чтобы smeta/normcontrol/checklist развивались через один информационный контракт | ✅ рантайм, focused/verify + ship/smoke + live workflow plan ✅ |
| 0.24.0.17 | HEAD | 2026-06-27 | Dataset passport benchmark: deep-паспорта датасетов получили `quality` (`good/partial/weak/empty`, score/warnings/signals), warmup теперь отдаёт per-dataset timing/cache-status, а новый `POST /api/rag/datasets/profiles/benchmark` сравнивает cold rebuild и warm cached read без reindex/OCR/LLM | ✅ рантайм, focused/verify + ship/smoke + live warmup/benchmark ✅ |
| 0.24.0.16 | HEAD | 2026-06-27 | Smeta composition candidates: объектная прикидка теперь показывает ГЭСН-кандидаты для непокрытого scope (`каркасные стены`, `сваи/ростверк`, `плоская кровля`, `крыльцо/терраса`) через `estimate_harness.search_norm`; кандидаты идут в answer/source/trace, но не добавляются в сумму автоматически | ✅ рантайм, focused/verify + ship/smoke + live dacha candidates ✅ |
| 0.24.0.15 | HEAD | 2026-06-27 | Smeta answer readability: объектная прикидка теперь отдаёт операторский список вместо плотного абзаца, прячет слово “шаблон” из видимого текста в пользу “типовой состав/локальный аналог”, warnings выводит отдельными bullet-строками, а итог — отдельным списком | ✅ рантайм, focused/verify + ship/smoke + preview ✅ |
| 0.24.0.14 | HEAD | 2026-06-27 | Smeta object analog fallback: объектная смета больше не падает в “нет шаблона” для близкого локального аналога; каркасная дача 150 м² на сваях считается по ближайшему ИЖС-аналогу `wooden_house` со статусом `rough_analog_object_assumed`, trace/provenance/source помечают аналог, а цепочка “два этажа → крыльцо → фундамент → плоская кровля” сохраняет контекст и выводит warnings по непокрытому scope | ✅ рантайм, full test + ship/smoke + live dacha dialogue ✅ |
| 0.24.0.13 | HEAD | 2026-06-27 | Smeta tool-trace memory: явный режим `smeta` читает прошлые `retrieval_trace` для продолжений tool-расчётов; fallback по массе для стальных/бронзовых конструкций не показывает `custom_mass_rates`/yaml как источники, добавляет кандидаты ГЭСН из сб.09 для ручной привязки, распознаёт высотные работы и применяет только явный коэффициент; `ГЭСН/ФЕР/ТЕР` PDF-нормы классифицируются как `NORMATIVE/NTD_CONSTRUCTION`, не `TABLE_SMETA` | ✅ рантайм, full test + ship/smoke + live smeta follow-up ✅ |
| 0.24.0.12 | HEAD | 2026-06-27 | Smeta context hardening: явный режим `smeta` собирает параметры объектной сметы из прошлых вопросов текущей сессии без склейки строк; `free`/read-attachment LLM-пути получают `session_memory`; парсер понимает «метров 150» и «в два этажа»; шаблонная смета предупреждает про сваи/крыльцо/плоскую кровлю вне состава; `estimate_harness` извлекает сборник из `ГЭСН:10-...` и rejects wrong collection для work_family | ✅ рантайм, full test + ship/smoke + live smeta context ✅ |
| 0.24.0.11 | HEAD | 2026-06-27 | Answer contract checks: финальные payload чата получают `answer_contract_check` с pass/warn, missing-полями и observed-сигналами таблиц/evidence; Совушка показывает операторское предупреждение «Контракт: замечания» и прячет детали в technical chips | ✅ рантайм, full test + ship/smoke + live SSE ✅ |
| 0.24.0.10 | HEAD | 2026-06-27 | Chat workflow contracts: `/api/chat/stream` шлёт операторские `progress`-события до final, tool/детерминированные ветки больше не выглядят как зависший чат; каждый final payload получает `scenario` и `answer_contract`, а `ProfileResolver.as_trace()` отдаёт `output_contract`; Совушка показывает сценарий и табличный контракт в чипах, технические id — в раскрывашке | ✅ рантайм, full test + ship/smoke + browser smoke ✅ |
| 0.24.0.9 | HEAD | 2026-06-27 | Passport dialog hotfix: «Паспорт области» больше не создаёт `ui.dialog()` из фоновой задачи; диалог предмонтирован в правильном NiceGUI slot и заполняется после async-загрузки памяти чата/deep-паспортов датасетов | ✅ рантайм, full test + ship/smoke + browser click ✅ |
| 0.24.0.8 | HEAD | 2026-06-27 | Operator UX/passports/streaming: первый слой чата показывает человеческие статусы (`Проверено`, `Без проверки`, маршрут, секунды), внутренние KOT/CTX/CACHE переехали в «Технические детали»; добавлена кнопка «Паспорт области» с памятью чата и deep-паспортами выбранных датасетов; SSE-токены принудительно обновляют пузырь ответа и скролл | ✅ рантайм, full test + ship/smoke ✅ |
| 0.24.0.7 | HEAD | 2026-06-27 | Chat table-format correction: локальный technical/legal RAG снова предпочитает компактную markdown-таблицу, если найдено несколько требований/условий; короткий профиль теперь режет простыни/постскриптумы, а не таблицы | ✅ рантайм, full test + ship/smoke + live table check ✅ |
| 0.24.0.6 | HEAD | 2026-06-27 | Chat stability/source trace: локальный MLX получает меньший default context budget и короткий формат для technical/legal RAG; `/api/chat` отдаёт `source_map`, совпадающий с номерами prompt-блоков `Источник N`; `latency_phases` возвращает retrieval/context/generation/validation/overhead/total; `saferag_service.py` добавлен в critical runtime alignment | ✅ рантайм, full test + ship/smoke + live chat latency/source-map ✅ |
| 0.24.0.5 | HEAD | 2026-06-27 | External Radar: Самовар получил no-reindex обзор внешних корней, `file_map.db`-кандидатов и уже indexed in-place `documents.source_path`; новый API `GET /api/external-radar/summary`; радар делает только shallow-статистику и не читает содержимое файлов | ✅ рантайм, full test + ship/smoke + live radar ✅ |
| 0.24.0.4 | HEAD | 2026-06-27 | Deep context memory: паспорта датасетов получили `depth=deep` поверх bounded read из `lexical_chunks` (top-documents/headings/content-keywords/norm_refs/table-signal/fragments) без reindex/OCR/LLM; prompt-блок ограничивает число датасетов; добавлен no-reindex прогрев `POST /api/rag/datasets/profiles/warmup`; профиль честно пишет `available=false`, если lexical index не готов | ✅ рантайм, full test + ship/smoke + live warmup ✅ |
| 0.24.0.3 | HEAD | 2026-06-27 | Context memory: добавлен `context_memory_service` с паспортом чата (`les_chat_profiles`) и паспортом датасета (`les_dataset_profiles` + `storage/datasets/{dataset_id}/_les_dataset_profile.json`); RAG-промпт получает компактный фон по текущей сессии/датасетам после resolve scope, явно помеченный как НЕ evidence; `save_chat_history` обновляет профиль сессии; добавлены API просмотра `GET /api/chat/memory/{session_id}`, `GET /api/rag/datasets/{id}/profile` и admin refresh | ✅ рантайм, full test + ship/smoke ✅ |
| 0.24.0.2 | HEAD | 2026-06-27 | Operator-facing source/normcontrol polish: вкладка «Инструменты» оставлена только под служебные источники данных с папками, кнопкой открытия и безопасной play-проверкой; `/api/service-sources/{id}/process` отдаёт понятный статус без скрытых импортов; явные режимы больше не теряют read-вложение: «Смета»/smeta_harness передают текст в инструмент, «Проверка проекта» честно просит датасет/PDF для layout-нормоконтроля; сметный чат получил weight-based fallback для тяжёлых стальных/бронзовых ярусов по массе с ASSUME-ставками; chat-report нормоконтроля очищен от служебных enum/англицизмов; drawer источников больше не показывает техническое предупреждение для логических refs типа ГЭСН/ГОСТ | ✅ рантайм, fast ship/smoke ✅ |
| 0.24.0.1 | HEAD | 2026-06-27 | Operator-facing normcontrol stabilization: `doc_review` получил persist-sidecar решений инженера (`confirmed/rejected/needs_more_evidence`) через API, JSON/XLSX/HTML и GUI-кнопки; вкладка «Инструменты» возвращена в админку; `sovushka_ng.py` добавлен в deploy/critical bundle, чтобы shell-правки реально выкатывались; чат получил явную панель служебных источников (ГЭСН/ФГИС/СПДС/layout); chat-report нормоконтроля больше не рендерится как огромные markdown-таблицы/авто-артефакт | ✅ рантайм, fast ship/smoke ✅ |
| 0.24.0.0 | HEAD | 2026-06-27 | SPDS/public-ready baseline: ГОСТ Р 21.101-2026 doc-review теперь отдаёт общий `normalized_remarks` contract поверх `items`/`defense` для checklist/DOCX/PDF renderers; XLSX включает лист `normalized_remarks`; Admin GUI скачивает XLSX/JSON/HTML; `/api/version.runtime_alignment` расширен на doc-review/service-sources entrypoints; добавлены source-available `LICENSE`, `SECURITY.md`, public publication checklist and `make public-check` guardrail | ✅ рантайм, full ship/smoke ✅ |
| 0.23.6.12 | uncommitted | 2026-06-27 | Service source registry + layout v1: added `config/service_sources.yaml`, `service_source_registry` and `/api/service-sources` so Admin/GUI shows required data for smeta and normcontrol (ГЭСН, ФГИС ЦС, coefficients/templates, СПДС rulepack, normative RAG, layout reference); Instruments page now surfaces those sources and missing/degraded status; title-block check now verifies that text-layer stamp signatures are in the expected bottom-right zone, and reports signatures outside the zone as a computed issue | ✅ рантайм, fast ship/smoke ✅ |
| 0.23.6.11 | uncommitted | 2026-06-27 | Normcontrol human defense report: chat doc-review now renders a defendable human report with verdict, evidence/action tables and “Защита решения”; working memory is no longer appended to doc-review answers; `defense` is exposed at top-level chat payload; D4-001 sheet format is computed from PDF page geometry via ГОСТ 2.301, while deeper element placement/fill remains explicit layout/title-block work | ✅ рантайм, fast ship/smoke ✅ |
| 0.23.6.10 | uncommitted | 2026-06-27 | Attachment UX + release cadence: after upload the chat now shows a visible system message and composer strip saying the file/table will go with the next request; `make ship` is the fast iteration gate (verify + focused tests + smoke + deploy + retry post-smoke), `make ship-full` keeps the full pytest release gate | ✅ рантайм, fast ship/smoke ✅ |
| 0.23.6.9 | uncommitted | 2026-06-27 | System defense-contract v1: `DefensePack/DefenseClaim` added to `evidence_contract`; object-estimate now exposes per-GESН formula values, physical quantities, direct/НР/СП build-up, resource price coverage/missing-price examples, explicit non-defensible-LSR status, and ASSUME sections as non-normative; doc-review/normcontrol JSON now emits the same `defense` contract; object-estimate chat payload includes `defense` for UI/export | ✅ рантайм, full pytest/smoke ✅ |
| 0.23.6.8 | uncommitted | 2026-06-27 | Chat attachment contract: default file attach is "to chat", composer/user bubble show the attached file, read attachments send filename-bearing `attachment_context` to the model; plain file-reading tasks use attachment-only LLM route without global RAG noise; direct/router LLM calls use local MLX when cloud is not keyed | ✅ рантайм, make ship/smoke/live attach ✅ |
| 0.23.6.7 | uncommitted | 2026-06-27 | Latency hotfix: `LES_ROUTER_PRIMARY` default is now explicit opt-in (`false` unless set) so deterministic chat paths do not wait the 12s LLM-router timeout before cascade fallback; added regression for router-primary default | ✅ рантайм, verify/test/smoke ✅ |
| 0.23.6.6 | uncommitted | 2026-06-27 | v0.23B partial: source chips with real `source_ref` open a citation drawer in the Artifacts panel; weak/vector and missing-ref sources do not fake file opening and expose a clear unavailable reason; citation drawer keeps snippets only and copy actions for `source_ref`/citation | ✅ рантайм via 0.23.6.7 |
| 0.23.6.5 | uncommitted | 2026-06-27 | Stability contract pass: read-attachment converter failures return controlled 422 instead of leaking a backend exception; the hidden-by-default artifact panel now has an explicit GUI open control; Guardrails documents the per-feature stability contract and current green test baseline | КОД, verify/test ✅, ждёт deploy |
| 0.23.6.4 | uncommitted | 2026-06-27 | UI defaults: chat/admin start in light theme, artifacts panel is collapsed by default and opens only on explicit artifact/file/verify actions; OpenAI-compatible cloud defaults to `gpt-4.1` instead of blank/local model names; object-estimate carries calculation footer, sources, trace and evidence summary through `/api/chat` | КОД, verify/test/smoke ✅, ждёт deploy |
| 0.23.6.3 | uncommitted | 2026-06-27 | UI/smeta stabilization: chat attachments get `read` mode (file text as request context), quick/index attachments are sent as `dataset_ids`; composer gets direct scope/folder buttons and removable attachment chip; object-estimate now produces a rough full-object budget from vague ToR (ГЭСН-конструктив + explicit `ASSUME` allowances + `price_level_k` + VAT) while detailed estimates remain file/dataset-driven | КОД, verify/test/smoke ✅, ждёт deploy |
| 0.23.6.2 | uncommitted | 2026-06-27 | v0.23A stabilization: default trusted loopback/proxy networks narrowed to `127.0.0.1/32`; KOT term matching uses word-boundary regex with explicit `противопожар`; Samovar verifies Qdrant point count for every indexed file by default; backup archives get `SHA256SUMS.txt`, restore refuses checksum mismatch | КОД, verify/test/smoke ✅, ждёт deploy |
| 0.23.6.1 | uncommitted | 2026-06-27 | router-primary fallback: `RouterUnavailable` ≠ `none`; при недоступном роутере включается deterministic cascade + legacy in-flow gates (`mail`/`reconcile`/`table_agg`/`clause`/scope clarification) с честным `route_source`; `maybe_agent_route` снова зависит только от `LES_AGENT_LOOP` | КОД, tests ✅, ждёт deploy |
| 0.23.6 | `3362cee`+ | 2026-06-27 | версия 0.23.N.P в /api/version (`LES_VERSION`) + 5 fail-фиксов (4 версионных стейл-теста, help topic_slices) + сметный скилл (`skills/smeta/SKILL.md`) + `make ship`-гейт | КОД, ждёт deploy |
| 0.23.5 | `1cb1bd4` | 2026-06-27 | docs-аудит (4 прохода, сверка с кодом) + `MODULE_INDEX.md` + `RELEASE_LEDGER.md` + 3 новых ALGO/GUARDRAILS + архив мёртвого | — (docs) |
| 0.23.4 | `8f777a8`/`f414c90` | 2026-06-27 | чистка доков: 18 исторических → `docs/archive/` + указатели | — (docs) |
| 0.23.3 | `75ed9da` | 2026-06-27 | нормоконтроль: doc-review retrieval-подфаза (факты корпуса + текст требования) | ✅ рантайм |
| 0.23.2 | `a21f7dc` | 2026-06-27 | нормоконтроль: title_block OCR для сканов (флаг `LES_TITLE_BLOCK_OCR`) | ✅ рантайм |
| 0.23.1 | `57e4337` | 2026-06-27 | смета: многопозиционная ЛСР форма Приложения 4 (разделы+свод) | ✅ рантайм |
| 0.23.0 | `530f07b` | 2026-06-27 | смета: рендер ЛСР в форму Приложения 4 (одна позиция) | ✅ рантайм |
| ≤0.23 | см. [releases.md](releases.md) | до 06-27 | вехи v0.19–v0.23 (version stamp, evidence UI, route safety, source ops, trust hardening) | — |

> Полная история вех v0.13–v0.23 — в [releases.md](releases.md). Этот леджер ведём с гранулярностью фич
> (`0.23.N`), releases.md — по вехам (`v0.NN`).

## Здоровье на 2026-06-27 (из прогона)

```
make verify:     ✅ зелёный (2062 собрано)
make test:       ✅ 2062 passed / 6 warnings / 317.64s
make smoke-basic: ✅ pass=9 / warn=0 / fail=0 (chat_glossary 75.6с; chat_project_noscope 106.3с)
make verify 0.23.6.7: ✅ зелёный (2063 собрано)
make test 0.23.6.7:   ✅ 2063 passed / 6 warnings / 223.75s
post-deploy smoke:    ✅ pass=9 / warn=0 / fail=0 (chat_glossary 5ms; chat_project_noscope 8ms)
make ship 0.23.6.8:   ✅ verify 2067 collected; test 2067 passed / 6 warnings / 220.73s; smoke pass=9
post-deploy 0.23.6.8: ✅ pass=9 / warn=0 / fail=0 (chat_glossary 49ms; chat_project_noscope 10ms)
live attach-check:    ✅ crag_status=ATTACHMENT; route=attachment_context/read_attachment; sources=[attachment:demo.txt]
make ship-full 0.23.6.9: ✅ verify 2068 collected; test 2068 passed / 6 warnings / 221.83s; smoke pass=9
post-deploy 0.23.6.9:   ✅ pass=9 / warn=0 / fail=0 (manual retry after restart; motivated retry-smoke)
make ship 0.23.6.10:    ✅ verify 2069 collected; focused 35 passed; pre-smoke pass=9; post-smoke pass=9 after retry
make ship 0.23.6.11:    ✅ verify 2071 collected; focused 40 passed; pre-smoke pass=9; post-smoke pass=9
live doc-review BAI:    ✅ crag_status=VERIFIED; cache=doc_review; items=15; top-level defense present; no LES.md/memory leak
make ship 0.23.6.12:    ✅ verify 2076 collected; focused 56 passed; pre-smoke pass=9; post-smoke pass=9
live service-sources:     ✅ /api/service-sources total=6; ok=5; missing_blocking=0; smoke pass=9 after runtime app registration
make ship-full 0.24.0.0: ✅ verify 2078 collected; test 2078 passed / 6 warnings / 223.10s; pre-smoke pass=9; post-smoke pass=9
live doc-review 0.24:   ✅ ГОСТ Р 21.101-2026; items=15; normalized_remarks=15; defense=true
public-check 0.24:      ✅ git-visible files: no forbidden runtime paths or high-signal secrets
focused 0.24.0.3:       ✅ 33 passed (context-memory + chat/version)
make verify 0.24.0.3:   ✅ 2088 collected
make test 0.24.0.3:     ✅ 2088 passed / 6 warnings / 220.92s
make ship 0.24.0.3:     ✅ verify 2088 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9
live context-memory:    ✅ /api/version 0.24.0.3 aligned checked=24; dataset profile endpoint wrote `_les_dataset_profile.json`
focused 0.24.0.4:       ✅ 60 passed (context-memory + datasets router + version)
make verify 0.24.0.4:   ✅ 2090 collected
make test 0.24.0.4:     ✅ 2090 passed / 6 warnings / 220.45s
make ship 0.24.0.4:     ✅ verify 2090 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9
live deep warmup:       ✅ /api/version 0.24.0.4 aligned checked=24; warmup status=ok built=3/3 depth=deep
focused 0.24.0.5:       ✅ 43 passed (external radar + external index/filemap/version)
make verify 0.24.0.5:   ✅ 2093 collected
make test 0.24.0.5:     ✅ 2093 passed / 6 warnings / 122.18s
make ship 0.24.0.5:     ✅ verify 2093 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9 after retry
live external-radar:    ✅ /api/version 0.24.0.5 aligned checked=26; summary status=ok roots=2 external_docs=1842 candidates=2
focused 0.24.0.6:       ✅ 65 passed (source-map/chat/version); после short-format tuning ✅ 32 passed
make verify 0.24.0.6:   ✅ 2096 collected
make test 0.24.0.6:     ✅ 2096 passed / 6 warnings / 126.83s
make ship 0.24.0.6:     ✅ verify 2096 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9
live chat 0.24.0.6:     ✅ FIRE 52.8s (source_map=5, unknown citations=0); HVAC 37.0s (source_map=4, unknown citations=0)
focused 0.24.0.7:       ✅ 32 passed (source-map/chat/version)
make test 0.24.0.7:     ✅ 2096 passed / 6 warnings / 121.69s
make ship 0.24.0.7:     ✅ verify 2096 collected; focused 61 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live table 0.24.0.7:    ✅ FIRE has_table=true; 50.6s; source_map=5; unknown citations=0
focused 0.24.0.10:      ✅ 58 passed (answer contracts + SSE progress + UI helpers + profile resolver + version)
make verify 0.24.0.10:  ✅ 2102 collected
make test 0.24.0.10:    ✅ 2102 passed / 6 warnings / 127.99s
make ship 0.24.0.10:    ✅ verify 2102 collected; focused 63 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.10:         ✅ /api/chat/stream emits progress→final with scenario=tool and answer_contract=tool_result_v1; /classic 200
focused 0.24.0.11:      ✅ 45 passed (answer_contract_check + SSE + UI chips + version)
make verify 0.24.0.11:  ✅ 2104 collected
make test 0.24.0.11:    ✅ 2104 passed / 6 warnings / 126.62s
make ship 0.24.0.11:    ✅ verify 2104 collected; focused 63 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.11:         ✅ /api/chat/stream final has answer_contract_check=pass for glossary tool route; /classic 200
focused 0.24.0.12:      ✅ 86 passed (memory + smeta/object + harness + attachment prompt)
make verify 0.24.0.12:  ✅ 2113 collected
make test 0.24.0.12:    ✅ 2113 passed / 6 warnings / 133.58s
make ship 0.24.0.12:    ✅ verify 2113 collected; focused 69 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.12:         ✅ /api/version 0.24.0.12 aligned checked=30; smeta follow-up `А давай два этажа` keeps 150 м² and returns `2 эт.`; frame-house request now recognizes area/floors/material and refuses no-template instead of losing params
focused 0.24.0.13:      ✅ 92 passed (document router + smeta/memory/harness)
make verify 0.24.0.13:  ✅ 2117 collected
make test 0.24.0.13:    ✅ 2117 passed / 6 warnings / 136.34s
make ship 0.24.0.13:    ✅ verify 2117 collected; focused 71 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.13:         ✅ /api/version 0.24.0.13 aligned checked=30; `учти высотные работы` reuses prior mass and blocks coefficient; `k=1,15` recalculates to 139 532 515.00 ₽; GESN PDF route=NORMATIVE/NTD_CONSTRUCTION
dataset 0.24.0.13:      ✅ external `GESN_NORMS_2022_PDF` = b774e116-8172-4b53-84da-9c923c13693d, 118 PDF as NORMATIVE/NTD_CONSTRUCTION, metadata profile built; parse left PENDING due memory guard
focused 0.24.0.14:      ✅ 30 passed (object_estimate + smeta_chat), ship-focused ✅ 74 passed
make verify 0.24.0.14:  ✅ 2120 collected
make test 0.24.0.14:    ✅ 2120 passed / 6 warnings / 133.34s
make ship 0.24.0.14:    ✅ verify 2120 collected; focused 74 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.14:         ✅ /api/version 0.24.0.14 aligned checked=30; smeta session `дача каркас 150 м² 1 эт.` → `два этажа` → `крыльцо` → `фундамент` → `плоская кровля` keeps 150 м²/2 эт., status `rough_analog_object_assumed`, total 48 283 098.41 ₽, warnings for piles/porch/flat roof
focused 0.24.0.15:      ✅ 30 passed (object_estimate + smeta_chat)
make verify 0.24.0.15:  ✅ 2120 collected
make ship 0.24.0.15:    ✅ verify 2120 collected; focused 74 passed; pre-smoke pass=9; post-smoke pass=9
live 0.24.0.15:         ✅ /api/version 0.24.0.15 aligned checked=30; object-estimate answer preview uses bullet blocks: `Коротко`, `Почему выбран этот аналог`, `Что не покрыто точно`, `Итог`, `Ключевые допущения`
focused 0.24.0.16:      ✅ 62 passed (object_estimate + smeta_chat + estimate_harness)
make verify 0.24.0.16:  ✅ 2121 collected
make ship 0.24.0.16:    ✅ verify 2121 collected; focused 75 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live 0.24.0.16:         ✅ /api/version 0.24.0.16 aligned checked=30; smeta dacha answer returns `composition_candidates.status=found`, source_kind `norm_candidate`, and visible ГЭСН candidates for frame walls/piles/flat roof/porch without adding them to the total
focused 0.24.0.17:      ✅ 38 passed (context-memory + datasets router)
make verify 0.24.0.17:  ✅ 2122 collected
make ship 0.24.0.17:    ✅ verify 2122 collected; focused 75 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live 0.24.0.17:         ✅ /api/version 0.24.0.17 aligned checked=30; dataset profiles warmup 31/31 in 19.007s; benchmark 31/31 cold 9988.91ms vs warm 3462.95ms, speedup 2.88x, quality good=22 partial=9
focused 0.24.0.18:      ✅ 54 passed (answer contracts + doc-review + smeta + version)
make verify 0.24.0.18:  ✅ 2123 collected
make ship 0.24.0.18:    ✅ verify 2123 collected; focused 75 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live 0.24.0.18:         ✅ /api/chat returns `workflow_plan.schema=workflow_plan_v1`; /api/version 0.24.0.18 aligned checked=31
focused 0.24.0.19:      ✅ 19 passed (sovushka chat + answer contracts)
make verify 0.24.0.19:  ✅ 2123 collected
make ship 0.24.0.19:    ✅ verify 2123 collected; focused 75 passed; pre-smoke pass=9; post-smoke pass=9 after restart retry
live 0.24.0.19:         ✅ /api/chat returns `workflow_plan.schema=workflow_plan_v1`, `workflow_id=tool`, `status=needs_data`, `finality=not_final`; /api/version 0.24.0.19 aligned checked=31
focused 0.24.0.20:      ✅ 92 passed (profile resolver + answer contracts + smeta quick tools + estimate harness + agent router)
make verify 0.24.0.20:  ✅ 2101 collected
make test 0.24.0.20:    ✅ 2101 passed / 6 warnings / 134.60s
make ship 0.24.0.20:    ✅ verify 2101 collected; focused 99 passed; pre-smoke pass=9; post-smoke pass=8 warn=1 fail=0 after proxy restart retry
live 0.24.0.20:         ✅ /api/version 0.24.0.20 aligned checked=31; runtime `object_templates.yaml` and `object_estimate_service.py` absent; quick smeta channel returns None for house/dacha/steel-mass object requests. ⚠ `/api/chat mode=smeta` dacha live probe timed out at 180s in model tool-loop — stability/latency backlog, not fallback.
```

**Закрыто в 0.23.6.7:** latency-smoke был не LLM generation, а 12s ожидание недоступного
LLM-router перед deterministic fallback (`router_unavailable_cascade_fallback`). Router-primary теперь
явный opt-in: без `LES_ROUTER_PRIMARY=true` быстрые deterministic/RAG fallback-пути не ждут router timeout.
**Закрыто в 0.23.6.8:** read-вложение стало контрактом "файл к следующему сообщению": UI показывает
имя файла, backend получает `attachment_context`, plain file-reading идёт по attachment-only LLM route
без глобального RAG, а direct/router LLM без облачного ключа уходит в локальный MLX вместо 401.
**Закрыто в 0.23.6.10:** после галочки upload файл не исчезает в тишину: composer показывает явную
плашку "к следующему сообщению", а в ленте чата появляется системное сообщение. Полный pytest теперь
`make ship-full`, быстрый итерационный выкат — `make ship` с retry post-deploy smoke.
**Закрыто в 0.23.6.11:** нормоконтроль в чате больше не выглядит как trace-мусор: это человеческий
отчёт с defended/blocked/manual секциями, source/action таблицами и top-level `defense`. `memory_block`
не примешивается к doc-review. Формат листа D4-001 снова computed: PDF-страницы измеряются и
классифицируются по ГОСТ 2.301; размещение рамки/граф и заполнение основной надписи остаются отдельной
layout/title-block задачей, а не скрытой уверенностью модели.
**Закрыто в 0.23.6.12:** служебные источники стали видимым контрактом (`/api/service-sources` + блок в
Инструментах): оператор видит, какие файлы нужны ЛЕСу для смет и нормоконтроля, где они лежат и что
деградирует без них. Layout v1 для основной надписи проверяет не только наличие сигнатур, но и попадание
в ожидаемую нижнюю правую зону листа; сигнатуры вне зоны дают computed issue.
**Закрыто в 0.24.0.0:** v0.24 оформлен как первый публично объяснимый SPDS workflow: doc-review
имеет человеческий отчёт, `defense_contract_v1`, `normalized_remarks` для последующих checklist/DOCX/PDF
слоёв, XLSX/JSON/HTML выгрузки в GUI, а repo получил source-available license/security/publication gate.
Полная публикация GitHub остаётся owner-gated: сначала scrub private data/secrets, затем менять visibility.

**Закрыто в 0.23.6.1:** router-primary регрессия переведена в честный
`RouterUnavailable` → deterministic cascade/in-flow fallback; `LES_ROUTER_PRIMARY` больше не включает
legacy agent loop. Латентность live-чата остаётся отдельной операционной темой.

## Следующее (по приоритету — хендофф)

1. **v0.24+ ПП-87/checklist/DOCX/PDF**: composition profile, checklist template import, rendered
   DOCX/PDF normcontrol reports.
2. **v0.26+ Минстрой-индексы** ([[minstroy-indices-source]]): последнее письмо ИФ/09 через VPS box →
   parquet → `index_lookup` к РИМ-трассе.
3. **GRAND-фиделити Прил.4** (долг #2): метаданные шапки из проекта, 179 колонок.
4. Доделать `make ship`-дисциплину как привычку: версия+леджер+док в каждом фиче-коммите
   (Definition of Done в AGENTS.md; стандарт — `docs/DOCUMENTATION_PLAYBOOK.md`).
