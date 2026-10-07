# Unified Construction Harness — Failure Ledger (v0.8)

## Кандидат 0.31.190 / 918 — передача результатов поиска и черновик из контрольной точки

Установленная917/7db62228 прошла4240 офлайн-тестов и RRF1/1. Release basic smoke
показал8 PASS/1 WARN/1 P1 FAIL; отдельный сохранённый повтор того же вопроса завершился
за19.45с. Это не заменяет первоначальный отрицательный smoke и не доказывает качество сметы.
Свежий БАП B0 на той же FreeToken:r8/CAS46 с reasoning-copy e951 завершился за144.22с
без файла: модель запросила10 дополнительных поисков, подготовлены60 карточек, но
следующий model wire не отправлен из-за evidence_read_capacity (235187 > 46171).
Причина: exact_card_read у hydrated search результата ошибочно делал полное непрочитанное
тело обязательным. Входной query завершён:4369 tokens/stop; увеличение query reserve
не исправляет этот сбой. Professional acceptance917=NOT_RUN_NO_DOCUMENT.

918 различает доступность точной карточки и её чтение: prepared search_sources
оставляет весь inventory и целые discovery groups, а тела допускаются по ёмкости.
Явные read_norm_card/read_resource_price/read_source, required refs и уже переданные
тела сохраняются обязательными; raw bytes, aliases, source identities и native tool
exchange не переписываются. Нормы и профессиональные решения по-прежнему выбирает модель.

Если следующий query завершился typed ModelQueryFailure после собственных durable
решений, действующий расчёт/export выдаёт честный partial-документ без новой генерации.
Исходная task identity/price basis, pause/held packet, все never-reached листы и lineage
сохраняются. Ошибка без принятых решений остаётся ошибкой; private failure payload
не переносится в публичный ответ. Повторная упаковка не принимает новых решений модели.

Регрессии: tests/test_model_discovery_read_admission.py и
tests/test_model_query_checkpoint_draft.py. Предыдущая профессиональная приёмка916
отрицательна: неверные norm/card bindings и повторная покупка сохраняемых материалов.
Новые технические тесты этого не отменяют. Exact desktop installer918 ещё не проверен;
установленный EXE остаётся5.1.813. Customer-ready=false до свежей приёмки физических документов.
Frozen918 offline canonical gates PASS: 4268 passed, 20 skipped, 5 warnings in 270.95s (0:04:30); mail: 66 passed, 4 warnings in 6.21s; metadata: 31 passed in 4.45s. Установленная live-приёмка ещё требуется.


## Кандидат 0.31.189 / 917 — полные карточки на прежней частичной странице

Установленная916/11ca92ca прошла4227 офлайн-проверок, RRF1/1 и basic10/10,
но профессиональную приёмку не прошла. БАП B0 завершился MODEL_RAG_QUERY_LIST_EMPTY;
B1 доставил19 исходных работ за410.48с, сохранив объёмы и СПб/3кв2026.
Подтверждённая сумма0, предварительная185742.54; шесть шифров расходятся со своими
цитируемыми карточками. Задание осталось paused на PDF_TEXT!R1: модель предложила
несколько альтернативных JSON и новые операции из реквизитов, предложение целиком
не принято. Отсутствие этих операций в XLSX не доказывает правильную классификацию
моделью. СКС→ВОР B0 также не дал принятого документа. Готовность заказчику=false.

Причина пропуска транспорта доказана тремя сохранёнными страницами БАП: all-inventory
не прошёл reserve, а полный typed-body trial был связан с успехом all-inventory.
Теперь один exact bound-wire trial полных тел уже показанного whole-group frontier
допускается и на прежнем partial inventory после отказа по ёмкости. Сохраняются
ordered inventory/unshown/deferred refs, показанные превью как буквальные префиксы,
пустые группы запросов, hidden bodies, original ceiling, READ reserve и владелец
счётчика, включая owner отвергнутого inventory probe. Unknown/changed owner,
небезопасная hydration или non-fit сохраняют прежний wire. Подбора норм кодом,
поэлементного greedy selection и дополнительных генераций модели нет.

Регрессия: tests/test_model_partial_inventory_complete_frontier.py; до правки8 FAIL,
после правки39 PASS вместе с соседними initial inventory/frontier suites.
Frozen917 offline canonical gates PASS: 4240 passed, 20 skipped, 5 warnings in 289.19s (0:04:49); mail: 66 passed, 4 warnings in 6.99s; metadata: 31 passed in 4.48s. Установленная live-приёмка ещё требуется.


Candidate916 final scope: exact complete typed bodies are offered only when the whole bound wire fits without changing the original ceiling, READ reserve or shown frontier. The model receives explicit source-context role instructions; code does not invent or classify operations. The first-scope4210PASS proof excludes these final additions; artifacts/gates_916_final is the required final gate. Installed915 live control failed professional acceptance despite complete file delivery (BAP: wrong norm/card bindings, double-counted retained materials and fictitious operations from context; SKS:18 material parents lacked operations). Customer-ready=false until fresh installed physical-document checks pass.


## Кандидат 0.31.188 / 916 — полная подача указателей и контекст технического повтора

Установленная 915/b648808b прошла RRF 1/1 и basic smoke 10/10. Обычный GUI-фактор системных запросов кандидатов включён; модель FreeToken:r8/CAS46, профиль и фактические 65536 токенов сохранены. БАП B0 за223.22с не создал документ: 8192-token незавершённый JSON запросов, затем ответ по существу вместо поисковой декларации. БАП B1 за331.83с создал одну ЛСР из22 строк модели; это техническая доставка, не доказательство применимости норм. СКС→ВОР B0 за355.98с создал122 строки (70 материалов,52 работы): все70 товарных позиций сохранены, но18 связей ведут к отсутствующей работе. Независимая профессиональная приёмка ВОР отрицательная (artifacts/live_915/acceptance/freetoken_sks_vor_baseline_independent_judge_915.json). Структурный draft=false не означает профессиональную полноту.

Первичная подача evidence пробует целый расширенный inventory по exact счётчику установленного подключения и прежнему запасу READ. Состав прежних показанных тел, метаданные, порядок запросов/рангов и исходный admission ceiling сохраняются. Если измерение недоступно, владелец подключения изменился либо пакет не помещается, исходные page/messages/packing остаются прежними. Это доставка найденных источников, не переподбор норм.

Единственный существующий технический повтор поиска получает полный видимый отклонённый ответ модели как DATA вместе с finish_reason и реальными ошибками разбора. Скрытые рассуждения и секреты исключены. Исходник, профиль и область не заменяются; потеря ранее показанного исходника либо переполнение дают явный отказ вместо усечения. Новых циклов и прямых модельных HTTP-вызовов нет; предметные решения модели код не меняет.

Frozen916 offline canonical gates PASS: 4227 passed, 20 skipped, 5 warnings in 268.05s (0:04:28); mail: 66 passed, 4 warnings in 6.48s; metadata: 31 passed in 4.39s. Установленная live-проверка и профессиональная приёмка916 ещё требуются; customer-ready=false.

## Кандидат 0.31.187 / 915 — авторские заголовки и сохранение характеристик поиска

На установленной 914/39cb94b5 FreeToken:r8/CAS46 восстановлен до фактических 65536 токенов: KV65536, MoE4025, Mamba24; роли, профиль, данные и существующие задания сохранены. Свежий БАП B0 закончился за177.95с без XLSX: четыре объявленных моделью header с quantity=0 ошибочно проверялись как работы и получили source_quantity_unconfirmed. B1 выдал файл за193.86с: 19 работ, 12 позиций, подтверждённая сумма0, предварительная781638.43. Шифры совпадают со своими сохранёнными карточками, но применимость не подтверждена: отдельному БАП предложен целый светильник, грунтовке — окраска, стеклохолсту потолка — обои стен. Полных карточек показано0, native READ0. Отрицательная профессиональная приёмка сохранена в artifacts/live_914/acceptance/freetoken_bap_independent_pair_judge_914.json; projection-correction уточняет, что durable job сохраняет gap_reason.

model_rag_row_kind уважает явно объявленный header и не проверяет его как работу; числовой ноль без роли не объявляется заголовком. Строки, количества, нормы и оценки модели не переписываются, проверки объёмов настоящих работ остаются блокирующими. Фильтр служебных колонок ADR-16 сравнивает денежные слова и полные порядковые заголовки: группа грунта, шифр, масса, условия, количество и номер изделия больше не теряются по подстроке. Штатный поиск, его происхождение и границы не изменены; переключатель системных запросов не активирован. SKILL согласован с принятой ограниченной поправкой ADR-16.

Frozen915 offline canonical gates PASS: 4185 passed, 20 skipped, 5 warnings in 264.86s (0:04:24); mail: 66 passed, 4 warnings in 6.31s; metadata: 31 passed in 4.47s. Установленный контроль исправления и независимая профессиональная приёмка ещё требуются; customer-ready=false.

## Кандидат 0.31.186 / 914 — контракт ВОР, транспорт запросов и возобновляемая ошибка

Установленная 913/c3391515: 4076 canonical tests (20 исторических skips), mail 66, metadata 31, RRF 1/1, basic 10/10. Gemma реально использовала 65536 контекста на GPU. Свежие БАП B0/B1 получили все 120/120 и 156/156 указателей, но 0 полных карточек и 0 native READ; оба выданных файла профессиональную приёмку не прошли. СКС→ВОР B0 видел все 75 исходных адресов, однако ответ исчерпал выходные 8192 токена и оборвал JSON; 52 законченных предложения в префиксе не были принятыми строками, монтажных работ там 0. СКС B1 завершился с MODEL_RAG_QUERY_LIST_EMPTY: модель дала запросы, но второй ответ состоял из отдельного commentary и единственного конверта с 8 запросами; reader отклонил такой транспорт. После терминальной ошибки принадлежащее контролю задание осталось running при нулевой очереди. Answer-thinking B0/B1 исчерпали выходные 8192 токена без финального ответа; доля reasoning tokens неизвестна. Все отрицательные receipts сохранены.

Тип документа объявляет модель. ВОР требует операции, единицы, объёмы и исходные основания; норма и цена не являются условием создания ВОР. Поля и проверка выбранных норм ЛСР сохранены. Транспорт допускает ровно один JSON-конверт модельных запросов рядом с отдельным объектом commentary: запросы, их порядок и повторы сохраняются дословно. Два конверта запросов, предметные sideobjects, дубли ключей, повреждённый JSON и конфликт artifact_kind отклоняются. При исчерпании технического исправления формата запросов владелец прохода приостанавливает своё durable-задание перед прежней SSE-ошибкой; идентификатор, исходник, принятые решения, кэш, контекст задания и остаток не заменяются. Присоединённый проход и чужие задания не меняются. Код не назначает операции, нормы, аналоги или профессиональные статусы. Финальный декодер ЛСР, расчёт, профиль, skill, retrieval, контекст и выходной лимит не изменены.

Семипольные строки явно объявленной моделью ВОР принимаются также из Markdown и block text без norm_code. Сохраняются уже объявленные пустые поля этой ВОР; отсутствующие поля не добавляются. Для ЛСР, необъявленного, конфликтного или недопустимого типа прежнее требование norm_code не меняется. Это устраняет подтверждённое расхождение JSON и текстовых представлений, не назначая операции или нормы.

Frozen914 offline canonical gates PASS: 4153 passed, 20 skipped, 5 warnings in 265.14s (0:04:25); mail: 66 passed, 4 warnings in 6.47s; metadata: 31 passed in 4.38s.

Эти исправления закрывают воспроизведённые дефекты harness, но не доказывают правильность монтажных операций, норм или завершение длинного ответа. Требуются свежие установленные B0/B1 на целевой модели и независимая проверка фактически скачанных документов. Customer-ready=false: разные ВОР/ЛСР, 300+ строк, image/drawing/multi-document intake и точный Windows installer ещё не приняты.

## Кандидат 0.31.185 / 913 — явный контекст в пределах наблюдаемой ёмкости

Установленная912/dd42132e прошла4056 canonical tests (20 исторических skips), mail66, metadata31, RRF1/1 и basic10/10. Карточка прочитана с7/7 правильными расходами, но native READ не доказан. Свежий БАП B0 завершён за76.5с: 19 решений,0 норм,0 денег. Все21 модельных запроса исполнены, однако answer видит16/126 identities,6 previews,0 полных карточек; reserve для native growth0. B1 завершён за169.19с с файлом, но профессиональную приёмку не прошёл. Сохранены отрицательные receipts в artifacts/live_912. Явное requested65536 при observed262144 ранее давало effective32768.

Явный положительный запрос контекста подключения ограничивается наблюдаемой ёмкостью backend, затем ограничениями workflow. Фабричный предел 32768 без явного запроса сохранён; неизвестная ёмкость, tools, batching, reasoning и output guards не меняются. Настройка и effective value остаются публичными. Модель, профиль, запросы, порядок RRF и предметные решения не изменяются.

Frozen913 offline canonical gates PASS: 4076 passed, 20 skipped, 5 warnings in 259.17s (0:04:19); mail: 66 passed, 4 warnings in 6.36s; metadata: 31 passed in 4.38s.

Больший контекст не доказывает достаточную GPU память или правильность сметы. После offline gates требуются установленный контроль effective/wire/GPU, свежий B0/B1 и профессиональная проверка выданных файлов. Customer-ready=false; 300+ строк, разные документы и точный Windows installer ещё не приняты.

## Candidate 0.31.184 / 912 - optional export declaration in model queries

Query JSON accepts queries without an artifact_kind for source questions; explicit model vor/lsr declarations and strict invalid-metadata checks remain. Bound profile/skill and literal searches are preserved. Frozen912 offline canonical gates PASS: 4056 passed, 20 skipped, 5 warnings in 256.51s (0:04:16); mail: 66 passed, 4 warnings in 6.27s; metadata: 31 passed in 4.40s. Customer-ready false.
Actual911 no-source READ received a model query lsr declaration, re-enabled the carrier and returned8 rows with fabricated resource quantities. The query-format constraint is corrected generally; the original negative is retained as confounded. Fresh native READ is required.

Candidate911: model-declared VOR preserves admitted work with visible source/citation issues; query metadata stays outside searches. LSR/identity/tail guards unchanged. Professional and installed acceptance pending; customer-ready false.
Frozen911 offline canonical gates PASS: 4031 passed, 20 skipped, 5 warnings in 258.34s (0:04:18); mail: 66 passed, 4 warnings in 6.39s; metadata: 31 passed in 4.48s.
Actual failures: frame3 declaration executed as a query; SKS derived installation quantities excluded. Local regressions do not establish professional applicability or verified derivation.

Earlier entries retain their stated build/date scope.

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

## Candidate 0.31.180 / 908 — quantity instructions, result transport and RTF

The active result instruction distinguishes physical units from the norm's scale:
source quantity/unit stay unchanged; code applies the norm scale once. Resource
consumption needs the complete card or a formula with provenance. Query instructions
separate the pricebook's region/period from norm search, retaining actual FSNB edition
and conditions. No query rewriting, norm choice, inferred quantities or verdict change.
Ordinary tools-off final calls now expose their actual READ closure reason without
new inference or execution of printed XML. Generic decorated result headers are
parsed mechanically; absent source/evidence fields remain explicit structural gaps.

RTF uses strict structural admission and a bounded hidden OS text reader. Converter,
upload, catalog, authored VOR packaging and existing UI pickers share this intake.
Verified table cells are literal; ambiguous tabs stay one-cell text rows. Native-text
offsets have their own basis, never original RTF-byte offsets. All extraction warnings
and source hashes survive to readers, frames, workbook and readiness; VOR source gaps
are partial in both the first result and durable replay. Empty optional offset metadata
does not change existing 907 frame bytes/hashes. No dependencies or model roles change.

Installed 907 measurements remain the pre-change reference. First-six BAP B0 took
49.23s, returned 8 decisions (6 works + 2 materials), confirmed money zero. Whole B1
took 421.28s and returned 20 decisions, zero EXACT; 19 source work locators were
accounted, PDF_TEXT remained open. Its preliminary 1,132,660.15 is not an accepted
estimate: 89.82% comes from an inapplicable glass fireproofing analogue for film cover.
Full-input B0 took 164.5s, 19 decisions/one EXACT, confirmed zero. A separate isolated
temperature-zero B0 took 63.97s, returned a real but structurally deficient Markdown
table and no file. Neither thinking, temperature-zero nor six-row input has proved
professional readiness. Source-frame factor 0 and the original active profile are
restored; no cloud calls. Basic 907 smoke is RED: history835 returned printed XML
after repeated_read_batch despite available context, not a timeout or missing evidence.

Local RTF probes preserve both approved originals: LVS has 831 ambiguous literal
text rows; KFIS has 2,433 verified table rows/25,148 cells. Both retain merge/tab/line
limitations and source_extraction_complete=false. These are intake measurements,
not accepted engineering VOR/LSR. OCR/drawing interpretation, ZIP project intake,
full pricing and diverse/big-document professional acceptance remain unproven.
Exact frozen 908 offline gate PASS: 3835 passed, 20 existing skips, 5 warnings in 253.98s.
Separate mail gate: 66 passed, 4 warnings in 6.52s; metadata:31 passed.
Both original approved RTFs passed atomic native-buffer/SHA checks, one read each;
extraction limitations remain explicit. Installed live controls are pending. Customer-ready false;
no public release or exact-installer acceptance is claimed.

Earlier entries record evidence at their stated build/date.

Exact frozen907 R2 offline gate PASS: 3751 passed, 20 skipped, 5 warnings in 241.75s.
Metadata31PASS; exact separate mail gate: 66 passed, 4 warnings in 6.37s.
Version/compile/collect/architecture/map/docs/active-artifact gates PASS;
foreign TEST_INVENTORY bytes preserved. Initial907 RED is retained:3old assertions
required the prior unconditional query-only phrase. They were replaced by4stronger
actual-request checks for both supported carriers and exact technical-stage scope;
query/evidence/history/model-call/inference assertions remain. Independent review
and267normal focused tests PASS. No tests were skipped to close these failures.
Installed907 source-frame/whole-document live comparison, professional applicability,
complete resource pricing and exact Windows installer/UI acceptance are still pending.
Customer readiness is not inferred from this offline gate. New nativeRTF parser is
unwired and excluded from907; two actualRTFs retain explicit merge/tab/line limitations.

##2026-10-06 - query persona leakage / source pressure / initial READ deadline

The query phase now has a consistent technical contract: the unchanged bound
profile/skill applies to the final operator answer; this call emits only model-authored
retrieval queries, as one optional queries envelope or literal lines. Primary, repair
and continuation prompts agree. No query rewriting/filtering, mandatory JSON plan,
norm selector, new retrieval route or native query-phase reader is introduced.
Initial selector calls are also recorded in the existing actual-model-call ledger;
the previous final/continuation-only count understated the number of provider calls.
Initial ordinary READ admission also rechecks the original deadline after model
selection and before each cached/executed READ; matching blocked replies preserve IDs
and do not acquire citations. WRITE packaging is unchanged. Late906 READ continuation
retains its original budget/deadline/executor and provider-native-only boundary.

An opt-in GUI-registered source frame (LES_CHAT_SOURCE_FRAME_ROWS=0 by default)
offers1..12 literal source rows with exact headers/sections and a complete address
inventory. Original source bytes and full reader access remain; B0/B1 share the first
frame. Detailed immutable audit and literal model rendering are distinct and hashed.
Whole-job coverage uses the complete original catalog. No unshown row is called read
or decided. Mode0 retains previous job identity; frame scope is durable, and a plain
continuation across changed frame contracts fails visibly409 before model calls.
An explicit fresh question can start a separate job. SKILL and ADR15 describe this
experimental transport contract, including the absent query-phase native reader.
Frame size/row count and helper tests do not prove speed or professional coverage.
Actual approved ВОР.xlsx measured439catalog rows/394candidates: complete legacy
selector164566UTF8bytes versus6-row model-frame selector22502bytes. Original source
SHA is unchanged; this is a source-wire measurement, not an inference speed test.

Installed906/0.31.178/94e988b5 exact owned runtime hashes and native RRF PASS.
Frozen906 offline:3653PASS/20existing opt-in skips/5warnings; metadata31PASS.
The one default basic smoke remains RED: project chat HTTPReadTimeout at90015ms;
its failed receipt is retained, and no90s threshold is weakened. A separate ordinary
turn completed59.31s with a genuine provider-native late READ and final stop;
this proves completion of that boundary, not that the failed smoke was repaired.
The initial READ deadline regression is independently reproduced in two actual-flow
tests; it is not asserted to explain the90s client timeout.

Original905 BAP B0/B1 each returned19rows and a downloadable partial XLSX, with
confirmed0 and preliminary82690.88/66674.14. B0 submitted119accepted literal queries,
including public prose/tables from a conflicting query prompt. Separate unactivated
thinking-profile B0/B1 took368.69/415.95s and exhausted16384answer tokens without XLSX.
Thinking alone and a larger model were not proven fixes.907 tests the measured query
phase conflict and literal source presentation on the unchanged original local model.
Native exact norm reads, professional norm applicability, complete pricing, big VOR,
diverse artifacts and exact Windows installer/UI acceptance remain required.
Image-only DOCX, RTF/ZIP and drawing extraction have no accepted end-to-end proof.
Windows OCR on a604x809image failed both original and one4x attempt (0/5manual checks);
no noisy OCR text is promoted to source evidence. No cloud/model/dependency change.
Customer-ready false;907 installed live comparison pending. No public release.

Exact frozen906 offline gate PASS:3653tests/20existing opt-in skips/5warnings,
279.69s; metadata31PASS. Version/compile/collect/architecture/map/docs/active-artifact
checks PASS; foreign TEST_INVENTORY raw bytes preserved. Installed906/live ordinary
continuation remains pending, so measured905 failure is not yet claimed closed.
The unactivated reasoning profile BAP B0 (same source/r8/task/dataset) took368.69s:
query4194tokens; answer exhausted16384output tokens without a final public table,
no downloadable XLSX. Profile/source/connection identity unchanged. Enabling thinking
alone is not a proven quality fix. Its same-profile B1 measurement is still running.

##2026-10-06 - ordinary tool-off boundary and rounded FSEM aggregate

Installed905/0.31.177/c13375ab has exact runtime hashes and native RRF PASS.
Final frozen905 canonical gate:3620PASS/20existing opt-in skips/5warnings;
metadata31PASS and all compile/collect/version/architecture/map/docs/artifact gates.
BAP same original profile/r8/task/source/dataset: B0 240.16s,19accepted rows,
one24262byte XLSX, confirmed0/preliminary82690.88; B1 370.28s,19accepted rows,
one27821byte XLSX, confirmed0/preliminary66674.14. Both remain partial; B1 has
4EXACT/4analogue/8needs-research/3missing, no native exact-card reads, and one raw
PDF_TEXT page block unfinished at8192output tokens. This is not full norm acceptance.
Ordinary installed905 control44.74s (history826) ended MODEL_OUTPUT_INCOMPLETE:
two web_search requests appeared as text with two READ calls still available,
but the final answer had tools disabled. Build906 addresses that measured boundary.
Reasoning-profile B0/B1 comparison, diverse artifacts/VOR, large VOR, complete resource
pricing and exact Windows installer/UI acceptance remain pending. Customer-ready false.
Image-only DOCX, RTF and ZIP members have no accepted end-to-end input proof; PDF
text extraction alone does not prove drawing/geometry completeness. No public release.

Ordinary final answers retain the original allowed READ schemas while the same
research budget and deadline permit them. Only provider-native calls are executed;
XML/text frames remain diagnostic output. The existing executor/cache/scope and bound
connection revision are reused. Entire batches pass schema/effect/ID/budget preflight
before execution. Each READ checks the original deadline; expired calls receive
matching blocked replies without execution/cache/source citations. Complete native
exchanges retain original IDs, arguments and source payloads. No budget reset, query
selector, model-authored query rewrite or second smeta workflow is introduced.
One tools-off final render closes an exhausted/expired/already-continued exchange;
unfinished final output does not trigger another READ loop. Context overflow and
revision change remain explicit; cancellation propagates. SSE publishes only the
completed public final answer. 15 new actual-flow regressions; 454 focused PASS;
independent review15PASS. Exact canonical906 PASS; installed live controls pending.

FSEM machine crew hours and source tariff codes compute machinist labour as
machine quantity x crew hours x hourly tariff, using raw Decimal quantities without
blanket rounding/scaling or a fitted tolerance. Anonymous unpriced labour aggregates
are retained in audit and never double charged. Existing explicit machinists/prices
are preserved; unknown/invalid mapping stays unresolved. If derived hours differ
from the norm aggregate, priced components are preliminary and the position keeps
fsem_aggregate_discrepancy / needs_fsem_resolution. The source/edition discrepancy
is not repaired by entering a price and never yields false confirmed readiness.
Regression fixture0.02+0.002machine hours yields0.022derived crew hours, while the
source aggregate0.02 remains an explicit reconciliation blocker. 172 focused PASS.
Primary basis:421/pr amended55/pr, paragraph80 formula1.2;916/pr paragraphs78-79.
577/pr Appendix15 is not a blanket licence to round imported resource quantities.
No normative data, authored choices, provider, dependencies or runtime factors changed.

## 2026-10-06 — malformed result field and lost terminal tool frame

Installed904/0.31.176/e916c68f, guarded patch18.44s, exact runtime hashes PASS.
Native RRF post-ship smoke PASS; basic smoke retained RED:8PASS/1WARN/1P1FAIL,
MODEL_OUTPUT_INCOMPLETE on the ordinary unscoped boiler-room question (history823).
Ordinary provider ended stop/49tokens with a textual tool frame; its original content
was discarded by the existing guard, so the requested tool cannot yet be proven.
BAP B0 (same original question, attachment, profile and r8):143.30s, no file;
structural_error. Two rows copied the instruction's pseudo-label as invalid JSON;
other rows invented source_file_id#Rn locators that were never issued.
BAP B1:344.03s, one12662byte draft (SHAa3dc83f9),12/20input rows accepted,
11work/1material,1position/0calculated, confirmed0/preliminary0. Ten EXACT claims
include unissued Q2.H1-H10 citations. The initial query repeated the user task;
later Q2 pointers belong to a different PDF_TEXT pass and cannot ground earlier choices.
Neither control invoked native exact-card reads or the live wire token counter.
Measurement completion is not professional acceptance. Customer-ready remains false.
Large/diverse VOR, artifact-to-VOR, complete norm/resource pricing, FSEM precision
and the exact new Windows installer remain unaccepted. No public release.

The model-result field instruction now names real row_role/resource_code fields
and requires copying the displayed source coordinate literally. No JSON-only format,
decoder repair, source rewrite or professional decision is introduced.
The query instruction no longer promises automatic per-row searches that are disabled.
Model-authored query execution and candidate choice stay unchanged. The carrier's
rows-first rule is clarified as terminal-result ordering after requested reads,
not a requirement to terminate before using available tools. This clarification
is not a proven causal explanation of the model's failure to read norm cards.
On the existing terminal-tool guard, diagnostics preserve full public provider text,
its UTF-8 SHA/byte count, finish reason, native call names/argument hashes and known
research shortlist/remaining budget. Human notice, status and tool execution remain
unchanged. Reasoning/native argument values are excluded; raw audit output is neither
streamed as an answer nor fed into dialogue memory or executed as another tool call.
Focused producer71PASS and actual-chat/diagnostic adjacent265PASS; canonical905 pending.
Installed/live905 pending. There is no claim that these fixes establish norm quality.
First frozen905 canonical gate PASS:3587 tests/20existing opt-in skips/5warnings;
all structural/doc/version/map/active-artifact gates PASS, metadata31PASS.
Independent replay found a temporal binding defect: an unissued early Q2.H1 could
be populated from a later packet's different card. The delivered B1 draft remained
unpriced, but prior structural facts and a subsequent validator could promote the alias.
Trusted first-bind now fixes application evidence maps using that model frame;
replay and final validation never fill empty/partial saved maps from future aliases.
Historic model-job packaging projects absent maps to visibly unresolved bindings,
preserving durable rows/SHA and operation IDs. A technical packaging cache miss is
allowed; no professional choice or saved job is rewritten. Direct operator rows unchanged.
Model-authored debug fields remain outside the decoder whitelist. No identity migration,
new marker, late-evidence lookup, model loop, norm choice or price substitution is added.
The second frozen905-r2 gate found one existing nested resource-map replay regression
(3614PASS/1FAIL/20existing opt-in skips). One-line correction recognizes a saved
nested application map as replay even without the top-level map;110 focused tests PASS.
Interrupted SSE first-follow also omitted file registration on terminal/paused state
and left sending active. Existing history/file registration and terminal plans now
restore downloads and settle send/stop controls without reload or a model call.
The third exact frozen905-r3 canonical gate PASS:3620 tests/20existing opt-in
skips/5warnings; metadata31PASS. Compile/collect/version/architecture/map/docs/
active-artifact checks PASS; untouched TEST_INVENTORY raw hash unchanged.
UI focused183PASS. Installed live comparisons remain pending. No customer-ready claim.


## 2026-10-06 — false source coverage / strict SI conflict / dropped discovery bodies

Installed903/0.31.175/b06d47bd, exact owned runtime hashes PASS; rollback902 retained.
Ollama was stopped: initial native RRF failed and BAP B0 used degraded_sparse_only.
After starting the existing embedding service, the unchanged native-RRF probe PASS/5hits.
BAP B0 delivered one41499byte XLSX in172.31s (SHA58af71cc):25authored rows,
19work+6material,17positions/1calculated, preliminary146244.46/confirmed0.
All19 PDF rows used the manifest's actual source_file_id!Rn: rejected aliases caused
false source coverage gaps. The catalogue lookup fix resolves them without rewriting rows.
Six materials lack explicit work_row; PDF_TEXT!R1 lacks a model decision. Genuine gaps remain.
B1 paused118.86s before rows/file: required context estimate52599 >46171, after
seven actual price searches. Discovery bodies Q1.H1-H6 had been dropped from replay.
Preserving them increases the estimate, so preserve-only is not a capacity proof.
903 is not customer-ready. Fresh healthy installed B0/B1, diverse inputs, large VOR,
professional norm/resource completeness, FSEM0.02/0.022 and fresh installer remain open.

Trusted source_catalog resolves only actual issued file-ID row aliases that
uniquely exist in the original catalogue. Raw source_row/evidence/operation_identity
are preserved; foreign/ambiguous/malformed aliases remain rejected. Both chat callers,
public repack, readiness and RIM receive the actual catalogue, loaded once by the adapter.
The selected book's price converts only explicit single SI units t/kg and km/m,
before rounding, including base/current/effective prices but never index or quantity.
Conversion provenance retains original price/unit, factor/formula, resource/book SHA,
region/period. Other dimensions, bulk units, price conflicts and nonfinite results stay blocked.
Confirmed discovery bodies remain required in every later read frame, whether cited
or not; unread inventory remains unread. Deferred retained-body delivery is recognised
downstream without modifying historic flags or upgrading a preview to a complete card.
Whole-wire admission can use a strict counter of the actual bound model including
tools; generation and safety reserves stay unchanged, schemas are not subtracted twice.
Unsupported/unverified counters retain the conservative fail-closed admission path.
Every recorded canonical response now preserves nullable provider usage and
canonical_request_sha256 (actual model identity included; not HTTP-byte SHA).
The local count binds loaded model identity across every probe, with a total15s deadline.
Measured native frames pin the same connection revision for generation; a changed primary
or fallback is a visible technical failure, not generation using another tokenizer.
Assembly checks strict book unit compatibility again after literal SI conversion.
workbook_result now clarifies that structured export rows precede operator commentary
in every supported format; saved profile bytes and explicit user format stay unchanged.
Both B0/B1 receive the same purpose-scoped clarification. Its live efficacy is not proven.
No norm, resource, query, professional verdict, coefficient or attachment text is selected
or corrected by this transport/calculation patch.
Canonical904-r3:3575PASS/20existing opt-in skips/5warnings; metadata31PASS.
Compile/collect, architecture, version, documentation, code map and active-artifact
gates PASS in the exact isolated final snapshot; foreign file hashes unchanged.
Prior RED gates remain retained. Guarded installation and live904 quality pending.


## 2026-10-05 — valid literal queries rejected after prose preface (903)

Installed902/0.31.174, commitc7647784, patch17.77s/runtime hashes PASS.
Canonical3394PASS/20existing skips/5warnings, metadata31PASS, focused81PASS.
Live BAP901 on unchanged default user profile/model connection r8, identityd843191a:
B0 failed39.11s with MODEL_RAG_QUERY_LIST_EMPTY/no artifact. Public session history817
preserved actual model output: 19 valid queries in JSON after a prose preface, then
18 valid queries in a fenced JSON after commentary; decoder rejected both.
This is a transport false-empty, not evidence that the model or catalogue lack queries.
B1 completed348.56s/19model rows/1downloaded41417byte XLSX, SHA9aa40024.
All input delivered (no truncation); one PDF_TEXT row unanswered. 13positions built,
calculated0, confirmed0/preliminary251771.08. Statuses8NEEDS_RESEARCH/9ANALOGUE_CANDIDATE/
2MISSING, zero EXACT; 4NRSP gaps,6resource groups,1KAC,2unit conflicts.
This is measured progress in delivery, NOT professional acceptance. Customer-ready false.
Cloud disabled/budget0; source/FSEM hours mismatch, ordinary basic chat1FAIL,
large input and fresh installer acceptance remain open.

_model_json_documents reads standalone line-level JSON or explicit JSON fences
using JSONDecoder boundaries, preserving outside commentary. decode_model_query_envelope
accepts exactly one valid optional envelope with that commentary; queries are never
rewritten, synthesized, selected by domain or clipped to a fixed count. Ordinary plain
query lists retain their existing reader. Duplicate fields, invalid/nested envelopes,
multiple documents and inline prose examples do not become executable envelopes.
decode_model_artifact_kind reads the same fragments; multiple declarations remain conflicts.
No prompts/model requests, native RAG, budgets, tool loops, roles or professional decisions changed.
This wires already authored literal queries into the existing frozen model→RAG path.
Regression: test_model_rag_query_declaration (1/7/19/30 queries, fences, preamble/tail,
quoted braces, ambiguity and invalid shapes). Red10/35PASS; related148PASS.
Canonical/install/live903 pending; no release or readiness assertion.

## 2026-10-05 — live901 invalidated the mirrored reuse-gap fixture (902)

Installed901/0.31.173, commit bc8965ca; guarded patch17.16s, exact runtime hashes PASS.
Canonical3393PASS/20existing skips/5warnings, metadata31PASS, focused80PASS.
Explicit new repack of default-profile B1 took8.59s, inference0, decisions SHA unchanged,
SPbQ32026 inherited, one position, coverage/reuse preserved, preliminary13976.62/confirmed0.
Live901 did NOT pass the price-gap regression: row source is row.source, not meta.price_source.
The narrow synthetic fixture incorrectly mirrored the latter shape. This finding is preserved
in artifacts/live_901/default_repack; no passing live acceptance is claimed for901.
Build902 reads the actual calculator row.source and tests build_position_trace output,
including serialized column keys and the known zero cost. Red2 reproduced the failure;
focused81PASS. Missing price/provenance negative cases remain open, not suppressed.
No authored decisions, source refs, tariffs, quantities, arithmetic or inference boundary changed.
Source/FSEM hours0.02/0.022 remain unresolved; default model quality, basic-chat1FAIL,
large input and fresh installer acceptance remain open. Cloud disabled/budget0.

collect_lsr_price_gaps checks the actual row.source ownership contract:
action=reuse + source=reuse + numeric zero column10 is an applied, known amount.
No price question is emitted for that amount; price/provenance missing is still a gap.
Entry: lsr_workbook_adapter_service.collect_lsr_price_gaps.
Regression: test_lsr_readiness_transport.test_calculated_reuse_does_not_generate_a_market_price_question
and parametrized zero/missing price/missing source cases. Canonical/install/live902 pending;
customer-ready false.

## 2026-10-05 — applied reuse produced a false price question (901)

Installed900/0.31.172, commit ea5ae27e; guarded patch16.97s, runtime hashes PASS.
Canonical3390PASS/20existing skips/5warnings, metadata31PASS, focused160PASS.
Retained default-profile B1 replay8.28s, inference0, accepted_rows SHA unchanged,
SPbQ32026 pinned, downloadable XLSX12195bytes/SHA67095dec.
Row projection bound/covered/resource_linked, one position, no false coverage ambiguity.
Authored reuse applied to exact material09.2.02.02-0011: qty157.5m, price0, amount0.
Preliminary33013.65→13976.62, confirmed0; source/FSEM hours0.02/0.022 remain unresolved.
The replay helper initially asserted the nonexistent status covered_by_work;
audit_repack_900 checks the actual covered contract and XLSX cells, core regression PASS.
Separate finding: price_gaps labelled applied reuse as a missing quotation.
No inference policy, model queries, evidence, tariffs or FSEM arithmetic changed.
Cloud disabled/budget0; default model quality, ordinary basic chat1FAIL,
large document and fresh installer acceptance remain open; customer-ready false.

collect_lsr_price_gaps does not ask for a market price when the calculator
has already returned action=reuse, source=reuse and a numeric zero price.
Missing price or missing reuse provenance still yields the existing gap.
This is a projection correction after model/calculation boundaries; authored rows,
zero-price basis, arithmetic, partial FSEM status and all genuine gaps are preserved.
Regression: test_lsr_readiness_transport, parametrized known zero/missing price/missing owner.
Red1/14PASS; focused80PASS. Canonical/install/live901 pending.

## 2026-10-05 — explicit action on a linked resource row was dropped (900)

Installed899/0.31.171, commit5681a6cd, exact runtime hashes подтверждены,
native RRF PASS1.66s. Три repack сохранённых898 решений скачали XLSX за8.23/0.12/0.53s,
decisions SHA неизменён, книгаСПбQ32026 наследована, provider counters неизменны,
inference0. Readiness не просит вторую норму у covered child; конфликты ресурсов видны.
Все три результата partial, professional acceptance не пройдена.
Matched live899 на действующем пользовательском estimator профиле, identity83e94984:
B0 23.22s/2rows/1XLSX, нормы не найдены, money0; B1 38.22s/3rows/1XLSX,
правильный шифр63-03-008-02 выбран, preliminary33013.65/confirmed0.00.
B1 модель явно записала reuse отдельной resource строкой с work_row, но калькулятор
не перенёс действие на работу; resource на том же source_row сделал coverage ambiguous.
Это потеря предметного решения после model boundary, не доказательство ошибки выбора.
Исходные ответы, SHA, XLSX и audits сохранены в artifacts/live_899/default_*.
Обычный чат basic8979PASS/1FAIL остаётся открытым; большой/default/installer gate не пройден.
Cloud off/budget0, native shell5.1.813.

resolve_work_coverage разрешает явный covered_by_work_id среди работ:
resource/material/header на том же locator не являются альтернативной работой.
Две реальные работы по одному адресу по-прежнему требуют operation_id.
positions_from_visible_lsr_rows переносит явно записанные resource_bindings
с resource строк на единственную указанную work строку, без поиска/выбора нормы.
Порядок действий сохраняется; у каждого действия остаются его owner source_row,
локальный индекс, исходное предложение и собственные evidence checks.
Многократные resource строки допустимы; чужие checks не подтверждают соседнее действие.
Неверная/неоднозначная родительская связь и другой явно названный шифр видны как конфликт;
ресурс не изменяется. Linked reviews сохраняются как неприменённые предложения,
а не подменяют review работы. Модельные строки не сливаются и не переписываются.
Сумма может измениться вследствие применения уже выбранного моделью reuse/exclude;
тарифы, арифметика и FSEM reconciliation policy прежние. Новых inference нет.

Red3 воспроизвели dropped action/false coverage ambiguity; negative two works PASS.
Focused160passed, включая порядок строк и собственные checks каждого owner.

Canonical/install/live900 pending; customer-ready false.

## 2026-10-05 — catalog annotations changed identity; unanswered rows called unsent (899)

Установлена898/0.31.170, commit397fcf60, 11 runtime hashes совпадают;
native RRF PASS. Matched query-off B0/B1 имеют identity79898d0e и скачали
по одному XLSX за189.41/230.05s. B0 учёл2/2 исходных строк, B1 только1/2;
оба priced_partial, confirmed0.00. Обычное замечание в том же чате за130.12s
вернуло2/2 строк; книга sankt-peterburg_3kv2026 наследована из задания.
Resource adjustment остаётся конфликтом; ФСЭМ0.02/0.022 не согласован.
Это экспериментальный immutable профиль, не глобальный пользовательский default.
Большой varied input, default flow и installer приёмку не прошли.
Basic8979PASS/1FAIL остаётся незакрытым; basic898 не повторялся.
Облако выключено, токенов облака0; nativeEXE5.1.813.

Каталожные _catalog_source_* annotations не входят в fallback operation
identity: профессиональные поля решения по-прежнему входят в SHA. В готовности
сохраняется та же связь covered, что в расчётной проекции.
Sheet pass отдельно считает доставленные packet locators и исходные строки,
не получившие решения в terminal result (unaccounted_result_locators).
Пропущенное решение не объявляется усечением вложения. При неполном покрытии
MODEL_RESULT_SOURCE_ROWS_UNACCOUNTED доходит до document_issues и priced_partial
также в прямом B0, без нового модельного цикла и без удаления рассчитанных строк.
collect_lsr_price_gaps переносит уже существующие resource_binding_conflicts
в понятные действия карточки готовности. Ввод цены не объявляется исправлением
ресурсного конфликта. Нормы, ресурсы, ставки, часы, допуски и запросы не меняются.

Red tests reproduced identity mismatch, false delivery diagnosis,
B0 priced_final on1/2 output rows and absent resource action gaps.
Focused70passed. Canonical/install/live899 pending; customer-ready false.

Canonical899 final snapshot artifacts/gates_899_r2:3381passed/20existing skipped/5warnings,
metadata31passed; verify, architecture, docs/map и active artifacts PASS.
Чужие UI-правки исключены и SHA сохранены. Первый snapshot superseded до
финального изменения repack; готовность определяется только final r2.
Install/live899 pending; professional acceptance не пройдена.

## 2026-10-05 — punctuated named records were not delivered (898)

Installed897 query-off B0 codex-live-selected-901228f2c12c completed in134.48s
with model-authored comma-separated bullet records and prices, but decoder
read zero rows and no XLSX. Answer retained in artifacts/live_897/query_off_baseline.
Red22 (format permutations and real workbook boundaries) and nested red2
reproduce transport/duplicate-field failures. 898 reads only explicit named
fields; prose/decimal/JSON punctuation stays literal. Invalid and repeated
labels retain raw proposals, including nested JSON. No inferred norms,
resources, match flags or extra model calls. Focused99passed; retained B0 now
decodes5 rows with unchanged answer and0 inference. Canonical8983370passed/
20existing skipped, metadata31; offline gates PASS. Install/live898 pending.
Separate matched query-thinking B1 stopped at8192 output/final0 (138.3s).
Basic8979PASS/1FAIL retained. Customer-ready false; no financial policy relaxed.

## 2026-10-05 — literal inline records and lost coverage link (897)

Installed896 candidate codex-live-selected-6ed4e8dcddbd returned two literal
named records and final artifact_kind=lsr, but no rows/XLSX were decoded.
The unchanged answer is retained in artifacts/live_896/compact_coverage_candidate.
Baseline896 produced a partial workbook but safe chat projection dropped
covered_by_operation_id and readiness asked the covered row for a second norm.
It also called unresolved FSEM hours a missing wage even with both tariffs present.
Red9/5 reproduced the independent decoder/projection/diagnostic defects. 897
reads named inline records without inference, preserves coverage identity and
names the FSEM prerequisite; duplicate fields stay raw rejected proposals.
No hour tolerance, tariff, amount or authored norm changes. Focused235passed;
canonical8973345passed/20existing skipped, metadata31; offline gates PASS.
Saved live answer re-read unchanged:2 rows,0 inference. Installed acceptance
pending; basic896 remains9PASS/1FAIL (12 web_search, final unparsed tool frame).
Customer readiness remains false.

## 2026-10-05 — a provisional document target blocked a completed result (896)

Installed895 B1 codex-live-selected-5d5e5a9ff7ee completed both source rows but
did not package an XLSX: query proposal said vor, terminal answer said lsr.
The actual trace is artifacts/live_895/compact_coverage_retry_candidate/target_audit.json;
matched B0 identity is equal. Red2 reproduced missing execution in both routes.
Known query proposals now have distinct authority from final model results;
the literal final target can supersede only a proposal, preserved in audit.
Final duplicates, inconsistent final packets and unclassified legacy records
remain blocked. No authored norm/resource/row is rewritten, no inference added.
Focused200passed; final canonical896:3326passed/20existing skipped, metadata31;
verify/architecture/docs/map/active artifacts PASS. Installed896 acceptance pending.
Read-only FSEM audit separately proved source0.02 versus derived0.022 despite
available tariffs. Official raw values are saved under artifacts/live_895/official_hours.
No permissive rounding rule or changed resource quantity was introduced.

## 2026-10-05 — target serialization and first-row price selection (candidate895)

An additional red2 reproduced accepting a base-column amount, or a conflicting
price row shown by search, as a quoted current price. The current quote now carries
explicit typed amount/unit/source; original components remain visible separately.
Published current wins over index and published zero is valid. Focused133 passed;
the final canonical rerun is artifacts/gates_895_r2.

Installed894 compact controls: one model action used a generic resource name;
another used the exact code but omitted action provenance. 895 offers a literal
Q/H#resource slot from a fully delivered immutable exact card. The model still
authors action and basis; invalid, deferred, mismatching or cross-packet pointers
remain conflicts. Red3 proves the missing reference transport; focused154 passed.
Separately, synthetic conflicting prices were silently resolved by input order
(red7). PriceBook now retains all conflicting records without a price; both
calculators and exact reader report the conflict. The real SPbQ32026 book has0
such conflicts, so this does not explain earlier missing amounts. Source proof
and controls are in artifacts/live_895; full gates/live pending, not accepted.

## 2026-10-03 — formula-only XLSX unreadable without recalculation (candidate889)

Live888 repack has226 formulas with empty cached values. Offline arithmetic matches
the API preliminary274783.91, while data_only readers see blank monetary totals.
889 keeps original numeric trace values in OOXML caches beside unchanged formulas.
Unknown prices remain blank; automatic recalculation after edits remains enabled.
No model decisions or calculation rates change. Formula/cache/export regressions
cover single/multiple positions, complete/partial totals, and actual artifact storage.

## 2026-10-03 — cloud budget hid already accepted workbook rows (candidate889)

Installed888 Flash BAP controls used455669+38520 tokens and retained12/19 rows,
but returned only budget errors. The public no-model repack returned a verified
28101-byte partial XLSX using the correct pinned SPbQ32026 pricebook.
Candidate889 routes budget stops after accepted packets through ordinary partial
packaging, preserves remaining rows/cursor, and makes no additional model call.
Before any decision,429 remains. No model choices are inferred or corrected.
Related91passed; canonical889:3249passed/20existing skipped, other offline gates exit0.
Installed/live889 pending. Professional quality remains failed:
unresolved groups/analogues and a model-authored duplicate combined ceiling norm.

## 2026-10-03 — installed887 raw tool frame accepted as final (candidate888)

History768 returned only Qwen XML web_search after calls_budget; basic smoke falsely
passed nonempty output. Independent receipt: artifacts/live_887/smoke/answer_audit.json.
888 explicitly marks ordinary native research final phase (no tools), detects
unconsumed protocol and reports MODEL_OUTPUT_INCOMPLETE without streaming/persisting
protocol or reasoning as the answer. No additional model call or fabricated result.
Basic smoke now fails raw frames/technical_pending. Fenced examples/valid answers
remain unchanged. Focused88passed/1existing skipped; canonical888:3242passed/
20existing skipped, other offline gates exit0. Install/live pending.

## 2026-10-03 — provider reasoning lost before native continuation (candidate887)

Transport discarded reasoning_content; bound runner reconstructed a reduced response;
active router parser also discarded native assistant content/literal arguments.
Qwen3.8 preserve_thinking requires separate historical assistant reasoning_content.
887 carries provider state through all three boundaries into typed budgeted exchanges.
No visible answer/receipt/trace exposure, no fabricated resume history; cloud disabled.
Regression covers actual B0/B1 callbacks, ordinary research, mock second HTTP, quoted
Markdown/JSON and required context/cloud budgets. Canonical887:3226passed/20existing
skipped, other offline gates exit0; installed/live acceptance pending.
Installed886 smoke after 64k restoration:10PASS/0WARN/0FAIL, but history766 contains
raw tool-call markup after calls_budget. Direct answer audit FAIL, release blocked:
artifacts/live_886/smoke_restored_64k/answer_audit.json. Nonempty smoke is insufficient.

## 2026-10-03 — installed885: native repeat aborted without cached feedback

Original19work BAP, FreeToken B0, physicalKV131072:1007.74s, no XLSX.
Three successful searches were followed by an identical read request; the driver
stopped before replying with the already saved result. Finalization also reported
unstructured instead of a technical stop. Candidate886 replays the bound receipt
once with the new native ID, charges max_calls, keeps the cache within the current
turn (price basis may change on resume), and keeps technical_pending/reason. No normative choice or literal body
changes. Offline B0/B1 callback regressions pass; installed/live acceptance pending.
Evidence: artifacts/live_885/bap_freetoken_128k/{final,expert_audit}.json.

## 2026-10-02 — installed878: capacity stop mislabeled as model format failure

B1 thinking requested12searches+4exactnormreads; all16returnedok, but the next
frame required54351 vs46171estimatedtokens. No terminal model decision existed.
Finalization overwrote phase with packets, called all20rows never-offered (12had
been presented), and reported unstructured/«таблица строк не получена».
Candidate879 preserves technical phase/reason and corrects only the offered
diagnostic; decisions, remaining rows and closure unchanged. Actual2packet
regression failed before fix; related48passed. Canonical8793178passed/20existing
skipped, verify/architecture/docs exit0. Install879 pending.
Exactbody duplicates were not found in saved119record replay;96Ki capacity trial
is recorded separately. B0 created11rows with0confirmed amount and incorrect
norm references. Neither run proves price-pointer878 fix live (no price calls).
Evidence: artifacts/live_878/audit_after_local.json and context_96k_control/.

## 2026-10-02 — installed877: context fix proven, estimate acceptance still failed

Exact installed commit0eea0e00, original BAP PDF, same question/profile/runtime,
FreeToken Qwen3.6-35B-A3B-NVFP4 engine0.1.3+g52322e984. B0 60.91s did not
package (`ARTIFACT_KIND_UNRESOLVED`, missing valid locators/citations). B1 397.58s
preserved a downloaded draft with verified SHA, but only7/19 real positions,
12 remaining source rows, confirmed0/preliminary11819.69. Requested SPbQ3 book
resolved exactly. First packet emitted128 parsed rows, repeated entries,
malformed Markdown cells and a length16383 cut; no guessed parser repairs applied.
Neither real run requested full native norm cards. Query source-map tokens0 in
all3 B1 queries proves the877 leakage fix; it does not prove professional quality
or billable cloud savings. Separate synthetic wire tests obtained actual native
read_norm_card calls with auto/off, forced/off and auto/on thinking. Thus native
tool emission works on a small prompt; success on the real task remains unproven.
Capability tools=supported alone merely proves HTTP acceptance, not tool execution.
Evidence: artifacts/live_877/audit_after_local.json, bap_ft_baseline/,
bap_ft_candidate/, native_wire_probe/. No Alibaba calls after the quota warning.
An isolated per-chat thinking profile finished226.69s without an artifact:
7 price searches +40 exact price reads,47ok receipts,0 norm reads. Its continuation
required85410 estimated tokens vs46171 available and stopped evidence_read_capacity.
Only answer thinking changed; the operator's active profile stayed unchanged.
This proves real native execution but not norm applicability or quality. Receipt:
artifacts/live_877/thinking_trial/result.json. No larger-context override applied.

## 2026-10-02 — candidate875: reopened review was contradicted by delta instructions

Actual874 BAP engineer remark left painting R18/R19 transport_pending. Original
decisions survive in prior history; reopen removes them from active accepted.
Four system/user clauses nevertheless promised unchanged rows remain and only
new/changed operations need return. A late user overlay cannot remove a system
contradiction. The narrow correction separates ordinary continuation delta from
explicit review full response: model returns all offered prior operations,
unchanged fields/citations copied literally with old operation_id and
expected_revision=shown revision. No old row is auto-restored/confirmed, no norm
or role is chosen by code, no schema handshake or extra model cycle is added.
RED3 old-wire failures → focused316passed (30.36s), actual full/cut fake-chat
frames and existing normal-delta behavior. Full returns unchangedA+changedB;
cut preserves active0/remaining2 and original prior event. Independent read-only
review finds no critical issue within scope. This does not prove painting quality
or live review completion. First875 gates predate this source freeze; second
exact gates/install/comparative live remain necessary, customer readiness pending.

## 2026-10-02 — candidate875: native-capacity resume exposed alias collision

Installed874 SKS plainContinue16.56s remained23/75,0 works/0 money, query1 and
no answer phase; this remains FAILED. Root's causal offline repair preserves
original held query texts/provenance/addresses/offset after native capacity pause
and reports initial answer required/available/overflow before inference. Strong
saved-read resume then exposed native price Q11/Q12 allocated after only10 shown
query groups while39 original queries owned that range. The binder now reserves
all query indices (including unshown/empty groups) and existing durable handles
before new native Q. The held raw cursor advances only by included queries;
native high-water marks cannot rename its tail. Original aliases, bodies, identities and delivery flags are
unchanged; old ambiguous unbound refs remain unresolved without auto-renumbering.
Binder RED4fail/1migrationcontrolpass→40GREEN; whole focused143passed (17.55s),
including actual unchanged saved bindings/read bodies and same-bound overflow.
No live875 call or professional acceptance follows from these fixtures.

## 2026-10-02 — installed874: empty-question repack drift and VOR marker row loss

Exact runtime `c4253e38ea9539eb841e993eb373a42665079c0a`. Saved SKS partial
repack created50 rows, but the second identical UI request with empty question
changed revision/hash: requested region/quarter gained learned book/self-revision
and changed origin notes. Real receipt: `artifacts/live_874/sks_saved_repack/`
before/response/replay/replay_diff. 875 records exact first arguments plus
server-owned immutable request/applied pin; repeated business input reuses them.
Changed source/rows/overlays/issues/profile or explicit basis remains new input.
Controlled replacement same-book bytes cannot reprice the old revision; missing
artifact/checkpoint returns explicit409 before executor/inference. Focused100 pass.

EOM874821.75s produced actual draft VOR46 rows/23 of56 locators, target literalvor.
First result was standalone `artifact_kind: vor` followed by valid naked JSON24
rows; parser found0, with finishstop/truncatedFalse/no transport diagnostics.
875 row decoder skips only that outer transport line; saved replay returns all24
original rows exactly. Artifact target duplicates/invalid/conflicts still fail
independently; no quantities/norm choices are repaired. RED10fail/11pass→139GREEN.
Bounded proof: `artifacts/live_874/eom_vor_natural_candidate/inspector_causal_report_874.json`
and inspector_decoder_replay_proof_875.json. Final remaining33 preserves all
unanswered locators; XLSX keeps21 material/24 work/1 header, authored quantities
and sources unchanged. This is partial draft evidence, not professional acceptance.

Installed874 BAP260.5s professional FAILED; B0~79s no artifact; SKS~387s overflow.
SKS explicit continue16.56s still23/75,0 works/0 money/no answer phase: FAILED.
BAP engineer remark738.11s creates a file, professional acceptance pending.
875 full gates/install/live remain pending; no customer-ready claim.

## 2026-10-02 — installed872: answer truncation and malformed exact readers

Fresh same-identity BAP controls:no overflow, neither produced XLSX. B0length at
8Kanswer limit (trial restored to16K); B1 paused0accepted/20remaining after
7searches+7malformed readers.26source locators preserved across packet scopes;
source loss not proven. Model's partial norm applicability/citation mistakes remain
professional failures. Independent facts:live_872/expert_audit/pair_expert_summary_v1.json.
Ordinary smoke alsoFAILED:180s timeout; history704 finished193.105s with42webhits
and5identical queries. Native assistant/tool history was absent in following rounds.
Candidate873 adds literal protocol replay and exclusive admitted norm evidence_ref
reads. Offline/live gates pending; neither fix licenses a customer-ready verdict.

## 2026-10-02 — installed871: bounded native continuation still has capacity failure

Public comparative identity byte-equal. B0 331.73s, seven read frames,
required46993/budget46246 (+747), no XLSX. B1 92.17s, paused20remaining/0accepted,
required47433 (+1187), no XLSX; six exact full cards actually delivered,
then four searches prepared but not admitted. Professional871 FAILED.
Seven B0 missing reads used parent/table ciphers without their full suffix;
some literal matching full-code siblings were already shown. Candidate872
missing feedback exposes only admitted prefix+dash neighbors/refs/literal title/
immutable provenance via native receipt trace. Status/hits/count, exact resolver
and model choice stay unchanged; no reader, fuzzy lookup, requery or hidden body.
Navigation RED2/control6 then8GREEN; source/tests mechanical proof, not live quality.
Lossless unread pointer-field aliases preserve all identities/provenance and do
not prove a body was read. Full canonical/exact installer872 pending.
Visible131k trial did not change observed physical KV65536 pages×page_size1,
despite advertised262144; original65k policy restored in public bindingr6.
No GPU/KV/server/model change. TOKEN_COUNT investigation remains separate.

## 2026-10-02 — 872 candidate: extracted Windows prepare fixture lost production UTF-8 setup

Private official prepare871 retained 2924 passed / 1 failed / 20 skipped /
6 warnings (219.48s). `test_actual_windows_prepare_cache_is_bound_to_baseline_bytes`
extracted only `Read-PreparedUpdate`, omitting the production Console UTF-8
preamble. With Python UTF-8 and inherited CP866, missing-baseline stderr contains
byte0xaa; the subprocess reader thread raises UnicodeDecodeError and returns
stderr=None. Exact isolated RED: 1 failed / 16 deselected / 1 warning (2.72s).
Two-line fixture fix restores the production UTF-8 writer contract and strict
UTF-8 capture; all17 release-local tests pass (4.18s) under CP866/PYTHONUTF8=1.
No skip, decode replacement, production change or relaxed assertions.
Receipt: `artifacts/test_release_encoding_871_red_green.json`.
Candidate872 metadata verify0 (23.48s), 2945 collected; version/docs/release
fixtures31 passed (4.99s), documentation contract0. Full canonical872 pending.

Installed871 `e8657ba3`: API/GUI/19 hashes aligned, native EXE858 retained;
native RRF exit0. Original90s smoke7 pass/1 warn/2 timeout fail remains recorded;
separate finite180s smoke exit0/10 pass/0 warn/0 fail (112.66s), glossary61.547s,
project48.687s. Professional871 live FAILED (both same-identity controls/no XLSX);
exact private prepare872 pending. Technical smoke does not prove model quality.

## 2026-10-02 — 871 candidate: second canonical green, first fixture failures retained

SECOND mandatory gate: verify0 (22.84s), 2925 passed / 20 existing opt-in skipped /
5 warnings (281.29s / wrapper 282.81s), architecture0 (9.75s), pinned baseline0
(7.23s), active artifacts0 (0.61s). First gate remains FAILED: verify0 (23s),
2923 passed / 2 failed / 20 skip / 5 warnings (286.72s / wrapper 288.22s).
The two old `test_model_research_evidence_actions` fixtures searched then read
exact cards before actual inventory admission. Only that test file changed
(+40/−4): explicit binder→Governor→confirm→register, negative pre-admission
assertions; original provenance, all 40 resources/НРСП and price-proof assertions
retained. Focused checks: 119 passed (15.60s); source8 unchanged, now5 test files.
Receipts/logs: `artifacts/*_871_second.exit.json`, `artifacts/*_871_second.log`;
the failed first receipts were not overwritten. The candidate was installed as
exact871 `e8657ba3`; professional871 FAILED/private exact installer pending,
native EXE858 retained. Previous runtime870 `7ba406a1` professional acceptance remains FAILED.
Offline fixtures and canonical gates are not real-model professional proof.

## 2026-10-02 — installed 870: native evidence delivery exceeds bound context

Exact installed commit `7ba406a1d90744b0917b9a4950956df77753fc52`, same
source/task/profile/model B0/B1, professional acceptance FAILED. B0 179.56s:
4 native searches / 24 prepared refs, no XLSX; required 55639 / budget 46246
(overflow 9393). B1 57.97s: paused/resumable, 0 accepted rows / 20 remaining,
no XLSX. First read frame 45230 admitted 5 exact full results; 5 reader missing
results are retained in the trace. Next 4 searches prepared 24 refs, but second
read frame required 72822 (overflow 26576) and was not delivered.

Saved B1 compact replay alone estimates 50317 tokens before profile/request/
native history: 30 byte-distinct stored body views (60519 chars), 44 unread pointers,
5 aliases already shared. This is canonical len/2 counting, not a provider
tokenizer result. Exact body duplicates are absent; choosing professional
candidates in code is not a remedy. 871 source/tests are frozen: common
`prepare_model_read_replay` / `govern_model_read_messages` retain mandatory
exact/cited bodies and literal inventory, while whole discovery groups are
optional and admitted by the actual Governor. Raw IDs/content/refs remain durable.
Inventory delivery and body delivery are separate; source map/manifest/row
binding/price guards do not use hidden raw bodies. Premature search registration
is removed; legacy exact-price receipts remain mandatory and pointer-only views
never claim full bodies. Final focused 10 suites: 392 passed (21.54s), four
causal old-boundary ablations red retained. Scripted B0/B1 authored JSON→XLSX
fixtures confirm 1800 and preserve 24 raw refs. These fixtures are not real-model
professional proof; 871 canonical is recorded above, installed live FAILED. No model/
provider/profile changes or professional rewrite are claimed.

870 final canonical: 2906 passed / 20 existing opt-in skipped / 5 warnings;
verify/architecture/pinned baseline exit0. Installed native RRF exit0. Basic 90s
smoke: 8 passed / 1 warning / 1 project-timeout FAIL. Separate finite
hardware-calibrated 180s smoke exit0: 10 PASS / 0 WARN / 0 FAIL (85.55s),
glossary/project 31.640s/51.438s, both below original 90s. FT request p95
128.233s motivated the explicit finite limit; the original failed run stays
recorded because ordinary latency varies. Technical smoke does not close
this professional failure.
Receipts: `artifacts/live_870/bap_lsr_{baseline,candidate}/`.

## 2026-10-02 — 870 candidate: duplicate native body and ambiguous row isolation

Installed 869 (`85d09d7e`) same-input/profile comparison FAILED. B0 stopped
at evidence_read_capacity after 76.88s, without final rows or XLSX. B1 after
311.64s delivered a SHA/revision-verified draft: 11 operations across 8/20
source locators, one customer header included, therefore only 7/19 real works;
12 works remain. Known preliminary amount 64 545.14, confirmed 0; actual
Saint Petersburg 2026 Q3 book matches and has a saved SHA. Known-part Decimal
matches, but full cards, applicability, resource review and prices remain open.
The repeated first packet is a transport/progress defect, not a professional
MISSING decision for unaccepted source rows.

870 removes the duplicate native receipt body from governed evidence
(saved-shaped frame −3092 tokens), validates numeric capacity and distinguishes
prepared results from actually admitted evidence. Immutable-ID promotion needs
the same literal body; durable read chunks become bindable after resumed frame
admission. Row-local duplicate JSON field ambiguity preserves the disputed row
and raw diagnostics while admitting independent rows; it never chooses a value.
Durable fixture keeps 3 valid rows / 1 remaining; plain continuation does not
repair, existing explicit reopen with new model correction produces a real XLSX.
Focused root 109 passed / native 56 passed / decoder-durable 22 red → 73 passed.
Final targeted parser: 10 red before fix → 118 passed (15.98s);
transport/persistence: 119 passed (20.44s). Final boundary checks: 8 red /
2 prose controls green → 128 passed (14.64s). Canonical and installed comparative
870 are recorded above; these fixes do not close failed professional acceptance.

## 2026-10-02 — 869 candidate: source scope and packet transport completeness

Installed 868 malformed first packet starved seven never-reached source rows.
Durable pending snapshots now remain distinct from fresh source packets; only
an explicit reopen plus newly admitted model rows can resolve them. Seven new
focused cases and 368 related cases passed. No parser or professional repair.
PDF tables previously erased non-table source context and could falsely claim
complete extraction. Stable table locators plus separate literal PDF_TEXT scope,
bounded not_shown manifest and visual/OCR warnings replace that claim (71 related
passed; six new cases failed before fix). Current attachment exact native reads
and old completed-job scope expansion verified by 169/374 related tests.
Literal table/prose spans and PDF-only packet facts avoid condition-order loss
and nonPDF context pollution (226 related passed). Completed installed 869
professional proof FAILED; the current 870 record above preserves that result.
Archive unpacking previously skipped nonempty partial output and returned zero
on failures. Source-bound completion marker plus manifest, safe paths and
preserved user conflicts now give honest nonzero failures (21 passed). Retired
previous-manifest paths cannot silently enter the next completed archive revision.
These are offline fixes; completed installed professional 869 gate FAILED,
as recorded above. The transport tests do not establish customer readiness.

## 2026-10-02 — 869 candidate: repeated continuation selected stale correction state

An exact identity for an earlier literal continuation preceded the document's
newer corrected revision. Repeating that text restored old quantities/basis.
Seven fixture cases failed before the fix; seventeen focused cases and 138
related cases pass afterward. The selector follows only a same-scope descendant
and validates every lineage step; explicit task reruns remain idempotent and
running guards are preserved. Installed 869 acceptance FAILED; no live readiness
is inferred from these tests. Installed 868 comparison independently failed:
B0 truncated JSON at length; B1 malformed Markdown and zero native reads, both
without a downloaded artifact (`artifacts/live_868/bap_lsr_{baseline,candidate}/`).

## 2026-10-01 — 858: explicit resource code lost; known contradictions hidden

Same-input installed EOM 856 delivered 51/51 rows but failed quality/financial
acceptance. Independent code review found that explicit resource_code was
dropped by visible readers/compact replay, and literal citation/source errors
were only persisted in trace, not shown in existing page/review calls. 858
preserves the field and separately recomputes structural facts from actual
immutable cards/catalog for all roles. Saved diagnostics are never trusted.
No additional model call, inference loop, professional decision or authored
quantity changes. Mechanical source comparison now accepts equal m/km, kg/t.
Offline red-to-green preserved; installed 858 technical gates passed, customer
quality acceptance FAILED. Same-source/task/model B0: 38/51 addresses, two fully
calculated works, zero source errors (295.6s). B1: 51/51 accounted but 18 faulty
work/material source decisions, one fully calculated work (1482.6s). Both omit
resource_code and nr_sp_rule_id; B1 retains 30 nr_sp_unresolved and 43 price gaps.
This closes the field loss/comparison transport defects, not model selection,
source accuracy or complete financial coverage. Artifacts/live_858 contains
downloaded SHA-verified files and comparative_acceptance.json with FAILED.

856 fresh comparative: full 51/51 delivery and collision-free evidence handles proved; model-selected norms/citations, four source errors, NR/SP and price gaps still fail professional/financial acceptance. See RELEASE_LEDGER and artifacts/live_856/comparative_acceptance.json. Customer-ready status is not asserted.

## 2026-10-01 — 856: reconnect projection drops the document kind

Installed full job and file panel correctly say VOR, but a subsequent terminal
notice rendered from chat_pending says LSR. workbook_job_to_pending_progress
copied document state and IDs but dropped artifact_kind/tool. 857 preserves both
literal fields. One red→green behavioral regression, focused UI/history/documents
189 passed. This changes no inference, query, file or quality status.

## 2026-10-01 — 854: review card handle shadows another packet's card

Ordinary installed EOM review shows Q18.H2 with the old selected card, while
durable evidence reuses that alias for four different cards. The model's new
answer preserves the old norm and literal citation but omits evidence_bindings;
the checker correctly rejects the now ambiguous handle. 856 prevents new
collisions by allocating Q after all saved handles. Held-page cursors are
preserved. No old citation, query, chosen norm or card content is rewritten.
Two regressions cover review binding beside a new packet and durable roundtrip;
fresh installed B0/B1 and ordinary restart/resume remain mandatory.

## 2026-10-01 — 854: restored VOR labelled as ready LSR

Browser startup now selects the correct latest job, but its generic filename
overwrites the real history filename and says «ЛСР · готово» for a VOR.
855 uses GET /api/artifacts/{revision_id} and checks matching revision identity.
Fallback preserves artifact kind and ID; execution completion does not claim
document quality. A late metadata response is discarded after session switching.
Three red→green regressions, focused UI/history/documents 188 passed.
Inference and arithmetic unchanged; fresh large/financial gates remain open.

## 2026-10-01 — 853: ordinary reload bypasses selected-history latest priority

Installed browser reload shows correct current VOR but old 7-row/46-open paused
status because persisted job_id takes the compatible night-reconnect branch.
854 always prefers an own-session newest job first, API and local fallback;
foreign night adoption is retained when no own job exists. Same regression in
both modes, focused 185 passed. No model choice or file is rewritten.

## 2026-10-01 — 852: history restores an open ancestor of the finished document

Browser download restores the correct latest VOR and matching SHA, but progress
uses local list_open and displays an older paused stage of the same session.
853 selected-history fetch checks the existing last API before open jobs;
local fallback checks latest too. No prior job is deleted or modified, default
night reconnect stays compatible. API and local regressions, focused 184 passed.
Installed browser control pending; model-quality control on unchanged 852 core.

## 2026-10-01 — 851: reference descriptions become repeated quantity-less materials

Fresh EOM B1 preserves actual quantity-bearing variants but returns six group
descriptions as materials three times each, with null/0/1 quantity, plus other
source binding gaps. 852 source packet explicitly labels requested/reference
rows and exact header-bound quantity cells, keeping null/unknown as source facts.
No operation, quantity or norm is rewritten by code. Fresh installed comparison
must establish whether model output actually improves; coverage alone is not QA.

## 2026-10-01 — 851: original task absent from resumed model request

Durable original_question decides packaging/prices, but sheet-pass query payload
and answer question_tail still contain req.question only. 852 restores the exact
original user task beside the latest message and effective explicit dimensions.
The latest request wins on conversion/repricing; no search query, norm or quantity
is invented. Three regressions; installed professional acceptance is separate.

## 2026-10-01 — 850: VOR resume changes to LSR, group descriptions omitted

The installed ordinary EOM review resumes with «Продолжи». Packaging ignores
durable original_question and defaults to LSR; its revision has no VOR parent.
851 persists the explicit target with legacy original-question fallback, keeps
prior-job parents separate from current-job replay. Generic six regressions.
Source packet slicing also omitted numbered empty-quantity descriptions beside
short product variants. Literal descriptors now stay in source context; no
quantity or professional decision is supplied by code. Source-quality/live
acceptance remains independent from structural tests and must not be claimed.

## 2026-10-01 — 844 candidate: source locator triggers a legacy domain rewrite

After 843 the model's own SKS queries describe cabinet/organizer/ground-bar
installation. The active reader still calls browse_norms with expansion enabled.
The sheet label in СКС!Rn matches structured_cabling and prepends cable queries;
different operations receive the same six cable candidates. This is measured in
the installed 843 cache and reproduced by a generic source-label rule, not a
domain fixture. 844 disables vocabulary expansion explicitly in model retrieval
and by default in the browser. Literal systematic candidates remain additive,
native RRF and rerank stay unchanged. Installed acceptance is required.

## 2026-10-01 — 843 candidate: the prompt forbids the model's own operation query

842 SKS receipts contain literal product queries and unrelated norm candidates;
11/75 rows were accounted, 0 work/money, with a visible evidence_capacity pause.
The shared query-format paragraph told the model not to change the source-row
wording. This contradicted the estimator contract that the model derives an
operation from a specification. 843 changes the prompt, not the declared-query
reader or ADR-16 literal builders: the model chooses the search wording and code
executes that declared query verbatim. A generic heating-operation query regression
failed before correction. Table-first output is requested after 842's marker-only
generation consumed the answer budget. Both are prompt contract repairs; installed
comparative/professional outcome is still required and not inferred from tests.

## 2026-10-01 — 840: retrieved evidence discarded after an early terminal row

839/838 receipts measure omitted returned norm candidates despite query headers
fitting. The allocator spent the body budget greedily on full first cards.
The scheduler then discarded leftover queries when their rows were settled.
Fix: reserve every card's required body before previews, split whole query
groups into capacity pages, preserve a durable query cursor independently of
settled decisions, replay authored rows and their cited evidence. Required
ContextGovernor groups cannot disappear in final prompt packing. A group
larger than a page remains a technical capacity pause, not no-data/NO_NORM.
Six regressions include SQLite restart, evidence-ID preservation and advancing
cursor versus identical held retry; focused 236 passed. Installed comparison/
financial acceptance pending, not closed yet.

## 2026-10-01 — 839: live delivery passes, professional completeness fails

Same original SKS/Qwen35B/r3: B0 210.2 s produced ungrounded citations and
source-volume changes (structural_error, no file); B1 442.6 s delivered 75/75
source accounting but 0 calculated works. Three named norms stay NEEDS_RESEARCH
with incompatible units/composition, not confirmed by code. 73 linkage gaps and
69 missing prices remain. Evidence: `artifacts/live_839/sks_{baseline,candidate}`.

PDF→VOR delivered 19 rows in 95.2 s, but 3 unresolved rows have quantity=null
and numeric unit cells; the model still makes missing norms a VOR question.
Questions are visible, not silently repaired (`vor_pdf_fresh`). PDF→LSR 95.8 s:
19 works + 11 supplies, 6 numerical positions, SPb 3q2026 exact basis, partial.
Six EXACT rows have same-cipher citations but lack match fields/coverage; current
exact-citation policy marks applicability as substantiated nonetheless. Thus
reported confirmed_amount 159877.35 is not proof of professional correctness.
No row/status/quantity is overridden to manufacture a ready document.

Read-only retrieval reference visibility 4/4 strict, 4/8 stress at k=6 is diagnostic,
not expert truth: the cabinet reference 10-04-087-05 describes a central-station
communication complex in the typed base. A retrieved code is not its applicability.
Budget-omitted cards, inter-row linkage, match declarations, VOR volumes and
commercial-resource pricing remain unclosed. 839 is not customer-ready.

## 2026-09-30 — применимый выбор НР/СП не проходил model→calculator

Live 837 SKS has 2 bound works, both nr_sp_unresolved. Catalog contains multiple
condition-specific rows, but model-facing norm cards omitted them. Visible result
decoder, review projection and RIM visible-row adapter also discarded nr_sp_rule_id.
Seven new regression cases reproduce these losses before the fix. 839 exposes all
exact collection candidates with source references/checksums and forwards the
authored ID. No percentage/default/professional choice is introduced by code.
Budgeted model messages retain the complete required prefix of shown cards;
others stay explicitly omitted. Missing/foreign choices remain ambiguous/rejected.
Focused 248 passed after.
Actual model applicability and financial release gate still require live proof.

## 2026-09-30 — 837 baseline: ложный будущий период и отсутствие книги

Same original SKS, Qwen35B/r3/profile, SPb IIIq2026. Direct run 62.3 s refused
without workbook because the model called IIIq2026 future and the pricebook
absent, although the execution date and installed catalog contradict it.
838 exposes observed UTC date and bounded typed catalog filenames in mandatory
profile prefix, not prices or code-selected applicability. Empty/partial catalog
remain explicit; non-estimator does not read books; paths are withheld.
Evidence: `artifacts/live_837/sks_baseline_complete/receipt.json`.
Financial acceptance remains open: B1 837 has 2 cited norms, 0 full calculations.

## 2026-09-30 — 836: доставка исправлена, подбор/финансовый gate не пройден

Initial 837 PDF→VOR: 19/19 source rows, 20 decisions, but 2 authored unresolved
questions were omitted from VOR readiness (`open_questions=[]`). The source has
the quantity for both. Short skill now separates VOR volumes from LSR norm
selection. `build_vor_result_readiness` forwards authored gaps, keeps roles and
quantities, and distinguishes `technical_complete` delivery from `vor_complete`.
Evidence: `artifacts/live_837/vor_pdf_fresh`. New live validation is required.

Installed 836 recovery returns the same revisions/SHA/calculation snapshot for
two identical VOR and LSR requests (0.25 s/8.24 s, no model). Freeform SKS review
executes ordinary model research and packages a revision in 436.7 s: 75/75
accounted, 4 selected norms, 0 calculated positions. Two EXACT-authored rows cite
different norm cards; code correctly does not treat them as confirmed evidence.
Fresh same-input/same-model B0: 134.1 s, 70/75 accounted, 11 works, 0 selected norms.
B1: 493.4 s, 75/75, 9 works, 0 selected norms, 0 calculated positions; 63 coverage
gaps (49 parent_not_work, 12 missing_work_row, 2 lost_work_link). B1 is not a
quality acceptance: no claim of non-regression in professional content.
Both use the original SKS SHA and SPb 3q2026 pricebook. Native RRF is healthy
hybrid with bge-m3; reranking is disabled by runtime policy. Catalog queries
show poorly relevant first cards. Separately, source-card transport drops
resource_preview and its source fields: regression proves that loss; 837 repairs
transport only, without ranking or professional code decisions. Norm applicability,
resource links, commercial prices and NR/SP remain unaccepted. Evidence:
`artifacts/live_836/{recovery,sks_baseline,sks_candidate,sks_refinement}` and
`norm_retrieval_probe.json`. No fresh 300+ acceptance or customer-ready claim.

## 2026-09-21 — Resume 164: очередь 19/19, файл 4/21, шифры не считались

Job `accepted_rows` first-won per locator, so materials vanished on resume.
Coverage last-write hid the work sibling and then the material. Named
`NEEDS_RESEARCH` ciphers existed in `les_smeta_base` (12/12 on BAP) but
`positions_from_visible_lsr_rows` skipped lookup. **Closed in 776:** durable
merge and coverage are per `(locator, role)`; named research ciphers are
priced as analogues; overlay parquet can fill missing GESNm10 cards.

Build 775 also requires an explicit code/norm_code cell to contain only a
code (formatting and colon prefixes are accepted). It never extracts a rejected
norm from shifted explanatory prose. Original cell text remains in the binding.


## 2026-09-21 — Live 162: 24 labels / 23 divider cells erased tables

Installed 774 accepted only 12 materials. Most tables had 24 labelled columns
but 23 decorative separators and were rejected wholesale. Candidate 775 reads
143 authored rows across attempts (88 after existing role/locator merge),
including 11 work rows. These works have missing/unresolved selections or
malformed cell alignment: restoring rows does not establish a priced estimate.
History 161 replay reads 84 merged decisions. Both produce audit workbooks;
neither is customer acceptance. New pass diagnostics retain parsed row count
and structural errors.


## 2026-09-21 — Live 161: material+work на одном локаторе выжигали шифры

Full SKS on installed 773: XLSX PRICED_PARTIAL with 4 materials, no money.
Packet R27–R38 authored install works with GESN, but `duplicate_source_row`
treated material+work as one locator collision and `sheet_pass_keep_rows`
dropped the works. **Closed in 774:** duplicate/merge key is (locator, role);
authored `row_role` drives kind; title `|` surplus folds into the title cell.

## 2026-09-21 — Live 159/160: одна нечисловая ячейка теряет всю таблицу

Same 35B/r3, physical KV 35000, three SKS positions. B0_DIRECT (159) refuses
after 24 model-authored search lines including prose; B1 (160) authors six rows
but accepts zero. Offline replay of the actual response: five rows parse, the
sixth contains `conversion_factor=305 м * 120 шт`; `parse_model_rag_result`
returns None for the entire table on that field. **Closed in 773:** preserve
authored numeric text; per-row `needs_input`; do not evaluate expressions or
choose a replacement norm. A subsequent length-truncated pass remains a
separate operational risk.

## 2026-09-21 — Build 772 candidate: cache target и конкурентная перестройка

History 158 использует bound FreeToken 35B при legacy Ollama/9B: проверка
`requires_cache_alignment` старого runtime пропускала фактический движок.
ACTIVE теперь выбирает target по extension answer connection. Чтение Settings
не перестраивает KV; chat cache preparation использует generation admission и
удерживает permit до завершения worker при отмене. Проверка конкурентности
покрывает стандартный локальный слот (LLM_CONCURRENCY=1); внешние клиенты не
координируются этим семафором. Live ВОР/ЛСР и installed acceptance ещё не пройдены.

## 2026-09-18 — Build 771: 35B ушла в 9B-envelope из‑за KV 8214

- **Симптом:** overnight СКС (история 157) шла 2ч44м / 142 прохода на
  `Qwen3.6-35B-A3B-NVFP4`, но effective preset был `qwen-9b-restrictive`,
  8214 in / 1200 out, пакеты по 3 строки.
- **Причина:** ACTIVE чат только читал live `num_pages`; исторические
  `FREETOKEN_CONTEXT_TOKENS=8253` и Settings GET могли ещё и сжать окно.
  Наблюдаемый KV < 16384 держит 9B-limits даже при 35B identity.
- **Исправление:** lift <16384 → 35000 для 35B; rebuild один раз в начале
  HTTP-хода; Settings не реконсилирует 8253 поверх живых 35000.

## 2026-09-17 — Build 769: пауза первого прохода выглядела как живая сборка

- **Симптом:** очередь 75 work-локаторов дошла до 0, появился XLSX, job
  `paused` с 48 пробелами покрытия, а пузырь писал «27/75, осталось 48,
  готово через ~4ч».
- **Причина:** pause кладёт в `remaining` незакрытое покрытие; follow
  считал любой найденный job живым (`bool(job)`), а N/M = 75 − новый
  remaining. История 17:01 с одной цитатой не была рассчитанной сметой.
- **Исправление:** paused → «первый проход закончен, сборка не идёт»;
  follow останавливается; `list_open` видит paused той же сессии.

## 2026-09-17 — Build 768: пузырь прогресса падал на UTC

- **Симптом:** после 767 в чате нет typing-пузыря; в UI log
  `TypeError: can't subtract offset-naive and offset-aware datetimes`.
- **Причина:** pending `created_at` стал `+00:00`, overlay не включал
  `compute_eta`, отрисовка истории обрывалась.
- **Исправление:** aware/naive в `compute_eta`; ETA не роняет пузырь;
  overlay `runtime_dispatcher.py`.

## 2026-09-17 — Build 767: из Истории пропал пузырь сборки

- **Симптом:** сессия 17:01 открывается, видны старый ответ 16:39 и вопрос,
  живого «Сборка продолжается» нет.
- **Причина:** «Открыть» из Истории подставлял messages и не читал
  `workbook_research_jobs`. После detach в истории нет PENDING-заглушки.
- **Исправление:** hydrate checkpoint по session_id и локальный typing-пузырь.

## 2026-09-17 — Build 766: 75 строк стали 65

- **Симптом:** после 0/30 пузырь показал 35/65. Пользователь видел пропажу
  10 строк из исходных 75, а N/M не двигался.
- **Причина:** 765 сложил 35 accepted (материал/оборудование) с 30 leftover
  **work**-локаторами. Это разные множества. 75 = каталог work+ambiguous;
  remaining всё ещё R48–R77 (30); 10 локаторов ушли из очереди без accepted.
- **Исправление:** знаменатель = max `remaining_total` из events (75).
  Числитель = 75 − remaining. В пузыре видны leftover-запросы текущего
  пакета (R48–R50, десятки query headers), иначе поиск выглядит как простой.

## 2026-09-17 — Build 765: пузырь 0/30 при 35 закрытых строках СКС

- **Симптом:** «Сборка продолжается: 0/30, осталось 30, идёт 4ч 25м».
- **Причина:** reconnect считал только `row_role=work`; на СКС закрыты
  material/equipment. «Идёт» читалось как ETA, хотя это wall-clock с 14:01.
- **Исправление:** closed = work-role, иначе все accepted source-строки
  (35/65 leftover 30). Текст «с начала задачи». GPU idle — поиск через
  bge-m3; 35B жива на FreeToken :1919, не в Ollama `/api/ps`.

## 2026-09-17 — Build 764: прогресс моргнул и вернулся «счётчик появится»

- **Симптом:** на секунду видны N/M, затем снова «Счётчик строк появится
  после первого принятого пакета».
- **Причина:** `completed_history_chat_payload` брал предыдущий ответ
  («ЛСР не создана» в 16:39) как финал текущего PENDING; follow стирал
  `chat_pending` и перерисовывал пустой пузырь.
- **Исправление:** завершение только у ответа текущего хода (после последнего
  user); пока job `running` или есть PENDING, счётчики не сбрасываются.

## 2026-09-17 — Build 763: реконнект без N/M и без «готово через»

- **Симптом:** после обновления Совушки пузырь только «Сборка продолжается.
  Не нажимайте Продолжить…». Живые 24/75 и оценка времени пропали.
- **Причина:** `tool_progress` шёл только в SSE. После рестарта UI
  `chat_pending` пустой, follow опрашивал лишь PENDING-историю без checkpoint.
- **Исправление:** follow читает `workbook_research_jobs` (`list_active` /
  GET by id, SQLite fallback без рестарта proxy) и перерисовывает N/M, этап
  и ETA каждые 8 с.

## 2026-09-17 — Build 762: «Связь с окном чата пропала» + «Запрос выполняется»

- **Симптом:** после реконнекта два пузыря: «Связь с окном чата пропала…» и
  «Запрос выполняется: Собери ЛСР…». Оператор видит обрыв связи, хотя
  сборка на сервере идёт.
- **Причина:** PENDING-строка истории рендерилась как connection-notice, а
  `chat_pending` добавлял второй typing-пузырь с исходным вопросом.
- **Исправление:** один текст «Сборка продолжается» с последним 24/75;
  `should_render_local_chat_pending` не дублирует PENDING; reconnect_timeout
  12 ч; CancelledError без кнопки Стоп не пишет «остановлен пользователем».

## 2026-09-17 — Build 759: SSE не владеет жизненным циклом ночной ЛСР

- **Симптом:** после overlay-рестарта / обрыва SSE чат писал красное
  «Соединение прервано после начала сборки»; sheet-pass получал
  `CancelledError` и pause. На 300–500 строк ночной прогон утром выглядел
  как смерть задачи.
- **Причина:** в 757 `event_source` ждал runner через `asyncio.gather`, поэтому
  отмена StreamingResponse передавалась в sheet-pass. Кандидат 758 заменил
  ожидание на `shield`, но обычное закрытие async-итератора могло ждать runner
  до конца многоминутной сборки.
- **Исправление:** `detach_chat_runner_after_disconnect` не ждёт task и хранит
  сильную process-local ссылку до завершения; UI опрашивает PENDING-историю;
  `claim_or_join_sheet_pass` сериализует повторный Continue. Явный Stop —
  pause API. Рестарт proxy по-прежнему завершает process-local runner.

## 2026-09-16 — Build 757: continue выглядел как новая сборка, без ETA

- **Симптом:** после «Продолжить незакрытые строки» в чате снова «Собери ЛСР»,
  статус `Лист «СКС» (1/1): поиск норм · 0/1`, режима Агент, строки
  «Результат будет готов через» нет.
- **Причина:** resume подставлял исходный вопрос в `chat_input` и слал
  `send_chat()`; `tool_progress` нёс `completed=sheet_index-1` при одном
  листе (всегда `0/1`); `compute_eta` молчит, пока `completed<=0`.
- **Исправление:** пузырь «Продолжаю незакрытые…», прогресс по принятым
  строкам, `eta_completed` этой сессии, seed ETA из `prior_elapsed_seconds`
  до bump `updated_at`, force режима Сметчик.

## 2026-09-16 — Build 756: slot-stack на «Продолжить незакрытые строки»

- **Симптом:** после частичной СКС `LSRCKCotMelnika2026-09-16_1653.xlsx`
  «Артефакты» показали English NiceGUI slot-stack. Лог:
  `_resume_lsr_packets` → `ui.notify` в фоновом `create_task`.
- **Причина:** click-handler запускает resume через `asyncio.create_task`;
  слот клика уже закрыт, голый `ui.notify` читает пустой slot stack. Toast
  падал до `send_chat`, а aside затирался текстом исключения.
- **Исправление:** `_notify` → `notify_in_element(chat_column)` с изоляцией
  ошибки; XLSX регистрируется до `_show_artifact`.

## 2026-09-16 — Build 755: English slot-stack в «Артефактах» после СКС

- **Симптом:** чат показал частичную ЛСР и `LSRCKCotMelnika2026-09-16_1653.xlsx`,
  панель «Артефакты» — «The current slot cannot be determined…».
- **Причина:** `send_chat` — фоновый asyncio-таск; после ответа `ui.notify`
  «Новый файл…» читает `context.client` без слота. Исключение затирало aside.
- **Исправление:** toast через `notify_in_element(chat_column)`; сбой панели
  после успешного ответа не подменяет пузырь; оценка remaining-time по
  completed/total.

## 2026-09-16 — Build 754: мастер «Подготовка…» и MODEL_QUEUE_TIMEOUT 45 с

- **Симптом:** кнопка запуска оставалась «Подготовка…»; второй чат во время
  ЛСР падал `MODEL_QUEUE_TIMEOUT` через 45 с.
- **Причина:** `start_from_setup` отклонял повтор, пока auto-boot держал
  `LIFECYCLE_IN_FLIGHT`; слот генерации ждали только 45 с на весь sheet-pass.
- **Исправление:** повтор запуска идемпотентен; опрос 2 с во время boot;
  `LES_MODEL_QUEUE_WAIT_SEC=1800` в реестре.

## 2026-09-16 — Build 753: новый XLSX после «Продолжить» не виден в артефактах

- **Симптом:** resume собрал `…_1506.xlsx` (19/19), чат показал таблицу 15:03,
  а панель артефактов осталась на `…_1452.xlsx` и старой карточке с 7 пробелами.
- **Причина:** файлы дописывались вниз, карточка готовности копилась, aside
  имел `overflow: hidden`, список файлов не входил в прокрутку.
- **Исправление:** список файлов пересобирается newest-first («Текущий файл»),
  одна карточка готовности, общий `sov-artifacts-scroll`, русские подписи полей.

## 2026-09-16 — Build 752: «ЛСР не создана» без таблицы после пустого поиска

- **Симптом:** чат 144 / job `wrj_5ca2c0f7…` вернул notice «ответ не разобран
  как таблица строк» при `accepted_rows=0`, `missing=19`. Лог:
  `[SHEET_PASS] search incomplete sheet=PDF`, затем `rows=0`.
- **Причина:** `search_sources` при нуле hits ставит `status=missing`.
  Sheet-pass трактовал любой статус ≠ `ok` как abort всего листа и не
  вызывал модель за таблицей, хотя предыдущие запросы уже дали hits.
- **Исправление:** `model_search_result_blocks_packet` продолжает пакет
  на `ok`/`missing`; abort только `blocked`/ошибка RRF. Пустые hits кэшируются.
  Notice «не таблица» больше не маскирует пустой sheet-pass.

## 2026-09-14 — Build 740 XLSX без денег из-за старого EXACT_VERIFIED замка

- **Симптом:** ADR-15 terminal-result path собрал XLSX за 58,7 с (19/19 строк,
  checkpoint complete, ~13 843 байта), но денежная часть осталась нулевой.
- **Причина:** независимый verifier больше не запускается, а
  `positions_from_visible_lsr_rows` всё ещё вызывал `pricing_block_reason`.
  Без `_quality_gate=verified` + `EXACT_VERIFIED` каждая строка получала
  `norms_unverified` и не попадала в расчёт.
- **Исправление:** adapter больше не вызывает этот замок. Явный шифр модели
  идёт в exact lookup; `MISSING`/`CONFLICT`, неизвестный код, единицы и
  отсутствие цены остаются отдельными gaps. Live money acceptance pending.

## 2026-09-01 — Windows runtime потерял динамический FGIS supervisor

- **Симптом:** build 678 прошёл оба installed bootstrap, API/UI, process hygiene
  и сметную baseline, но FGIS smoke оставался в `starting` без живого процесса.
- **Причина:** API запускает `python -m tools.fgis_update_supervisor`; этот
  динамический entrypoint не виден import-аудиту и отсутствовал в Windows
  runtime manifest, хотя вызываемый им `fgis_full_update.py` был включён.
- **Исправление:** supervisor добавлен в staged runtime, а manifest regression
  фиксирует его как обязательную установленную зависимость.

## 2026-09-01 — Editable-build clean smoke превысил Windows path limit

- **Симптом:** NSIS `5.1.677` успешно собрался и установился в изолированный
  каталог, но offline `uv sync` завершил Hatchling с `0xc0000106` до запуска
  приложения.
- **Причина:** checkout-owned smoke-root включал полный commit и GUID; глубокие
  временные каталоги editable build превысили допустимую длину Windows path
  (`STATUS_NAME_TOO_LONG`).
- **Исправление:** изоляция сохранена, имя ограничено
  `.codex_tmp/wrs/<sha12>-<id8>`; regression фиксирует обе границы длины.

## 2026-09-01 — Clean-install smoke унаследовал несовместимый PSModulePath

- **Симптом:** Tauri и NSIS успешно создали `ЛЕС_5.1.676_x64-setup.exe`, clean
  install распаковал полный runtime, но первый bootstrap завершился как
  `bundled_runtime_unavailable`: Windows PowerShell не находил `Get-FileHash`.
- **Причина:** release-run был запущен из PowerShell 7/Codex environment;
  `windows_release_smoke.ps1` передал дочернему `powershell.exe` несовместимый
  `PSModulePath`. Быстрый prebundle gate уже нормализовал окружение, installed
  smoke — ещё нет.
- **Исправление:** installed smoke применяет тот же Windows PowerShell 5.1
  module path и удаляет dev `VIRTUAL_ENV/UV_*` перед обоими bootstrap-проходами.
  Установщик, bundled cache и пользовательские данные не были причиной отказа.

## 2026-09-01 — Полный Windows runtime не содержал package README

- **Симптом:** все release gates были зелёными, но локальный полный NSIS prepare
  падал внутри `uv sync --locked`; оркестратор показывал только exit code 1.
- **Причина:** `config/windows_runtime_manifest.json` включал `pyproject.toml`,
  где объявлен `readme = "README.md"`, но исключал сам корневой `README.md`.
  Hatchling не мог собрать staged локальный пакет. Захваченный stderr не
  добавлялся в ошибку верхнего уровня.
- **Исправление:** `README.md` включён в Windows runtime manifest; regression
  проверяет его как обязательную продуктовую поверхность. Local full builder
  возвращает bounded stdout/stderr исходного prepare-отказа. Это исправляет
  упаковку и диагностику, не меняя runtime-модель, RAG, сметное ядро или данные.

## 2026-09-01 — Patch release не учитывал worktree и несовместимый установленный runtime

- **Симптом 1:** release остановился до prepare, потому что искал attested
  `full-base/latest.json` только внутри feature worktree, хотя канонический feed
  находился в основном checkout.
- **Симптом 2:** после зелёных gates cumulative patch дошёл до acceptance и был
  правильно отклонён checksum guard: установленный
  `chat_evidence_application_service.py` не совпадал ни с deploy-stamp commit,
  ни с одной доверенной ancestry-ревизией даже после LF-нормализации.
- **Причина:** feed-resolution не учитывал общий `repo_root`; release
  classification не имела явного полного recovery-пути, а local full builder
  безусловно пытался использовать SSH.
- **Исправление:** канонический feed разрешается worktree-safe; `--force-full`
  фиксирует в receipt причину полного выпуска; `--host local` готовит exact NSIS
  локально и создаёт hard-update job для штатной acceptance. Произвольный SHA
  не добавляется в manifest, checksum guard остаётся fail-closed.

## 2026-09-01 — Harness мешал рабочей Qwen обратиться к RAG

- **Прямой baseline:** Qwen 3.5 9B без tools прочитала реальную ВОР, за несколько
  секунд сама сформулировала пять разных запросов; штатный RAG вернул по шесть
  карточек `SMETA_NORMS_Index` на каждый запрос, после чего та же модель оценила
  кандидатов.
- **Штатный harness на тех же входах:** tool-loop 19 раз подряд вызвал один и тот
  же `build_vor_workbook`, получил 19 `rejected` и завершился по deadline, ни разу
  не обратившись к RAG.
- **Вывод:** модель и RAG были работоспособны; отказ создал orchestration-код.
  Зелёные тесты не обнаружили это, потому что использовали короткое фиктивное
  вложение и заранее запрограммированные tool-call модели.
- **Инвариант:** приёмочный тест № 1 всегда сравнивает direct model baseline со
  штатным harness. Harness не проходит выпуск, если мешает модели получить
  evidence или результат. Подробный контракт — `docs/TEST_INVENTORY.md`.
- **Живое подтверждение полного пути:** Qwen 3.5 9B получила реальную ВОР из 19
  строк, сама сформулировала 19 запросов к явно выбранному `SMETA_NORMS_Index`,
  увидела ответы общего RAG и вернула 19 решений. Штатный
  `build_lsr_workbook_from_decisions` сохранил эти решения, выполнил структурную
  привязку/расчёт и создал XLSX. Число строк не является параметром harness.
- **Оставшийся продуктовый дефект:** установленный chat-контур передал вложение
  первому вызову, но не сохранил его в финальном вызове вместе с RAG evidence.
  Внешний запуск доказал архитектуру, но не закрывает пользовательскую кнопку:
  после терминального ответа модели ЛЕС обязан сам вызвать расчёт/упаковку и
  приложить XLSX к тому же ответу.
- **Цены:** после модельного выбора норм код может и должен заполнить ресурсные
  цены из выбранной/системной Сплит-формы и сохранить их provenance. Цена не
  выбирается моделью и не требует нового профессионального цикла.
- **Живая проверка pricebook без модели:** те же 19 неизменённых решений Qwen
  переданы штатному расчётчику с системной книгой
  `sankt-peterburg_2kv2026`. Код заполнил 77 ресурсных строк прямой текущей
  ценой и 71 строку как базовую цену × индекс; известная рассчитанная часть —
  `970 961,48 руб.`. Семь ресурсов честно требуют КАЦ, два — ставки машиниста,
  а две исходные строки сохраняют `unit_conflict`, поэтому результат правильно
  выпущен как `priced_partial`, не как согласованная финальная смета.

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
