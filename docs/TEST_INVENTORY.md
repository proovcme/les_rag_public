# TEST_INVENTORY — текущая карта проверок ЛЕС

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

- ADR-16 (сметный путь): систематический сбор кандидатов кодом — `test_lsr_candidate_query_service`
  (дословная композиция из ячеек, drop-if-ungrounded, происхождение
  `original`/`derived`/`model`, лимит = interrupted/deferred, а не «нормы нет»);
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
