# TEST_INVENTORY — текущая карта проверок ЛЕС

## 11.10.2026 — .204, шаг 4: однозначная область поисковых запросов

В model_rag_query_instruction сметная инструкция начинает с работ и материалов,
заголовки оставляет контекстом. Убрано противоречивое требование охватить «все
строки»; generic RAG сохраняет прежний текст. Парсер и исполнение literal queries
не менялись. Доставка проверена интеграционным тестом (focused136 PASS).
Живой .203 не улучшил запросы: заголовки2→3, цены0; новая .204 ещё не принята.
Полные факты и следующий шаг — audits/lsr-pr21-integration-20261008/p9/query-step4-20261011/REPORT.md.


## 11.10.2026 — .203, подготовка

Шаг4 .203: tests/test_model_rag_query_budget_rows.py — инструкция заголовок/работа + сохранение literal queries + неизменность generic RAG; tests/test_chat_evidence_application_service.py — доставка через штатный query Governor. 136 passed. Runtime registry clean-source/stale-staging regressions отдельно; canonical pending.


11.10.2026: оба коммита Claude fc606ba1 (.201) и 61b2e2c1 (.202) перенесены
fast-forward в codex/public-03064-modular-uplift. Установлено .201/build841/fc606ba13d47;
.202 находится в исходниках, не выложена. Локальные документы и исходный индекс
сохранены в .test-tmp/claude-integration-20261011; предыдущий HEAD защищён веткой
codex/backup-before-claude-integration-20261011. Код до переноса совпадал с frozen .200.
Модели/настройки не менялись: answer r11 IQ3_XXS-text/Vulkan, bge CPU, timeout1800.
Следующий шаг: формирование запросов, сохранённый v2-контроль; практика none, STOP318.
Новые контрольные прогоны: только p9-run-control-vulkan-text.py, probe-vor-v2.xlsx,
--expected-rows 9, абсолютный --out, без --question-file. Это 9 исходных строк,
из которых 3 содержательные работы, не расширенный набор из 9 работ.
Поправка: срез v1 и дополнение к вопросу ошибочно связывали АР1.31 с демонтажом.
Оценка «укладка вместо демонтажа» отозвана как оценка полной ВОР; прежнее0/3
нельзя использовать как сопоставимую метрику. Неверный стеклянный материал,
несовпадение ссылок и неполнота доставки сохраняют собственные доказательства.
Текущий источник истины: CLAUDE-SMETA-HANDOFF-2026-10-11.md и план10.10;
сведения о прошлых установках ниже исторические. D1 на v1/r10 не запускать.


P9.19 .202/build842 (Claude, 11.10): reranker по умолчанию — bge-reranker-v2-m3.
Адаптер `lemonade_host.py` читает `LEMONADE_RERANK_MODEL`, затем общий `RERANK_MODEL`, умолчание
`bge-reranker-v2-m3-GGUF` (было зашито `Qwen3-Reranker-0.6B-Q8_0-GGUF`). Замер на 48 реальных
карточках норм, один запрос, два повтора: Qwen3-Reranker CPU 54 с / Vulkan 10,6 с; bge CPU 17,6 с /
Vulkan 4,0 с; топ-5 почти совпадает. bge на Vulkan рядом с 35B IQ3_XXS-text даёт
ErrorOutOfDeviceMemory на генерации, поэтому в Lemonade ему сохранён backend cpu; с ним
реальный запрос ответа .199 прошёл (157 ток/с промпт, 15,7 ток/с ответ).
Качество на трёх запросах не хуже Qwen; это замер скорости, не приёмка подбора норм.

P9.18 .201/build841 (Claude, 11.10): доставка нормативных карточек целиком.
`_fit_evidence_into_budget` мерит запрос по полным телам карточек: поздние запросы, которым
не хватило места, уходят целиком и объявляются в [ОХВАТ]; карточка больше доли бюджета на
запрос (max_chars // 5) сокращается открыто и чужие запросы не вытесняет. Replay сохранённой
выдачи .199 (28137 символов, без модели): было 15 запросов / 0 целых из 60 нормативных
карточек; стало 8 запросов / 19 целых + 6 ссылок / 0 обрезанных.
Бюджет запросов считается по строкам порции с единицей или количеством
(`query_rows_in_pass`): на входе .199 12 вместо 40; предел генерации списка запросов —
48 токенов на запрос бюджета, не выше LES_CHAT_MODEL_RAG_QUERY_MAX_TOKENS (576 вместо 1600).
Это ограничивает повтор запросов, но не устраняет его.
Контракт теста `test_model_rag_evidence_keeps_configured_candidates_*` изменён осознанно:
прежний закреплял «все запросы, тела урезаны поровну».
Installed остаётся .200; живого контроля .201 нет; профессиональная приёмка 0/3 не закрыта.
Известно: `test_assigned_model_timeout_is_named_and_restart_bound` падает на чистом checkout
и до этих правок — умолчание 300.0 он находит только в неотслеживаемых копиях сборки
`desktop/tauri/src-tauri/{resources,target}/runtime`.

P9.16 .200/build840: focused root47PASS; canonical2655PASS/19SKIP/5warnings
201.26s, verify2674collected/all4commands0, architecture0. Installed still199.
Closed material-status grammar reports exact raw invalid row, no guessed cells.
Installed199 saved-row replay reproduces accepted invalid prose; candidate200
installed replay and official rollback acceptance next. Professional0/3 not closed.

Release accounting repair: main index enumerates1160Pythonfiles, frozen1991167,
candidate2001168. Candidate map generated/checked with isolated index; main index
and HEAD preserved. All frozen199 Python bytes equal workspace except intended
chat_evidence parser; the new test is explicit. Full behavior suite ran before
generated-map-only refresh; fresh verify uses candidate-index ONLY for map command,
never for pytest (Git fixture subprocesses must keep their own indexes).
Candidate builder asserts frozen tree1168 matches generatedmap. After immutable
freeze regenerate workspace map for original main-index inventory; this does not
change tested runtime code or frozen artifact. Proof: table-width-20261010/candidate-index-proof.json.

.199 control finished2012.7s/all3restored, actualr10/IQ3 nofallback, nativecalls0,
fullpreviews0/102.84XLSXformulasPASS, same20queries/source/question197; wire verified
factoryadapter, system5491→5393,40remainingevidencechanges. Content audit pending.
35B officiallyidle-unloaded, noactiveinference. Practice none,STOP318,nopublic.

Historical installed .200 checkpoint:
P9.16 .200/build840 установлена: frozen5544c8e66e59,2replace/0delete,
install→rollback199→reinstall, nativeRRF3/3,33runtimefiles exact.
Canonical2655PASS19SKIP/verify2674/architecture0. Installed saved-row replay
199→200: invalid prose status now diagnosed, original31/32cells preserved.
Это подтверждает decoder boundary, не новую модельную/сметную приёмку.
.199 same-input control completed2012.7s/all3restored;0/102fullpreviews,reads0,
84формулыPASS. Content audit и direct thin baseline preparation следующий шаг.
Practice none,STOP318,nopublic. Подробности: p9/table-width-20261010 и handoff.

Исторические точки:

P9.15 .199/build839 установлена: exact frozen9affdc415e35,4replace/0delete,
install→rollback198→reinstall, nativeRRF3/3,33runtimefiles exact.
Canonical2641PASS19SKIP/verify2660/architecture0. Same-input none/r10 контроль
ACTIVE16770 в p9/candidate-0199-none-available-tools; результата ещё нет.
Последний .198 pass2: полные receipts8/8+1/1, но0/3; новый mismatch и31/32cells.
P9.16 source-only диагностика format status начата отдельно, в runtime199 её нет.

Исторические точки:

P9.15 source-кандидат .199/build839: ACTIVE model-driven estimator answer использует
только фактически доступный search_sources и Qn.Hm citations. Исправляются лишь
code-owned fragments проверенного factory prompt/skill (IDs + exact texts + hashes).
Custom/unknown historical тексты, query stage и nonestimate/legacy/shadow сохранены.
Registered factory texts/seed не менялись; original/rendered fingerprints разделены.
Root independently177PASS9.69s; live влияние на чтение и профессиональный выбор не доказано.
Runtime .198, последний pass2 завершён: полные receipts8/8+1/1, но профессионально0/3.
Canonical/installed .199 ещё pending. Модуль: docs/modules/chat-profiles.md.

P9.14 .198/build838 установлена и принята: frozen7efee9e69f26,
install→rollback197→reinstall, nativeRRF3/3,31runtimefiles exact.
GET-проверка показала честный tools UNKNOWN/legacy_http_accepted_no_native_proof;
выбранная r10/IQ3_XXS/32768 сохраняется без fallback. Snapshots/reprobe не менялись.
Canonical2632PASS/19SKIP,verify2651,architecture0. Это исправление диагностики.
Сейчас обычный pass2 той же сессии .197 идёт на .198 (exec59456): модель получает
настоящие расчётные чеки и сама решает, что исправить. Это не новый свежий baseline.
Последняя профессиональная приёмка pass1:0/3; текущий pass2 ещё не завершён.

Исторические срезы ниже:

P9.14 source-кандидат .198/build838: capability TOOLS требует наблюдаемого native
вызова вместо одного HTTP200. Старое HTTP2xx и advertised SUPPORTED показываются
как UNKNOWN без изменения immutable snapshots. Optional UNKNOWN сохраняет выбранный
primary и schema; explicit UNSUPPORTED и обязательные CHAT/security gates остаются.
Root review обнаружил и закрыл две границы через RED/GREEN; independently92PASS.
Canonical:2632PASS/19SKIP/5warnings156.46s; verify2651/all0; architecture0.
Installed .198 acceptance pending. Runtime .197/build837: контроль завершён,
native reads0, full previews0/102, частичный XLSX79формулPASS; профессионально0/3.
Модульный док: docs/ALGO-model-connections.md; evidence p9/capability-boundary-20261010.

Final .197 r1 canonical:2595PASS/19SKIP/5warnings, verify2614/all0,
architecture0. Wall11824.72s includes Windows Modern Standby observed in System:
506 at05:19:58 (SC_MONITORPOWER),507 at08:33:44 (Power Button),10.10.2026.
No caller identity is established. Initial pre-review gate199.22s is preserved
but is not the final release gate. Review availability P2 closed by conditional
wording with RED1→GREEN1; independent static review closed. Installed .197 accepted:
install→rollback196→reinstall/nativeRRF3/3, 30runtimefiles exact, 3HTTP norm reads
with14resources each. Same-input none/r10 control ACTIVE53086; professional result pending.

P9.13 source-кандидат .197/build837: `model_answer_request` явно ограничивает
Markdown/первую строку/noJSON итоговым пользовательским ответом; до него доступен
необязательный native search_sources по решению модели. Профессиональные правила,
schema, profile, queries и обычный ответный путь неизменны. RED1 → GREEN1;
diff-proof подтверждает старый contract после удаления одного уточнения.
Гипотеза требует installed same-input проверки, улучшение нормы не доказано.
Предыдущий .196 final: exact wire schema присутствует/HTTP200, reads0, книги нет
из-за6duplicateworkIDs; все3temporarysettings восстановлены, профессионально0/3.

P9.11: `tests/test_smeta_preview_resource_coverage.py` — пустой preview с известным
positive count, invalid/bool/unknown значения, labor-only и unchanged full read,
доставка при прежнем truncation. 11 focused PASS; независимый review PASS.
P9.12: transport/application tests — exact serialized bytes, retry/fallback,
отдельная корреляция, private-body/public-ref граница, cancellation, writer failure
без лишнего inference, opt-in только final/read. Review repair RED4 → 27 transport PASS,
independent11 audit PASS; event failure correlation и collision покрыты;
полный gate .196 завершён:2594PASS/19SKIP/5warnings, verify2613/all0,
architecture0. Installed/live request audit ещё pending.

P9.10: `tests/test_smeta_resource_group_parser.py` — 17 регрессий на буквальных
строках .193 и допустимых/недопустимых кодах. Installed .195 canonical:
2572 PASS / 19 SKIP, verify2591. P9.9 и P9.8c входят в этот gate.

P9.9: `tests/test_smeta_model_section_outcome.py` — explicit authored section,
reason/conflicts/duplicate IDs, no calculated work or receipt review, retained XLSX
source registry and cursor reopen/recalculation. 8 focused PASS; canonical pending.

P9.8c: `tests/test_smeta_real_receipt_governed_continuation.py` — numerical
receipt from the calculator → persisted portion/reopen → next governed messages,
including full JSON and last resource; exact review hash versus mismatched hash.
2 focused PASS (10.10.2026); full canonical rerun pending after live .193 finishes.
This boundary fixture does not demonstrate live model review or professional acceptance.

P9.8a: `tests/test_model_rag_read_continuation.py` — whole current card,
original context, omissions/cursor, required overflow, native schema reserve,
global Q-offset и UTF-8 durable receipt. `test_chat_evidence_application_service`
проверяет actual ACTIVE native-call → exact read → same model terminal messages,
ресурсы, scope и отсутствие авто-чтений в обычных ответах. Live pending.

P9/.192 candidate: full lexical/native union + sequential CrossEncoder24 batches; raw scores/global indices preserved; any failed or zero-valid batch raises. 65s per HTTP request, max browser100→5 requests. 70 focused PASS; live46 indices and 24 identical scores PASS. Canonical/installed pending. See [algorithm](ALGO-lsr-assembly.md).

P9 pool preservation (source candidate): `test_browse_does_not_drop_disjoint_channel_tail_before_reranking`
воспроизводит потерю хвоста одного из двух непересекающихся каналов до cross-encoder.
RED1→60PASS norm_browser; прежний wide-pool test усилен до проверки всех40карточек.
Никаких профессиональных ожидаемых норм; выходной limit6/5 сохранён. Live pending.

P9/.191: `test_cross_encoder_waits_for_a_valid_slow_host_response` воспроизводит
внешний deadline30с при разрешённых host60с и ответе35с (виртуальное время).
RED1→6PASS файла: все24 документа/индекса, один запрос, буквальный query сохранены;
явно заданный короткий timeout продолжает действовать. Live replay обязателен отдельно.

Дополнение P9/.190 (09.10.2026): `tests/test_smeta_norm_browser.py` проверяет
реальным SQLite FTS5 различение 0,8/0,5, 3,5/3,0 и 4/40, десятичную запятую/точку,
влияние тринадцатого слова на выдачу и trace всех слов при сохранённом exact key.
RED6 → 59 PASS всего файла. Эти проверки не доказывают семантическую применимость
норм и не заменяют installed native-RRF/model gate.


P9 .189: `test_smeta_receipt_budget.py` проверяет автоматическую вместимость
8/12/25 строк, сохранность полного receipt, явные1/7/25/0/-1 и неверный override.
`test_smeta_portion_profile_boundary.py` исполняет production вызов с исходником.
RED3 (реально показаны только7) →23focusedPASS. `test_smeta_source_registry_workbook.py`
добавляет обе формы метки source_row через structural check→официальный XLSX,
сохранность авторских полей и пять отрицательных неоднозначных/чужих ссылок.
Для метки RED2/10PASS; вместе с бюджетом/partial rows73PASS.
Канонические .189:2516PASS/19SKIP,verify2535,architecture0.

P9 .188: `test_model_rag_partial_rows.py` добавляет пять проверок полноты списка
запрошенных смысловых полей, roundtrip всех пяти без придуманной нормы и
отсутствие требования одной таблицы при разрешённых нескольких. RED6/1PASS,
focused169PASS вместе с application service и reference binding.
Канонические .188:2500PASS/19SKIP,verify2519,architecture0.

P9 .187: `test_smeta_norm_revision_binding.py` связывает validation→binding для
новой неизвестной ссылки, текущей ссылки на другую норму, найденной, но не
доставленной карточки, прежней ссылки без коллизии/без ссылки и новой валидной
редакции. Проверяет сохранность авторских полей и прежнего доказательства.
RED2 →17PASS; frozen replay реального pass2 .186 воспроизводит старое отсутствие
ошибки и новый `unknown_evidence_ref`, без новых генераций/изменения книги.
Канонические гейты .187:2493PASS/19SKIP,verify2512,architecture0.

P9 .186: `test_optional_practice_budget.py` — 18 проверок сохранения query preview
при optional full/preview cards, двух порядках групп, двух бюджетах и
переполненном query-only пути. Старый actual-chat archive-header контракт не
ослаблен. `test_decode_race_with_colliding_file_metadata_is_detected` меняет
реальный Parquet при имитации одинаковых файловых метаданных; reader обязан
обнаружить смену SHA. Focused packing56 PASS, price revision/basis40 PASS.
Полные гейты .186:2487PASS/19SKIP, verify2506,architecture0.
Installed install→rollback .185→reinstall .186 и3nativeRRF PASS;
профессиональная приёмка не пройдена.

P9 .185: `test_exact_read_does_not_materialize_unrelated_norm_resources` проверяет
реальную SQLite: cold exact read не нормализует чужие ресурсы, возвращает верную
identity, защищён от изменения копии; полный каталог после него не усечён.
Регрессия ловит воспроизведённый installed timeout .184 без временных порогов
в тесте. Реальная профилировка записана отдельно:41.48→0.98с,14ресурсов.

P9 .184: `test_active_chat_retrieval_executes_only_model_query` (4 случая) вызывает настоящий `retrieve_smeta_norm_cards` и browser с реальной временной SQLite; fake native-RRF/reranker только записывают фактические входы. Проверяются исходный запрос, отсутствие придуманных условий и query_expansion=False. Старый тест на mocked callback этого не доказывал. RED 4, focused 145 PASS; P9 .184/build824: canonical 2467 PASS / 19 SKIP, verify 2486 collected/0, architecture0.

0.30.183 P8: `test_smeta_transport_resume_contract` — реальные SQLite checkpoint/artifact stores и synthetic XLSX: commit→failure→restart без второго adapter, commit-then-error, ambiguity/provenance, один repair child, повторный storage failure, отмена и ошибка её сохранения. `test_chat_evidence_application_service` — отмена после окончательного ответа при delivery/packaging, cursor restart и rebuild без нового model transport. `test_request_idempotency_service`/`test_runtime_admission` — отмена SQLite workers и владение gate. `test_qdrant_adapter_parse` — пустой/шумовой replacement оставляет прежние dense+sparse+lexical данные. Это контролируемые исключения/отмена и sequential retry; не гарантия hard kill или конкурентного exactly-once.

P7 .182: exact-code/table scope intersection, nativeRRF prefetch/query filters, пустое пересечение без unscoped fallback; таблица и операции в actual final messages обычного/полного чтения. Синтетические SQLite и capture transport проверяют структурный контракт, не заменяют живую приёмку поиска.

P6 .181: long-work preview notice проверяется в фактических final messages; короткий состав и full read не получают ложной пометки. Существующие norm-full-read, context delivery, evidence budget и receipt budget остаются обязательными. Replay сохраняет точные входы/выходы,131 historical evidence SHA и раздельные границы потерь; это не новый model run.

P5 дополняет `test_smeta_norm_revision_reader`: принудительное совпадение metadata stamp при разных bytes, read lock до SHA, отсутствие повторного хеширования retained snapshot. Прогноз скорости по синтетической базе не заменяет замера реальной.

0.30.180 P5: `test_smeta_price_revision_reader`, `test_smeta_document_price_basis`, `test_smeta_price_basis_continuation` входят в canonical. Реальные synthetic Parquet A/B и XLSX, same-path replacement/cache/restart, conflicting exact records, persistent document basis, source SHA, early answer cache, SQL10/current20, missing/excluded цены,1000м. Это технические ценовые контракты, не профессиональная приёмка модели.

0.30.179 P4: `test_smeta_resource_identity_reader/binding/contract` включены в canonical SMETA_ACCOUNTING_TESTS. SQL→карточка→фактический пакет→parser→cursor restart→расчёт→чек→XLSX; одинаковые коды/цены10 и20, code-less/empty-name, группы, пропуски доставки, forged proof, aliases, цитата после обрезки, независимые количества, снятие/замена/машины/unknown. Профессиональный подбор не проверяется синтетическими решениями.

0.30.178: `test_smeta_source_cells_contract` — реальные XLSX/CSV/PDF с пустыми колонками,0/unknown, соседней массой, нестандартной единицей, словом «всего», заголовком/итогом и частичным ответом до настоящей XLSX. Форматирование пустого XFD не раздувает текст/ревизию; реальные данные XFD сохраняют исходный индекс. Включён в canonical SMETA_ACCOUNTING_TESTS. Это транспорт/охват, не профессиональная приёмка модельного подбора.

0.30.177: `test_smeta_norm_revision_reader/binding/contract` включены в SMETA_ACCOUNTING_TESTS. Контракты: A/B, cache/restart/race/WAL, mutable-cache isolation, доставка/подделка identity, локальные Qrefs/rebuild/fallback, receipt и XLSX. Synthetic evidence не является профессиональной приёмкой сметы; gate results — SESSION_LOG и audit receipt.

0.30.176: `test_smeta_unknown_consumption_contract` проверяет unknown/NaN/text
против настоящего 0/1 через Parquet→SQLite→reader→trace→receipt→XLSX,
legacy NOT NULL, различение null/0 при дедупликации, неизвестные часы ФСЭМ,
трудовые итоги и нечисловую явную цену. Это синтетическая регрессия целостности,
не оценка профессионального выбора нормы; результаты — P1 receipt/SESSION_LOG.

0.30.175: test_lemonade_model_connection_flow проверяет resolved4096 против catalog262144
и operator32768 до реального resolver; test_model_capability_service покрывает
недоступный/чужой/невалидный/слишком большой options и redirect. Предел модели не
подменяет configured/resolved окно. Это offline capability contract, не приёмка сметы.

0.30.174: test_smeta_norm_full_read содержит15 проверок: добавлены два маршрута практики, source→packed→final ресурсные строки/aliases, preview≠full, потеря при renderer и реальный Governor omission. Saved36/budget12–24–48k и cross-edition проверяют новый trace в test_resource_evidence_delivery_review. Offline replay проверяет24/26/33 настоящих строк через каждый из трёх маршрутов.

0.30.173: test_smeta_norm_full_read включён в CURRENT_TESTS через SMETA_ACCOUNTING_TESTS;9 проверок полного чтения/identity/нулей/unknown/бюджета. test_resource_evidence_delivery_review дополнен4 проверками разных исторических карточек и provenance. Это offline, не приёмка сметы.

T111.3: `SMETA_ACCOUNTING_TESTS` включён в `CURRENT_TESTS` Makefile. Семь файлов:
`test_model_material_accounting`, `test_material_accounting_review`,
`test_material_allocation_completeness_review`, `test_material_parent_context`,
`test_smeta_portion_profile_boundary`, `test_smeta_final_accounting`,
`test_resource_evidence_delivery_review`. Проверяют расчёт/остатки ресурсов,
ценовые единицы, комментарии реального XLSX, границу профилей и итоговые messages.
Это дополняет прежний явный current-gate; legacy-наборы не включаются автоматически.
T111.4 добавляет `test_model_rag_partial_rows`: сохранение исходных неоднозначных
ячеек, отсутствие расчёта такой строки, целостность ревизии и диагностика коэффициента.

> Plan C1: `test_windows_prebundle_smoke` executes a disposable PowerShell bootstrap fixture,
> real Python PID and HTTP servers: accepts current v2, rejects v1/unknown/empty contracts,
> retains bootstrap error diagnostics and isolated cleanup. This does not replace real bootstrap.
> Ingestion ownership subprocess receipts are per-PID files: shared Windows append lost a row in
> an aggregate run. Both same-file exclusion and unrelated-file interval overlap remain mandatory.

> Plan B5: `desktop/tauri/src-tauri/src/setup_probe.rs` includes six actual child-process tests:
> success, exit status, pipe-buffer-sized output, overflow, timeout and missing executable.
> Its ignored child fixture is explicitly invoked by the parent tests, not skipped acceptance.
> `test_tauri_desktop` pins async command delegation and the existing JSON/provider-neutral UI.
> Plan B4: `test_index_contract_parse_boundary` proves three no-op exits preserve contract bytes
> and mtime, and missing/mismatched contracts reject before parse/status writes on initialized collections.

> Plan B3: `test_ingestion_ownership` proves process exclusion, timeout and release on exception.
> `test_ingestion_replacement` exercises real `_sync_parse` with disposable MetaDB/LexicalIndex and
> in-memory Qdrant: six injected failures preserve accepted evidence; successful replacement retires
> exact IDs; two concurrent parses cannot share a stale census; SQLite rule/lexical transactions roll
> back on failure and preserve other owners. Pagination covers600 IDs. Removing the lock was observed
> to fail the concurrency regression. Existing resume test now asserts stored points, not delete counts.

> Plan B2: `test_converter_corrupt_pdf`, `test_converter_scanned_pdf_ocr`,
> `test_converter_process_isolation`, `test_format_pipelines`, `test_ocr_parser_backend`,
> `test_parse_pipeline_w14`, `test_qdrant_adapter_parse`, `test_tesseract_ocr` cover typed
> OCR failure, real blank/short-text PDFs, required subprocess timeout, Windows PNG access,
> source/page identity, preservation of previous evidence, and Public hierarchy compatibility.

> Plan B1: `test_retrieve_chat_chunks_preserves_native_results_on_reranker_error` covers
> constructor and inference failure with literal two-document content/order and typed bypass.
> Index-contract blocking tests and successful rerank/context expansion remain in the same suite.

> `tests/test_update_service.py` executes five real detached CLI cases (hard engine/lifecycle,
> soft helper/engine/lifecycle) without checkout or editable-install hooks, and checks soft
> dependency target-byte selection plus checksum rejection. These regressions caught missing
> Lemonade package imports that in-process mocked lifecycle tests did not expose.

> 0.30.79 regression audit: RIM timestamps must stay chronological, with append order only as the
> tie-breaker; release
> `prepare` must have local install/runtime/state defaults; Windows prepare SHA must use the local
> .NET helper without `Get-FileHash`; `smeta-base` is inspected as a static Makefile recipe, so
> this contract does not require GNU Make on Windows.

> `LEMONADE_EXTENSION_TESTS` входит в канонический `make test/verify` и фиксирует transport,
> factual vendor status, engine operation, host, end-to-end capability→resolver→request flow и
> Windows provider environment. Его offline lifecycle
> contract исполняет PowerShell provider map дважды, получает фактический PowerShell lifecycle-state,
> затем через disposable state и контролируемые Python process mocks доказывает освобождение owned
> adapter PID/`18080` перед candidate/rollback, сохранение foreign owner и отказ от dynamic port.
> Отдельная hard-update regression исполняет genuine pre-fix PowerShell v1 state с adapter URL
> `127.0.0.1:18081` (без port field), доказывает path-validated PID ownership, candidate rollback
> после unavailable adapter identity endpoint и отказ остановить foreign PID; реальный runtime не
> запускается.
> Updater acceptance проверяет shared embedding identity, принимает compatible operator/index-owned
> chunk contract и не переписывает `RAG_CHUNK_*`; реальный runtime не запускается.

> `CHECKLIST_TESTS` covers the checklist compatibility suites, the module registry contract
> and `test_lexical_pdf_provenance.py`. Frozen replay asserts 29 cards, 28 corrected and only
> `PD-AR-047` manual; tests use disposable SQLite/filesystem roots and do not open live Qdrant.

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

- Evidence/chat: scope `none | selected | all`, evidence packet, context governor,
  typed citations/source navigation, immutable model-visible evidence manifest,
  explicit source-only capability, research tools и отсутствие кодового final вместо модели.
  Отдельные регрессии фиксируют обычные model-authored query lines, либеральное
  снятие только presentation wrappers, запрет memory-driven подмены provider,
  runtime-relative attachment handoff и неизменность model-owned workbook rows.
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
  OpenAI-compatible transport и одинаковый governed path для 9B/35B. Lemonade extension tests
  отдельно фиксируют Qwen 3.6/`llama_cpp` transport policy, factual vendor loaded-state, exact
  embedding identity и loopback GET→dry-run→receipt-approved Flash Attention без FLM mutation.
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
- Package/update boundary: `tests/test_extension_package_boundaries.py` locks both literal
  package roots into wheel discovery, tracked Windows staging and Windows/Mac/VPS update allowlists;
  it additionally stages the only two trusted `proxy/storage/*.py` application files and rejects all
  other storage/data/secret paths. Arbitrary plugin, cache, persistent-state, absolute and traversal
  paths fail closed.
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
# P9.10 — групповые коды ресурсов (10.10.2026)

`tests/test_smeta_resource_group_parser.py` включён в CURRENT_TESTS: буквальные
строки модели и расчётные ресурсы из portable fixture, допустимые code/target
group fields, действующий hyphen code, сдвинутый hash и malformed dotted negatives.
RED6fail/11pass → focused67PASS с соседними partial/identity tests; canonical pending.
