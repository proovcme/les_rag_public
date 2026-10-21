# ADR-15 — Модель → RAG → результат модели → расчёт и XLSX

## 984 — пакетная идентичность операций

`admit_model_operation_batch` сравнивает полный canonical JSON вариантов одной
непустой operation_id, включая evidence, пояснения и типы значений. Все
различающиеся варианты остаются unapplied proposals; код не выбирает роль,
норму или последнюю строку. Буквальный повтор одной ID идемпотентен, пустые ID
самостоятельных операций не группируются. Общая проверка вызывается также
внутри транзакции `record_packet` при обоих режимах scope до разрешения source
conflicts и отметки pending operations отвеченными. Старое принятое решение
сохраняется, независимая допустимая операция того же пакета может быть принята.

Общий result/native контракт различает повторяемый source_row и однократную
непустую ID. Производный объём, в том числе кратность той же физической величины,
не подменяет исходные quantity/unit. Формула и числовой результат остаются
решением модели. Техническая однозначность не доказывает применимость нормы.

Существующий `stage_proof_operations` уже выдаёт непринятым строкам временные
адреса. После stage либо восстановления pending snapshot `_start_sheet_proof`
согласует native schema с этим же application-owned контекстом. Отдельный
`proof_operation_ids` расширяет только enum ID результата; work_row и
covered_by_work_id сохраняют известные исходные адреса и durable ID. Адрес
признаётся выданным по issued map и тому же буквальному source_row, не по
префиксу строки. Смешанный proof требует expected_revision только у durable ID;
непринятая операция не обязана придумывать сохранённую ревизию. Default без
proof IDs и прямой B0 не получают нового цикла или новых адресов. Native reads,
fallback и terminal extractor используют согласованную схему; перед admission
штатный restore снимает только действительно выданные временные ID.

## Кандидат 0.31.186 / 914 — контракт ВОР, транспорт запросов и возобновляемая ошибка

Тип документа объявляет модель. ВОР требует операции, единицы, объёмы и исходные основания; норма и цена не являются условием создания ВОР. Поля и проверка выбранных норм ЛСР сохранены. Транспорт допускает ровно один JSON-конверт модельных запросов рядом с отдельным объектом commentary: запросы, их порядок и повторы сохраняются дословно. Два конверта запросов, предметные sideobjects, дубли ключей, повреждённый JSON и конфликт artifact_kind отклоняются. При исчерпании технического исправления формата запросов владелец прохода приостанавливает своё durable-задание перед прежней SSE-ошибкой; идентификатор, исходник, принятые решения, кэш, контекст задания и остаток не заменяются. Присоединённый проход и чужие задания не меняются. Код не назначает операции, нормы, аналоги или профессиональные статусы. Финальный декодер ЛСР, расчёт, профиль, skill, retrieval, контекст и выходной лимит не изменены.

Точки изменения: model_lsr_result_field_instruction; decode_model_query_envelope; shared operation instruction; ветвь терминального отказа query-фазы в chat_evidence_application_service. BASE_FIELDS и SELECTED_NORM_FIELDS сохранены. Допуск commentary — lossless transport adapter, не восстановление повреждённой предметной таблицы. Техническая пауза не создаёт MISSING и не запускает новый предметный цикл.

Семипольные строки явно объявленной моделью ВОР принимаются также из Markdown и block text без norm_code. Сохраняются уже объявленные пустые поля этой ВОР; отсутствующие поля не добавляются. Для ЛСР, необъявленного, конфликтного или недопустимого типа прежнее требование norm_code не меняется. Это устраняет подтверждённое расхождение JSON и текстовых представлений, не назначая операции или нормы.

Frozen914 offline canonical gates PASS: 4153 passed, 20 skipped, 5 warnings in 265.14s (0:04:25); mail: 66 passed, 4 warnings in 6.47s; metadata: 31 passed in 4.38s.

Эти исправления закрывают воспроизведённые дефекты harness, но не доказывают правильность монтажных операций, норм или завершение длинного ответа. Требуются свежие установленные B0/B1 на целевой модели и независимая проверка фактически скачанных документов. Customer-ready=false: разные ВОР/ЛСР, 300+ строк, image/drawing/multi-document intake и точный Windows installer ещё не приняты.

## Candidate 0.31.182 / 910 — preserve available evidence during hydration

Build909 exact commit dff2c65a has canonical3889 passed/20 historical skips,
mail66 passed and metadata31 passed. Installed native RRF passed. Initial basic
smoke had one RAM-health failure at98%; the unchanged repeat after natural model
TTL expiry passed9/1WARN/0FAIL in60.99s. The same embedding revision received its
standard expired-capability refresh; answer bindings were not changed.

The failed908 SKS-to-VOR job now publicly repacks its34 saved model decisions,
without inference or changing durable decisions, held packet or50 remaining
addresses. The delivered workbook explicitly says VOR NOT FINISHED. This proves
recovery, not professional completeness. Fresh909 BAP comparison produced files
in143.67/175.27s, but confirmed money is0 in both. Baseline17 claimed EXACT rows
are not professional acceptance; candidate19 MISSING decisions do not close the
engineering task. Independent file review remains authoritative.

An actual same-query/budget replay proved a909 transport regression: hydrated
whole cards left7 inventory refs and7 admissible native READ refs, versus51 in
the original whole-preview page. Forty-four refs had become unavailable. Build910
compares both whole-page plans at the same budget and permits hydration only when
every legacy inventory and body ref survives. Otherwise it sends the entire
original preview page with explicit incomplete facts and guarded exact READs.
Literal queries, RRF order, aliases, resources, decisions, model/profile, source
frame0 and context limits remain unchanged. No semantic choice is made by code.

Fresh909 also demonstrated a query-transport error: a markdown result table and
its prose were accepted as35 search lines. Build910 treats a structurally formed
markdown table outside an explicit query envelope as an invalid query response,
preserves its literal raw text and reason, and uses the existing bounded format
repair. It does not invent queries or interpret table cells as searches. Explicit
JSON queries with commentary tables and supported literal list formats remain.

Receipt: artifacts/live_909/hydration_capacity_comparison.json. Frozen910 offline canonical gate PASS: 3922 passed, 20 skipped, 5 warnings in 258.14s (0:04:18).
Mail: 66 passed, 4 warnings in 6.64s; metadata: 31 passed in 4.45s.
All verify/architecture/map/docs/active-artifact checks passed. Installed same-model
B0/B1, professional varied-document tests and exact Windows installer acceptance
remain pending. Customer-ready false. Drawing/OCR,
ZIP/multiple-document engineering completeness and300+row acceptance are unproven.

Earlier entries retain their stated build/date scope.

## Candidate 0.31.181 / 909 — exact evidence and partial VOR delivery

Retained norm cards are mechanically hydrated after final ranking, from one read-only
normative-base snapshot. Query text, IDs, order, selected norms and decisions remain
model-owned. Actual normative SQLite bytes have their own SHA/basis; failed hydration
preserves the previous preview and expected generation separately. Full-card delivery
uses the existing budget. If the first full query group cannot fit, the complete old
preview page is retained with explicit incomplete flags and guarded native READ.
Full resources, zero consumption and more than sixteen resources survive exact reads.
The result instruction requires reading an available selected incomplete card before
declaring its composition unknown, and distinguishes individual norm codes and Qx.Hy
evidence references from table headings and document source IDs.

VOR query instructions no longer unconditionally demand norm search. Existing model
declaration {artifact_kind:vor,queries:[]} remains valid; code neither selects operations
nor suppresses model-authored queries. A failed late VOR turn can package previously
saved model rows only with an unambiguous model-declared VOR intent and explicit draft,
technical-error and remaining-source notices. Completed decisions are not rewritten;
failed/unprocessed rows remain visible in document-level diagnostics. No new inference
is made by partial packaging. Normal completed VOR behavior remains covered separately.

Exact wire token-count identity ignores the observed ephemeral /models created field;
model ID, root, provider, connection revision, wire hash and before/after guards remain.
Fresh env.example enables already-supported RTF/XLSM without altering existing custom
upload overrides. No dependencies, model roles, context limits or source-frame defaults
change. Source frame remains 0; cloud disabled. Installed live proof remains mandatory.

Installed 908 reference is exact commit14e35980: basic smoke9PASS/1WARN/0FAIL in99.34s
and native RRF PASS. BAP B0/B1 took125.84/180.67s with confirmed money0 in both;
neither produced a professionally substantiated estimate. B1 preliminary179640.65 is
not acceptance:63.88% belongs to an inapplicable walking/stop-bracket repair norm.
Independent judge:artifacts/live_908/acceptance/bap_independent_judge_908.json.
SKS-to-VOR control stopped after919.34s with no file:25/75 source locators accounted,
34 durable decisions; fourth query and repair both hit8192 output tokens. Quantities
were preserved, but wrong operations, parent links and norm references remain model
quality failures. Query input contained its actual12-row packet plus source headers;
whole-source oversize is not the measured cause. Independent judge:
artifacts/live_908/acceptance/sks_vor_independent_judge_908.json.

Both approved real RTFs upload through installed908 with unchanged source/text hashes;
their extraction limitations remain explicit. This proves transport, not engineering
completeness. OCR/drawing interpretation, ZIP/multi-document project intake, diverse
complete VOR/LSR and exact-installer acceptance remain unproven. Exact frozen909 offline canonical gate PASS: 3889 passed, 20 skipped, 5 warnings in 256.10s (0:04:16).
Mail gate: 66 passed, 4 warnings in 6.42s; metadata: 31 passed in 4.42s.
All verify/architecture/map/docs/active-artifact checks passed.
Installed B0/B1 and professional results remain pending. Customer-ready false; no public
release or guarantee for arbitrary missing/ambiguous source information is claimed.

Earlier entries record evidence at their stated build/date.

##908 — result and query contracts

The active result instruction distinguishes physical units from the norm's scale:
source quantity/unit stay unchanged; code applies the norm scale once. Resource
consumption needs the complete card or a formula with provenance. Query instructions
separate the pricebook's region/period from norm search, retaining actual FSNB edition
and conditions. No query rewriting, norm choice, inferred quantities or verdict change.
Ordinary tools-off final calls now expose their actual READ closure reason without
new inference or execution of printed XML. Generic decorated result headers are
parsed mechanically; absent source/evidence fields remain explicit structural gaps.


Installed professional proof is pending. Existing model choices and past artifact bytes are preserved.

Earlier entries record evidence at their stated build/date.

## Build907: experimental literal source frames

The complete-input route remains the default (`LES_CHAT_SOURCE_FRAME_ROWS=0`).
The optional `1..12` mode changes only technical source presentation: the original
file and whole catalog are retained, all exact locators are disclosed, the current
literal rows keep their headers/sections/values/formulas/notes, and the same
`read_source` reader can read every not-shown row during the answer phase.
The model authors all searches, engineering roles, norm choices and decisions.
No code summary, candidate norm selector or compulsory professional review is added.
The query phase has no native reader; its source contract says so explicitly.

Both B0 and B1 share the same first frame, question, model, scope and reader access.
Whole-job denominator and source bytes remain unchanged. Detailed immutable source
audit and hashes are stored separately from the lossless literal model rendering.
Frame mode, catalog identity and requested scope participate in new frame-job
identity; the default mode preserves prior identity. A plain continuation across
incompatible source-frame scopes fails visibly before model calls and preserves
the existing job/question/price basis. An explicit fresh question can start a new job.

This mode is an opt-in transport experiment until installed live comparison passes.
First-frame success does not close whole-document, professional norm, large-input,
diverse-format, complete-price or exact-installer acceptance. Full RAG payloads and
native tool exchanges are never clipped to make the experiment fit.

Статус: **принято** (2026-09-01).

Candidate **859**, установленный baseline **858**: изменения ниже ещё требуют
живой сравнительной приёмки точного candidate; локальные тесты не доказывают
профессиональную полноту ВОР/ЛСР.

В 859 модель может по собственной необходимости вызвать read-only native
tools внутри того же answer-хода: `read_norm_card`,
`search_pricebook_resources`, `read_resource_price`, `search_sources` с
`target=documents` и `read_source`. Это получение evidence до терминального
решения, а не обязательный selector, review или повторный профессиональный
цикл после ответа. Обычный итог без вызовов принимается сразу. B0_DIRECT и
candidate имеют одинаковые возможности такого чтения.

`read_norm_card_exact` читает только ранее показанный точный norm pointer;
возвращает все ресурсные строки с расходами/единицами, work steps, provenance
и явными признаками полноты. Несовпадающие key/code дают conflict без выбора
другой нормы. Документы читаются в явно выбранном scope, цена — в закреплённой
региональной/периодной книге. Чтение цены не подтверждает применимость ресурса.
Официальный pricebook reader кэширует snapshot по SHA-256 всех исходных bytes
и размеру; один path/mtime не подтверждает прежнее содержимое. Typed price
evidence повторяет exact file hash/name/size в теле и source_ref. Изменение
источника во время чтения или несовпадение с явно сохранённым task hash даёт
conflict, без выбора другой книги или изменения authored resource. Фактический
hash сохраняется в `price_basis` упаковки и document/job projection; continuation
той же literal книги проверяет его до расчёта и render. Замена bytes даёт
`PRICEBOOK_VERSION_CONFLICT` без нового artifact. Старый файл не архивируется;
legacy basis без hash не получает доказательство прошлой версии.
Фактически показанные тела и immutable aliases сохраняются в durable evidence
до следующего вызова модели. Registry повторяет дословное тело предыдущего
evidence; только доказанно одинаковые представления одной norm card с тем же
pointer/источником/редакцией разделяют тело. Недоступное тело обозначается
явно. Повтор одинакового чтения или нехватка окна приводит к технической
pause, не к MISSING нормы и не к подмене решения.

`model_lsr_result_contract` задаёт один условный контракт полей для таблицы,
подписанного текста и необязательного JSON. Для выбранной нормы нужны пять
флагов соответствия и coverage; для выбранного материала/оборудования —
`resource_code` с refs; для выбранного условия НР/СП — показанный
`nr_sp_rule_id`, иначе конкретный вопрос в open_gap. Эти поля сообщает модель;
код не назначает EXACT, ставку или соответствие. Delta-ответ может содержать
только новые/изменённые операции: существующая сохраняет `operation_id` и
`expected_revision` из показанной revision, новую revision назначает store.
Строка вне requested packet без известной identity, чужой ID/source или
переданная устаревшая revision сохраняется целиком как unapplied proposal,
не попадает в accepted rows и не теряется в аудите. Разные авторские операции
одного source locator не объединяются по названию или роли.

Кандидат983 версионирует управление технической revision в обычном model
transport: приложение захватывает immutable operation-ID/source/revision
snapshot предложенной области до ответа. После завершения ответа только для
точного ID и того же адреса оно связывает expected_revision с этим snapshot,
а не с более поздним latest state; сырые authored revision/base/expected
сохраняются в отдельном application audit. Норма, объём, роль, состав, ресурсы,
цитаты и другие предметные поля не меняются. Транзакция по-прежнему сверяет
expected с фактической durable revision, поэтому параллельное изменение не
перезаписывается. Новые/чужие ID и другой source не получают допуск.
Сравнение технических адресов использует прежний catalog canonicalizer;
авторский source_row результата не меняется. Для пустого набора обновлений
снимок/аудит сохраняются, но ненужная инструкция о ревизиях не занимает окно.
Pending proof хранит тот же snapshot; resume не реконструирует его из latest.
Для явно legacy pending без нового контракта и ручных API действует прежний
authored-CAS. Неполный или повреждённый новый snapshot — техническая ошибка.

С кандидата983 краткие перечни ВОР явно содержат поддерживаемые `coverage`,
`covered_by_work_id`, `evidence_refs`, на которые ссылаются требования
обоснования работ и связей. Native terminal schema ЛСР объявляет существующие
необязательные `calc_quantity`, `calc_unit`, `conversion_factor`,
`conversion_source`, `resource_code`, `resource_bindings`, `resource_review`.
Они не становятся обязательными; literal decoder и последующие guards прежние.
Устранение расхождения описания и schema не доказывает качество выбора модели:
для этого нужны установленный paired gate и проверка физического документа.

В983 существующий `read_norm_card` также принимает один буквальный полный
family-qualified `norm_code`, даже если общий поиск не показал эту карточку.
Это точное чтение выбранной моделью идентичности, не поиск аналога и не выбор
применимости кодом. Оно разрешено только в нормативном профиле; непоказанный
внутренний ключ, частичный шифр и смешанные селекторы такого допуска не получают.
Показанный pointer сохраняет прежние проверки источника и поколения без обхода.
Новый exact read требует passed manifest и сверяет SHA фактической SQLite до/после
чтения; изменение manifest или конфликт с уже показанным поколением не создаёт
пригодной карточки. Chunk проходит прежние binding/admission/delivery и получает
собственную ссылку. Он не выдаётся за ранее показанный pointer и не подтверждает
норму. RRF/CE, literal поисковые запросы и ресурсы карточки не переписываются.

При ещё не объявленном типе документа общий список полей ВОР показывается один
раз: повтор того же списка в вложенном контракте ЛСР удалён. Явный контракт ЛСР
по умолчанию сохраняет прежний текст. Это освобождает место для evidence при
неизменных budget guards; новые optional поля по-прежнему объявлены.

С 852 sheet-pass query/answer calls одновременно получают исходную задачу,
текущее сообщение и исходные строки с RAG evidence. Явные актуальные параметры
сохранённого задания имеют приоритет над прежними; literal question упаковки
и идентичность вызова не изменяются. Это пользовательский task context,
не профессиональное дополнение к retrieval query.
Пакет явно разделяет requested/reference source rows и показывает source
quantity cells; null/unknown не превращается в 0/1. Всё исходное evidence
сохраняется, авторские операции/роли не изменяются.

С 851 исходный target ВОР/ЛСР сохраняется в task_context.artifact_intent.
Plain resume не выбирает priced default; новый явно названный target имеет
приоритет. Предыдущие jobs дают родителя workbook revision, но не settled replay.
Пакет сохраняет дословные quantity-empty group descriptions текущего листа;
код не выбирает вид работ и не присваивает описанию количество варианта.

С 849 безопасная проекция workbook result сохраняет каждый vor_source_errors
locator (ограничивается длина сообщения, не число строк). Harvester/чат/readiness
видят те же замечания, что XLSX. Repack ВОР возвращает собственную vor readiness,
не проверки цен/норм ЛСР, без вызова модели и без изменения её решений.

С 848 одинаковые физические объёмы в простых/масштабированных единицах проходят
catalog→adapter→calculation без повторного деления. Подтверждённая колонка единиц
используется вместо поиска буквы в названии; авторские поля не изменяются.
VOR packager отдаёт приоритет готовым decisions над spec reader на всех форматах.
Материалы проверяются после результата, ошибки и open_gap сохраняются в самом
XLSX и vor readiness; приложение не выбирает монтаж вместо модели.

С 0.31.119 / 847 PDF layout и CSV source catalog сохраняют пустые ячейки
на исходных позициях. Построчное удаление пустых полей сдвигало количество
под заголовок массы/единицы и мешало принять правильный ответ модели.
Полностью пустые CSV-строки пропускаются без перенумерации остальных локаторов.
Это чтение доказательств; профессиональные строки и выборы модели не заменяются.

С 0.31.118 / 846 read-intake проверяет OOXML DOCX: контейнер только с
изображениями без текстовых элементов не принимается как прочитанный текст.
`chat_attachment_service.docx_is_image_only` и
`datasets._prepare_read_attachment` возвращают HTTP 422 с необходимостью OCR,
до сохранения вложения и до чата. Transitional/strict OOXML поддерживаются;
текст с картинками проходит штатно, altChunk не объявляется сканом без
прочтения его содержимого. Это проверка доступности входного текста, не
предметное решение и не автоматическое распознавание изображения.

Заменяет ADR-13 для активного продуктового chat/estimate-пути. Старые
`SmetaSession`, пошаговые tool-loop, R1/R2-review и mapping lock остаются только
историческими/экспериментальными контурами.

## Контекст

Живая Qwen 3.5 9B показала достаточный рабочий контур на реальной ВОР: модель
сама сформулировала запросы, сметный RAG вернул карточки выбранного датасета, та же
модель выбрала нормы, а штатный адаптер ЛЕС рассчитал и оформил XLSX.

Отказы создавались не моделью и не RAG, а промежуточной обвязкой: обязательными
JSON-планами, специальными status/decision-вызовами, фиксированным числом ходов,
повторными подтверждениями и потерей исходного вложения перед финальным вызовом.
Изолированные тесты эти пользовательские отказы не обнаружили.

## Решение

Активный путь один:

```text
исходный вопрос + полное вложение (по умолчанию) + явно выбранный датасет
  → та же модель формулирует любое необходимое число RAG-запросов
  → код буквально исполняет запросы через настроенный dedicated сметный RAG
  → код группирует profile-owned число карточек на запрос как Qx.Hy и сохраняет все группы
  → та же модель видит исходный ввод и весь возвращённый evidence
  → при необходимости сама запрашивает точные карточки/ресурсы/документы
    и получает их evidence в том же answer-ходе
  → модель обычным текстом выдаёт все профессиональные строки и решения
  → код механически читает строки из ответа, не меняя сам видимый ответ
  → код проверяет структуру/единицы/provenance, подставляет цены, считает
  → ЛЕС автоматически прикладывает XLSX к ответу
```

Число строк и запросов не ограничивается предметной константой: 7, 19, 30 или
иное фактическое количество обрабатывается одним и тем же контрактом.

До терминального результата модели код имеет право только:

- разрешить явно выбранный dataset scope;
- предоставить read-only RAG и буквально исполнить запросы модели;
- исполнить необязательное точное чтение evidence, выбранное самой моделью;
- вернуть evidence с координатами и сохранить trace;
- прервать только технически бесконечное исполнение.

До терминального результата модели код не имеет права:

- выбирать или переписывать запросы, нормы, аналоги, coverage и статус решения;
- заменять исходный файл сводкой или терять доступ к нему перед финальным вызовом;
- требовать специальный JSON-план как допуск к RAG;
- требовать JSON/schema или model tool-call для итогового ответа;
- навязывать R1/R2-review, mapping lock, подтверждение привязки или фиксированное
  число ходов/строк;
- считать обычный текст модели ошибкой протокола и поэтому не пускать её в RAG.

Для estimate-профиля имя сметной коллекции берётся из active base/runtime
configuration и может быть любым. Общий `les_rag` не является fallback: если
dedicated dense+sparse native RRF не готов, поиск блокируется явно, чтобы
смешанный пользовательский корпус не маскировал ошибку маршрутизации.
Model-authored query является инвариантом estimate workflow и применяется к
старым keep-state user-profile snapshots без изменения их prompt/skill.
Только профиль `estimator` маршрутизируется в карточки ФСНБ; обычный профиль с
model-authored запросами остаётся в явно выбранном пользовательском dataset.
Внутренний retrieval для одного запроса делает широкий native-RRF overfetch,
удаляет только точные дубли и ограничивает долю одного физического документа,
после чего передаёт profile-owned число результатов (заводской default 6).
Пул в 256–512 model-facing hits не создаётся. На этом bounded-пути также
не запускается document-router: каждый запрос модели сразу идёт в native RRF,
без отдельного JSON/LLM-вызова и без скрытого предварительного отбора документов.

После терминального результата модели код обязан послушно сохранить её выбор и
может выполнять только детерминированную работу: проверить ссылочную структуру,
совместимость единиц и provenance, получить цены ресурсов из выбранной либо
системной Сплит-формы, посчитать итоги и сформировать XLSX. Найденные конфликты
показываются в результате, но не дают коду права тихо изменить или удалить
решение модели.

Ссылочная проверка `work_row` требует существующего решения модели с ролью
`work`: одного совпадения с координатой исходника или материала недостаточно.
Материал со ссылкой на себя сохраняется в черновике, но не закрывает пакет.
Полный список незавершённых координат отделён от ограниченного списка замечаний
для отображения; лимит UI не скрывает строки при продолжении. Отчёт готовности
не считает сам факт сохранения строки доказательством
завершённости: `remaining_locators` сохраняет строки с дефектными связями.
Инструкция модели
разрешает вывести монтажные работы из спецификации по задаче и evidence, но не
требует отдельной нормы для каждого изделия и не заменяет этот выбор кодом.

Перед XLSX выполняется одна локальная проверка ссылочной целостности. Она не
вызывает модель повторно и не создаёт новый workflow-шаг: проверяются только
полнота `source_row`, отсутствие дублей, существование `Qx.Hy` и принадлежность
переданного `norm_code` указанной карточке. Проверка ничего не исправляет; при
ошибке она запрещает только ложный XLSX. Значения `source_row` и `norm_code`
парсер и расчётный адаптер больше не перенумеровывают и не вырезают регулярным
выражением. Конфликты упаковщика сохраняются рядом с готовым XLSX как `partial`,
а не маскируются внешним статусом полного успеха.

Если датасет не выбран, ЛЕС работает как обычный AI-harness без неявного RAG.

## Приёмка

Минимальное доказательство строится на живом пользовательском пути, а не на
изолированном mock-тесте:

1. Пользователь прикладывает реальный файл и явно выбирает один датасет.
2. Trace показывает запросы, написанные моделью для всех фактических строк.
3. Финальный model-call одновременно содержит исходный файл и RAG evidence.
4. Та же модель возвращает все строки без фиксированного лимита.
5. ЛЕС в том же ответе автоматически выдаёт рассчитанный XLSX.
6. Если подключена Сплит-форма, графы цен заполнены кодом с provenance; пробелы
   и конфликты видны и не переписывают модельный выбор.

Живая приёмка 2026-09-01 на изолированном dev proxy `8060` прошла с реальным
PDF: 19 строк/2366 символов без обрезки; Qwen 3.5 9B сформировала 11 запросов;
RAG вернул 11 групп по 6 карточек; answer context включил 6 блоков вложения и
все 11 evidence-групп без evidence omission; Qwen вернула 19 строк с 19
`norm_code` и 19 ссылками `Qx.Hy`; код самостоятельно вызвал упаковщик. Итоговый
XLSX содержит 17 `bound`, 2 `unit_conflict`, штатную базу цен Санкт-Петербурга
за II квартал 2026 года, 395 формул и формульную рассчитанную часть без НДС
3 564 688,87 руб. Установленные `8050/8051` не менялись.

Перед любой правкой chat/RAG/estimate автор обязан ответить «да» на три вопроса:

1. Финальная модель видит исходный ввод и возвращённый evidence одновременно?
2. Между моделью и RAG нет кода, принимающего профессиональное решение или
   запрещающего доступ из-за собственного orchestration-протокола?
3. Живая приёмка доказывает пользовательский ответ и файл, а не только зелёные
   внутренние тесты?

## Следствия

- `build_lsr_workbook_from_decisions` является пост-модельным адаптером, а не
  сметным мозгом.
- Автоматическая выдача XLSX и подключение pricebook входят в один
  пользовательский запрос; внешний ручной вызов адаптера является только
  диагностикой.
- Любая новая обязательная профессиональная стадия до результата модели требует
  нового ADR и прямого одобрения владельца.

## Перекрёстная ссылка: ADR-16

[ADR-16](ADR-16-systematic-candidate-retrieval.md) сохраняет историю разрешённых
28.09.2026 системных запросов. В кандидате975 это исключение отозвано:
все новые запросы активного chat/estimate пути, включая B0_DIRECT, формулирует
модель. Код не добавляет `original`/`derived` группы и не меняет её решения.
Прежние evidence/квитанции сохраняются; границы lineage и ценового provenance
из ADR-16 не отменяются. История приёмок остаётся историей, а новый candidate
требует собственного установленного сравнения, не только offline GREEN.
