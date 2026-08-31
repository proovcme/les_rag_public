# Unified Construction Harness — Failure Ledger (v0.8)

## 2026-08-31 — После включения tools selector не видел само вложение

- **Симптом:** установленный профиль показывал оба workbook-tools, но Qwen 9B
  возвращала `calls: []` и просила повторно загрузить уже прикреплённый XLSX.
- **Причина:** переход рабочего PR `dbd4123a` на общий ContextGovernor сохранил
  tools и trusted execution, но потерял `attachment_id` в обязательном
  selector-request. Большой извлечённый текст оставался низкоприоритетной памятью
  и не помещался в restrictive-контекст 9B.
- **Исправление:** обязательный request содержит bounded-факт `attachment.bound`
  и exact временный ID; полный текст не дублируется. Модель сама выбирает tool,
  executor по-прежнему fail-closed привязывает exact server-owned файл.
- **Регрессия:** selector payload обязан объявлять attachment без копирования
  `attachment_context`.

## 2026-08-31 — Патч добавил workbook-tools в код, но не в установленный профиль

- **Симптом:** новый чат в режиме «Сметчик» с XLSX-вложением отвечал текстом;
  trace показывал `tool_loop.enabled=false`, XLSX не создавался.
- **Причина:** `_seed_factory()` завершался, если в MetaDB уже было четыре
  factory-профиля. Установленный `factory:profile:estimator:base` от 24 августа
  поэтому сохранил allowlist без `build_lsr_workbook` и `build_vor_workbook`.
- **Исправление:** startup синхронизирует stable factory Base с текущим code
  contract и обновляет только bindings на factory revision ID. Пользовательские
  ревизии и их bindings остаются immutable.
- **Дополнительно:** route trace обычного bound-чата теперь показывает
  фактическое исполнение `active`, а не rollout-default `shadow`.
- **Регрессия:** тест начинает со stale factory snapshot и stale chat binding,
  затем требует оба workbook-tools после повторного открытия registry.

## 2026-08-31 — Cumulative patch отвергал доверенный mixed-EOL runtime

- **Симптом:** 0.30.27 остановился до установки с `base checksum mismatch` на
  `openai_compatible_transport_service.py`, хотя файл содержательно совпадал с
  установленной 0.30.26.
- **Причина:** исторические Windows patch-применения оставили в одном точном
  файле смесь LF/CRLF. Его LF-нормализованный SHA совпадал с доверенным commit,
  но manifest перечислял только полностью LF и полностью CRLF варианты.
- **Исправление:** release builder получает exact установленный runtime и
  включает raw SHA только при доказанном нормализованном совпадении с Git
  ancestry. Новый клиент/helper дополнительно сравнивает canonical LF hash для
  разрешённых текстовых файлов. Иное содержимое остаётся недопустимым.
- **Граница:** пользовательские данные, бинарные файлы и произвольные локальные
  изменения никогда не нормализуются и не допускаются.

## 2026-08-31 — Режим «Сметчик» не показывал модели workbook-tools

- **Симптом:** при приложенной ВОР и явном «Собери ЛСР» модель отвечала текстом,
  XLSX не создавался. Внешняя диагностика ошибочно связала это с default
  `shadow` и отсутствующим promotion receipt.
- **Причина:** обычная назначенная answer model уже исполнялась в `active`, но
  restrictive preset оставлял модели только первые пять инструментов профиля.
  `build_lsr_workbook` и `build_vor_workbook` стояли седьмым и восьмым и
  исключались как `preset_limit`.
- **Исправление:** в attachment-bound draft оба workbook-tool поднимаются в
  начало model-visible shortlist. Код не выбирает инструмент, не создаёт
  решения и не вмешивается в `smeta_core`; модель по-прежнему сама решает,
  какой tool вызвать и с какими аргументами.
- **Регрессия:** 9B shortlist с восемью estimator tools обязан содержать оба
  workbook-tool в первых двух позициях.

## 2026-08-31 — Назначенная Ollama-модель не отвечала без ручной проверки

- **Симптом:** новая ревизия сохранялась и назначалась в UI, но обычный чат
  возвращал `MODEL_CONNECTION_RESOLUTION_FAILED: CAPABILITY_SNAPSHOT_MISSING`;
  оператору приходилось догадаться отдельно нажать «Проверить». После проверки
  Qwen 3.5 9B через OpenAI-compatible endpoint могла исчерпать ответ внутренним
  reasoning вместо финального текста.
- **Причина:** bind API не замыкал обязательный capability lifecycle, а общий
  transport всегда выбирал `/v1/chat/completions`. Нативный профиль Ollama,
  уже доказанный старым контуром, не был перенесён в immutable model connection.
- **Исправление:** bind автоматически probe-ит точную ревизию и fail-closed
  проверяет capability роли. Явно помеченный Ollama получает дополнительный
  live probe `/api/chat`; только подтверждённый snapshot включает нативный
  transport с `think=false`. Выбор не делается по имени модели.
- **Регрессия:** router test начинает с ревизии без snapshot; capability и
  transport tests требуют live-derived protocol и нативное тело запроса.
- **Scope:** модель, prompt, RAG, tool policy, сметы и пользовательские данные
  не менялись.

## 2026-08-25 — Release smoke omitted its isolation environment

- **Symptom:** NSIS returned exit code 0, but the requested isolated `app` directory stayed empty;
  the installer hook selected the canonical `%LOCALAPPDATA%\Programs\LES` path instead.
- **Cause:** `windows_patch_release.ps1` passed `/D`, but unlike the prepared-update contour did not
  set `LES_RELEASE_SMOKE=1` and `LES_WINDOWS_STATE_ROOT` before starting NSIS.
- **Fix:** the release script now scopes both variables to the installer process and restores their
  previous values in `finally`; regression tests require that contract. The same built installer was
  proven to install `0.28.2 / 589` into a unique smoke root before publication.
- **Impact:** program files reached `0.28.2`; user state was not deleted. Publication and the
  transactional production phase remained blocked until isolated acceptance became green.

## 2026-08-25 — Installed smoke rejected a valid repaired environment

- **Symptom:** both bootstraps were `ready`, the second was `skipped`, API/UI/base/RRF checks passed,
  but the aggregate report stayed `ok=false`.
- **Cause:** the first-pass allowlist predated the lock-bound venv contract and omitted its valid
  `environment_action=repaired` state.
- **Fix:** `repaired` is accepted only for the first pass; the second remains strictly `skipped`.
  A repeated isolated installed smoke passed with Docker/Qdrant unavailable as optional capability
  warnings.

## 2026-08-25 — Windows clean-install RRF seed parsed twice

- **Symptom:** installed `0.28.1` reached bootstrap `ready`, API/UI and process hygiene, but the
  isolated RRF seed failed with `QDRANT_POINT_COUNT_MISMATCH: got 2, expected 1`.
- **Cause:** upload background parsing held `parse_semaphore`, while the six-second durable
  auto-resume supervisor called the global scheduler without that semaphore. Both selected the same
  `PENDING` row and upserted different point identities concurrently.
- **Fix:** `run_parse_scheduler` now acquires the shared parse semaphore around every batch;
  regression test holds the semaphore and proves no backend parse begins until release.
- **Scope:** scheduling/consistency only. Retrieval ranking, prompts, providers and `smeta_core`
  were not changed.

## 2026-08-25 — Offline cold bootstrap exceeded the legacy smoke timeout

- **Symptom:** the second isolated install stayed healthy but the 480-second release-smoke deadline
  expired as status moved from cache extraction to locked `uv sync`.
- **Evidence:** the 421 MB archive expanded to 39,577 files / 1.305 GB in about 470 seconds on the
  Windows release host; stderr remained empty and the next phase was reached.
- **Fix:** measured cold-bootstrap allowance is 900 seconds and troubleshooting documents the
  expected 8–15 minute first run. The terminal `ready|failed` requirement remains fail-closed.

Реестр поведения на operational-смоуке. `no_data`/`MISSING` с честным evidence — НЕ баг, а
корректный отказ. Баг — только системная ошибка, фейковый источник или маршрут не туда.

**Как включить (dev):** `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1` (OFF по умолчанию — в коде и
тестах не меняется). Смоук: `LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 uv run python
scripts/smoke_unified_v08.py` (фикстура) или `--dataset-id <ds>` (реальный проект). Trace ответа:
`query_route.version=unified_construction_harness_v0_8` + `unified_trace` + `evidence_summary`.
Выключить: убрать env-переменную. Runtime (`/Users/ovc/LES/.env`) НЕ трогался — флаг ставит оператор.

## Operational incident 2026-07-15: Gemma returned prose instead of the required smeta tool call

На реальной ВОР из 19 строк обычная модель чата `gemma4:12b` неявно стала моделью document workflow
и после 81,2 с вернула prose без `tool_calls`. ЛСР не была собрана. Локальный Ollama игнорировал
`LES_SMETA_DOCUMENT_MODEL`, а непустой prose не попадал под transport retry. Исправление отделяет
сметную модель от чата, повторяет исходную модель с обязательным tool-call и разрешает явную
резервную модель. Резерв можно отключить для чистого сравнения Gemma.

**Rule:** выбор модели чата не меняет сметного агента. Смена модели внутри сметного хода не может
быть скрытой; код не подменяет отсутствующий mapping собственным выбором норм.

Живой повтор на Legion после 0.24.16 уточнил корень: через `/v1/chat/completions` Gemma дважды
вернула пустой message без tools, а тот же `gemma4:12b` через нативный `/api/chat` немедленно вызвал
тестовый tool. Локальный smeta transport переведён на native Ollama; модельный контракт не менялся.

Следующий чистый прогон выявил ещё две transport-особенности Gemma: служебная JSON-генерация
search/read раздувалась при общем большом token budget, а иногда правильный `work_id` попадал внутрь
`technology_check`. Workflow больше не режет ВОР на строки или скрытые пакеты: модель получает весь
исходник одним разговором; transport даёт короткий бюджет только search/read и полный — итоговому
mapping. Узкий нормализатор переносит только служебный идентификатор, не выбирая и не меняя норму,
аналог, применимость или ресурсы. Чистый Mac-прогон 19 строк с отключённым fallback дошёл по реальным
данным до `search_norms_batch` (370,7 с) и `read_norms_batch` (639,4 с); это подтверждает native tools,
но одновременно показывает, что Mac/Gemma не является приемлемым production-профилем скорости.
Полный XLSX и время на Legion остаются обязательным release-gate.

Первый полный Legion-прогон дошёл до `read_norms_batch` и показал ещё одну безопасную вариацию:
для 18 однокодовых чтений Gemma передала scalar `norm_code`, хотя контракт описывал массив
`norm_codes`. Tool transport теперь оборачивает только это значение в список. Сам код нормы,
принадлежность строке и профессиональное решение остаются неизменными.

Повтор build 429 открыл карточки всех 19 строк, но итоговый mapping после полных ресурсных перечней
не завершился за 12 минут и transport начал повтор. Полные ресурсы теперь запрашиваются самой
моделью через `include_resources=true`; обычный read возвращает состав работ и честные count/kinds.
Внутренняя карточка и расчёт сохраняют весь ресурсный состав без лимита.

На build 430 Gemma после успешного поиска дважды вернула пустой ход, пока одновременно видела
`search`, `read` и преждевременный `submit`. Tool-set теперь отражает структурно допустимую стадию:
после поиска только повторный search/read, после чтения снова доступен submit. Это workflow guard,
а не selector профессионального решения.

Контрольный Qwen-прогон затем передал корректные 19 пар `work_id`/`norm_code`, но дважды
сериализовал `items` как JSON-строку и вынес `include_resources` на уровень вызова. Transport
распаковывает массив и наследует только этот boolean; значения строк и кодов не меняются.
Build 432 показал дополнительный уровень: сам `arguments` или `items` мог оставаться строкой после
первого decode. Parser теперь ограниченно рекурсивен и принимает только JSON/literal containers.

Контрольный build 433 дошёл до чтения всех 19 выбранных кодов, но RAG выдавал часть display-кодов
с двоеточием после семейства, а модель возвращала тот же код без двоеточия. Точное строковое
сравнение ошибочно считало карточку неоткрытой. Build 434 сопоставляет только канонически равные
family-aware ссылки (`ГЭСН` отдельно от `ГЭСНм/ГЭСНр/ФЕР`); выбранная моделью норма не заменяется.

Повтор build 434 показал точный транспортный дефект большого вызова: все 19 `work_id` и выбранных
кодов присутствовали, но Ollama не дописала единственную закрывающую `]` у строкового массива
`items`. Build 435 умеет только закрыть до трёх незавершённых trailing JSON-контейнеров при
структурно правильном префиксе; повреждённый текст, элементы и профессиональные поля не чинятся.

Build 435 открыл реальные карточки, но Qwen вынес `include_resources=true` на неописанный верхний
уровень и получил ресурсы сразу всех норм; итоговый ход занял 225,9 с и повторился из-за отсутствия
пустого `analog_limitations` у exact-строк. Build 436 принимает полный ресурсный состав только по
объявленному item-level запросу самой модели, а отсутствующий exact-массив нормализует в `[]`.
Аналоги, коды, resource actions и их причины код по-прежнему не достраивает.

На build 436 первый компактный mapping показал ещё две schema-вариации: модель одновременно явно
ставила `close_analog` с ограничениями и ошибочный enum `selection_kind=exact`, а reason действия
оставляла в reason той же строки. Build 437 не принимает профессионального решения: он сводит enum
к уже выраженному моделью analog-намерению и копирует только собственный текст модели в пустое
одноимённое поле действия. Код нормы, применимость, ограничения и само действие остаются исходными.

Контрольный build 437 дал 18 валидных решений и одну строку, которой потребовался дополнительный
search/read. Прежний retry отбрасывал 18 уже принятых модельных строк и требовал повторить весь
mapping. Build 438 сохраняет их неизменными внутри незавершённого хода и просит модель вернуть
только `remaining_work_ids`; это transport checkpoint, а не выбор или исправление нормы кодом.

Финальный Legion gate build 438 завершился настоящим XLSX: 19 решений модели, 14 рассчитанных
позиций, 5 открытых строк, Qwen `qwen3.5:9b`, fallback отключён, НДС 22%, итог известной части
1 268 288,62 ₽ с НДС. Шесть модельных ходов заняли около 10,1 мин; единственная дополнительная
строка после checkpoint прошла search→read→submit за 44,3 с, остальные 18 не генерировались заново.
Gemma подтверждена как пригодная для обычного RAG, но её строгий smeta tool-loop на Legion остаётся
медленнее и менее стабилен Qwen, поэтому production smeta default не переключён на Gemma.

**Rule:** tool-transport обязан быть терпим к безопасной перестановке служебного идентификатора, но
не имеет права достраивать отсутствующее профессиональное решение модели.

## Operational incident 2026-07-15: cumulative VPS patch rejected an installed intermediate patch

Первый накопительный manifest разрешал для каждого файла только состояние полного release-base или
конечного target. После установки одного патча следующий видел смесь файлов из промежуточного commit
и ошибочно считал её посторонней локальной модификацией.

**Rule:** builder фиксирует SHA каждого разрешённого файла на всей доверенной git ancestry между
полным совместимым release-base и target. Для разрешённого текстового Windows runtime LF/CRLF
канонизируются только при сравнении содержания; raw SHA текущего runtime включается лишь после
такого совпадения. Произвольный локальный файл по-прежнему fail-closed отклоняется.

## Operational incident 2026-07-15: FGIS unified parquet diverged from structured manifest

Legion bootstrap history recorded a real repair with reason `unified parquet does not match
structured-base manifest`. The release baseline restored one internally consistent set; the
0.24.14 production deployment later returned `action=kept_valid`, so it did not overwrite the
validated Legion state. This proves the archive is a clean-install/recovery floor, not an update
mechanism.

**Rule:** a full FGIS update must build typed parquet, structured SQLite, manifests, integrity
reports and FSEM linkage in staging; validate the complete linked set; then atomically activate it.
No canonical file may be replaced before the whole generation is green. A failed generation stays
available for diagnosis and the previous active generation remains live.

**Status:** recovery and fail-closed validation work; end-to-end atomic FGIS generation activation
remains open and must not be represented as solved by bundling a release archive.

## Operational incident 2026-07-15: production smoke outlived neither OpenSSH session nor job

The 0.24.14 production gate proved API/UI and heavy-PDF RRF while its remote PowerShell session was
still open, then published successfully. A separate request after the SSH command returned found no
listeners on 8050/8051: children created from session 0 had exited with the remote job. The installed
Tauri executable was then started in the logged-in Oleg session through a one-shot interactive
scheduled task; the task was removed, and a new independent SSH probe confirmed version 0.24.14,
`qwen3.5:9b` and UI HTTP 200.

**Rule:** an in-session smoke is necessary but not sufficient for Windows production persistence.
The release orchestrator must close the build/deploy SSH session, then independently verify that
the interactive desktop-owned runtime still answers. If it does not, release publication must stop.

The same defect recurred after the 0.24.15 release session: in-session production checks were green,
but independent 8050/8051 probes failed. The installed Tauri shell was recovered again through a
one-shot interactive task and independently verified as 0.24.15/build 426 with UI 200 and
`qwen3.5:9b`.

**Status:** production was recovered and independently verified twice; automated post-session
persistence gate remains open and is a release-orchestrator blocker, not a runtime-data failure.

The first 0.24.15 VPS docs patch exposed the same Windows job boundary inside the updater itself:
`DETACHED_PROCESS` did not escape the Tauri job-object, so the helper replaced the file and died when
the UI listener was stopped, before restart/status completion. The public feed was removed before
general use. The corrected contract starts both helper and replacement Tauri shell through separate
interactive Scheduled Tasks; 0.24.15 is not an updater-compatible base.

## Operational incident 2026-07-14: clean Windows smoke reused shared Qdrant collection

Изолированная Windows-установка получила собственные MetaDB/storage, но сохранила дефолтную
`RAG_COLLECTION_NAME=les_rag` и подключилась к общей непустой Qdrant-коллекции. Локальный паспорт
индекса отсутствовал, фоновый parse упал на fail-closed contract gate, а upload-документ остался
`PENDING`, поэтому выпускной smoke ждал таймаут вместо немедленной диагностируемой ошибки.

**Rule:** release-smoke обязан владеть и state, и одноразовой Qdrant-коллекцией. Любая ошибка
фонового intake должна атомарно переводить конкретный document id в `ERROR` с `last_error`;
`queued` и HTTP 200 не являются доказательством индексации.

**Follow-up:** первый изолированный прогон обнаружил второй drift: Windows/Ollama переписывал
`MLX_URL`, но оставлял parse-only `EMBED_URL_PARSE=:8081` из Mac/dev-профиля. Query dense был
жив, а новые документы не индексировались. Windows startup теперь атомарно направляет оба пути
на `OLLAMA_BASE_URL`; выпускной smoke обязан доказать именно upload→INDEXED→RRF.

## Operational incident 2026-06-27: partial runtime deploy with divergent app.py

During v0.23.6.12 rollout, `make ship` copied the new `service_sources` router and service, but
skipped divergent `proxy/app.py`; `/api/service-sources` returned 404. A targeted `--force` copy of
`proxy/app.py` then exposed older clean@HEAD app dependencies that were not present in the runtime
clone (`incoming_control`, `estimates`, `extract` routers and their services), so proxy failed to
start until those files were copied too. Final recovery: copy missing clean dependencies, verify
`create_app()` in `/Users/ovc/LES`, `launchctl kickstart -k gui/$(id -u)/me.ovc.les.proxy`, then
`/api/service-sources` and `tools/basic_function_smoke.py` passed.

**Rule:** when force-copying a divergent runtime entrypoint, also audit imports against the runtime
clone before restart; `make ship` only follows dirty files and can miss clean tracked dependencies
that never existed in `/Users/ovc/LES`.

## Прогон 2026-06-24 (фикстура «котельная», 10 кейсов, offline)

| # | вопрос | route | status | failure_type | вердикт |
|---|--------|-------|--------|--------------|---------|
| 1 | опиши проект + реестр | project_document_registry | complete (6 src, 3 мусор) | — | OK |
| 2 | найди ОЗК в актах | asbuilt_extract | complete (1 src) | — | OK (не нормы) |
| 3 | найди КДУ в актах | asbuilt_extract | no_data | term-not-in-source | OK (generic, честный MISSING) |
| 4 | найди ОЗК в спецификации | project_doc_entity_search | complete (1 src) | — | OK (не «монтаж») |
| 5 | правила расстановки ОЗК | norm_qa | no_data | **lexical_miss** | limitation |
| 6 | что писали в почте | mail_entity_search | no_data | **mail_source_missing** | limitation |
| 7 | извлеки ВОР из Ф9 | bor_extract | complete (1 src) | — | OK |
| 8 | собери ЛСР по Ф9 | estimate_from_bor | complete | — | OK |
| 9 | проверь пример обсчёта | resource_cost_calc | complete (real workbook) | — | OK |
| 10 | что требует КАЦ | resource_cost_calc | complete | — | OK |

**Маршрутизация: 10/10 верно.** source_scope доминирует над термином (2,3,4 → не нормы),
generic-термины без словаря (КДУ), нормы/обсчёт раздельно.

## Открытые limitation'ы (не баги — честный MISSING)

| failure_type | где | причина | proposed_fix | статус |
|--------------|-----|---------|--------------|--------|
| `no_scope` | project/asbuilt/ВОР/mail без проекта | нет project_id/dataset_ids | **actionable MISSING** (какой источник нужен) | ✅ v0.8 |
| `lexical_miss` | norm_qa | в фикстуре нет lexical-индекса; PDF-тело не ищется | Qdrant-vector + PDF-тело в norm_qa | ⏳ v0.9 |
| `mail_source_missing` | mail_entity | async `mail_query` не интегрирован в unified | read-only mail-adapter (rag_backend + mail-dataset) | ⏳ v0.9 |
| `parquet_only_limitation` | source_scoped | ищет в parquet-строках + именах файлов, не в теле PDF/чанках | tier-3 lexical + tier-4 vector с пометкой `chunk` | ⏳ v0.9 |
| `qdrant_not_used` | norm/source_scoped | vector-ретрив не подключён к unified | source-adapter к Qdrant | ⏳ v0.9 |
| `price_db_missing` | resource | цены из workbook-ячеек, не из ФГИС | bridge `fgis_price_lookup` (готов, not_found) | ⏳ |

## Safety-инварианты (подтверждены смоуком + тестами)

- числа/нормы/письма/факт монтажа — НЕ из модели; нет фейковых source_refs;
- spec-совпадение (#4) ≠ подтверждение монтажа;
- мусор (#1) помечен, НЕ удалён физически;
- mail read-only (нет send/push); reconstructed workbook не выдаётся за real;
- `final_total` только при complete; «П»/needs_kac → MISSING.

## ✅ v0.9 (2026-06-24): real source adapters — размытые limitation'ы → ЯВНЫЕ статусы

`proxy/services/source_adapters.py` (unavailable-safe, без фейков): lexical (sync SQLite/FTS — реально
находит при наличии индекса), vector (Qdrant — async+backend → `unavailable` в sync-пути), mail
(async mail_query+backend → `mail_backend_not_configured`). source_scoped и norm_qa отчитываются
`searched_tiers`; trace v0_9 несёт searched_tiers + adapter_warnings. Смоук v0.9 (`smoke_unified_v09.py
--append-ledger`):

| статус был (v0.8) | стал (v0.9) |
|---|---|
| `parquet_only_limitation` (молча) | tier-chain: parquet→filename→**lexical_chunk**→vector; searched_tiers в trace |
| `lexical_miss` (vague) | norm_qa layered (lexical→vector); MISSING перечисляет tier'ы |
| `qdrant_not_used` (vague) | **explicit `vector_unavailable`** warning (async не вшит в sync-путь) |
| `mail_source_missing` (vague) | **explicit `mail_backend_not_configured`** (read-only adapter, нет send/push) |

Прогон фикстуры: КДУ-в-актах → no_data, tiers=4, `vector_unavailable`; нормы → no_data, tiers=2;
почта → no_data, `mail_backend_not_configured`. Маршруты 10/10. Адаптеры в оффлайне честно
`unavailable`/`not_found` — НЕ фейк.

## ✅ v0.10 (2026-06-24): async real adapters — vector/mail из static unavailable → реальные

`source_adapters.py`: `search_vector_chunks_async` / `retrieve_mail_evidence_async` (через инжекцию
async-замыкания из `_run_chat`; адаптер не знает тяжёлую сигнатуру retrieve_chat_chunks/mail_query).
`run_unified_construction_harness_async` (sync-first + async-escalate): sync делает tier 1-3, при
наличии backend эскалирует tier-4 vector / mail. Trace v0_10 несёт `adapter_statuses`
{parquet/lexical/vector/mail}. Новые статусы: timeout, error, weak_related, no_source.

| было (v0.9) | стало (v0.10) |
|---|---|
| vector static `unavailable` | реальный async-адаптер: backend→found, нет→unavailable, медленно→timeout, сбой→error |
| mail static `not_configured` | реальный async mail_query (read-only): backend→found(message_id), нет→unavailable |
| — | **семантический vector без точного термина → `weak_related`, НЕ «найдено»** (анти-overclaim) |

Smoke v0.10 (`smoke_unified_v10.py --stub-vector --stub-mail`): norm→complete vector=found;
mail→complete mail=found; КДУ-в-актах→vector=**weak_related** (семантика, термина нет). Offline (без
backend) → честный unavailable. `_run_chat` строит vector_fn/mail_fn ТОЛЬКО при реальном backend
(есть list_datasets); test/offline → fn=None → unavailable. Нет asyncio.run в running loop.

## ✅ v0.12 (2026-06-24): FILE_BODY + EML + MARKDOWN — закрыт реальный gap v0.11

v0.11 вскрыл: реальные датасеты = `.md`/`.eml`, не parquet. v0.12 читает их НАПРЯМУЮ read-only (без
OCR/бинарей), source_ref до файла/строки/message_id.

`source_adapters.py`: `search_file_body` (.md/.txt, path-traversal + лимиты), `search_eml_messages`
(.eml через email.parser, snippet-only, нет send/delete), `extract_markdown_tables_from_file`/
`markdown_table_to_rows` (markdown pipe-таблица → ВОР-строки). Интеграция: source_scoped tier-chain
parquet→filename→**file_body→eml**→lexical→vector; norm_qa file_body первым tier'ом; retrieve_project_doc
markdown-fallback при no_parquet. index_health +md/txt/eml/markdown_table counts + readable_body_available.
doc_classifier: revit-api/cad_bim/speckle .md → external_reference (не проектный док), .md/.txt→project_doc.

| было (v0.11) | стало (v0.12) |
|---|---|
| `no_lexical_index` (слепо) | **file_body** ищет в .md напрямую → RETRIEVED; health: no_lexical_index_but_file_body_available |
| `mail_backend_not_configured` | **.eml читается** → mail_not_found (термина нет) ИЛИ found(message_id); backend опционален |
| `f9_not_found_no_parquet` | **markdown-таблица в .md** → ВОР-строки с source_ref (ЛСР проходит) |

**Реальный прогон датасета 11da8ad7 (402 .eml):** health eml=402; mail → `mail_not_found` (прочитал 402
реальных письма, термина нет — НЕ backend_not_configured); norm file_body-tier. Синтетика: markdown
Ф9 → ВОР (3 строки), .eml ОЗК → found(message_id), file_body .md → found(#L3). 33 теста v0.12.

**Безопасность v0.12:** read-only, без OCR, path-traversal блок, лимит размера/числа файлов/сниппетов,
snippet-only (нет полного тела письма), нет send/delete/mutate, нет fake source_refs, нет хардкод-словаря.

## ✅ v0.13 (2026-06-24): DOCUMENT BODY EXTRACTION — PDF/DOCX/XLSX → searchable

v0.12 закрыл .md/.eml; v0.13 закрывает БИНАРНЫЕ доки через read-only sidecar-извлечение (БЕЗ OCR,
без облака, оригиналы не трогаются). Библиотеки в окружении: fitz/PyMuPDF + pdfplumber (PDF),
python-docx (DOCX), openpyxl (XLSX) — все есть.

`doc_extract_service.py`: extract_pdf_text (no_text_layer без OCR), extract_docx (абзацы+таблицы),
extract_xlsx_generic (строки), extract_bor_tables (xlsx/docx → ВОР-таблицы), sidecar write/read
(storage/datasets/{ds}/_extracted/<rel>.jsonl). source_ref до page/paragraph/sheet/row.
`search_extracted_body` адаптер: source_ref до ОРИГИНАЛА (не sidecar). Интеграция: source_scoped
tier-5 extracted_body (после file_body/eml, до lexical); norm_qa tier-2; retrieve_project_doc xlsx/
docx-table fallback. index_health +pdf/docx/xlsx/sidecar counts. extract_dataset_bodies_v13.py
(--dry-run/--report, path-safe, лимит размера).

| было (v0.11/v0.12) | стало (v0.13) |
|---|---|
| `no_lexical_index` для PDF/DOCX | **extracted_body** ищет в sidecar → RETRIEVED #page/#para |
| `pdf_files_without_sidecars` (новый health-warn) | actionable: «запустите extract_dataset_bodies_v13.py» |
| `f9_not_found_no_parquet` | **ВОР из XLSX/DOCX-таблицы** (sheet!row / table-row source_ref) |
| `no_text_layer` (новый) | scanned PDF → честный no_text_layer, не фейк (OCR вне hot-path) |

Смоук (синтетика): PDF/DOCX/XLSX → extract (sidecar), search_extracted «ОЗК» → found #para1,
source-scoped спец → complete (extracted_body tier), ВОР из XLSX → 2 строки. 28 тестов v0.13.
**runtime .env НЕ трогал; sidecar в рантайм НЕ писал** (только dry-run разрешён без ОК оператора).

**Безопасность v0.13:** read-only оригиналы (тест на неизменность байтов), без OCR, path-traversal
блок, лимит размера 40МБ, dry-run не пишет, нет fake source_refs, нет облака, extractor_version в каждом
item, scanned PDF → no_text_layer (не выдумка).

## ✅ v0.14 (2026-06-24): RUNTIME SIDECAR ACCEPTANCE + WRITE-POLICY + TEST-STABILITY

v0.13 доказал extraction на синтетике; v0.14 — operator-safe runtime-процесс + реальная dry-run-
приёмка + починка test-flakiness.

**Test-stability (КОРЕНЬ найден):** «2 chat-падения в общей сессии» — НЕ chat-state leakage и НЕ
pytest-randomly (его вообще нет в окружении). Реальная причина: `test_agent_router.py::test_classify_*`
мокали `les_md_service._llm_text`, а `_classify` зовёт `_route_llm_text` → мок не срабатывал → РЕАЛЬНЫЙ
LLM-вызов на :8080 (24с), шум→'none'. «Flaky» = зависело, ответил ли живой :8080. Фикс: мок на правильный
путь `ar._route_llm_text` → герметично (24с→0.25с). Полный chat/router/mail-сет: 2 failed → **0 failed (83)**.

**Write-policy gate:** doc_extract_service +manifest/staleness/runtime-guard. scripts/extract_dataset_
bodies_v14.py: dry-run по умолчанию; --write-sidecars пишет; запись в RUNTIME (/Users/ovc/LES) требует
--confirm-runtime-write И env LES_ALLOW_RUNTIME_SIDECAR_WRITE=1, иначе ⛔ `runtime_sidecar_write_not_
approved` (dry-run). manifest.json (mtime/size оригиналов) → `sidecar_stale`. index_health +manifest_
present/stale_count/sidecar_stale-warning.

**Реальная dry-run приёмка (датасет 844a2b53, 27 ГОСТ/СП .docx, read-only):** would_write=27,
**docx_paragraphs=23 930** извлекаемо, 0 failures, originals_mutated=False. Gate проверен: --write в runtime
без разрешения → ⛔, _extracted НЕ создан. **Sidecar в рантайм НЕ писал (нет одобрения оператора в этой
сессии); runtime .env НЕ трогал.**

15 тестов v0.14 (write-policy gate, manifest, staleness, real dry-run, agent_router-герметичность,
регрессии). 345 unified-сюита + 83 chat (0 failed) + verify зелёные.

**Safety v0.14:** оригиналы read-only (тест на байты), dry-run не пишет, runtime-write за двойным гейтом,
без OCR, без облака, нет fake source_refs, staleness честно помечается, evidence-контракт цел.

## ✅ v0.15 (2026-06-24): APPROVED RUNTIME SIDECAR WRITE + REAL EXTRACTED-BODY SMOKE

**Оператор ЯВНО разрешил запись** sidecar для датасета 844a2b53 (через AskUserQuestion). Выполнен
approved runtime write (env LES_ALLOW_RUNTIME_SIDECAR_WRITE=1 + --confirm-runtime-write):
- 27 ГОСТ/СП .docx → **27 sidecar'ов + manifest.json**, **23 930 параграфов**, 0 failures;
- **оригиналы БАЙТ-В-БАЙТ идентичны** (shasum до/после), only _extracted/ добавлен;
- index_health: sidecar_available=True, extracted_body=23930, stale=0, warns→
  `no_lexical_index_but_file_body_available` (НЕ blind).

**Реальный extracted_body smoke (через unified harness на данных оператора):**
- registry → complete (27 ГОСТ/СП);
- norm_qa «правила огнестойкости стен» → **complete → СП 327.1325800.2017 #para85**;
- «требования к кровлям» → СП 17.13330; «опалубку» → СП 114.13330; «по нормам для серверной» → 9 src;
- «АУПТ для серверной» → honest `norm_no_source` (термина нет в структурных ГОСТ — НЕ no_lexical_index);
- asbuilt/spec → `no_source_in_scope` (нет актов в норм-датасете).

**v0.15 фиксы:** (1) norm_qa word-expansion — фраза нормализуется в склеенный блок и не матчит тело →
добавлен поиск по СОДЕРЖАТЕЛЬНЫМ словам >5 симв (кроме служебных); «огнестойкости» в «правила
огнестойкости стен» теперь матчит. (2) sample_extracted_terms_v15.py — сэмпл реальных норм-кодов/слов/
заголовков из sidecar (для позитивного smoke, не только negative).

| было (v0.14) | стало (v0.15) |
|---|---|
| no_lexical_index для ГОСТ-датасета | **extracted_body → complete с source_ref до .docx#para** ИЛИ honest norm_no_source |
| dry-run only | **approved runtime write** (27 sidecar, оригиналы read-only доказано) |
| — | term-sampler находит реальные термины (СП 20.13330, огнестойкость…) с source_ref |

24 теста v0.15 (norm word-expansion, sidecar-available, sampler, **4 реальных на 844a2b53-sidecars**,
write-policy/staleness регрессии). 351 unified-сюита + 83 chat (0 failed) + verify зелёные.

**Safety v0.15:** запись ТОЛЬКО с явным разрешением оператора (получено), оригиналы read-only (shasum),
без OCR, без облака, source_ref до реального абзаца (не sidecar-путь), нет fake-хитов, no_lexical_index
заменён реальным RETRIEVED или честным term_not_found. runtime .env НЕ трогал.

## ✅ v0.16 (2026-06-24): SIDECAR OPERATIONS + CLASSIFIER + EXTRACTION UX HOOKS

Извлечение стало **операторски видимой и управляемой** операцией (бэкенд; флаг OFF не менялся, runtime
.env не трогал, новых runtime-записей без одобрения НЕТ — только dry-run).

**§1 Инвентарь (28 датасетов, без записи):** mail=1 (11da8ad7, 402 .eml), norm=15, project-like=4,
extract-candidates=19, already-extracted=1 (844a2b53). `inspect_runtime_datasets_v16.py` →
`artifacts/runtime_dataset_inventory_v16.json`.

**§2 Dry-run на реальных датасетах (БЕЗ записи, оригиналы целы):** e19cc409 (project docx): files_seen=22,
would_write=22, **docx_paragraphs=20054**, originals_mutated=False; 11da8ad7: 402 .eml + 1 pdf; a1cc873f:
файлы `.xls` (legacy) + уже `_parquet/` — **парсер-лимит: .xls не извлекается** (данные уже в parquet);
844a2b53: manifest/sidecar=27/stale=0 — **дубль-записи не делал**; write без env → wrote_sidecars=0.

**§3 Классификатор по заголовкам** (`classify_document_from_sidecar`): мусорное имя + heading «Акт …
смонтированного оборудования» → **installed_equipment_act** (by=sidecar_heading); 844a2b53 остаётся
**norm** (by=filename). Heading улучшает, filename — фолбэк, «не-мусор» не теряется.

**§4 Extraction-state сообщения** (видимый MISSING/BLOCKED + действие, 7 кейсов A–G): sidecar_exists_and_
searched / extraction_required / extraction_write_not_approved / sidecar_stale / no_text_layer(ocr_required) /
term_absent_after_extracted_search / eml_dataset_searched. **Нет дженерик «не найдено»/«no_lexical_index».**

**§5 GUI/API** (backend готов; кнопка — TODO): `GET …/datasets/{id}/extraction-status`, `POST …/extract-
body/dry-run`, `POST …/extract-body/write` (write только confirm+env, иначе blocked-отчёт). Сервис:
`extraction_status`, `extract_body_op` (гейт extract_v14).

**§6A Lexical extracted_fts** (отдельная FTS): dry-run 844a2b53 → would_index=23930; write+search находит
текст с сохранённым source_ref до `.docx#para`; дубли по source_ref не переиндексируются. **§6B Qdrant —
только отчёт** (~2386 точек, deferred, embedding_run=False).

**§7 OCR — только детект** (`ocr_detection`): pdf_no_text_layer_count из manifest, ocr_status=deferred.
OCR не реализован, зависимостей не добавлено.

**§8 Smoke v16** (`smoke_unified_v16.py`, 15 канон.вопросов): 844a2b53 — norm_qa→complete (СП 70/114 с
source_ref), АУПТ→term_absent_after_extracted_search; 11da8ad7 — mail→eml_dataset_searched.

**Категории:** extraction_dry_run_done · extraction_write_blocked_by_policy · extraction_already_present ·
sidecar_heading_classified · extracted_lexical_index_ready · qdrant_index_deferred · no_text_layer/ocr_
required · eml_dataset_read · project_like_dataset(.xls лимит).

50 тестов + verify + 254 backend-регрессия + 17 chat OFF — зелёные. Safety: оригиналы read-only (shasum),
запись только env+confirm, без OCR/облака/Qdrant-эмбеддинга, без фейк-source_ref, без хардкода терминов,
флаг OFF и runtime .env не тронуты.

## Открыто (когда backend подключён в рантайме)
- vector/mail сейчас `unavailable` в **sync** unified-пути (async retrieve/mail_query не вшит). Закрыть —
  async-обёртка адаптеров в chat-пути ИЛИ sync-мост к Qdrant.
- lexical реально найдёт тело PDF, **если корпус проиндексирован** в lexical_chunks (в фикстуре пусто).
- реальный resource-price DB/ФГИС (bridge готов, not_found). **На реальном проекте в GUI прогон ещё не
  делался** — оператору включить флаг в рантайме (`LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1`) и
  `smoke_unified_v09.py --dataset-id <id> --append-ledger`.

## ✅ v0.11 (2026-06-24): REAL-DATA ACCEPTANCE (26 датасетов рантайма, read-only)

**runtime flag NOT changed by policy** — оператор не давал явного разрешения; прогон только через
script-smoke на реальных данных `/Users/ovc/LES/storage/datasets` (read-only). `inspect_dataset_index_
health` (§5) превращает общий lexical_miss в КОНКРЕТНЫЙ no_lexical_index/no_parquet.

**Главное открытие о реальных данных:** датасеты рантайма НЕ хранят `_parquet/` — это `.md`/`.docx`/
`.eml`, проиндексированные в Qdrant/lexical. parquet-путь harness'а (ВОР/ЛСР/source-scoped-по-строкам)
на реале пуст; нужен lexical/vector (в dev-view индекс пуст → no_lexical_index).

**Прогон датасета 844a2b53 (27 реальных ГОСТ/СП, 16 вопросов) — 16/16 классифицировано верно:**

| вопрос-класс | route | status | failure_type | вердикт |
|---|---|---|---|---|
| опиши проект + реестр | project_document_registry | **complete (27 src)** | — | ✅ WIN: registry РАБОТАЕТ на реальных ГОСТ/СП |
| найди ОЗК/КДУ в актах | asbuilt_extract | no_data | `no_source_in_scope` | OK (нет актов в норм-датасете) |
| правила/нормы (×4) | norm_qa | no_data | `no_lexical_index` | limitation (индекс пуст → проиндексировать) |
| почта (×2) | mail_entity_search | no_data | `mail_backend_not_configured` | limitation |
| ВОР/ЛСР | bor/estimate | no_data | `f9_not_found_no_parquet` | OK (Ф9 не выгружен как parquet) |
| обсчёт/КАЦ | resource_cost_calc | **complete** | — | ✅ real workbook |

**Категории (real): no_source_in_scope=4, no_lexical_index=4, mail_backend_not_configured=2,
f9_not_found_no_parquet=2.** Все — честные limitation'ы (нет источника нужного типа в датасете), НЕ
баги: маршрут верный, evidence честный, нет фейков/галлюцинаций. elapsed 0.2–155 мс.

**Закрыто в v0.11 (failure-driven):**
- ✅ `lexical_miss` → конкретный **`no_lexical_index`** через index-health (norm_qa MISSING называет
  причину: «корпус не проиндексирован, проиндексируйте документы», а не общее «не найдено»).
- ✅ failure-классификация по intent (был баг: asbuilt-без-актов помечался mail → теперь no_source_in_scope).

**Блокировано отсутствием инфраструктуры (не баг, нужен оператор/рантайм):**
- `no_lexical_index` — индекс lexical_chunks пуст в dev-view (в рантайме наполнен; нужен прогон ТАМ).
- `mail_backend_not_configured` — async mail_query требует живой rag_backend (есть в рантайме).
- `f9_not_found_no_parquet` — реальные Ф9/ВОР индексируются, не лежат parquet'ом в датасете.

**Следующий шаг — РЕАЛЬНЫЙ прогон В РАНТАЙМЕ** (оператор включает флаг): тогда lexical/vector/mail
наполнены → no_lexical_index/mail закроются реальными RETRIEVED. Команда: `LES_UNIFIED_CONSTRUCTION_
HARNESS_ENABLED=1 python scripts/smoke_unified_v11.py --dataset-id <ID> --storage-root /Users/ovc/LES/
storage/datasets --append-ledger`.

- smoke v16 `e19cc409-ac45-42b9-8029-d74cd9659a12`: corpus=norm sidecar=True states=['sidecar_exists_and_searched', 'term_absent_after_extracted_search'] complete=6/15
## Operational incident 2026-07-17: missing recommended Ollama model killed first launch

**Symptom:** clean Windows install opened a fatal `bootstrap_unhandled` screen with
`Error: model 'qwen3.5:9b' not found`.

**Cause:** Windows bootstrap silently selected the recommended tag, attempted model provisioning in
the critical startup path and promoted any Ollama exception to a process-wide failure. External
programs, Docker/WSL readiness and user-managed models had no normal first-run state.

**Rule:** bundled Python/uv may prepare automatically, but missing external components and models are
`setup_required`, not fatal. Tauri owns a persistent setup/help wizard; winget installation requires
an explicit user action, the answer model is selected only from installed tags, and bootstrap never
calls `ollama pull`. `qwen3.5:9b` is a recommendation; `bge-m3` remains the explicit embedding
contract. Internal preparation failures stay visible in the same wizard with code and log path.

## Operational incident 2026-08-25: boxed Windows bootstrap took eight minutes

**Symptom:** clean release smoke appeared frozen while unpacking the bundled offline dependency
cache; a 480-second smoke timeout expired just as `uv sync` began. Repeated release attempts also
collided with stale ACLs in the fixed smoke state directory, and the builder rebuilt the same
lock-bound dependency cache unless an operator supplied an environment variable.

**Cause:** Windows PowerShell `Expand-Archive` spent about 470 seconds creating 39,563 small cache
files. Smoke install/state paths were stable across attempts. The build cache had validation but no
content-addressed persistent lookup.

**Fix/guard:** bundled CPython now extracts the verified archive (`25.1 s` in the same Legion
measurement); the builder automatically caches by `uv.lock` plus Python/uv contracts; both prepare
and release smoke use GUID-qualified roots. Focused tests assert all three boundaries. A release is
not publishable until one new-state installer smoke passes in a single run.

## Operational incident 2026-08-25: production update rolled back a healthy cold start

**Symptom:** the exact installer passed new-state release smoke, but production update returned
`start-runtime failed (1)` and restored the previous application tree. User state remained intact.

**Cause:** the real `les_rag` corpus needed about 82 seconds to import and expose `/api/version`.
`windows_runtime.py` allowed only 60 seconds, so it terminated a healthy cold process. The outer
transaction timeout was too close to that inner boundary to preserve useful diagnostics.

**Fix/guard:** proxy readiness is bounded at 120 seconds and the outer updater command at 180
seconds. The final health/index/RRF checks are unchanged and remain fail-closed; a regression test
locks both limits. The failed deployment's automatic rollback is retained as positive evidence for
the whole-tree recovery boundary.
