# TEST_INVENTORY — текущая карта проверок ЛЕС

## Кандидат980 — соответствие поставки и владение денежным подтверждением

`test_lsr_repack_calculation_contract_980.py` добавлен в CURRENT_TESTS: версия
фактического расчёта/replay, LSR-only execution identity, versioned repack args,
точная projection даже `[]`, stale issued parent/child, сохранение старого файла,
existing UI repack priority и reconnect. Совместный guard/transport/price gate:
339passed/43.83s, `artifacts/offline_980/guard_green06.xml`. Соседние старые
positive fixtures отдельно приводятся к явному current calculation contract;
проверки конфликтов/overflow/неизменности строк не отменяются.

Consumer08:474passed/1failed — один current final-event fixture без версии;
исправлен только явной версией. Focused73passed/3.78s и architecture rc0
(`architecture_green09.xml`). Capacity fixture теперь явно содержит40k native
body при24k input; initial inventory должен дойти до инструмента, а полное
тело — всё ещё переполнить предел. Positive B0/B1 wire54k, negative B1 wire50k
и все assertions сохранены; производственные context guards не менялись.

В существующих owner-файлах, без нового test profile:

- `test_rim_lsr_trace_service.py`: cited/book-priced material/equipment без
  match, с no/unknown, пустым reason и устаревшими title/code/refset сохраняют
  строку, ресурс, количество и preliminary, но не confirmed/full amount.
  Проверяются точный yes, порядок refs, quantity/unit-only overlay, в том числе
  поверх модельного confirmed_price, actual operator price80/0 и последующее
  изменение количества. Реальный trace→readiness возвращает финансовый пробел
  в retry и сохраняет закрытого доверенного соседа.
- `test_model_lsr_result_contract.py`, `test_model_workbook_terminal_transport_962.py`:
  один объект supply_resource_match в JSON/native/табличном transport; title/code/
  decision/reason/refs не превращаются в предметное решение приложения.
- `test_resource_group_proof_932.py`: прямой supply debt без группы, stale yes,
  буквальные показанные записи, единый proof/receipt, сохранение соседей и
  operation/revision, ограничение4 с явным deferred count. Добавлены два случая
  существующих алиасов «материал»/«оборудование» без переписывания роли.

Доказательства в `artifacts/offline_980/`: transport GREEN142passed
(`transport_green01.xml`); первый финансовый GREEN22passed
(`supply_match_green01.xml`), пакет с quantity/unit overlay GREEN32passed
(`operator_overlay_green01.xml`). Это отдельные гейты, их counts не суммируются
в полную приёмку. OwnerGREEN03:316passed/10failed (`owner_green03.xml`),
положительные fixtures дорабатываются; alias RED2failed (`alias_red01.xml`).
Повторный guard gate339passed/43.83s (`guard_green06.xml`), repack/lineage/zero
consumers155passed/11.59s (`repack_green07.xml`). Metadata/calculation contract
прошёл RED→GREEN, включая reconnect; полный sheet capacity consumer проверяется
отдельно. `repack_contract_red01.xml` и `repack_metadata_red02.xml` сохраняются
как первоначальные RED-доказательства, не итоговая приёмка.
Полный gate, установка и live980 не пройдены; точность норм/90% и готовность
разных ВОР/ЛСР этими fixtures не доказываются.

## Кандидат979 — полные карточки и добор неопределённых решений

Existing `test_model_rag_grouped_evidence_service` проверяет точный общий
header, сохранение уникального preview и полных ресурсов/цен/нулей/Unicode,
byte-exact восстановление full, несовпадающие headers и прежнее НР/СП factoring
с действующими resource/fidelity checks. ROOT RED3failed/2passed.
Existing `test_plain_lsr_gap_continuation_976` проверяет unresolved role с/без
norm status: точные readiness/retry IDs, сохранение выбранного шифра, closed
соседа на том же адресе, evidence/cache/книги и исключение source-confirmed zero.
ROOT RED4failed → related270passed/12.44s (`green_related02.xml`). Tests не
назначают role=work и не служат приёмкой норм. Первый related run269passed/1failed
выявил неверное ожидание входного alias ID в новом zero fixture; проверка
исправлена на durable ID из сохранённого checkpoint, равенство всех строк до/после
продолжения сохраняется. Product-код после этого не менялся.
Доказательства: `artifacts/offline_979/`; новый test profile не добавлен.
По сверке с RELEASE_LEDGER полный979 завершён:6965passed/20skipped,
exact installer технически принят, установлен commit babaf652. Свежие
ordinary/B0979 не прошли профессиональную приёмку: цена книги не потеряна,
но ordinary ошибочно подтвердил кабель по цене монтажной ленты, B0 не посчитал
ни одной работы. Это основание узкого исправления980, а не customer PASS.

Первый full979:6964passed/20skipped/1failed (`prepare_console01/2_prepare.log`).
Старый exact-key test `test_money_states_23` требовал прежние пять buckets.
Теперь строго проверяет все шесть и role_unresolved.count0 у явных работ;
`test_plain_lsr_gap_continuation_976` дополнительно требует count2 у двух
unresolved операций. Ни один ключ/проверка сохранения не исключены. Related
529passed/61.96s: `artifacts/offline_979/contract_followup02.xml`. Это промежуточный
гейт; итог полного979 и отрицательная профессиональная live-приёмка указаны выше.

## Кандидат978 — найденные кандидаты доходят до reranker

Existing `test_smeta_norm_browser` проверяет непересекающиеся50+50карточек,
native tail в visible response после оценки, одинаковый pool для visible6/50,
dedup identity, measured CE-order без повторной fusion и disabled/error/partial
fallback (remaining input tail без вымышленных CE ranks). Existing
`test_smeta_rerank_ab_probe` проверяет полные stage traces/structured cards,
literal Unicode/пробелы в UTF-8 queries-file и invalid/conflicting CLI inputs.
ROOT pool RED2failed/1passed; probe RED2failed/6passed; CE-order RED3failed;
related GREEN78passed/3.38s:
`artifacts/offline_978/green_ce_order_related.xml`. Крупный test profile не добавлен.
Independent probe lookup RED1 после реальных normalized keys → related
norm/core/action callers228passed/20.91s (`green_final_related.xml`).
Полный978 gate:6956passed/20skipped; updater328passed. Exact installer собран,
но installed acceptance отказала при desktop restart из-за USERNAME,
не переданного локальным оператором. Runtime976 восстановлен/aligned98;
профессиональная применимость не подтверждена.
Existing ownership/held tests проверяют oldv1 empty/card → fresh literal search,
currentv2 replay и archived cache без потери авторских решений/дополнительного
model cycle. Existing gap/refinement tests проверяют finite aliases, exact IDs,
closed shared source и normal remarks; VOR/unknown target не становится plain
norm resume. RED cache5/gap3/kind6 → related111passed/18.62s.

## Кандидат977 — сохранённый файл, ожидание ревизии и печатная форма

Расширены существующие файлы; новый test profile/framework не добавлен.
`test_workbook_partial_draft`: authentic unknown-ID proof → accepted-only draft,
literal raw/audit сохранены; no accepted checkpoint/foreign source не упаковываются.
`test_proof_role_identity_972`: omitted expected/base revision не теряется перед
packet admission; stale update и явно неверное/cross-field ожидание отклоняются.
`test_vor_print_template_966`: actual VOR producer→plain resume, original title,
legacy fallback, unchanged nonplain correction/audit и точная SHA delivered revision.
`test_rim_trace_xlsx`: compact E–G, decimal/scientific boundaries/zero/signs,
сохранённые значения/формулы/денежные суммы и numeric price conversion H–K.
ROOT RED→GREEN:43passed/34.55s; related263passed/74.79s;
header/delivery/XLSX61passed/36.33s; CAS/header/packet/proof79passed/12.87s.
`test_model_phase_instruction_975` и `test_sheet_proof_context_admission_967`:
одна trusted PHASE_INSTRUCTION вместо дублирования в evidence-data, полный прежний
ответ/карточки/native chain, unchanged wire/count admission и durable pending proof.
ROOT RED3failed/33passed → related59passed/6.70s.
`test_smeta_norm_browser`: весь measured CE ranking запрашивается перед fusion,
reverse-order24-card control сохраняет CE-head и native-head без вымышленных ranks.
ROOT RED1 → related49passed/2.65s; существующие partial/failure/runtime-policy
controls сохранены. Staged live retrieval не квалифицирован по качеству норм.
Существующие930/pending975, model_rag_sheet_evidence_reads и native_read_scope956
проверяют новый контракт actual PHASE/checkpoint и exact accepted-only draft,
включая сохранённый unknown transport/raw proposal. Dead init spy заменён
проверкой реально отправленного query frame без преждевременных reader/terminal
обязательств; literal source/question и все прежние реальные read tool schemas сохранены.
Первый полный977:6919passed/7failed/20skipped; эти7ожиданий мигрированы без
дальнейшей правки production-кода. ROOT related72passed/15.20s и76passed/28.42s.
Повторный полный gate — `artifacts/offline_977/canonical02/receipt.json`;
installed/live977 не выполнялись. Fixtures не доказывают качество норм.

## Кандидат976 — обычное продолжение и честная готовность

`test_plain_lsr_gap_continuation_976`: exact shared-source operation IDs,
preserved accepted/evidence/cache/price basis, owner claim, held/proof/unfinished
priority, zero/VOR/ready guards, current vs stale financial snapshots и реальный
producer с двумя новыми model calls без автоматического цикла. ROOT RED16→GREEN16;
related continuation155passed/37.19s.
`test_lsr_candidate_confirmation_976` + прежний `test_lsr_norm_applicability`: открытый
match не закрывает применимость; положительный5yes candidate сохраняет активный
контракт; тот же шифр/расчёт, partial aggregate при неподтверждённой позиции.
Дополнительные owner/CAS случаи проверяют newer lineage и изменившийся snapshot;
никакой unclaimed job не может стать продолжением уже занятого producer.
`test_rim_trace_xlsx`: дробные0.375/0.000125, исходные/cached числа и денежный формат.
`test_model_query_ownership_975`: фактические reader measurements и honest cache replay.
RRF/basic smoke регрессии — в прежних test_rag_golden_set/test_basic_function_smoke.
363 файла CURRENT_TESTS (два добавлены, прежние не удалены); полный976:
6910passed/20skipped,9команд rc0. Exact installer976 принят; live-документы
профессионально незавершены, что не заменяется технической приёмкой.

## Кандидат975 — фазовый контекст, carrier и сохранное возобновление

`test_model_phase_instruction_975`/`test_model_index_context_975`: required READ-фаза,
None-wire/native chain, budgets и index-only scope; `test_model_result_carrier_975`/
`test_model_result_carrier_edges_975`: JSON после заголовка и прежние ambiguity guards.
`test_model_query_ownership_975`/architecture: active system-query call запрещён.
`test_safe_held_query_{resume,edges,unknown_sheet}_975`: cache replay/redeclare/unknown scope.
`test_pending_proof_checkpoint_975`: public checkpoint до/после actual read, pause,
явный человеческий resume только proof, scope/preset/stale/actual-read guards.
ROOT: related625passed/87.53s после изменений кода; это не full975 gate/install/live.

Installed974: main6741passed/20skipped и все9 gate-команд rc0, accepted install,
rollback/reapply и native EXE-only. Профессиональные ВОР/ЛСР controls отрицательны;
упаковка/структурные checks не означают customer-ready. Старые статусы ниже исторические.

## Кандидат974 — регрессии Windows rollback rename

В существующий `test_windows_native_boot_960.py` добавляются случаи временных
WinError5/32/33 в primary/recovery rename, ограниченного постоянного отказа,
неповторяемой ошибки, изменившихся filesystem preconditions и второго rename
с успешным либо неуспешным возвратом candidate. Проверки сохраняют original
exception, отдельную recovery note и прежние native/PID/identity guards.
Новых test-файлов нет. ROOT RED9failed/4passed →GREEN13passed; первоначальный
updater325passed/20,41s. Peer review добавил2 случая filesystem drift во время
retry sleep: оба дали RED; после post-sleep проверки final related99passed/2,48s
по native-boot и Windows application suites, включая15новых случаев.
Полный974 gate/install/live не подтверждены; ранний updater325 не объявляется
повторным полным прогоном после последней post-sleep правки.

Exact973 main suite завершена6726passed/20skipped, но `test-updater` вернулrc1
в исходном gate и append-only продолжении: два разных rollback-теста встретили
WinError5 в том же directory `os.replace`. Успешная main suite не заменяет
updater gate и не подтверждает установку. Фактически установлен971;972/973
отдельно не устанавливались. Профессиональный ordinary/B0 gate ещё открыт.

## Кандидат973 — явное чтение выбранной карточки

`test_optional_tool_choice_transport_973.py`: optional typed tool_choice,
неизменённый None wire, exact count/complete/stream parity, изоляция входного
dict, неверные/неизвестные функции до HTTP, явный отказ unsupported native
Ollama без fallback. Root RED36failed по отсутствующему полю, затем GREEN
152passed/1,90s вместе с прежними transport/token-count/native regressions.
`test_explicit_norm_proof_read_973.py`:23 случая selected/admitted identity,
чужой edition/alias/base/key, frozen budget, missing/conflict consumption,
legacy whitespace без повторного чтения, count/cloud/wire parity, complete
previous answer, ignored choice/native_chat/default и conservative/exact budget.
Root RED по отсутствующему контракту/передаче; дополнительный alias и legacy
no-repeat RED устранены до общего related275passed/36,26s.
967 budget regression теперь сравнивает неизменный полный input envelope
(messages+provider schema/choice reserve): меньшая schema не равна прежнему
message-only allowance. Отдельный capacity-edge тест ловит потерю choice bytes.
В прежнем catalog-файле добавлены4 проверки XLSX blank/headerless/merged:
Root2failed/1passed до правки и отдельный merged control1passed на прежнем коде;
catalog/header/quote/VOR structural related105passed/5,16s после правки.
Основной973 pytest:6726passed/20skipped; полный gate остановлен в updater,
install/live не выполнены. CURRENT_TESTS973 содержит352 файла.
Настоящий локальный transport-probe728/32 доказал только нативный вызов
конкретного reader; применимость нормы и качество документов он не проверял.

## Кандидат972 — proof identity и передача нуля

В CURRENT_TESTS добавлены `test_proof_role_identity_972.py`,
`test_proof_role_identity_pipeline_972.py`, `test_attachment_zero_preview_972.py`,
`test_lsr_numeric_string_zero_972.py`. Покрыты неоднозначная смена роли/unknown ID,
literal proposal/raw и durable pending, частичный proof, явное новое пустое ID,
несколько операций на одном source; настоящий XLSX в3раскладках колонок;
точные numeric-string-zero, underflow±1e-999999, неизвестный/ненулевой источник,
boolean/произвольный текст, прежние charge/resource guards, pipeline/retry/XLSX.
Старый969 negative«0» заменён произвольным текстом; допустимые числовые строки
теперь имеют отдельные positive/negative проверки, source-type guard сохранён.

Root RED: proof4failed/7passed; extension3функциональных failed и1неверное
ожидание служебной evidence_bindings; zero8failed/36passed. GREEN related
114passed/4,65s и pipeline1passed/2,20s. Полный972 gate:6663passed/20skipped,
5warnings, все9 команд rc0; отдельная установка972 не выполнялась.
Frozen971:6599passed/20skipped,9команд rc0. Его оба installed small7 файла
профессиональную приёмку не прошли. Это отдельная граница от зелёных тестов.


## Кандидат971 — ограниченное дополнение evidence

В CURRENT_TESTS добавлены `test_model_partial_card_supplement_971.py` и
`test_rag_evidence_budget_registry_971.py`. Первый проверяет целые префиксы,
атомарные aliases, ceiling/native reserve, отсутствие пропуска первого
непоместившегося тела, смену/недоступность счётчика после валидного wire и
фактические B0/B1 trace updates. Root RED8failed/1,65s; усиленный набор с двумя
предыдущими frontier-suite —42passed/5,22s.

Реестр проверяется через snapshot/save и настоящий `_local_context_budget`,
с изолированными Unicode/spaces путями. Root RED7failed/38,92s, смежные56passed/
108,59s; после независимой проверки GUI запрещает0 из-за семантики обычного
renderer. Последующая проверка положительного ограничения обязательна.
Независимая проверка добавила два воспроизведённых RED: GUI0 скрывал бы ordinary
evidence, а смена loaded-model hash при неизменной revision могла оставить
устаревший counted wire. Квитанция `independent_review_red.xml` содержит2failed;
оба случая исправлены: итоговые51passed/48,87s
(`artifacts/live_970/diagnostic971/independent_review_green01.xml`).
Полный frozen971 gate, installer и installed live пока pending.

Базис970: `artifacts/gates_970_final_v3/receipt.json`, все9 команд rc0,
6580passed/20skipped; exact970 установлен. Его живые файлы остаются частичными.
Диагностические короткие вызовы Qwen с полными карточками не являются
release-доказательством: source fidelity и ≥90% применимости не подтверждены.

## Кандидат970 — три измеренные границы документа

В CURRENT_TESTS добавлены три файла970. Полный frozen gate, точный установщик
и installed live-приёмка970 пока не выполнены; установлен969/4ca27dd4.

`test_norm_card_complete_delivery_970.py`:10 случаев actual page→binder,
неполный preview против полного native read той же immutable карточки,
чужая редакция, противоречивый header/meta, неизвестный legacy-факт,
подделка модельных полей и один существующий bounded proof без замены нормы.
Первый осмысленный RED после исправления FrozenInstanceError fixture:
7failed/3passed; после product fix10passed/2,73s. Связанные10suite:
202passed/30,49s (`artifacts/live_970/offline_targeted/core_adjacent.xml`).
Усиленный финансовый тест проверен root вместе со всем файлом:10passed/3,27s
(`artifacts/live_970/serial_verification/strong_financial.xml`). При полностью
прочитанной карточке и выбранной книге сумма подтверждена; тот же preview
оставляет ровно ту же сумму предварительной с единственной причиной unread.

`test_vor_quantitative_metadata_exclusion_970.py`:32 случая количественной
исходной строки, оставленной только metadata без объяснения; header-bound
единицы, ноль/отрицательное значение, aliases, sibling operations, неизвестные
и неполные каталоги. Реальный public build→XLSX→readiness, literal authored
решения не меняются. RED16failed/16passed; GREEN32passed/1,18s. Связанные8suite:
272passed/17,82s (`artifacts/live_970/offline_targeted/vor_adjacent.xml`).

Первый frozen970 на263327a9 остановился до pytest: runtime-map rc0,
architecture guard увидел workbook invocation и проверку текста вопроса
в одной test-функции. Чистая проверка текста вынесена в отдельный helper;
guard, product code и все assertions сохранены. RED-квитанция остаётся в
`artifacts/gates_970_final/receipt.json`; повтор требует нового exact HEAD.
После разделения96passed/2,77s в metadata+architecture suites,
`artifacts/live_970/offline_targeted/metadata_arch.xml`; guard не изменялся.

Frozen V2/60182971:6579passed/1failed/20skipped/908,07s. Единственное расхождение —
старый `test_model_evidence_delivery_frontier` ожидал selected-card body=true у
явного incomplete preview. Уточнён только этот expected verdict: citation и
resource-code proof остаются проверяемыми, raw body/replay/bindings неизменны,
а долг полного чтения явно сохраняется. Production-код после60182971 не менялся.
V2 RED receipt сохранён; новый полный gate требует нового exact HEAD.
После уточнения frontier:18passed/3,22s, два полных файла frontier+complete-card
(`artifacts/live_970/offline_targeted/card_frontier.xml`).

`test_lsr_zero_repack_history_970.py`: два случая source0 с ненулевым либо
неизвестным соседом. Реальные registry/trusted executor/adapter/RIM/XLSX,
bounded history и public readiness; model tripwire, изолированные attachment/
job/artifact roots и отсутствующие pricebooks. Точные persisted operation IDs,
сохранность исходника/решений/evidence/cache и replay ревизии проверяются
вместе с исключением только подтверждённого0 из research targets.
Первый RED:2 KeyError charge_not_required. После минимального whitelist fix
проверка дошла до двух неверных fixture-ожиданий literal IDs; тест исправлен
на реально сохранённые canonical IDs. Targeted:72passed/3,22s,
`artifacts/live_970/offline_targeted/zero_history_v2.xml`. Новая suite включена
в CURRENT_TESTS; полный frozen gate и installed970 ещё не подтверждены.

## Кандидат969 — регрессии измеренных границ968

CURRENT_TESTS содержит341 уникальный файл. Related targeted:316passed/6,29s
(`artifacts/live_969/offline_targeted/core_v2.xml`) и233passed/7,15s
(`artifacts/live_969/offline_targeted/adjacent.xml`); наборы пересекаются.
После V2 budget-regression:110passed/40,28s по carrier/actual wire/quantity/
ownership suites (`artifacts/live_969/offline_targeted/compact_adjacent.xml`).
Все прежние wire/input лимиты сохранены; полный V2 остаётся RED9fail и не
используется как release-доказательство.
Полный frozen969 `artifacts/gates_969_final_v3/receipt.json`, commit4ca27dd4:
все9команд rc0,6536passed/20skipped за903,76s. Точный установленный969 прошёл
upgrade/rollback/reinstall/native-only,18/18 retention и basic smoke9pass/1warn.
Это техническая приёмка: реальные B0/B1 выдали частичные файлы7строк,
calculated_positions=0; точность норм≥90% не подтверждена. У B1 телеметрия
исполнения rerank UNKNOWN, не PASS и не доказанный отказ retrieval.

- `test_lsr_zero_charge_observation_969.py`: каталогом доказанный numeric0,
  смешанные zero/nonzero работы, неизвестные/bool/text/nonfinite, явный calc/
  quote/ресурсы/норма; одна граница validator→RIM→XLSX→readiness/retry.
- `test_resource_price_scalar_measures_969.py`: оба реальных калькулятора,
  authoritative quote до конверсии, физическая инвариантность, большая/знаковая/
  нулевая величина, обратимость, прежний SI/identical-unit порядок, group/manual/
  conflict/overflow guards, actual supply→LSR и формулы/кэши XLSX. Отдельно
  HALF_UP для cent ties новой numeric_measure ветки; старый round не заменяется.
- `test_lsr_uncomputed_norm_components_969.py`: parser/compact deep-copy,
  неполнота base/quoted/covered позиции, отдельные соседние операции, отсутствие
  основной нормы, malformed literal и длинный безопасный аудит без потерь;
  ни авторского коэффициента, ни работы код не создаёт.
- `test_lsr_additional_norm_prompt_969.py`: explicit additional-row инструкция
  во всех LSR carriers, прежние исходные объёмы/scale/covered правила, отсутствие
  сметных требований в ВОР и literal roundtrip без сгенерированных операций.

Смежные `test_sovushka_chat` проверяют actual nested history follow: no artifact,
plaintext, старый файл/текущий отказ, current partial, legacy LSR и legacy VOR.
В `test_resource_price_unit_conversion` только две совместимые числовые меры
перенесены из отрицательных в положительные проверки общего правила.
Исторические byte pins948/950 сохраняются через точное обратное удаление новых
instruction literals; прежние budgets и semantic guards не ослаблены.

## Кандидат968 — регрессии установленных отказов967

`test_workbook_collection_terminal_binding_968.py`:22case, root/member binding
на реальном transport→packer и B0/B1, второй файл в remaining, foreign/empty/
ambiguous origins/SHA, неизменные raw0/null. `test_lsr_same_source_quantity_scope_968.py`:
17case, несколько операций по одному адресу, доказанная мера, unknown/identity/
duplicate/tail guards. Один прежний fixture исправлен: валидный sibling сохраняется,
невалидный остаётся proposal; прочие проверки не удалены.
`test_rim_explicit_derived_quantities_968.py`:51case, calc_unit/SI/масштаб,
противоречие/overflow, signed/zero и quote quantity. Related242passed/31.58s.
`test_lsr_derived_quantity_presentation_968.py`:3case, контракт, видимая формула,
неизменные решения и обычная строка без выдуманного пересчёта.
Root compact+snapshot+tiny-context25passed/4.48s: бюджеты и card assertions
не ослаблены. Два прежних byte pins восстанавливаются обратными literal
изменениями. Новые файлы включены в CURRENT_TESTS.

Первый frozen968:6280passed/11failed/20skipped,844.06s. Шесть отказов проверяли
прежнюю формулировку масштаба, пять — границы native evidence/context. Исправлено:
старая инструкция масштаба восстановлена буквально; root/member-пояснение даётся
только комплектам, одиночный terminal instruction сохранён byte-exact. Убраны
лишь повторные optional names из хвоста; все поля по-прежнему явно объявлены.
Без изменения budgets/fixtures/assertions: весь evidence_reads61passed/23.27s;
12 смежных suites392passed/17.07s, включая полный chat_evidence_application_service.
Квитанции: `artifacts/live_968/gate_boundary_repair/`. Первый RED сохранён отдельно;
повторный полный gate и installed live968 pending.

V2:6295passed/20skipped/842.73s,332files,9rc0. До установки добавлен
`test_norm_card_cited_pointer_debt_968.py`:20cases, реальный binder→proof helper
и native chat seam. Bare code остаётся конфликтом, но exact cited typed pointer
получает отдельный долг чтения. Проверены неизвестные/неоднозначные ссылки,
разные редакции, full identity под другим alias/global hit, forged model fields,
replay и прежние qualified verdicts. RED4failed/13passed; peer ambiguity RED1failed;
после исправления uniqueness всех typed identities —77passed/7.57s с4смежными
файлами; root7suites369passed/31.67s. Квитанции:
`artifacts/live_968/cited_pointer_debt/`; новый полный gate
и установленная live-проверка pending, прежний зелёный V2 не подменяет их.

V3:6315passed/20skipped/844.40s,333files,9rc0. Два последующих fresh installer
prebundle завершились ошибкой bundled uv при Windows PE resources (`-2147024891`),
до сборки NSIS; установленный967 не менялся. Новый
`test_windows_uv_sync_retry_968.py`:15случаев actual PowerShell helper/environment
block с fake native uv, ограничение повтора, прежние аргументы, EAP, stale marker,
следующий запуск, redaction и import smoke. RED подтверждён; related95passed/52.80s.
В CURRENT_TESTS также включены затронутые `test_installer_windows`,
`test_windows_venv_contract`, `test_windows_prebundle_smoke`; их guards не удалены.
Два чистых изолированных bootstrap со staged working-tree PS прошли67.937/67.609s:
реальные bundled deps, API/UI на8052/8053, canonical cleanup; installed967 не менялся.
`artifacts/live_968/bootstrap_retry_probe/` — debug-only, не installer acceptance.
Очередной точный gate/install pending.

967 V3:6202passed/20skipped/834.20s,328files/9rc0. Exact NSIS0028ff8a…,
packaged native80236fbc…,517files; install/rollback/reinstall/EXE-only и basic
9PASS/1WARN. Capacity обоих новых B0/B1 measured_pass, input131072/answer32768.
Технические доказательства не заменяют профессиональную приёмку документов.

## Кандидат967 — измеренные границы установленного966

966 V2 завершён:6171passed/20skipped/818.65s,325files,9commands rc0;
exact NSIS/upgrade/rollback/reinstall/EXE-only приняты, basic9pass/1warn.
Live B0/B1 создали файлы, но нормовая/финансовая приёмка не закрыта.
Основные frames реально32768; два B1 proof вызова без отдельных Governor
receipts оставляют общий capacity verdict unknown. Это не причина считать
резерв этих вызовов доказанно16k и не основание ослаблять guard.

`test_windows_reranker_bootstrap_967.py`:21case, реальные Python loader и
изолированные штатные PS helpers, persisted/process/default и явный false.
RED13failed/8passed → adjacent56passed/9.07s.
`test_nrsp_catalog_reference_967.py`:4case, canonical ID и hash контейнера,
двухправильный каталог, literal preservation, отсутствие автомаппинга.
RED3failed/1passed → grouped93passed/0.83s; adjacent235passed/32.18s;
context/capacity319passed/26.92s.
`test_sheet_proof_context_admission_967.py`: собственный existing Governor
для двух proof requests, сохранность author rows/source/evidence, явный
technical overflow без нового предметного решения.6cases, включая два настоящих
вторых хода «Продолжи»: прежние строки terminal/complete, без новых вызовов,
паузы или pending. RED выявил обход admission и zombie continuation;
исправленный adjacent:127passed/28.53s. Root независимые3новых suite:
31passed/12.16s, `artifacts/live_967/root_independent_final.xml`.
Все три файла включены в CURRENT_TESTS. Full967 V2:6197passed/20skipped/
5failed/833.88s,328files. Все5отказов — прежняя SHA инструкции в2VOR suites:
намеренно уточнён только nr_sp_rule_id. Проверки сохраняют прежний SHA после
ровно одной обратной замены этой фразы и дополнительно фиксируют новый SHA;
остальные инструкции не разрешено менять. Related3suite24passed/4.34s,
`artifacts/live_967/lsr_instruction_sha_alignment/targeted.xml`.
Первый RED сохранён отдельно;
повторный full gate и installed live pending.

## Кандидат966 — шаблон ВОР, Windows retention, namespace добора

Первый full966:6155passed/20skipped/16failed/820.05s. Отказы — прежние
active-sheet coordinates в4transport/workbook suites плюс их5повторов внутри
hermeticity830. Контрактные assertions перемещены на именованный canonical ВОР,
добавлены проверки печатного active и rawJSON; ни одна денежная/источниковая
проверка не убрана, hermeticity suite неизменён. Related5files124passed/6.47s,
`artifacts/live_966/print_template/active_sheet_contract_final.xml`.
Full V2 завершён:6171passed/20skipped/818.65s,9commands rc0;
первый RED сохранён отдельно.

`test_chat_attachment_retention_966.py`:12case; общая OS-lock между пятью
lifecycle API и независимым процессом, два first pin, освобождение при crash,
ограниченный видимый timeout, no-resurrection/current metadata и сохранность SHA.
Исходная конкурентная регрессия965 не ослаблялась. RED WinError5 сохранён;
13 adjacent suites349passed/2skipped/39.76s:
`artifacts/live_966/retention/adjacent_final.xml`.

`test_lsr_multifile_gap_identity_966.py`:14case; реальный генератор gaps,
namespace `::`, Unicode/metadata/двоеточия, неизвестные/legacy статусы, повторные
операции на общем адресе. RED10failed/4passed; GREEN с5related suites122passed,
10.30s: `artifacts/live_966/multifile_gap_identity/`.

`test_vor_print_template_966.py`: first five-column printable view, unchanged
canonical rows/audit,0/null/derived measures, множество строк/файлов и повторный
intake без дублей; fake/modified view сохраняется как источник с warning.
15 новых cases с aliases/1/37/318работами; related82passed/4.97s, no deselect.
Root combined6files156passed/13.43s: `artifacts/live_966/independent_review.xml`.
Отдельный test в collection suite проверяет literal formula-like filename.
Все три файла включены в CURRENT_TESTS. Полный frozen966, installed32k B0/B1,
инженерная точность, добор и big stop/resume — отдельные обязательные доказательства.

## Кандидат965 — вместимость и комплект исходников

Полный964:6054passed/20skipped/9failed/814,93s. Семь отказов связаны с ростом
служебного workbook-result текста и потерей evidence/native capacity; их
исправление — меньший фазовый текст при прежних лимитах, без удаления карточек.
Два устаревших fixture expectation обновляются под действующий формат профиля
и keyword `include_retry_token` с сохранением прежних проверок данных.
Четыре связанные suite после ремонта контекста:319passed/26,00s;
`artifacts/live_965/context_repair.xml`. Полный965 и installed live pending.

`test_attachment_collection_965.py`:39cases, с adjacent212passed/7,08s.
Проверены точные байты/SHA, разные количества файлов/строк, trusted контейнер,
namespace и literal cells, unread blockers, native source provenance вне frame,
93строки/3файла без дублирования origins в model render, VOR/LSR packaging,
источник в человекочитаемой «Проверке»,0/null, forged provenance и TTL/restart.
Файлы с одинаковыми bytes и разными IDs сохраняются отдельно; повтор одного
ID/alias отклоняется до фиксации parent. Библиотечный source expiry не удаляет
успешно использованный single/collection; неверный SHA не получает pin.
Конкурентный pin: оба reader доходят до markerFalse и записи temp, оба успешно
завершаются, sourceSHA/bytes прежние, незавершённых временных файлов нет.

`test_chat_attachment_collection_ui_965.py`:20cases, с adjacent276passed/13,76s.
Batch ordering/session/epoch, ошибки и запрет prefix-send, автоматический parent,
stale parent/new selection, сохранение другого чата/вкладки, оба входа истории,
снятие uploaded без reset активной загрузки, прежние quick/index и singleton.
Регрессии registry:7passed/5,27s; действительный TTL default604800, source,
restart boundary и отказ нецелых/неположительных значений до записи настроек.
Квитанции — `artifacts/live_965/attachment_collection/`. Это scoped offline
доказательства, не установленная профессиональная приёмка.
Дополнительная проверка11связанных attachment/source маршрутов:367passed/1failed
(старая `_Cat` без штатных row_origin/locator),53,16s. Заглушка получила точный
пустой single-file origin; прежние проверки неизменности model cells сохранены.
Повтор одного исправленного случая и7registry cases:8passed/5,65s. Обе
квитанции сохранены: `retention_adjacent.xml`, `retention_adjacent_repair.xml`.

## Регрессии964 — текстовый carrier и сохраняемая подсказка добора

`test_model_quoted_text_scalar_964.py`: фактическая форма явных multiline
записей из live963, complete JSON-string scalar, буквальное сохранение
решений/raw, пустые/escaped значения,0/null и quoted"null", duplicate fields
до отбрасывания пустого значения, несколько операций одного source_row,
operation_id-first list/CAS fields и пустая норма у незакрытой работы ЛСР.
Не допускает интерпретацию YAML-выражений, nested/non-string/trailing payload
или конфликтующих типов. Общие правила обычного ответа не запрещают формат
активного документа, сохранённый prompt не переписывается. Первый adjacent
текстового carrier:99passed; полный гейт кандидата ещё требуется.
После отрицательных границ и проверки вместимости:177passed, включая
literal resource capacity/native continuations/неполный draft. Это scoped
проверка, её результат не заменяет frozen gate или реальную ЛСР.

`test_lsr_gap_hint_resume_964.py`: сохраняемая дословная подсказка и точные
pending ID при прежнем вопросе/ценовой базе, настоящие SQLite межоперационные
конфликты, повторный клик/устаревшая карточка/новый ввод и неприменённый POST,
обычный native LSR review без расширения на закрытых соседей. Первый scoped
run58passed, adjacent402passed; это пересекающиеся проверки, не release gate.
Финальный targeted run83passed и adjacent402passed после peer-замечаний;
квитанции и первый непройденный fixture сохранены в `artifacts/live_964/gap_hint/`.
Оба файла включены в CURRENT_TESTS. Установленный UI, повтор подсказки и
профессиональный результат требуют живого доказательства точного кандидата.

## Регрессии963 — авторская оболочка и отсутствие query-типа

`test_model_query_wrapper_963.py`: actual784char replay с7запросами, сохранение
Vor/commentary и равенство прежнему canonical reader; недоверенный wrapper
не становится runtime facts. Негативы: extra metadata/rows/results/цены,
duplicates/два JSON/конфликт/невалидные queries.48новых cases;241смежный
и124граничных проверки прошли до полного gate.
`test_model_workbook_unknown_terminal_963.py`: explicit empty type позволяет
один выбранный моделью Vor/LSR terminal; omitted/None сохраняет legacy Vor.
Mixed/два terminal/видимый конфликт/raw guards неизменны. RED12→GREEN128 с adjacent.
`test_model_document_kind_availability_963.py`: actual B0/B1 при missing-kind,
оба доступных optional tools, единый прежний packager, literal решения и
отсутствие лишнего inference; условный ВОР и обычное чтение без документа.
Компактный production-вариант:204passed, включая прежние ограниченные wire-cases;
полный frozen gate и installed live ещё требуются. Десять исходных падений
первого adjacent замера сохранены, лимиты ради зелёного не увеличивались.
Первый полный963:5985passed/20skipped/3failed. Legacy exact-card tests теперь
требуют byte-equal readers + ровно оба optional terminal для missing type;
проверки настоящих READ, literal decisions и source facts сохранены. Прежние
conditional wording/LSR SHA/компактность сохранены. Целевой повтор80passed;
новый полный frozen gate обязателен перед установкой.

## Регрессии962 — literal native terminal и запрет spec-copy

`test_model_workbook_terminal_transport_962.py`: сохранение исходных аргументов,
авторских строк/дополнительных полей/ID/0/null, одного источника для нескольких
операций, отказ при duplicate JSON fields, mixed/multiple calls и двух
противоречащих carrier-ответах. Schema сужает технические адреса, не выбирает работы.
`test_model_evidence_terminal_boundary_962.py`: native-only/empty text/max_reads0,
read→terminal, точность обычного текста и отсутствие лишнего чтения/упаковки/
model continuation. RED5→GREEN63 вместе с adjacent read/native reasoning.
Canonical workbook tests проверяют missing/None decisions до checkpoint,
явный[] как пустой черновик, literal ID/revision и отдельный legacy reader.
`test_vor_native_terminal_workflow_962.py`: одинаковые optional tool schemas
в B0/B1, native-only результат после чтений, сохранение прежних ID/revision
при обычном пересмотре и техническая остановка при противоречащих carrier,
другом attachment или усечённом ответе. Pure transport focused: 170 passed;
main capacity/adjacent: 273 passed; canonical workbook совместимость:
332 passed. Это пересекающиеся точечные suites, не суммарный release гейт.
`test_lsr_supply_retry_962.py`: отдельная поставка остаётся самостоятельной
только по явному отношению модели с pinned/delivered выбранной карточкой.
Общий keep_all_confirmed, разные шифры и непроверенные ссылки не снимают
overlap. Старое exact исключение сохраняется. Финансовый retry выбирает
неполные операции и сохраняет закрытых соседей. Immutable feedback не
переиспользуется при другой строке/revision/источнике/книге или без её SHA.
Nested refs имеют собственные immutable bindings при первом ходе и replay;
повтор alias на другую карточку не меняет источник решения. Реальный XLSX
сохраняет literal reason/refs отдельной поставки. Resource/trace/adjacent:
301 passed.
`test_lsr_native_feedback_962.py`: активный запрос сохраняет калькуляторную
проекцию при упаковке; обычное замечание получает точные финансовые вопросы
той же ревизии, а native результат обновляет прежние ID без изменения parent.
Все пять новых файлов добавлены в CURRENT_TESTS.
Первый frozen gate962:5890passed/20skipped/10failed. Шесть старых fixtures
обновлены для явных авторских work rows/ролей и раннего отказа ВОР без decisions;
прежние проверки ценовой базы, scope, checkpoint и revision сохранены. Четыре
read-scope cases отдельно проверяют неизменные reader schemas и ровно
один соответствующий объявленному типу optional terminal. Две дополнительные
парные проверки сравнивают все schema каждого фактического read frame B0/B1.
Точечный повтор:7passed для шести fixture-падений с параметризацией;
read-scope/terminal/read-boundary:56passed. Первичный failed
receipt сохранён; повторный полный gate и live962 ещё требуются. Unit mocks
не являются приёмкой модели.

## Регрессии961 — XLSX source metadata и release version hygiene

`test_xlsx_literal_metadata_961.py`:40случаев шести print parts/трёх секций,
полных classic comments/rich text/author/ref, hidden/empty cells и notes-only
листов, exact lookup/manifest/frame context и неизменного work denominator.
Unknown XML/text/tails/threaded comments/pictures остаются warning. Устаревшие
955 unread assertions заменены усиленными проверками фактически прочитанного
body/refs; никакая warning не снята без предоставления исходного содержания.
RED39failed/1passed; private GREEN совместно с adjacent:181passed.

`test_software_versions.py` проверяет синхронизацию единственной local editable
project version в uv.lock при неизменности всех dependency records.
REDKeyError до исправления, затем6passed. Frozen961:5729passed/20skipped,
updater312passed, все9команд rc0. Установленный mixed CSV7 и обычное уточнение
проверены; DOCX и общая профессиональная приёмка остаются незакрытыми.

## Регрессии960 — native reasoning и Windows boot

`test_native_reasoning_frame_960.py`: 9 случаев actual B0/B1 message boundaries,
точного сохранения source/cards/native chain, required cue/whole-wire budget,
None/empty/whitespace compatibility и запрета активации untrusted reasoning.
Прежние current-read-frame tests обновлены только для явно непустого reasoning;
их ограничения бюджета и проверки содержимого не ослаблялись.

`test_windows_native_boot_960.py`: 26 behavioral случаев native-first boot,
точной identity при rollback, отдельной recovery error и guarded foreign PID
для 9 hard/soft маршрутов. Headless helpers неизменны. Оба новых файла включены
в CURRENT_TESTS, updater-файл также в отдельный updater gate.
Focused результаты до full gate: 69 reasoning-related + 99 updater-related PASS.
Они не заменяют установленную приёмку и профессиональную проверку документов.

`test_vor_operation_basis_960.py`: 18 случаев false-green при неверном endpoint
work, совместимости blank/self/source/operation_id и cross-packet relationships,
дословного экспорта решения, замечаний в readiness и следующем обычном review.
VOR-only instruction проверяется отдельно от неизменного LSR contract; кейсовых
шифров/изделий нет. Файл входит в CURRENT_TESTS. RED8failed/10passed, GREEN
совместно с94 прежними VOR-проверками:112passed; это не live quality acceptance.

## Регрессии959 — транспорт запросов и пользовательская проекция

`test_model_query_declaration_transport_959.py` проверяет actual B0/B1 callsites:
literal Unicode queries в native arguments, `tool_calls` finish, ошибочные arguments,
один прежний repair, unknown/stale capability и точный text fallback при overflow
схемы. Если оба кадра не помещаются, модель не вызывается. Это протокольное
доказательство; качество норм и скорость требуют установленного сравнения.
`test_workbook_pending_source_progress_959.py` отделяет число исходных адресов от
числа операций и пересмотра. `test_model_output_observability_959.py` проверяет
reported reasoning usage и размеры каналов без публикации текста размышлений.
`test_sovushka_chat.py` проверяет ВОР-блок без
требования нормы, исходные/расчётные величины, связи и неизменность ЛСР-проекции.
`test_workbook_primary_artifact_959.py` проверяет совпадение экспортированной
revision в history/job/final при навигационном реестре; отсутствие workbook
сохраняет прежний выбор основного навигационного артефакта.
`test_windows_hard_rejection_recovery_959.py` проверяет возврат прежнего запуска
при pre-move отказе после stop, fail-closed disk identity и отдельное сохранение
исходной ошибки и ошибки восстановления. Это не live-приёмка установщика.

## Регрессии958 — идентичность сохраняемого пересмотра

`test_pending_review_operation_identity.py` включён в CURRENT_TESTS. Actual sheet
fixtures проверяют JSON/Markdown без ID: семь прежних операций остаются, семь
ожиданий сохраняются, ответы доступны как proposals, дополнительных вызовов нет.
Корректные ID/ревизии обновляют только выбранные операции; явно новые работы
разрешены. Отдельно проверены технические алиасы ID/локатора закрытой соседней
операции, разные admission scopes и отсутствие предметного сопоставления кодом.
Live-результат и профессиональная корректность проверяются отдельно от fixtures.
`test_workbook_latest_identity_projection.py` также включён в CURRENT_TESTS:
большие данные чужих заданий не декодируются и не выбираются полностью, при этом
сохраняются newest/session/attachment/оба ID и полный результат выбранного задания
с его документом. Старая сессия находится после201 новых чужих заданий, в том числе
при limit1. SQL trace и row factory проверяют фактическую проекцию и ранний scope.

## Регрессии957 — остановка выполняющегося вызова

`test_workbook_model_call_cancellation.py` включён в CURRENT_TESTS: настоящий
hanging await и штатный pause API временного store, cleanup, независимые jobs,
готовый response/stop race, отсутствие следующего вызова, видимые сетевые ошибки.
Actual sheet fixture останавливается на query/native continuation с сохранёнными
строками и карточками; частичный файл упаковывается, job gate освобождается.
Эти тесты не доказывают остановку генерации внешним провайдером — нужен live.

## Регрессии955 — сохранение решений и явный повторный проход

956 дополняет `test_vor_task_instruction_955.py`: явный vor получает собственный
native read-contract, lsr/unknown сохраняют прежний строковый контракт; tools и
evidence не меняются. Проверяется передача буквального типа в packet/direct
callsites в `test_vor_native_read_scope_956.py` (включён в CURRENT_TESTS).
Это structural/behavior tests, не доказательство профессионального
качества ВОР модели; установленный B0/B1 фиксируется отдельными квитанциями.

В CURRENT_TESTS включены `test_workbook_gap_followup_955.py`,
`test_unresolved_retry_routes_955.py`, `test_retry_target_projection_955.py`:
сохранность baseline/цитат/ценовой базы после нового store и продолжения,
открытая и закрытая операции одного source_row, stale/source-conflict replies,
пустой ответ, terminal job и пустые targets, проверки session/attachment/running.
Завершение с неотвеченными targets остаётся на паузе; сохранённые решения не
удаляются по omission. Прежние контрактные тесты review/readiness обновлены
под этот заявленный продуктовый контракт, source/revision guards сохранены.

`test_csv_literal_boundaries_955.py` проверяет delimiter вне кавычек, multiline
и физические адреса, BOM/CP1251, Unicode-пути и нулевые значения.
`test_xlsx_unread_metadata_955.py` проверяет предупреждения о непрочитанных
комментариях и всех шести вариантах колонтитулов; это не тест их извлечения.
`test_vor_task_instruction_955.py` проверяет различие требований ВОР/ЛСР и
managed factory-overlay без изменения immutable snapshot/custom skill.
Тот же файл проверяет межпакетный accepted_work_index, настоящий двухпакетный
обмен и наличие индекса в каждом позднем query/reader/answer. Нули, null, названия,
ID и ревизии не переписываются;318 работ помещаются в131072 query/answer без omissions.
Тот же тест проверяет буквальную обратную связь о пяти признаках применимости:
проза остаётся unknown, исходные строки/цитаты не меняются; ВОР без нормы не
получает новых требований. Явные MODEL_GAP_REASONS сохраняются при техническом
norm_not_found, при этом cipher-without-citation корректно уступает точному
machine-факту отсутствующего шифра. Ни один из этих фактов не выбирает норму.
Проверки professional B0/B1 и installed955 фиксируются отдельно после freeze;
сам по себе этот offline-набор не подтверждает готовность ВОР/ЛСР заказчику.

## Регрессии954 — контекст типа при разборе строк

`test_model_packet_document_context_954.py` включён в CURRENT_TESTS:
нормы не требуются от уже объявленной ВОР при Markdown/текстовых пакетах;
B0/B1 и три последовательных пакета сохраняют авторские строки. Неизвестный
тип не назначается ВОР; явный новый тип и конфликты имеют прежнюю силу.
Реальный сохранённый ответ953 проверен отдельно: прежний parser терял все
семь строк, исправленный сохраняет их без изменения raw и предметных полей.
Это проверка транспорта, а не профессиональная приёмка ВОР.

Frozen gate954/2958602c:5305 passed/20 skipped;9 команд rc0, updater286/286.
Installed smoke10/10 и nativeRRF rc0. Реальные DOCX и CSV проверены B0/B1:
сохранность принятых строк подтверждена; профессиональный full-VOR gate не пройден.
Точные результаты/ограничения — RELEASE_LEDGER и `artifacts/live_954/`.

## Регрессии953 — два согласованных транспорта и факты review

В CURRENT_TESTS включены `test_equivalent_artifact_transport_953.py` и
`test_vor_review_structural_facts_953.py`.
Эквивалентная plain+JSON пара проверяется на vor/lsr и реальном sheet-pass,
включая неизменённые rows и частичную готовность. Отрицательные случаи сохраняют
duplicate keys, два JSON, два plain label, конфликт типов и неполный JSON.
Факты review проверяются отдельно: полный prior graph, корректная межпакетная
связь, неизменность строк и отсутствие нового модельного цикла.
Durable regression сохраняет Vor review → новый текущий LSR → pause → новый store
→ plain continuation: тип прежнего результата и факты остаются Vor, текущий — LSR.
Повторный показ авторского расчёта сохраняет также `calc_unit`; поле уже было
в контракте и экспорте949, но отсутствовало в compact replay whitelist.

## Регрессии952 — подпись количества и повторное чтение

`test_vor_authored_measure_provenance_952.py` включён в CURRENT_TESTS: null,
явный ноль, дробь, прежняя колонка F отдельно от расчётной Q, реальный экспорт
модельного нуля при пустом источнике. Подпись не утверждает происхождение,
rawdecision и исходный файл сохраняются, расхождение остаётся видимым.

## Регрессии951 — технический этап без потери исходника

`test_model_query_phase_request_951.py` входит в CURRENT_TESTS: реальные B0/B1
query и repair, одинаковые этап/вопрос/источники, неизменность payload вызывающего
кода, отсутствие дополнительного модельного цикла и fail-closed budget overflow.
Старый `test_model_vor_export_instruction.py` сохраняет существенные условные
правила ВОР/ЛСР. Эти тесты не подтверждают профессиональное качество генерации.

## Регрессии950 — неопределённый тип документа

`test_vor_candidate_scope_950.py` проверяет, что системные сметные добавки не
включаются для неопределённого типа или ВОР. Запросы модели сохраняются;
явная новая ЛСР после ВОР допускает добавки. Неопределённый конечный тип
получает условные контракты, а явная ЛСР — прежний неизменённый контракт.

## Регрессии949 — расчётный объём и доставка ВОР

В CURRENT_TESTS добавлены `test_vor_derived_quantity_export_949.py` и
`test_vor_delivery_notice_949.py`: исходный объём отдельно от авторского
расчётного, разные физические единицы, ноль, неизвестные исходные величины,
некорректные расчёты, повторный intake XLSX и сохранный JSON-аудит.
Конечный B0/B1 application-path проверяет ВОР без обязательных внешних
сметных ссылок; выбранная норма и явно указанные ссылки по-прежнему проверяются.
Технические ошибки ВОР не описываются как частичная ЛСР. Это офлайн-регрессии,
а не доказательство профессионального качества произвольного документа.

## Регрессии948 — ВОР, запросы и восстановление

В CURRENT_TESTS добавлены test_vor_workflow_contract_948,
test_vor_result_integrity_948, test_vor_operation_instructions_948,
test_docx_empty_notes_948. Они проверяют буквальные JSON-запросы, отсутствие
ложного поиска в прогрессе, ВОР без обязательных норм/цен, честную неполноту
при неверных связях, сохранность авторских решений, ноль отдельно от null,
и DOCX empty-note scaffolding отдельно от реального непрочитанного содержимого.
Recovery/UI regressions находятся в существующих test_packaging_recovery_service
и test_sovushka_chat. Эти проверки не являются профессиональной live-приёмкой.

## 947 — ссылки и продолжение работы при материале того же адреса

`test_model_workbook_citation_instructions_947.py`: реальные governed messages
B0/B1 и native-read continuation не получают противоречащих правил ссылок;
карточки, исходник и обычный чат сохраняются. Парсер не угадывает `[Источник N]`.
`test_model_source_conflict_resume_947.py`: материал не закрывает отклонённый
work; продолжение получает оба адреса, исправляет предложения по одному,
сохраняет материалы и raw proposals. Анонимная поправка требует явного
resolves_proposal_id; существующая операция — точного operation_id. Чужой
маркер/роль/адрес и stale revision не снимают pending. Допустимые aliases проверяются как scope,
без переписывания авторской строки. Оба файла включены в CURRENT_TESTS.
`test_model_quote_dimensions_947.py` исключает стоимость от несовместимых
единиц, проверяет отдельное сохранение цитаты цены, совместимые SI/масштаб,
явный пересчёт, work unit_price/position_total/unknown и сохранность
действительного нормативного subtotal. Файл также включён в CURRENT_TESTS;
соседние provenance/SI проверки усилены, а не пропущены.
`test_model_query_phase_scope` различает ссылки ответа, чтения и документа,
проверяя неизменность профиля/skill. `test_runtime_config_registry_service`
исключает архивные AST-факторы и сохраняет дефолт 300.0. Первый полный запуск
зафиксирован как failed в RELEASE_LEDGER; он не засчитан готовностью кандидата.

## 946 — сохранность отклонённых решений и capability admission

`test_model_lsr_rejected_source_proposals.py`: source guard отклоняет строки,
но полные решения и точные причины сохраняются отдельно от accepted; смешанный
пакет сохраняет корректного соседа; явное продолжение получает неприменённые
предложения отдельно от принятых решений. `test_model_capability_service.py`
проверяет полный повторный замер requested union previous measured scope той же
revision, регрессии capability и отсутствие переноса template/другой revision.
`test_model_capability_admission_946.py`: отказ до model HTTP, отсутствие fallback
и явная ошибка локального допуска. Новые файлы включены в CURRENT_TESTS Makefile.

Candidate942 adds mandatory test_attachment_sheet_accounting_942.py: an overflowing tabular
attachment frame must name every sheet of the document with delivered-versus-actual non-empty row
counts, must mark a sheet the model never saw at all, must not invent a gap when the frame is
complete, and CSV goes through the same accounting. 3 RED / 1 PASS before the change, 165 PASS
together with test_datasets_router, test_chat_harness_format and
test_live_workbook_acceptance_contract after it. Measured on the real customer ВОР.xlsx: the frame
now states 155 delivered of 439 non-empty rows across 10 sheets and names six undelivered sheets.
test_connection_window_budget_942.py additionally pins the budget convention that made today's
8214-token truncation readable: input_token_limit is the whole observed window, the Governor packet
budget is that window minus the declared generation and safety reserves, and the native path names
the same window it was given. Characterization only — no product behaviour changed there, because
the hypothesis that the transport conflated the two numbers was disproved by the live measurement.

Candidate944 adds test_resource_group_packet_overflow_944.py: the per-packet cap on resource-group
asks must state its own surplus. Four tests were RED (5 detected groups, 4 shown, deferred count
absent everywhere), 30 pass with test_resource_group_proof_932 and
test_lsr_group_resource_specificity. Nothing is chosen and no status promoted: the deferred debt
keeps its `price_missing:<код>` gap.

Coverage correction in the same build: the regression files added in 942-944 were **not** listed in
the Makefile `UNIT_TESTS`, so the green `CURRENT_TESTS` gate never ran them.
test_attachment_sheet_accounting_942, test_connection_window_budget_942,
test_lsr_render_byte_determinism_943 and test_resource_group_packet_overflow_944 are now part of
the canonical gate. This was a gap in verification coverage, not in product behaviour.

Candidate943 adds test_lsr_render_byte_determinism_943.py: the delivered LSR must carry no
build-time wall clock in its document properties, because the same saved decisions repacked from
another session produced 39 707 and 39 708 bytes with different hashes and the diff was confined
to docProps/core.xml. Both statements are pinned — the pinned epoch inside core.xml, and equal
content for every archive part across two renders. 1 RED / 1 PASS before the change, 52 PASS with
test_rim_trace_xlsx, test_workbook_partial_draft and test_revision_projection_830 after it. Raw
ZIP entry timestamps are explicitly out of scope and stated as such, not hidden.

Candidate873 adds mandatory test_chat_native_research_exchange.py (actual ordinary
chat rounds/final, literal native protocol, invalid IDs/args, physical overflow,
legacy unchanged) and test_model_norm_evidence_ref_reads.py (actual admission,
exclusive refs, prepared/unknown/ambiguous/source-version negatives, delivery).
Mixed workbook/read native batch covers first, last and prior-round order through
the actual application and Broker, with all literal calls and real replies retained.
Both are generic synthetic regression fixtures, not real engineering acceptance.
Installed872 B0/B1 professional FAILED; answer8К trial reverted, live873pending.

Candidate872 — UTF-8 Windows prepare fixture, literal shown-code navigation и
lossless unread pointer-field aliases. `test_model_norm_pointer_navigation.py`:
2 RED / 6 control pass → 8 GREEN; admitted literal siblings/aliases/source/edition/
identity, no hidden title/no reader before admission, exact dash boundary,
conflicting key unchanged и real native receipt feedback. Exact full read unchanged.
`test_release_local_full.py` повторяет production UTF-8 Console preamble и
строгий UTF-8 capture. Inherited CP866 + UTF-8 Python воспроизвели byte0xaa и
stderr=None: 1 failed / 16 deselected / 1 warning (2.72s). Под тем же codepage
и PYTHONUTF8=1 после paired encoding — **17 passed (4.18s)**, исходные cache/
baseline/provenance assertions сохранены, production неизменён.
Private prepare871 отдельно: **2924 passed / 1 failed / 20 skipped / 6 warnings,
219.48s**; exact private prepare872 pending. RED/GREEN commands сохранены в
`artifacts/test_release_encoding_871_red_green.json`.
Candidate872 metadata: verify exit0 (23.48s), 2945 collected; version/docs/
release fixtures31 passed (4.99s) под CP866/PYTHONUTF8=1; documentation contract0.
Receipts: `artifacts/{verify_872_metadata.exit,metadata_docs_872_checks}.json`.
Это не полный canonical872 и не installed/private acceptance.
Installed871 `e8657ba3`: API/GUI/19 hashes сверены, native EXE858 retained.
Native RRF exit0; original90s smoke **7 pass / 1 warn / 2 timeout fail**
(182.59s / wrapper183.91s). Separate finite180s smoke **exit0 / 10 pass /
0 warn / 0 fail / 112.66s**, glossary61.547s/project48.687s; первый run сохранён.
Professional871 **FAILED**: same-identity B0 331.73s required46993/budget46246,
7 read frames; B1 92.17s required47433/budget46246, paused20remaining/0accepted,
6 exact cards delivered. Оба без XLSX; это не professional readiness.

871 capacity delivery: сохранённое offline-доказательство, source/5 tests frozen,
8 production source files reviewed.
Initial focused 10 suites **392 passed (21.54s)**; четыре causal old-boundary
ablations red сохранены. Scripted B0/B1 actual JSON→XLSX fixtures подтверждают
1800 и сохраняют 24 raw refs; inventory-delivered не означает body-delivered.
Existing `test_model_rag_grouped_evidence_service`, `test_model_rag_sheet_evidence_reads`,
`test_model_evidence_read_contract`, `test_model_price_provenance_service` проверяют
общий mandatory exact/cited replay + optional whole discovery groups, legacy
exact-price receipts и pointer-only price/body guards. Это offline механика,
не real-model/professional proof. SECOND canonical 871: **2925 passed /
20 existing opt-in skipped / 5 warnings** (281.29s / wrapper 282.81s), verify0
(22.84s), architecture0 (9.75s), baseline0 (7.23s), active artifacts0 (0.61s).
Первый FAILED gate сохранён: 2923 passed / 2 failed / 20 skip / 5 warnings
(286.72s / wrapper 288.22s), verify0 (23s). Два old rawsearch→exactread fixtures
не выполняли inventory admission; только `test_model_research_evidence_actions`
обновлён explicit binder→Governor→confirm→register и before-admission negative
assertions (+40/−4), original provenance/40 resources/НРСП/price assertions сохранены.
Focused fixture checks: 119 passed (15.60s), source8 без изменений. Receipts/logs:
`artifacts/*_871_second.exit.json`, `artifacts/*_871_second.log`; первый run не заменён.
Установка871 сверена; exact private installer pending, native EXE858 retained.
Это не professional readiness.
Предыдущий exact870 `7ba406a1`: финальный
canonical 2906 passed / 20 existing opt-in skipped / 5 warnings, verify/
architecture/pinned baseline exit0. Installed native RRF exit0; basic 90s:
8 passed / 1 warning / 1 project-timeout FAIL. Separate finite hardware-calibrated
180s smoke exit0: 10 PASS / 0 WARN / 0 FAIL (85.55s), glossary/project
31.640s/51.438s, оба ниже исходного 90s; FT request p95 128.233s.
Первый failed результат сохраняется: обычная latency изменчива.
Professional comparison 870 FAILED: B0 179.56s required 55639 / budget 46246,
4 searches / 24 prepared refs, no XLSX; B1 57.97s paused, 0 rows / 20 remaining,
first read frame 45230 admitted, second required 72822 / budget 46246, no XLSX.
Offline checks и выполненные reads не доказывают delivery или профессиональную
приёмку. Receipts: `artifacts/live_870/bap_lsr_{baseline,candidate}/`.

870 focused transport/source/contract checks: root 109 passed (14.2s), native
exchange/read 56 passed (3.5s), decoder/durable 22 red → 73 passed. Existing
`test_model_evidence_native_exchange`, `test_model_evidence_read_contract`,
`test_chat_evidence_manifest_service`, `test_source_locator_service`,
`test_model_result_resource_actions` и `test_model_rag_sheet_evidence_reads`
проверяют один native body, safe numeric capacity, prepared≠delivered,
same-body immutable-ID promotion и admission saved read chunks. Row-local
duplicate fields сохраняют conflict raw в durable snapshot, три независимых
решения принимаются, один locator остаётся; plain continue не запускает repair,
explicit reopen с новым model correction сохраняет реальный XLSX.
Final targeted parser: 10 red до fix → 118 passed (15.98s);
transport/persistence: 119 passed (20.44s). Последние boundary checks:
8 red / 2 prose controls green → 128 passed (14.64s); canonical 870 зафиксирован выше.
Предыдущий installed 869 comparison **FAILED**: B0 capacity/no XLSX (76.88s), B1 paused
draft (311.64s), 11 operations / 8 scope locators = 7/19 реальных работ плюс
header; предварительно 64 545.14, подтверждено 0. SHA/revision и known-part
Decimal совпали; это не доказательство применимости норм/ресурсов/полной цены.

869: `test_workbook_research_job_service` добавляет 17 regressions повторной
plain continuation после correction/restart: latest rows/basis/evidence/overrides,
completed/paused, legacy caller, explicit rerun, шесть scope границ, running guards,
foreign intermediate и question/hash mismatch. Before fix 7 failed / 7 passed;
after 17 passed, related job/context/refinement/packaging/sheet bundle 138 passed.
Это offline доказательство; completed установленная приёмка 869 FAILED.
`test_model_lsr_result_contract`: 3 новых red→green регрессии приоритета явного
формата и порядка общего контракта; examples не меняют выбор пользователя.
Related format/research/gap/packet bundle: 59 passed; parsers не ограничены.
`test_model_rag_sheet_evidence_reads`: queue starvation, all-malformed join,
explicit reopen и последовательное снятие одного/нескольких snapshots;
7 новых focused passed, related bundle 368 passed. PDF source catalogue:
6 новых tests failed до fix, mixed text/table/full literal/visual warnings
и стабильные PDF!Rn после fix — 71 related passed.
`test_sovushka_chat` проверяет XLSM picker + default policy и сохранение
operator override; chat/UIKit/input bundle 200 passed (red до fix).
`test_unpack_archives` зарегистрирован в canonical UNIT_TESTS; marker/SHA,
partial retry, conflict preservation и безопасные targets: 21 passed,
15 failed до fix; retired prior-owned output блокирует ложный complete без удаления.
Native attached-source: 21 failed before, 169 related passed after;
governor/native receipt/durable replay сохраняют полный body, SHA и source offsets.
PDF source order и непригодные для nonPDF fact keys: 226 catalog/chat passed,
оба прежних budget-bound chat cases восстановлены без ослабления assertions.
Completed scope expansion/join: 2 scope + 2 join regressions failed before;
374 related passed after. Real XLSX fixture adds only newly catalogued context,
retains old rows/evidence/basis and gives a new final revision.
Frozen canonical 869: 2838 passed / 20 existing opt-in skipped / 5 warnings;
verify, architecture, pinned baseline и active-artifacts exit0. Installed
professional acceptance FAILED; offline results do not replace it.

868: `test_model_query_reasoning` включён в canonical UNIT_TESTS: strict optional
bool/inheritance, immutable profile, GUI select и runtime diagnostics; реальные
mocked FreeToken requests проверяют query=False / answer+native=True при общем
reasoning=True и отдельные governed output reserves. `test_qdrant_adapter_parse`
проверяет пустые final nodes без embed/delete/upsert, сохранение dense/sparse/
lexical/rules и обработку следующего файла. `test_sovushka_documents` проверяет
legacy INDEXED0, fallback-карту и частичный PDF-sidecar. Это транспортные и
целостностные проверки; frozen canonical 868 — 2745 passed / 20 existing opt-in
skipped / 5 warnings, verify/architecture/baseline/active-artifacts exit0.
Installed 868 smoke: native RRF exit0, basic 9 passed / 1 diagnostic warning /
0 failed. Comparative quality FAILED: B0 length with incomplete JSON, B1 stop
with ten malformed Markdown rows; zero downloaded artifacts in both controls.
`test_model_rag_grouped_evidence_service` воспроизводит 150 synthetic candidates
и запрещает раздувание compact inventory в mandatory replay, выдачу unshown
stored body и объединение разных SHA/edition. Два теста падали до исправления.
First-fit 6000/4800 проверяет requested reserve 3000 / effective 1200 и целый body.
Native B0/B1 integration при достаточном окне выполняет три tool replies и
получает финальный XLSX; узкое окно сохраняет три receipts и честный checkpoint
без выдуманных строк. Driver не запрещает final answer после последнего read slot.
Focused: 218 query/profile, 127+1 native/context, 56 documents/UIKit,
180 chat/UIKit passed. Качество настоящей модели проверяется отдельным live gate.

867: durable terminal packet snapshots и независимые source packets проверяются
`test_workbook_research_job_service` и `test_model_rag_sheet_evidence_reads`:
3 новых регрессии failed до изменения, целевой повтор с chat/refinement — 282 passed.
Проверяются
сохранение решений/курсов при reopen, переход только к новым locator группам,
честный remaining при пропуске моделью и отсутствие нового ответа за прежний
пакет. `test_model_evidence_native_exchange` добавлен в canonical UNIT_TESTS;
он проверяет роли/ID и budget actual native continuation, а не качество нормы.
Совместный focused bundle native exchange/read driver/ContextGovernor/transport/
sheet — 97 passed; 3 регрессии падали до исправления.
UI/общий UIKit/chat refinement, включая запрет reopen работающего задания —
197 passed (4.41s).
Query failure сохраняет bounded final output/parse facts через typed exception
в existing history, без раскрытия reasoning/credentials в history или public
errors. Совместный focused повтор — 289 passed (12.42s), включая stream/nonstream,
quoted JSON credentials и отказ от arbitrary HTTP trace promotion. Новый
`test_model_query_failure_diagnostics` включён в canonical UNIT_TESTS.
Frozen full gate 867: 2696 passed / 20 existing opt-in skipped / 5 warnings;
verify/architecture/pinned baseline exit0. Установленная профессиональная
приёмка 867 FAILED: B0 query length/empty final, B1 native reads3/capacity pause,
0 accepted / 19 remaining и no artifact; offline gate её не заменяет.

866: test_model_lsr_result_contract проверяет advertised quantity_basis и review
statuses реальными constructors ResourceBinding/ResourceReview, включая правила
add/replace и component reasons. Совместный focused gate с read-turn, sheet/cursor
и literal resource transport — 76 passed; после выявленного вытеснения обычного
RAG evidence общий field contract сохранён, guide ограничен actual read turn:
277 focused passed, включая обе исходные failed проверки без изменений.
Установленные model-only требования
не считаются доказательством профессиональной правильности; live 866 FAILED.

865: `test_model_result_resource_actions` проверяет реальный JSON inventory
pointer, отдельное full read той же identity и запрет metadata без буквального
шифра/с частичным совпадением. `test_model_rag_sheet_evidence_reads` воспроизводит
хвост 35 queries с ограничением body: один terminal native-tool ход сохраняет
полные либо partial строки, пакует один раз, сохраняет held cursor при reopen.
B0 получает те же literal queries и native reads. Эти тесты не подтверждают
профессиональные нормы/цены; свежая live приёмка 865 пока pending.

864 регрессии включены в canonical UNIT_TESTS: `test_model_result_resource_actions`
проверяет полный JSON-массив/объект с prose, неоднозначность и усечение без repair,
all-format nested fields, durable alias collision, independent norm/action refs,
literal price provenance и сохранение действий в XLSX. `test_model_resource_binding_service`
и `test_rim_lsr_trace_service` проверяют atomic replacement, фактический расход,
reuse zero-price precedence, неоднозначные цели и actual parser→binder→RIM→XLSX.
Отдельная поставка должна сохранять расходники нормы и показывать незакрытое
пересечение вместо blanket deletion. Полный gate 864 и live acceptance пока открыты.
`test_model_rag_grouped_evidence_service` проверяет lossless общие каталоги,
разные источники/редакции, единый capacity-план и прогресс первой целой группы.
Pointer-only, parent cipher, иной source/edition, duplicate JSON keys/aliases
не закрывают provenance; sparse JSON роли сохраняются без новых значений.

Установленный 863: B0 416.20s, полный авторский JSON array19, parser0, XLSX0;
independent professional audit FAILED. B1 791.81s, answer length32768, paused19,
XLSX0. Эти измерения не заменяются fixtures или позднейшим исправлением reader.

863 output budget regressions: строгая profile валидация/round-trip и UI/registry
113 passed; preset и реальные mocked chat call-boundary проверки включают
post-cache capacity refresh, native-tool overhead, разделение query/answer,
unobserved clamp и неизменные defaults. Fixtures — механические доказательства,
не live professional acceptance. Live 861 JSON reasoning B0: 350.61s, answer
length/no final; B1: 86.89s, query4095/4096 length/no final, 19 remaining paused.
Professional/financial для них N/A_NO_FINAL_RESULT/NO_ARTIFACT, не missing norms.

Кандидат **862**, установлен runtime **861**. Executable PowerShell regression
в `tests/test_installer_windows.py` проверяет occupied/free explicit/implicit
ports release smoke против production controls без реальных stop/listeners.
`tests/test_tauri_desktop.py` проверяет Windows Path/PATH и Unix case-sensitive
environment. Первый regression действительно воспроизвёл остановку рабочего
proxy/UI в prebundle 861; frozen 861 full gates не обнаруживали этот дефект.
861 native RRF/basic smoke прошли после штатного восстановления. Quality/live
comparison 861 и точный installer пока не приняты; technical green не readiness.
862 gates: verify/architecture/actual pinned baseline exit0; canonical 2457
passed, 20 existing opt-in skipped, 5 warnings, 250.70s. Focused release tests:
34 Tauri + 78 Windows installer passed. BAP JSON B0 861 measurement FAILED:
220.27s, malformed Markdown вместо JSON, без файла. Reasoning control pending.

Кандидат **861**, установлен runtime **860**. B0 860 имеет SHA-проверенный XLSX,
но независимая профессиональная проверка FAILED; B1 остановлен с malformed
proposals без XLSX. 861 добавляет regressions query budget/cut final без repair,
safe specific public errors, GUI auto factor и exact updater Make-less recipe.
Тесты включены в прежние канонические файлы. Full gates/live comparison/exact
installer 861 пока открыты; 2441 passed ниже — результат frozen 860.

861 frozen full gates: **2457 passed / 20 existing opt-in skipped / 5 warnings**,
240.59s, verify/architecture/pinned-baseline passed. Exact third-attempt receipts:
`artifacts/*_861_third.exit.json`; initial version-sync and generated-map failures
preserved. Independent narrow transport review found no actionable defect.

Candidate **860**, установлен runtime **859**. Сравнительная профессиональная
приёмка 859 FAILED: parser cell shifts и необоснованные авторские нормы при
согласованном расчёте/XLSX. Новые offline regressions добавлены в `UNIT_TESTS +=`;
полный candidate verify/test и живая сравнительная приёмка фиксируются
отдельными результатами, не выводятся из перечисления tests. Live pass для 860
этим документом не заявлен.

860 frozen canonical offline gate: verify passed; **2441 passed / 20 existing
opt-in skipped / 5 warnings**, 228.84s. Architecture and actual v2 baseline
archive verification passed. Exact receipts are in `artifacts/*_860.exit.json`.

- `test_model_result_table_transport.py`: literal malformed proposals, no
  padding/merging, compatible empty tails, escaped pipes и resumable technical
  hold без MISSING/retry/model confirmation.
- `test_model_reasoning_control.py`: default-off strict boolean, GUI/profile
  persistence, same B0/B1/continuation policy, supported/effective boundary,
  separate reasoning/final, split tags и literal XML/code preservation;
  reasoning-only length не создаёт workbook или новый model turn.
- `test_release_local_full.py`: exact clean detached local-only full, no fake
  upstream/base, unchanged all gates и explicit publication denial.
- `test_release_candidate_freeze.py`: actual Windows sharing lock, bounded
  atomic-rename retries, visible final refusal и frozen-byte integrity.

Новые scoped файлы:

- `test_smeta_exact_norm_card.py`: exact key/code conflict, все resource rows и
  расходы/единицы/нулевой расход, provenance, unknown consumption/count mismatch;
  без поиска альтернативы.
- `test_model_lsr_result_contract.py`: единые conditional fields/examples,
  обычный текст/optional JSON/delta и expected_revision.
- `test_model_evidence_read_contract.py`: immutable aliases и literal registry
  bodies, safe same-card dedup/prefix/shared reference, missing/cycles explicit;
  docs/prices разных identities не схлопываются, durable exact read не закрывает
  source rows.
- `test_model_evidence_read_service.py`: literal argument identity, same-tool
  distinct reads, repeat/budget/capacity stop, plain final без нового model call.
- `test_model_research_evidence_actions.py`: ранее показанный exact pointer,
  полный resource transport, selected document scope и read-only action executor.
- `test_model_rag_sheet_evidence_reads.py`: offline B0/B1 native reads через
  настоящий chat/workbook executor до рассчитанного XLSX; это integration fixture,
  не живое доказательство профессионального выбора модели.
- `test_model_result_packet_service.py`: текущий packet, operation/source/revision
  conflicts как полные unapplied proposals, разные операции одного locator,
  durable restart/redelivery без повторной revision.
- `test_model_price_provenance_service.py`: цена/unit/source и optional quote
  context сверяются по реальным cited bodies, без model→operator confirmation.
- `test_resource_binding_provenance.py`: literal selected resource_code/ref
  binding, неизменный authored выбор и неизвестное соответствие.
- `test_rim_visible_price_provenance.py`: source/operator price ownership,
  confirmed/preliminary граница, price unit/kind и отсутствие ложного complete.
- `test_fgis_pricebook_snapshot.py`: official reader/cache по exact whole-file
  hash; смена bytes при прежних path/size/mtime не возвращает старые цены;
  drift во время decode не кэширует ложный snapshot, typed source context и
  реальный расчёт используют прочитанную официальную книгу; packaging/job basis
  сохраняет hash, а continuation той же заменённой книги завершается
  `PRICEBOOK_VERSION_CONFLICT` без artifact и без изменения model decisions.
- `test_vor_input_transport.py`: uncapped PDF catalog, long cells/zero/blank,
  все XLSX листы, DOCX body/nested tables/header locators и unread-content warning,
  authored DOCX/CSV XLSX export, notes-only reference scope, empty source без
  artifact, явный unsupported RTF/ZIP.

Локальные scoped измерения: exact-reader/contract group **76 passed**;
source-transport group **85 passed**; registry/read-driver/native integration
group **31 passed**. Группы пересекаются и не суммируются в новый full gate.

858 final canonical: 2101 passed / 20 existing opt-in skipped / 5 warnings;
verify 2121 collected. Architecture/active artifacts green. Full-path E2E proves
literal resource code and selected-book money survive into XLSX. Installed
13/13 hashes, native RRF 1/1, idle basic 9 pass / 1 existing WARN / 0 fail.
Fresh exact-source/model/question B0/B1 receipts saved in artifacts/live_858:
B0 38/51 source addresses / 2 calculated / 0 source errors / 295.6s;
B1 51/51 accounted / 1 calculated / 18 work/material source errors / 1482.6s.
Both estimate_complete=false; customer source/norm/financial acceptance FAILED.
No resource_code or nr_sp_rule_id authored in either live result. The initial
stale generated-map failure is preserved. 300+ and exact installer NOT ACCEPTED.

Candidate 0.31.130 / 858: `tests/test_model_result_resource_code.py` adds
14 offline cases for an explicit model-authored `resource_code`: Markdown,
inline and multiline × material/equipment/work, compact replay with unchanged
case/value, and no inferred/default code when the title merely mentions one.
The downstream material calculator already reads this field; the visible
decoder and replay must carry it separately from `norm_code`.
One full-path E2E also proves selected-book ownership across parse/replay,
immutable evidence/catalog, RIM and XLSX: 12 m × 100 = 1200 confirmed,
preliminary 0; reference-only 777 in evidence does not become the price.
Saved red baseline after correcting the multiline fixture: 12 failed / 1 passed.

Eight new `test_prior_page_*` cases in `test_chat_evidence_application_service.py`
reproduce lost mechanical feedback: same/different cited cipher, unavailable
immutable card despite stale saved diagnostics, and a material quantity placed
on an unquantified group beside its quantified variant. The separate
`prior_result_structural_facts` packet exposes observed comparisons for all
authored source roles without replacing choices, roles, quantities or cards.
They also guard stale empty-norm diagnostics, equivalent source measures and
reused handles with different durable IDs. Four direct source catalog cases
prove exact m/km, kg/t comparisons and preserve a real unequal-quantity error.
An empty header remains empty; an unavailable cipher comparison stays unknown.
Saved red baseline: 4 failed. This adds facts to existing page/review calls,
without a post-model selection loop or a change to packaging admission.
Final offline/install gates passed; installed source/norm/financial acceptance
FAILED as above. The failed 856 quality measurements below are retained.

Installed 0.31.129 / 857 verified on 01.10: 14/14 patch hashes match
committed source; rollback 856 retained. Post-deploy native RRF 1/1 and standard
basic smoke 9 pass / 1 existing diagnostics WARN / 0 fail (117.14s).
The previous 856 timeout under concurrent model load is preserved as a failed
measurement; the standard idle smoke passed without changing its 90s timeout.
Live progress transport: 13,750,633 → 17,908 bytes, all non-bulk fields identical;
last/active projections also checked. Browser reload restored the own completed
VOR notice and immutable real filename, without foreign progress. UI download
13,568 bytes saved to Downloads; SHA c6d491e5… matches the prior revision.
These checks prove technical delivery/UI only. Fresh source/norm/financial
acceptance failed as recorded below; 300+ and exact Windows installer remain
not accepted. This is an installed test build, not a customer-ready release.

Fresh installed same-model/input EOM LSR control on exact 856 completed:
B0 256.9s / 27 of 51 source rows / structural_error / no file;
B1 1266.6s / 51 of 51 / remaining 0 / 86 decisions (32 work, 39 material,
14 header, one unresolved), rev_2e529f5b / 83,844 bytes, downloaded SHA exact.
Both use FreeToken Qwen3.6-35B-A3B-NVFP4 r4 and identical task/source.
Fresh evidence handles: 936 refs, zero collisions (856 alias repair proved).
Actual model choices still disagree with cited card ciphers (e.g. 593-19
cites card 593-12; cable 398-02 cites culvert 30-07-006-11). No code correction
of these professional choices was made. Four source unit/quantity errors,
four duplicate header groups and one unresolved variant remain.
32 named norms / 14 substantiated; composition check absent on 12 works.
Exact SPb 3кв2026; calculated_positions 0, confirmed 0, preliminary 331226.92.
Final gaps: 1 missing norm, 17 unsubstantiated norms, 47 price gaps;
row reasons: 31 unresolved NR/SP, 40 price_missing, one unresolved FSEM.
Execution/delivery succeeded; professional/financial acceptance FAILED.
The fresh 300+ and exact-installer customer release gates remain NOT ACCEPTED.
Active-artifact release baseline verify-root passed with 49,818 norms,
504,891 resources, 1,576 FSEM rows and 281,223 price rows.

Canonical final 2075 passed / 20 existing opt-in skipped / 5 warnings,
224.75s; verify 2095 collected, compileall/version and explicit architecture
gate green. Official dry-run 14 files, rollback 856 preserved; installed 857 pending.

Completed ordinary 856 restart/resume: 1544.0s, 51/51 source rows,
83 decisions (32 work/41 material/10 header), exact inherited SPb 3кв2026,
parent rev_75c3e5e2 → rev_0d9e52fd, SHA d42bd30a8861437cc218aa5aaf43892261138b9410cf18293cf60a089fa69681.
Five source unit/quantity errors persist after freeform review; 30 named norms,
15 substantiated, one arithmetic-complete position with unsubstantiated applicability,
confirmed 0 / preliminary 418317.04. Gaps: 5 missing norms, 12 unsubstantiated,
47 price gaps; row reasons include 25 unresolved NR/SP and one unresolved FSEM.
Execution/delivery passed; professional and financial acceptance FAILED.
Fresh same-input B0 on 856: 256.9s, 73 rows, only 27/51 accounted, no file,
structural_error; B1 completed (see final comparative measurement above). Fresh 300+/exact installer not accepted.

857 UI transport: `view=progress` on job/last/active drops only bulk
evidence and query_cache from the HTTP response, retaining authored rows,
identity, task, held cursor, remaining scope and recovery projection. Default
full response and all durable data remain unchanged; the model uses full state.
Own 854 checkpoint is 17,643,398 bytes pretty JSON; UI does not need raw cards/cache.
Three route regressions preserve full reads/source dictionaries; focused UI/API
212 passed. This reduces polling traffic, not generation time. Installed size
measurement and browser recovery after the ongoing 856 controls remain pending.

Build 857: projection→terminal notice regression catches lost VOR kind;
focused UI/history/documents 189 passed. Installed model controls remain on
unchanged 856 inference core. Basic 856 under concurrent model load failed
project-noscope 90s timeout; preserved, requires idle retest, not suppressed.

Build 856: two regressions preserve a model's old citation in a fresh
answer beside new evidence and preserve the next query ordinal after durable
roundtrip. Focused core/query/task 226 passed. Existing legacy ambiguous
handles remain fail-closed; new packets cannot shadow prior cited cards.
Canonical 2071 passed / 20 existing opt-in skipped / 5 warnings, 215.49s;
verify 2091 collected, architecture green.

Build 855: three filename regressions distinguish VOR, a partial LSR's
immutable filename and foreign revision metadata. Focused UI/history/documents
188 passed. No source/norm/price choice is changed; quality gates remain open.
Canonical 2069 passed / 20 existing opt-in skipped / 5 warnings, 213.65s;
verify 2089 collected, architecture green.

Build 854: latest-over-paused regression covers explicit history selection and
ordinary startup with saved job_id. Focused UI/history/documents 185 passed.
Canonical 2066 passed / 20 existing opt-in skipped / 5 warnings, 211.41s;
verify 2086 collected. Installed acceptance pending; fixtures do not prove model quality.

Build 853: latest finished document beats an older paused stage in selected
history, including local API-unavailable fallback; default reconnect preserved.
Two additional UI regressions, focused UI/history/documents 184 passed.
Canonical 2065 passed / 20 existing opt-in skipped / 5 warnings, 226.10s;
verify 2085 collected, architecture green. Installed UI acceptance pending.

Build 852: three task_context cases cover original/current task in resumed model
calls, effective explicit repricing dimensions and mandatory source/card/task
presence in ContextGovernor. Three UI regressions cover history pending clear,
foreign adoption and own-job selection over a foreign pin. Focused core 305,
UI/source-context 180 passed. Canonical rerun/live pending after UI fix.
Source catalog regressions additionally assert requested/reference scope,
exact 30m quantity, null group cell and absent quantity for unknown columns.
Final focused core/source/UI 437 passed; canonical 2063 passed / 20 existing
opt-in skipped / 5 warnings, 201.13s; verify 2083 collected. Installed RRF/basic,
immutable recovery and mail 66 passed; fresh B0/B1 model-quality control pending.

Build 851: four task_context regressions cover VOR after remark/restart/resume,
explicit conversion to LSR, old task fallback and parent-vs-replay across jobs.
Two source_catalog regressions cover numbered descriptors beside variants and
quantity-unknown layouts. Red cases reproduced before fixing; focused 295 passed.
Canonical 2057 passed / 20 existing opt-in skipped / 5 warnings, 204.52 seconds;
verify 2077 collected, compileall/version/architecture green. Installed
comparative controls pending, not a customer-ready claim.

Build 850: five regressions in `test_workbook_chat_refinement.py` cover review
identities/source binding, resumed instruction/exact cited body, incomplete
review baseline and no resurrection after a completed model result. Real SQLite
jobs are reopened/inherited; record_packet keeps the old ID and next revision.
Operator-confirmed data survive a new resume job. Focused 256 passed; canonical
2051 passed / 20 existing opt-in skipped / 5 warnings, 197.43 seconds. Verify
2071 collected, compileall/version/architecture green. Installed gate pending.

Build 849: regression reproduces safe history dropping VOR source audit; all
318 warning addresses survive repeat projection, status is partial. VOR repack
retains lineage and returns VOR-specific readiness without LSR requirements.
Two red tests before, focused carrier/recovery/workbook/prices 270 passed.
Full canonical gate 2046 passed / 20 existing opt-in skipped / 5 warnings,
198.25 seconds; verify 2066 collected, compileall/version/architecture green.
Installed 848 big repack: 427 saved decisions, 185 blocks, 23 calculated,
priced_partial, exact SHA/parent/replay; zero model calls. Not fresh inference.

Build 848: regressions reproduce 100-fold money error for an already scaled
source measure, lost multiplier in kg→t, overflow, equivalent-measure rejection
through actual catalog/adapter/money, and unit matched inside a title.
Notation aliases keep the physical dimension; wrong quantity remains rejected.
VOR regression reproduces model XLSX operations replaced by spec reader/dictionary;
material mismatch and model open_gap must remain visible with unchanged rows.
Focused quantity/price gate 116 passed; VOR/trace 137 passed. Canonical full gate
2045 passed / 20 existing opt-in skipped / 5 warnings, 194.36 seconds;
verify 2065 collected, compileall/version/architecture and active artifacts pass.
Installed acceptance remains pending.
New EOM installed 847 B1 delivered 83 rows/51 source addresses, but independent
source check found 11 material errors and one model unresolved operation.
Downloading a complete file did not establish professional readiness.

Build 847: four regressions reproduce sparse PDF/CSV row compaction losing quantity
column identity. Two integration cases include an optional supplier, adjacent
mass and different blank fields; a synthetic gridded PDF uses actual find_tables.
CSV tests both delimiters and unchanged locators across a fully empty source row.
Red before: 4 failed; after: PDF/catalog focused 21 passed / 1 existing skip for
absent optional corpus. Original EOM project quantities now bind to their headers.
Installed model comparison remains required, not inferred from these tests.
Canonical gate 2039 passed / 20 existing opt-in skipped / 5 warnings; verify
2059 collected, compileall/version/architecture and installed active-artifact
semantic checks passed. No tests weakened and no dependencies changed.

Build 846: image-only DOCX read-intake rejects converter image-label markup
before persistence. Regression reproduced the false success before the fix;
transitional/strict namespaces, real text plus image and altChunk are covered.
Focused datasets/attachment gate 65 passed. Customer corpus preflight found
the actual image-only DOCX and an unsupported RTF; this is not an OCR success.
Canonical gate 2038 passed / 20 existing opt-in skipped; verify 2058 collected.
Separate canonical mail gate 66 passed. Installed RRF 1/1 and basic 9 pass /
1 diagnostics WARN / 0 fail; VOR/LSR recovery retains revisions, bytes and price
basis. Same 35B/input 64K БАП: B0 no calculated rows; B1 19/19 source rows,
8 calculated positions, 467.8 s. Full estimate remains incomplete. EOM B0
source quantity failure is reproduced in the PDF parser regressions of 847.

Build 845: legacy/foreign query-cache contracts (including empty hits) refresh
without changing accepted operation revisions, cited evidence or held cursor;
infrastructure failure stays technical. Prior context preserves authored fields
and exact cited cards but excludes repeated application diagnostic dumps.
EXACT/EXACT_VERIFIED with an explicit no/unknown fact stays unsubstantiated in
both readiness and the money trace, without rewriting the model choice.
Ten regressions failed before corrections; focused gate 325 passed.

Build 844: generic source-label fixtures exercise the real model norm reader
and the default browser through a vocabulary rule; only the declared queries
may reach native RRF and each result must retain its own query identity.
The model-reader regression failed before the fix. Professional selection
requires installed controls and is not inferred from this mock.

Build 843: query instruction must permit a model-authored mounting operation
instead of literal product-label copying; the reader preserves that query.
Result instruction requests the table first and excludes marker-only expansion.
Both regressions failed before correction. Installed/model outcome pending;
offline prompt contracts do not prove professional norm selection.

Build 842: three regression cases reproduce the missing output-ID contract,
mounting resources calculated on explicit supply/header roles, and non-work
ciphers inflating selected-work-norm counts. The role test asserts no norm
lookup/calculation, preserved authored role/code/source, and an explicit conflict.
Before: 3 failed / 86 passed; after: 119 passed, including 782 identity/money tests.

Build 841: regression cases in `test_chat_evidence_application_service.py`
cover surplus explanatory cells with known unit/quantity, echoed durable IDs,
checkpoint revision continuity, rejection of invented/moved IDs, exact-card
sharing with all eight query refs, distinct-source isolation, and shared
prior citations retaining immutable IDs. The required-prefix fixture uses two
distinct sources to continue testing that neither legal prefix may be cut.
Focused chat/research/architecture gate: 284 passed. Live acceptance remains
separate: 840 B1 finished with 23/75 accounted, 0 calculated, 920.8 seconds;
0 omitted cards per delivered page establishes transport only, not quality.

Build 839: seven regression cases in `test_model_research_tool_service.py`,
`test_chat_evidence_application_service.py`, `test_rim_lsr_trace_service.py`
prove the pre-existing loss of NR/SP options and the authored rule ID.
They cover all four visible formats, review projection, exact catalog source
checksums without private paths/selection, calculator forwarding, missing choice
remaining ambiguous and a foreign-collection choice rejected. A bounded model
message preserves the complete required typed-card prefix or omits the card;
it never cuts the legal candidate block midway. Before: 7 failed;
after: 248 passed across the related tool/chat/RIM/catalog/refinement suites.
The actual model choice and full customer LSR remain subject to installed live gates.

Build 838: four runtime-facts tests in `test_chat_evidence_application_service.py`
check a fixed observed date, actual catalog names without private paths, absence
of code-side price/norm selection, non-estimator isolation, empty catalog, and
1000-file bounded rendering with explicit partial inventory. Focused 174 passed.
This does not establish professional applicability or financial completeness.

Build 837: `test_estimator_card_keeps_source_resource_evidence_without_inventing_composition`
in `test_model_research_tool_service.py` reproduces dropped typed resource evidence,
checks unchanged source fields and explicit missing work composition, and forbids
invented applicability/selection. Before fix: 1 failed/9 passed; after: tool-service
and norm-browser suites 42 passed. Financial live acceptance remains separate.
`test_sheet_packet_prompts_do_not_request_the_whole_sheet_again` reproduces the
contradictory whole-sheet instruction for a one-row packet; packet/refinement
and chat tests pass (178). It does not impose a fixed operation count.
Three `test_vor_readiness_*` in `test_chat_evidence_application_service.py`
verify preserved authored unresolved gaps, unchanged row roles/quantities,
independence from norms/prices, and separate delivery/completeness flags.
This closes live-observed hidden questions in the initial 837 PDF VOR.

Build 836: `test_completed_replay_after_restart_keeps_calculation_snapshot_and_same_file`
in `test_workbook_tool_service.py` verifies immutable calculation metadata and
same revision/SHA on replay through a newly created checkpoint/artifact context.

Build 835: `test_artifact_revision_service.py` reproduces the installed 834
duplicate revision-number failure after local repack and concurrent deliveries
from the same parent. `test_workbook_chat_refinement.py` verifies a freeform
remark reopens the original document without a model planning handshake,
preserves all prior decisions and operator confirmations, and forwards all
five applicability flags and citations. These checks do not prove financial
readiness; installed model → RAG → XLSX acceptance remains mandatory.

Build 775: table divider width regression preserves both material and work
rows at one locator for short/equal/long dividers; existing invalid-divider
and invalid-numeric-cell protections remain covered in
`tests/test_chat_evidence_application_service.py`.


Build 772: `tests/test_freetoken_cache_profile_service.py` covers ACTIVE engine
selection independent of legacy provider, generation admission and cancellation
while a rebuild worker still runs. Settings reads use the non-mutating probe in
`tests/test_proxy_routers.py`. These do not replace live workbook acceptance.

`tests/test_lsr_source_coverage_service.py` and `tests/test_lsr_packet_integrity.py`:
material self-links, links to non-work decisions and all unresolved locators in
sources larger than the 80-item display limit remain open without rewriting rows.

`tests/test_lsr_packet_integrity.py`: low output budgets, invalid source
fragments and resumption of broken links without changing model norms.
`tests/test_lsr_source_coverage_service.py`: relative work-row coordinates
remain scoped to the source sheet and preserve explicit cross-sheet links.
`tests/test_installer_windows.py`: startup logs and `windows-light-state.json`
use the direct persistent-state path on a clean Windows install; runtime
junctions remain compatibility readers, not the creation path.
`tests/test_runtime_paths.py`: clean Windows state owns proxy/RAG MetaDB paths
and a fresh `JobService` creates its SQLite file directly under state `data`.

> **Статус: актуально.** Источник команд — `Makefile`; состав конкретных наборов
> задают его именованные переменные. Исторические счётчики и описание прежних
> поколений тестов перенесены в
> [`archive/TEST_INVENTORY_HISTORY_2026-08-30.md`](archive/TEST_INVENTORY_HISTORY_2026-08-30.md).

## Канонический gate

| Команда | Что доказывает | Чего не доказывает |
|---|---|---|
| `make verify` | version drift, импорт/синтаксис и сбор текущего явно перечисленного набора | живые сервисы и качество ответа модели |
| `make test` | короткий текущий contract/behavior gate `CURRENT_TESTS` | весь исторический репозиторий, GPU, пользовательский корпус |
| `make test-updater` | soft/hard update, rollback, persistent-state isolation, release receipt, Windows/Mac updater contracts | NSIS-сборку и установленный live runtime |
| `make test-rag-core` | contract native dense+sparse/RRF, атомарную alias activation/rollback, retrieval и index integrity | recall конкретного пользовательского корпуса |
| `make test-mail` | IMAP/Outlook registry, dedup, intake, API/UI и static Windows sidecar | живой Outlook COM на Legion |
| `make test-mail-release` | `test-mail` плюс Tauri compile-check | установленный Outlook и реальный ящик |

`make test` и `make verify` используют workspace-local
`.test-tmp/<profile>`. Непредсказуемый системный `%TEMP%` на Windows не является
частью контракта.

## Что входит в текущий LES

- Terminal LSR path: регрессия фиксирует ровно два вызова 9B-класса
  (model-authored queries и terminal result), отсутствие post-model quality
  loop в обычном запросе **включая sheet-pass**, неизменную передачу решений в
  workbook adapter и один идемпотентный packaging retry по той же checkpoint.
  Adapter принимает явный шифр `EXACT`/`ANALOGUE` без `EXACT_VERIFIED`;
  неизвестный код, единицы и model `MISSING` остаются unbound
  (`test_workbook_tool_service`, `test_rim_lsr_trace_service`,
  `test_chat_evidence_application_service`). Durable packet checkpoint
  (`test_workbook_research_job_service`) переживает pause/resume без повторного
  поиска кэшированных запросов: `should_cancel` остаётся истинным после `pause()`,
  иначе живой цикл продолжает пакеты. Этап Б: расчёт отказывается от позиции, если авторство модели по количеству/единице расходится с каталогом исходника без явного основания пересчёта — строка остаётся видимой как `unconfirmed_quantity` и не попадает ни в одну сумму; этап В разводит состояния строки в `readiness` (учтена/операция/норма/применимость/объём/расчёт/цены), заголовок `row_role=header` учитывается как `structure_accounted` без монтажной нормы, подтверждённая и предварительная суммы разделены (`test_rim_lsr_trace_service`, `test_lsr_result_readiness_service`); этап Г: namespace evidence различает попытки пакета (`:a<n>`), chunk meta хранит запрос модели (`model_query_text`), событие `search_cache` — sheet/packet/locators/queries, строка решения — `_evidence_check` (происхождение цитаты шифра без изменения статуса модели) (`test_chat_evidence_application_service`, `test_workbook_research_job_service`); этап Д: результат ЛСР содержит `price_basis` (запрошенная база — аргумент `pricebook`, уровень цен из текста исходника или период из вопроса — против фактических region/quarter книги; exact/mismatch/unspecified/no_book), несовпадение блокирует размерность цен до явного подтверждения альтернативы и печатается в шапке XLSX; список отсутствующих цен называет позицию, количество с единицей, проверенную базу и зависимые итоги (`test_workbook_tool_service`, `test_lsr_result_readiness_service`, `test_rim_trace_xlsx`); материал без количества больше не получает молча qty=1 (`test_rim_lsr_trace_service`). Точечное reopen locator сохраняет чужие
  решения. Этап А: `operation_id` устойчив через pause/resume/пересборку,
  несколько разных операций на одном локаторе не склеиваются, повтор того же
  решения не дублирует позицию, уточнение дописывает ревизию в
  `workbook_research_revisions`, запоздалая запись по устаревшему
  `base_revision` отклоняется (`test_workbook_research_job_service`, 12 тестов). `ChatRequest.comparative_acceptance_variant` принимает `B0_DIRECT`
  (`test_sovushka_chat`). Покрытие исходника,
  нормы и цены — `test_lsr_source_coverage_service`,
  `test_lsr_result_readiness_service`; UI уточнения/подтверждения без модели —
  `test_sovushka_chat`. Панель артефактов показывает новый XLSX сверху и
  прокручивает карточку готовности (`order_chat_file_artifacts`).
  Toast нового файла и кнопок ЛСР (resume/repack/confirm) входят в слот
  чата (`_notify` / `notify_in_element`); оценка
  remaining-time — `format_job_ready_eta_line` (`test_sovushka_chat`,
  `test_indexing_eta`). Reconnect closed-count uses accepted source rows
  when work-role is empty (`workbook_job_to_pending_progress`). N/M uses
  catalog work count, not accepted_all+leftover (`45/75` not `35/65`).
  History open hydrates a running job without a PENDING stub
  (`hydrate_chat_pending_from_workbook`). A paused first pass is not live
  assembly (`format_paused_assembly_notice`, `list_open`). Continue показывает leftover/accepted и seed ETA
  (`format_lsr_resume_display`, `sheet_pass_progress_counts`).
  Обрыв SSE после `tool_progress` не отменяет и не задерживает runner (`detach_chat_runner_after_disconnect`,
  `test_chat_stream_w51`) и не показывает «Соединение прервано»
  (`format_detached_stream_notice`, `follow_detached_chat_history`);
  реконнект не дублирует PENDING (`should_render_local_chat_pending`,
  `format_in_progress_assembly_notice`); live N/M и ETA после обрыва SSE
  читаются из checkpoint (`list_active`, `workbook_job_to_pending_progress`);
  повторный Continue не dual-run (`claim_or_join_sheet_pass`).
  Очередь модели ждёт `LES_MODEL_QUEUE_WAIT_SEC` (`test_runtime_admission`);
  мастер запуска идемпотентен; NSIS копируется из `CARGO_TARGET_DIR`
  (`test_tauri_desktop`). Контракт упаковки принимает operator `confirmed_data`
  (`test_workbook_tool_service`, `test_workbook_tool_contracts`,
  `test_chat_evidence_application_service`). Overflow workbook result
  остаётся у оператора (`test_chat_lsr_executor_keeps_overflow_workbook_for_operator`).
  Единый sheet-pass для малого и большого каталога —
  `test_chat_evidence_application_service`. Пустой `search_sources`
  (`missing`) не abort'ит пакет до таблицы строк
  (`model_search_result_blocks_packet`). Конверсия единиц только с источником
  и без угадывания габарита из названия — `test_rim_lsr_trace_service`.

- Исторический ADR-16: literal candidate helpers — `test_lsr_candidate_query_service`
  (дословная композиция из ячеек, drop-if-ungrounded, происхождение
  `original`/`derived`/`model`, compatibility прямого helper; в active chat975
  системные запросы не исполняются, старые квитанции сохранены);
  применижность нормы — `test_lsr_norm_applicability` (`EXACT` от модели ≠
  подтверждённая применимость, `norm_code` с evidence другого шифра не закрывает
  готовность, `ANALOGUE_CANDIDATE` без обоснования остаётся черновиком);
  групповые ресурсы — `test_lsr_group_resource_specificity`; ценовая база —
  `test_lsr_price_basis_explicit` (город ≠ ценовая зона, отсутствующий квартал
  предлагается и не применяется, запрошенная база не подменяется другой книгой,
  список доступных книг видим); владение ценой — `test_lsr_price_ownership`
  (подтверждённая цена оператора и выбранная книга сильнее ставки из карточки
  нормы; помеченная ставка карточки считается, но остаётся в
  `preliminary_amount`, называется в `price_gaps` и не делает позицию полной);
  замаскированная незакрытость — `test_lsr_disguised_gaps` (§ 11: «демонтаж»,
  посчитанный нормой «монтаж», остаётся вопросом; совпадающие и неоднозначные
  формулировки ложного вопроса не дают; шт не пересчитывается в 100 м²;
  подтверждённая цена материала не закрывает отсутствующую норму работ;
  двойной учёт одного предмета в двух ролях и неадресованное подтверждение не
  становятся подтверждённой суммой).
  Архитектурный gate закрепляет всё четырьмя кодами:
  `DERIVED_QUERY_SEMANTIC_INVENTION`, `QUERY_PROVENANCE_MISSING`,
  `PRICE_BASIS_SILENT_DEFAULT`, `UNOWNED_PRICE_SOURCE`
  (`test_architecture_contract_gate`).

- LSR quality gate: нейтральная проверка карточки, сохранение последнего
  `CONFLICT` после исчерпания поиска, отдельный честный `MISSING`, store-card
  и PDF Markdown source catalog с устойчивыми локаторами и точным work-row count;
  verify и выпуск доступного partial-XLSX при нуле подтверждённых строк.

- Evidence/chat: scope `none | selected | all`, evidence packet, context governor,
  typed citations/source navigation, immutable model-visible evidence manifest,
  explicit source-only capability, research tools и отсутствие кодового final вместо модели.
  Отдельные регрессии фиксируют обычные model-authored query lines, либеральное
  снятие только presentation wrappers, запрет memory-driven подмены provider,
  runtime-relative attachment handoff и неизменность model-owned workbook rows.
  Reader принимает короткий markdown-divider, заголовок монтажа с `norm_code` и
  явные спецификационные таблицы без нормы; stream keepalive и PENDING-history
  покрыты `test_chat_stream_w51` / `test_chat_history_router`.
  Заголовки model-authored `Qn`, которые не влезают в остаток окна, не роняют
  чат: регрессия фиксирует split/omit вместо `MODEL_RAG_EVIDENCE_BUDGET_TOO_SMALL_FOR_ALL_QUERY_HEADERS`.
  FreeToken KV: default 35000, 35B lift from legacy <16384, rebuild clamp к
  `max_feasible_kv`, ACTIVE выравнивает KV в начале хода
  (`test_freetoken_cache_profile_service`).
- RAG: contract-versioned named `dense + bm25_sparse`, native RRF, rerank,
  profile-owned overfetch/diversity/evidence limits, hierarchy/parent expansion,
  dimensional readiness, ready-generation guard для ColBERT и dataset integrity.
  Сметный integration-набор отдельно проверяет exact-SHA sibling-сборку
  SQLite+RAG, транзакционный rollback файлов и alias, startup reconciliation,
  фоновое восстановление, межпроцессную гонку, stale/fresh lock, произвольное
  переименование базы/alias, locked SQLite, недоступный Qdrant и явный
  GUI-warning при рассогласовании. `test_update_resilience_matrix.py`
  fail-closed связывает эти проверки с dataset/general-RAG/baseline/soft/hard
  update и не даёт им исчезнуть из именованных гейтов;
  отдельный boundary-test
  подтверждает, что живые source adapters используют самостоятельный document classifier,
  а не выключенный Unified Harness.
- Models: connection registry, secrets boundary, capability resolution,
  OpenAI-compatible transport, наблюдаемый KV FreeToken (`/v1/cache/status`)
  и одинаковый governed path для 9B/35B.
- UI: общий UIKit, WCAG AA, документы, чат, источники, model connections и
  отсутствие скрытого автоматического scope.
- Runtime/release: Windows process ownership, persistent-state boundary,
  bounded model queue, resident-model admission, отключаемые startup mutations
  для изолированной приёмки, safe public errors, lightweight/full update, legacy
  `les.release-attempt.v1` и раздельные
  `les.release-gate-receipt.v1` / `les.release-artifact.v1` /
  `les.release-acceptance.v2` / `les.release-publication.v1` и публичную
  проекцию `les.release-receipt.v2`; тесты фиксируют exact commit/tree/policy,
  неизменность artifact при failed acceptance, SHA-drift, revocation и выбор
  только успешной попытки. Publication требует accepted artifact, сохраняет
  draft/postflight checkpoints и не может вызвать builder. До Tauri/NSIS отдельный registry-тест сверяет
  literal `python -m` callsites с реально staged модулями и runtime manifest;
  незарегистрированный или отсутствующий entrypoint падает fail-closed.
  Registry покрывает dotted/simple `python -m`, staged Python/PowerShell/EXE;
  lock-bound `uvicorn` объявлен отдельно. Неопределённый acceptance failure
  блокирует retry до записанного operator reconciliation и не разрешает смену host.
  Full acceptance дополнительно связывает canonical hard-update job по SHA и
  сверяет все mutation roots до запуска Windows update engine.
  Installed acceptance и rollback сохраняются;
  native-RRF fixture не может схлопнуться в zero-chunk, а его exact временный
  dataset удаляется без snapshot всей пользовательской коллекции.
- Профессиональные модули: только их действующие contract-тесты. Сметный
  benchmark запускается отдельно и не заменяется общим pytest.

Точный перечень файлов всегда берётся из `CURRENT_TESTS` в `Makefile`. Новый
активный модуль добавляется туда в том же коммите, что и его код.

## Отдельные профили

| Профиль | Назначение |
|---|---|
| `make test-unit` | быстрые чистые unit-контракты |
| `make test-smoke` | герметичный offline API/scope/version smoke |
| `make test-integration` | временные SQLite/API/release-артефакты |
| `make test-model-connections-live` | явная opt-in проверка реального model endpoint |
| `make live-workbook-acceptance` | owner-authorized реальный workbook/model run |
| `make smoke-general-native-rrf` | установленный пользовательский RAG и native RRF |
| `make smoke-smeta-rerank` | active smeta base → RRF → reranker |
| `make smoke-basic-release` | живые API/UI после установки кандидата |

Live-профиль не запускается автоматически против пользовательских данных.
Отсутствующий Qdrant или корпус получает `N/A`, а не синтетический `PASS`.

## Историческая диагностика

- `make test-legacy` — 11 файлов прежнего Unified/Construction Harness.
- `make test-legacy-full` — repository-wide диагностика без отдельных ARTEL и
  legacy-harness профилей.
- Эти команды не являются release evidence и не входят в updater.

Исторический тест удаляется только вместе с доказанно удалённым поведением.
Большое число файлов в `tests/` само по себе не означает большое продуктовое
ядро: карта кода помечает тесты и ручные CLI как `TEST_OR_TOOL_ONLY`, но не
объявляет их мусором.

## Живые приёмки

### Тест № 1 — не мешает ли harness модели

Первым проверяется контрольный прямой путь на одинаковых входах:

`модель → сформулированные ею запросы → штатный RAG → та же модель`.

Затем та же модель, задача, вложение и dataset проходят через штатный ЛЕС.
Проверка fail-closed, если harness:

- передал модели меньше исходного текста или evidence, чем baseline;
- подменил поисковые запросы или предметные решения модели;
- показал `NO_DATA`, хотя вложение или RAG-результаты были доступны;
- повторил одинаковый отклонённый вызов либо дошёл до deadline вместо результата;
- ухудшил source coverage/инженерное решение относительно baseline без явной
  причины в trace.

Это installed live acceptance, а не pytest с заранее заданными ответами модели.
Unit/contract-тесты запускаются после него для закрепления уже доказанного
поведения и не могут превратить провал этого теста в `PASS`.

| Изменение | Обязательная дополнительная проверка |
|---|---|
| inference/RAG/workflow | тест № 1: direct model baseline ↔ штатный harness на одинаковых входах |
| retrieval/router при наличии корпуса | `tools/rag_golden_set.py` и открытая dataset-story acceptance |
| Windows выпуск | `make release`: install → smoke → rollback → restored smoke → reinstall |
| сметное поведение | защищённый benchmark из `AGENTS.md` |
| classic Outlook | установленный Legion COM/task/index/open smoke |
| model binding | explicit model-connection live acceptance |

Публичный выпуск допустим только после принятого installed receipt. Offline
pytest не подменяет этот результат.

## Правило сопровождения

При изменении поведения:

1. сначала тест, который падает на старом коде;
2. минимальное исправление;
3. точечный прогон;
4. `make verify` и `make test`;
5. обновление этой карты только при изменении профиля или границы проверки.

Не добавлять сюда хронологию релизов и старые числа `passed`: состояние выпуска
живёт в [`RELEASE_LEDGER.md`](RELEASE_LEDGER.md), история — в Git и архиве.
<!-- candidate945-meta-store-env-binding:v1 -->
## Кандидат945 — герметичность по хранилищу и честный состав гейта

* `tests/test_meta_store_env_binding_945.py` — 4 теста: `meta_db_path()` следует за окружением на
  каждом вызове; `WorkbookResearchJobService` и `MemoryStore` без явного пути берут путь из
  окружения и создают хранилище по нему; явный `db_path` приоритетнее окружения; два значения
  окружения дают два разных хранилища. До правки — ImportError/падение, после — 4 passed.
* Соседняя проверка переснята целиком: `tests/test_model_query_checkpoint_draft.py` — 15 passed
  при выставленном `RAG_META_DB_PATH` (пустое хранилище) и 15 passed при не выставленном. До
  правки в той же конфигурации — 8 и 4 падения.
* Регрессии 942–945 зарегистрированы в `Makefile` (`UNIT_TESTS += …`) и входят в канонический
  состав: `CURRENT_TESTS` = 274 файла, 4 960 теста.
  Полный прогон этого состава 15.10: 4 939 passed, 21 skipped, `GATE RESULT: GREEN`
  (`.test-tmp/gate945b.log`); пять файлов регрессий вместе — 17 passed.
* Зазор прежних проверок (важно для независимого пересмотра): разборщик гейта в
  `.test-tmp/gate942/943/944.py` терял 55 из 57 строк `UNIT_TESTS`, поэтому заявления
  «903 passed / 17 skipped» покрывали 65 файлов, а не весь состав. Полный прогон пересобран в
  `.test-tmp/gate945b.py` и печатает состав по группам перед запуском.
