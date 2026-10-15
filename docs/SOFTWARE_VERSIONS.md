# Версии программного контура ЛЕС

## Кандидат0.31.218 / 946; установлен945

Product0.31.218/build946/metadata5.1.946 — кандидат, gate/install pending.
Последняя живая сверка: runtime945/0.31.217, a0a5c1fd, alignment aligned.
Native EXE5.1.813 по предыдущей квитанции; новая Windows-поставка не принята.
NSIS3.11 найден и version-call проверен; это ещё не installer acceptance.
ANSWER: назначенная immutable FreeToken revision r10, Qwen3.6-35B-A3B-NVFP4.
customer-ready=false; подробности и ограничения — RELEASE_LEDGER.

<!-- candidate941-cited-literals-bound-warmup:v1 -->
## Кандидат0.31.213 / 941; установлен940

Product0.31.213/build941/metadata5.1.941 — кандидат; gate/install pending.
Установлен940/0.31.212, commitf42c379f4f315fa3a5cb4d63ee0e46edb0694e94.
Native EXE5.1.813, новый installer не проверен. Frozen940:4889 passed,
20 skipped; B0/B1/refinement XLSX доставлены, профессиональная приёмка failed.
Операторский startup warmup=false, ANSWER FreeToken r10. customer-ready=false.
Точный статус и отрицательные квитанции указаны в RELEASE_LEDGER.

<!-- candidate940-neutral-source-facts:v1 -->
## Кандидат0.31.212 / 940; установлен939

Product0.31.212/build940/metadata5.1.940 — кандидат. Runtime939/0.31.211,
commit2cfc255b6083904269783b8c9c680afbbd24383c; native EXE5.1.813.
Frozen939:4882 passed; post-deploy basic smoke10/10, native-RRF1/1.
Четыре контроля r10/r11 профессиональную приёмку ЛСР не прошли.
Gate/install/live940 pending; customer-ready=false. Полный новый installer
не принимался. Exact deployment/factor guard receipts указаны в RELEASE_LEDGER.

<!-- candidate939-proof-kind-sampling:v1 -->
## Кандидат0.31.211 / 939

Product0.31.211, build939, metadata5.1.939. Установлен runtime938,
commit2dbd7b527849dc0af5a4522d49aa735473a893d2; native EXE5.1.813.
938: frozen4798 passed,13 receipts rc=0; repack936 без модели проверен.
Свежие938 B0/B1 не прошли профессиональную приёмку. Gate/install/live939
pending; **customer-ready=false**. Новый native установщик не проверен.

## Кандидат0.31.210 / 938

Product0.31.210, build938, metadata5.1.938. Установлен runtime937,
commit979366e433e6f8cf5483fada66b85b68ba6e6c82; native EXE5.1.813.
937: frozen4779 passed,13 receipts rc=0; repack936 без модели подтверждён.
Свежий B0 частичный, B1 query-generation-limit; **customer-ready=false**.
Gate/install/live938 pending. Наличие новой metadata-версии не доказывает
приёмку нового native установщика или качество выбора норм.

## Кандидат0.31.209 / 937

Product0.31.209, build937, package metadata5.1.937. Установлен runtime936,
код339e652684e71f463e4d695a39035441c513ef30; native EXE5.1.813.
Frozen gate937/установка/живые документы pending; **customer-ready=false**.
Полная независимая проверка исправлений и ограничения — RELEASE_LEDGER.

<!-- installed-930-931-norm-card-proof:v1 -->
## Установлен 0.31.202 / 930 и 0.31.203 / 931

Product0.31.203, build931, desktop5.1.931; native EXE остаётся5.1.813 — это runtime-патч,
приёмка нового установщика не заявляется. 930 (`1bb9a5ad`) и 931 (`139f6fd2ce94324efbd2ca29075f1b5a79704b8e`)
установлены dry-run → apply → штатный stop/start; откат на 930 и 929 описан планами
`artifacts/rollback_929_to_930/` и `artifacts/rollback_930_to_931/`.

Frozen профиль931: **4703 passed, 20 skipped, 5 warnings за 696.84 с**
(`artifacts/gates_931_cipher_verdict_final/`), все гейты rc=0. Живой замер на FreeToken
`Qwen3.6-35B-A3B-NVFP4` (ревизия подключения `…:r10`, `input_token_limit` 8214): 930 дал один
proof-раунд и 15 строк без вердикта о показе карточки; 931 записывает вердикт для каждой
строки с шифром, дал два proof-раунда (12 непрочитанных строк → 7 прочтений модели; 3 ссылки →
6 прочтений) и впервые поднял `norms_applicability_substantiated` с 0 до 8 из 17.
`calculated_positions` 0, подтверждённая сумма 0,00; СКС остановлен на
`MODEL_QUERY_GENERATION_LIMIT` (0 из 75). Большой ВОР (386 нумерованных строк в 10 листах)
дал draft-ревизию `rev_69f9d13c103f44d2851330302eae3686` (sha256
`73271e2e72e6b5dc4a6a0dc6b555f8089e002ad375e95c8d74b0c01982191cad`) с нулём блоков, где
деньги стоят на шифре без показанной карточки; учтено 34 строки из 386, задача на паузе
(`model_query_generation_pending`), темп 1,08 строки в минуту. **customer-ready=false**;
подробные числа, причины и незакрытые проверки — RELEASE_LEDGER.

<!-- installed-929-live-closeout:v1 -->
## Установлен929: результаты живого сравнительного контроля

Установлен runtime **0.31.201 / 929**, commit `c2624773f6b7dcf7856efb38d0012a971c6aa45b`; receipt `artifacts/live_929/installed.json`, 23 доставленных файлов. Это runtime-патч: native EXE не переустанавливался, приёмка нового установщика не заявляется. **customer-ready=false**.

Frozen r3: **4683 passed, 20 skipped, 5 warnings in 693.80s (0:11:33)**; 16 exit receipts успешны. Smoke929: **8 PASS / 2 FAIL / 0 WARN**. Отрицательные результаты сохранены: diagnostics_endpoint: diagnostics overall='err', 1484.0 мс; chat_project_noscope: ReadTimeout: timed out, 90016.0 мс. Увеличением тайм-аута они не заменены.

Оба контроля: `Qwen3.6-35B-A3B-NVFP4`; источник, вопрос, профиль, назначенное подключение и область B0/B1 сверены по comparative_identity. Профили и модель не изменяются этим закрывающим документом.

- **B0_DIRECT**: 143.19 с; `measurement_complete`; решений модели 19 (work=19), адресов источника в решениях 19/20. Исходник: 19 рабочих строк + 1 PDF_TEXT-контекст; norm_selected=true у 7/19 строк проекции; XLSX 1. confirmed=0.0, preliminary=510742.89, вычисленных позиций=0. `priced_partial`. Ценовая книга `sankt-peterburg_3kv2026`, match=`exact`.
  Доставка по тексту, допущенному governor: полные ресурсы 6 карточек; показанный состав 1, literal composition lines 1; declared complete 1. Это наблюдение доставки, не применимости. Native calls=0; исполненных запросов 19, search_hits=114. Grouped trace агрегирован по 1 страницам; это page observations с возможными повторами, его исходные completeness counters не заменяют governor delivery. Model result=`accepted_unchanged`, packaged=True; ошибки receipt: нет.

- **B1_CANDIDATE**: 315.38 с; `measurement_complete`; решений модели 20 (unresolved=1, work=18, header=1), адресов источника в решениях 20/20. Исходник: 19 рабочих строк + 1 PDF_TEXT-контекст; norm_selected=true у 11/20 строк проекции; XLSX 1. confirmed=0.0, preliminary=35877.1, вычисленных позиций=0. `priced_partial`. Ценовая книга `sankt-peterburg_3kv2026`, match=`exact`.
  Доставка по тексту, допущенному governor: полные ресурсы 18 карточек; показанный состав 12, literal composition lines 12; declared complete 12. Это наблюдение доставки, не применимости. Native calls=0; исполненных запросов 30, search_hits=180. Grouped trace агрегирован по 3 страницам; это page observations с возможными повторами, его исходные completeness counters не заменяют governor delivery. Model result=`accepted_unchanged`, packaged=True; ошибки receipt: нет.

Числа получены из завершённых receipt/final/source_audit и calculation_snapshot; SHA и размеры скачанных файлов проверяются. norm_selected, суммы и наличие XLSX не доказывают профессиональную применимость норм или качество всех документов. Сравнение относится к одному БАП; разные разделы, большой ВОР, multi-input/ZIP, реальная котировка ЭТМ и точный установщик остаются отдельными незакрытыми проверками.

Источники: `artifacts/live_929/installed929_bap_b0/`, `artifacts/live_929/installed929_bap_b1/`, `artifacts/live_929/basic_function_smoke.json`. Прежние negative gates и записи этапов ниже сохранены как история; их pending-статусы не описывают текущую установленную сборку.

## Кандидат 0.31.201 / 929

Frozen r3 завершён: **4683 passed, 20 historical skipped, 5 warnings**;
version/compile/collect/architecture/map/docs/active-artifacts/mail/metadata
успешны (mail66, metadata31). Receipts: `artifacts/gates_929_frontier_r3/`.
Пять посторонних файлов не менялись. Все11 обновляемых runtime-файлов
соответствуют известной928 при предустановочной сверке; очередь свободна.
Кандидат ещё не установлен, live929 pending; **customer-ready=false**.

Product0.31.201, build929, metadata desktop5.1.929. Установлен runtime928
(`e80564d7`), native EXE5.1.813.929 ещё не установлен; **customer-ready=false**.
FreeToken Qwen3.6-35B-A3B-NVFP4, connection r8, профиль,64K и budgets не меняются.
Гейт9284561 passed; live B0/B1 не прошли качество, smoke8 PASS/2 FAIL.
Подробные результаты, причины и rollback — RELEASE_LEDGER.

## Кандидат 0.31.200 / 928

Product0.31.200, build928, metadata desktop5.1.928; native установленный EXE
остаётся5.1.813. Установлен runtime927/`9221b04c`; exact candidate928 install,
live comparative gate и качество разных ВОР/ЛСР ещё не подтверждены.
Модель FreeToken Qwen3.6-35B-A3B-NVFP4 отвечает в read-only preflight;
зависимости, индекс и inference defaults не изменены. Перед выпуском нужны
frozen verify/test/architecture/docs и реальные baseline/candidate документы.
**customer-ready=false**. Контракты: MODULE_INDEX и RELEASE_LEDGER.

## Установлен 0.31.199 / 927

Read-only источник ЭТМ, маскированные GUI-факторы и поиск/прайс XLSX;
distinct suppliers и совместимые единицы в КАЦ. Целевые81 passed;
frozen927:4411 passed,20 historical skipped,mail66,metadata31;
structural gates exit0. Установлен927/9221b04c; API/stamp/runtime19 SHA сверены.
Native EXE5.1.813. Модели, зависимости, профиль inference и retrieval не менялись.
API6 PASS, RRF1/1; первый smoke9/10, отдельный повтор10/10. Холодное сравнение
с926 подтвердило сохранение факторов, подключений, профилей и jobs.
iPRO задан в скрытых GUI-полях, API-авторизация не подтверждена. Live котировка
и профессиональная приёмка разных ВОР/ЛСР открыты;
customer-ready=false. [Контракт](modules/etm-supplier.md).

## Установлен 0.31.198 / 926

Установлен runtime **0.31.198 / 926**, code commit `8748b76f`.
API, deploy stamp и три поставленных SHA сверены; native EXE остаётся 5.1.813.
Default profile, назначение FreeToken r8/Qwen3.6-35B-A3B-NVFP4/64K и старые
задания сохранены. Откат runtime925 подготовлен в `artifacts/rollback_925_to_926/`.
Это runtime patch; приёмка точного нового установщика не проведена.

926 исправляет только lifecycle: `ModelTransportError` внутри owned sheet pass
сохраняет checkpoint, ставит `model_transport_pending` и возвращает исходную
ошибку; `finally` освобождает gate. Принятые строки, evidence/cache, task/source
и identity не переписываются. Ни нового поиска, решения, MISSING или успешного
документа обработчик не создаёт. Actual-producer RED2 и GREEN10 сохранены;
четыре постоянных failure-point регрессии находятся в
`tests/test_model_query_failure_job_lifecycle.py`.
Канонический full926: **4367 passed, 20 historical skipped**, mail66,
metadata31; все 16 офлайн-гейтов exit0. Живые опыты ниже не заменены этими тестами.

Живые контроли отрицательны: продолжение полного БАП сохранило тот же job,
task/source и cache29→42, но required62232>47104 остановил его до файла.
Парный первый frame4: B0_DIRECT доставил черновой XLSX с неправомерными
аналогами (в том числе труба800мм вместо кабеля), confirmed0; B1 после
сохранённого начального503 и одного явного повтора дважды исчерпал8192 на
незавершённые запросы и остановился до RAG. Frame возвращён в0; Thinking16K
не активирован. **customer-ready=false**: произвольные документы,300+ строк,
профессиональный подбор и новый установщик не квалифицированы.
Точные измерения и различия контрольных областей —
[RELEASE_LEDGER](RELEASE_LEDGER.md).

## Кандидат 0.31.197 / 925

Фактический runtime924/41ea6db3; native EXE5.1.813. Кандидат925 меняет только
capacity admission fresh discovery inventory и подтверждение доставленных refs.
Подключение FreeToken r8/Qwen3.6-35B-A3B-NVFP4/64K, профили, output limits,
source_frame_rows=0 и роль embedding не изменены. Целевые205 tests passed;
full925r2:4363 passed,20 исторических skipped, mail66, metadata31,
structural/docs/map gates exit0. Installed925 ещё pending. Предыдущие парные Thinking16K измерения924
отрицательные: B0 output LENGTH16384, B1 required52012>47104. customer-ready=false.

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

Installed reference 913/c3391515. Candidate 914 changes VOR instructions, strict query metadata transport and owned-job technical pause; no new dependency, model or global profile. Семипольные строки явно объявленной моделью ВОР принимаются также из Markdown и block text без norm_code. Сохраняются уже объявленные пустые поля этой ВОР; отсутствующие поля не добавляются. Для ЛСР, необъявленного, конфликтного или недопустимого типа прежнее требование norm_code не меняется. Это устраняет подтверждённое расхождение JSON и текстовых представлений, не назначая операции или нормы.

Frozen914 offline canonical gates PASS: 4153 passed, 20 skipped, 5 warnings in 265.14s (0:04:25); mail: 66 passed, 4 warnings in 6.47s; metadata: 31 passed in 4.38s. Fresh installed professional controls pending; customer-ready=false.

## Кандидат 0.31.185 / 913 — явный контекст в пределах наблюдаемой ёмкости

Installed reference912/dd42132e. Candidate913 needs fresh installed context and professional controls. No new dependency, model or profile change. Frozen913 offline canonical gates PASS: 4076 passed, 20 skipped, 5 warnings in 259.17s (0:04:19); mail: 66 passed, 4 warnings in 6.36s; metadata: 31 passed in 4.38s. Customer-ready=false.

## Candidate 0.31.184 / 912 - optional export declaration in model queries

Installed reference911/ccfa7bfa; candidate912 requires fresh installed proof. No new dependencies or model-setting changes. Frozen912 offline canonical gates PASS: 4056 passed, 20 skipped, 5 warnings in 256.51s (0:04:16); mail: 66 passed, 4 warnings in 6.27s; metadata: 31 passed in 4.40s.

Candidate0.31.183/build911; installed reference910/6a150da8. No dependency changes.
Frozen911 offline canonical gates PASS: 4031 passed, 20 skipped, 5 warnings in 258.34s (0:04:18); mail: 66 passed, 4 warnings in 6.39s; metadata: 31 passed in 4.48s. Local Gemma comparison is separate from FT acceptance and does not establish customer readiness.

Earlier entries retain their stated build/date scope.

Candidate0.31.182/build910; installed reference909/dff2c65a. FT r8/profile/dependencies/budgets unchanged. Frozen910 offline gates PASS; installed/professional acceptance and exact installer remain pending.

Earlier entries retain their stated build/date scope.

Candidate0.31.181/build909; installed pre-change reference908/14e35980.
Original FT r8/profile/dependencies unchanged. Frozen909 offline gate PASS; installed/professional gates pending; customer-ready false.

Earlier entries record evidence at their stated build/date.

Candidate0.31.180/build908; installed pre-change reference907/8fd316a2.
Dependencies, original FT r8 and active estimator profile unchanged. Frozen offline gate3835PASS; install/professional gates pending.

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

Candidate0.31.179/build907; original local model/r8/profile/dependencies unchanged.
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

Candidate0.31.178/build906; models/providers/dependencies unchanged.
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

Candidate0.31.177/build905; dependencies/providers/models unchanged.
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

Candidate0.31.176/build904; dependencies/providers/models unchanged.
Provider count deadline15s; bound revision guard and purpose-scoped carrier clarified;
context/generation reserves and saved profiles unchanged. Installed/live904 pending.
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

Кандидат0.31.175/build903, dependencies/providers unchanged.
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

Кандидат0.31.174/build902, dependencies/providers unchanged.
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

Кандидат0.31.173/build901, dependencies/providers unchanged.
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

Кандидат0.31.172/build900: доставка выбранных действий resource строк.
Dependency graph и модели прежние; новая installed приёмка pending.
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

Canonical/install/live900 pending; customer-ready false.

Кандидат0.31.171/build899: покрытие/operation identity/действия готовности.
Dependency graph, модели и финансовые правила прежние.
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

Focused70passed + repack33passed; canonical/install/live899 pending. Customer-ready false.

Кандидат0.31.170/build898: буквальный разбор punctuated named records, включая
bullet/numbered lists; dependency graph, модели и финансовые правила прежние.
Installed897 f3c348e4: nativeRRF PASS, basic9PASS/1FAIL, matched B1 query output
исчерпан без запросов; query-off B0 ответил, но comma-records не дали XLSX.
Query-off B1 за148.02s скачал priced_partial; не закрыты FSEM, НР/СП и reuse.
Canonical8983370passed/20existing skipped, metadata31; offline gates PASS.
Профессиональная приёмка не пройдена, nativeEXE5.1.813; install/live898 pending.

Кандидат0.31.169/build897: именованные inline-строки, сохранение coverage identity,
отдельный диагностический вопрос unresolved ФСЭМ. Финансовые правила и зависимости
не меняются. Canonical8973345passed/20existing skipped, metadata31; прочие
offline gates PASS. Installed8969fa11dd1, nativeRRF PASS; B0 priced_partial/B1
no XLSX, basic9PASS/1FAIL. Профессиональная приёмка не пройдена;
live897 pending. NativeEXE5.1.813, облако выключено.

Кандидат0.31.168/build896: authority поискового и итогового типа документа.
Installed895 a9fb241b; nativeRRF PASS, matched B0/B1 не прошли профессиональную
приёмку. FreeToken35B r8/64k и Ollama bge-m3 r1 восстановлены без смены ролей.
Dependency graph прежний; focused200passed, canonical3326passed/20existing skipped,
metadata31; остальные offline gates PASS. Install/live896 pending.
Новый native EXE не собран; установленный shell5.1.813. Cloud выключен.

Кандидат0.31.167/build895: адрес ресурса exact-card и конфликтующие строки книги.
Исходный runtime89450f8eb06; новая профессиональная приёмка pending. Dependency graph
не изменён; fgis-mcp0.3.1 прочитан как внешний исходник, пакет не установлен.
NativeEXE5.1.813 сохраняется; текущий публичныйmain142c41c6 содержитbuild712.
Canonical895:3312passed/20existing skipped, metadata31; остальные offline gates PASS.
Текущий установленный runtime: `/api/version`; контрольные receipts: artifacts/live_895.

Кандидат0.31.166/build894: query target публикуется с принятой попыткой.
Установлена893 ac042060, canonical3276passed/20existing skipped; B0/B1 без XLSX.
Зависимости прежние, EXE5.1.813, профессиональная приёмка не пройдена.

Кандидат0.31.165/build893: инструкции по фазам поиска/итога; зависимости прежние.
Installed892 d26f0df2; nativeRRF PASS, basic8PASS/1WARN/1FAIL, synthetic B1 без XLSX.
Профессиональная приёмка не пройдена; EXE5.1.813 не пересобран.

Кандидат0.31.164/build892: точный query envelope/commentary, зависимости прежние.
Installed891 `4f435358`, canonical3272passed/20existing skipped, nativeRRF PASS,
basic9PASS/1WARN. Синтетические B0/B1 дали XLSX, профессиональная приёмка не пройдена.
Native EXE5.1.813 не пересобран. FreeToken r8/64k; Flash r3 output8192 отключён.

Кандидат `0.31.161` / build `889`: выдача частичного workbook при cloud budget stop.
Зависимости неизменны. Installed888 `e84afdee`: offline3242passed/20existing skipped,
RRF PASS, basic9PASS/1WARN; liveFlash БАП12/19, customer-ready false.
Canonical889:3249passed/20existing skipped, остальные offline gates exit0.
Install/live889 pending. NativeEXE5.1.813 не пересобран.

Кандидат `0.31.160` / build `888`: финальный protocol guard и строгий basic smoke.
Зависимости неизменны. Installed887 `962d965b`: RRF PASS, basic9PASS/1WARN,
answer audit FAIL (raw tool frame). Canonical888:3242passed/20existing skipped,
остальные offline gates exit0. Install/live888 pending.
Нативный EXE по-прежнему5.1.813; профессиональная приёмка не заявлена.

Кандидат `0.31.159` / build `887`: provider reasoning_content в native продолжениях.
Зависимости неизменны. Installed886 `efb28f25`: после возврата FreeToken r8/64k
nativeRRF PASS, basic10PASS/0WARN/0FAIL, но answer audit выявил raw tool-call
в history766 (ложноположительный basic). Canonical887:3226passed/20existing skipped,
остальные offline gates exit0. Install/live protocol887 pending.
Реальный desktop EXE остаётся5.1.813; новый установщик не собран.

Кандидат `0.31.158` / build `886`: ограниченный native receipt replay и точная
диагностика read stops. Dependency graph прежний. Installed885 `10c3c827`:
canonical3206passed/20existing skipped, RRF PASS, basic9PASS/1WARN/0FAIL.
FreeToken128k B0 завершился без XLSX по повторному запросу; приёмка не пройдена.
Canonical886:3216passed/20existing skipped, verify/architecture/docs exit0.
Install886 pending. Native EXE остаётся5.1.813.

Кандидат `0.31.157` / build `885`: восстановление legacy read ledger через
цепочку продолжений документа. Зависимости неизменны. Installed884 `8c2fb702`:
RRF PASS, basic9PASS/1WARN/0FAIL. Native EXE остаётся5.1.813.
Canonical885:3206passed/20existing skipped; verify/architecture/docs exit0.
Install885 pending; профессиональная готовность не подтверждена.

Кандидат `0.31.156`/build`884`/Tauri`5.1.884`: накопление receipts после resume,
без изменения dependency graph. Canonical/install pending. Installed883
`22a88e81`: smoke9PASS/1WARN/0FAIL, nativeRRF PASS. Flash B1 и продолжение дали
14 успешных чтений норм,257092tokens, затем budget stop; готового XLSX нет.
Native EXE остаётся5.1.813; профессиональная приёмка не пройдена.

Кандидат `0.31.155`/build`883`/Tauri`5.1.883`: подтверждение доставки исходных
evidence для чтения по Qx.Hy. Dependency graph прежний; related245passed,
canonical3203passed/20existing skipped; verify/architecture/docs exit0.
Install/live pending. Installed882 `1b09191c`, nativeRRF PASS,
basic9PASS/1WARN/0FAIL. Native EXE остаётся5.1.813; готовность не подтверждена.

Канонический паспорт совместимости. Версия продукта и номер сборки берутся только из
[`config/version.json`](../config/version.json). Полный Python-граф фиксирует `uv.lock`.

Кандидат `0.31.154`/build`882`/Tauri`5.1.882`: wire-admission optional context и
native budget checkpoint. Dependency graph прежний; related146passed,
canonical3196passed/20existing skipped, verify/architecture/docs exit0; live
pending. Установлен881 `95de9b32`, RRF PASS, basic9PASS/1WARN/0FAIL.
Flash B1 stopped budget после66364 tokens, final/XLSX нет; ready не подтверждено.

Кандидат `0.31.153`/build`881`/Tauri`5.1.881`: safe budget diagnostics через
HTTP/SSE/history, без изменения dependency graph. Профильные91passed,
canonical8813191passed/20existing skipped. Установлен880 `6554b3fe`, smoke10PASS после запуска Ollama;
BAP Flash B0 stopped budget113s, XLSX нет. Готовность не подтверждена.

Таблица описывает кандидат `0.31.152`/build`880`/Tauri`5.1.880`;
880 добавляет необязательный GUI-бюджет облачного хода; dependency graph прежний.
Canonical880:3189passed/20existing skipped, verify/architecture/docs exit0.
Установка/профессиональная приёмка880 pending. Установлен879:
879 сохраняет техническую причину native capacity stop в итоговой диагностике.
Dependency graph прежний; related48passed, canonical8793178passed/20existing
skipped, verify/architecture/docs exit0. Установлен Python runtime879,
commit `1b5c0b40564b199895584e20caa3a9a3663dee60`, exact stamp/rawSHA проверены.
NativeRRF exit0; basic smoke7PASS/1WARN/2FAIL (оба chat timeout180s).
Поздняя история: завершены225/266s, research deadline после5/8 web calls,
raw tool markup в одном ответе. Приёмка не пройдена; native EXE5.1.813 сохранён.
Предыдущий установленный контроль:
установлен Python runtime `0.31.150`/build`878` commit
`cc6d8b5d58e8a5536bcceb1efcb8283d612b7d76`: metadata имени/единицы ценовых
кандидатов. Focused131passed; canonical3177passed; exact install/SHA/nativeRRF
подтверждены, basic9PASS/1WARN/0FAIL. FreeToken engine0.1.3+g52322e984:
B0 thinking11rows/confirmed0; B1capacity54351/46171estimatedtokens, нет XLSX.
Price-pointer path этими прогонами не вызван. Профессиональная приёмка FAILED.
Installed876 canonical:
3174 passed; smoke9PASS/1WARN; Alibaba B0/B1 завершились с partial XLSX,
профессиональная готовность не подтверждена. Native EXE остаётся5.1.813.
Состояние и точные receipts — RELEASE_LEDGER, раздел878/879.

Ниже сохранена историческая запись875 до установки:
candidate `0.31.147`/build`875`/Tauri`5.1.875`;
установлен `0.31.146`/build`874` commit
`c4253e38ea9539eb841e993eb373a42665079c0a`. 875 содержит narrow saved-repack
replay guard и поддержку standalone artifact_kind transport для row decoder.
Native-capacity resume сохраняет literal query state и truthful overflow trace;
read binder резервирует весь original query range до новых native Q refs.
Deferred raw cursor не зависит от native handles и сохраняет исходный alias order.
Reopened review instruction требует все предложенные прежние операции; ordinary
continuation сохраняет delta. Код не восстанавливает omitted review rows.
Pinned pricebook SHA и model-authored rows сохраняются; missing immutable
artifact/checkpoint не запускает новый расчёт под старой identity.
Focused cache100/transport139/native-read143/review316 passed. Second875 gates
после последнего source freeze GREEN: verify25.59s; test3128 passed/20 existing
skipped/5 warnings318.59s (wrapper320.12s); architecture10.42s/baseline7.86s/
active artifacts0.61s, все exit0. Receipts: `artifacts/verify_875_second.exit.json`,
`artifacts/test_875_second.exit.json`, `artifacts/architecture_875_second.exit.json`,
`artifacts/baseline_875_second.exit.json`, `artifacts/active_artifacts_875_second.exit.json`.
Exact install и fresh comparative live875 pending; ready не заявлено.
Installed874 professional FAILED: BAP260.5s, B0~79s без файла, SKS~387s overflow;
EOM821.75s partial ВОР23/56, первое24-row JSON тело потерял parser (875 replay
exact-equal). SKS continue16.56s без answer phase, BAP remark738.11s с файлом
ещё не принят. Готовность заказчику не заявлена.

Следующие замеры относятся к прежнему состоянию872/871:
candidate 0.31.144/build 872; установлен 0.31.143/build 871
(`e8657ba38eed88dac8de327b5e4dd9b2999869f4`). API/GUI и 19 runtime hashes сверены;
native EXE858 retained. Candidate872: UTF-8 Windows prepare fixture, literal
previously-shown full-code navigation при missing exact read и lossless unread
pointer-field aliases. Код не выбирает норму и не расширяет context/GPU budget.
SECOND canonical 871: 2925 passed / 20 existing opt-in skipped / 5 warnings,
verify/architecture/baseline/active artifacts exit0. Private prepare 871 отдельно
сохранил 2924 passed / 1 encoding fixture failure / 20 skipped / 6 warnings
(219.48s). CP866 + UTF-8 Python воспроизвели byte0xaa; после восстановления
production UTF-8 preamble и strict capture — 17 passed (4.18s). Exact prepare872 pending.
Metadata872 verify0 (23.48s), 2945 collected; version/docs/release31 passed (4.99s),
documentation contract0. Полный canonical872 pending.
Installed native RRF871 exit0 (0.91s). Original basic90s: 7 pass / 1 warn /
2 timeout fail (182.59s; wrapper183.91s), glossary/project по90s. Separate finite
180s run: exit0, 10 PASS / 0 WARN / 0 FAIL за112.66s; glossary61.547s,
project48.687s. Исходный failed run сохранён; latency изменчива.
Professional871 **FAILED**: same-identity B0 331.73s required46993/budget46246
(+747), семь read frames; B1 92.17s required47433 (+1187), paused20remaining/
0accepted, шесть exact cards delivered; оба без XLSX. Visible131k trial не изменил
observed physical KV65536 pages×page_size1 при advertised262144. Исходная65k
policy восстановлена в public bindingr6; GPU/KV/server/model не менялись.
Готовность заказчику не заявлена.
Техническая доступность не доказывает профессиональное качество.
Фактические receipts и состояние выпуска — [`RELEASE_LEDGER.md`](RELEASE_LEDGER.md).

## Версия ЛЕС

| Поле | Значение | Назначение |
|---|---:|---|
| Версия продукта | `0.31.218` | Единственный пользовательский номер по схеме `X.Y.Z` |
| Номер сборки | `946` | Монотонный номер Windows-пакета; не является четвёртой частью версии |
| Версия пакета Tauri/NSIS | `5.1.946` | Внутренняя монотонная версия установщика для обновления существующих `5.1.x` |
| Схема строительного контура | `0.24` | Внутренняя версия контракта; в пользовательский номер не входит |

`0.29.2` — release candidate с идемпотентным offline bootstrap, внешним Qdrant по HTTP,
ограничениями profile text и GitHub Releases update channel. Docker не входит в lifecycle ЛЕС
и остаётся лишь одним из пользовательских способов запуска Qdrant. Статус фактической установки и публикации фиксируется только в
`docs/RELEASE_LEDGER.md`. Новая несовместимая возможность получает следующий minor SemVer;
готовый стабильный продукт — `1.0.0`.

Canonical899 final snapshot artifacts/gates_899_r2:3381passed/20existing skipped/5warnings,
metadata31passed; verify, architecture, docs/map и active artifacts PASS.
Чужие UI-правки исключены и SHA сохранены. Первый snapshot superseded до
финального изменения repack; готовность определяется только final r2.
Install/live899 pending; professional acceptance не пройдена.

## Рабочий контур Windows

Снимок проверен на контрольной Windows-машине 29 августа 2026 года. «Проверено» описывает воспроизведённую среду, а не
разрешение бесконтрольно обновлять компоненты.

| Компонент | Зафиксировано в проекте | Проверено на Legion | Роль |
|---|---|---|---|
| Windows | Windows 11 x64 | Windows 11 Pro `10.0.26200` | Целевая рабочая система |
| Python | bundled portable CPython `3.13.12`, SHA-256 проверяется при staging и перед распаковкой без MSI/реестра; `uv` запрещено скачивать интерпретатор | `3.13.12` | API, интерфейс, обработка документов |
| uv | bundled `0.11.29`, SHA-256 проверяется при staging/bootstrap; exact lock + offline cache, без system/network fallback | release smoke обязателен | Среда и воспроизводимые зависимости |
| Docker Desktop | не является runtime ЛЕС; версия не зашита | Docker `29.3.1` | Только один из внешних способов запустить Qdrant |
| Qdrant | внешний HTTP-сервис; container-профили фиксируют `qdrant/qdrant:v1.17.1`, GUI хранит `QDRANT_URL` | native Windows `1.19.0`; существующая collection `les_rag_v563`, 101 366 points | Dense и sparse индексы, нативный RRF |
| Ollama | внешний user-managed runtime; wizard показывает status и официальный адрес | `0.31.1` | Один из локальных answer/embedding providers |
| Основная модель | выбирается пользователем в настроенном provider; у ЛЕС нет обязательной модели | Big Qwen и `qwen3.5:9b` проверялись отдельно | Ответы и работа с инструментами |
| FreeToken | внешний loopback OpenAI-compatible runtime, запускаемый своим GUI | `0.1.1+g30aa89115` | Альтернативная локальная генерация; ЛЕС не запускает второй engine |
| FreeToken Big Qwen | выбирается оператором в FreeToken GUI | `Qwen3.6-35B-A3B-NVFP4`, API metadata context `262144`; LES default window `35000` (factory 35B), rebuild clamps to GPU-feasible KV with min MoE; extended preset needs observed KV ≥ 16384 | Большая локальная MoE-модель; transport принудительно отключает thinking, сохраняет dialogue memory и наполняет общий multi-document evidence до безопасной capacity |
| Эмбеддер | отдельная user-configured роль; опубликованный индекс требует совместимую identity/размерность | `bge-m3:latest`, `1024` в принятом корпусе | Dense-векторы |
| ColBERT late interaction | `BAAI/bge-m3`, token vectors `1024`; optional, GUI-controlled | требует live preflight/сборку sibling generation для `0.27.54` | MaxSim rerank до общего cross-encoder |
| RAPTOR summarizer | local Ollama `qwen3.5:9b` или deterministic extractive fallback; optional, GUI-controlled | требует live publication acceptance для `0.27.54` | Navigation-only summary tree; не evidence |
| Реранжировщик | `BAAI/bge-reranker-v2-m3`, optional и выключен по умолчанию | отдельный `sentence-transformers` вес проверялся | Экспериментальный реранк после RRF; отсутствие сохраняет RRF |

`latest` запрещён для Qdrant: изменение серверной версии способно изменить формат хранения и
поведение поиска без изменения кода ЛЕС. Для моделей Ollama тег остаётся частью их идентификатора;
перед заменой фактического содержимого модели нужен отдельный контроль качества.

## Сборочный контур Windows

Эти программы нужны на Windows-сборщике для создания EXE, но не устанавливаются пользователю вместе с ЛЕС.

| Компонент | Зафиксировано | Проверено на Legion |
|---|---|---|
| Node.js | lock-файл npm | `24.14.0` |
| npm | `package-lock.json` | `11.9.0` |
| Rust | `Cargo.lock` | `rustc 1.97.0`, Cargo `1.97.0` |
| Tauri CLI | `2.11.4` | `2.11.4` |
| Tauri | `2.11.5` | собирается Cargo |
| tauri-build | `2.6.3` | собирается Cargo |

## Python-пакеты ядра

Точные версии читаются из `uv.lock`. На текущем зафиксированном графе ключевые пакеты:

| Пакет | Версия |
|---|---:|
| FastAPI | `0.136.1` |
| NiceGUI | `3.12.0` |
| qdrant-client | `1.18.0` |
| ollama (Python-клиент) | `0.6.2` |
| Qwen-Agent | `0.0.34` |
| Google ADK | `2.5.0` |
| Google GenAI | `2.12.1` |
| Starlette | `1.3.1` |
| websockets | `15.0.1` |
| pytest | `9.0.3` |

## Правило обновления компонентов

1. Не использовать плавающий образ инфраструктуры.
2. Сначала изменить этот паспорт и lock/config.
3. Прогнать `make test`, `make test-rag-core` и живой Windows-smoke.
4. Для Qdrant дополнительно проверить существующий named volume и откат.
5. Для модели повторить качество инструментов, RAG и сметного сценария.
