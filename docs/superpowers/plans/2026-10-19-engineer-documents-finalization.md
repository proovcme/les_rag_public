# Финализация инженерных документов ЛЕС — Implementation Plan

> **For agentic workers:** исполнение task-by-task с независимой проверкой изменений; системная диагностика, RED/GREEN и verification-before-completion из obra/superpowers. Пользователь прямо поручил автономное исполнение; дополнительного согласования плана не требуется.

**Goal:** выдавать проверяемую ВОР в структуре образца и возобновляемую ЛСР, сохраняя правильные решения и добирая незакрытые позиции; подтвердить не менее90% применимости выбранных норм на проверенной выборке.

**Architecture:** сохраняем текущий model-owned маршрут, единый RAG и механический расчёт/экспорт. Исправляем только доказанные транспортные/экспортные дефекты, границы допуска и передачи evidence; модель выбирает работы, нормы и аналоги. Принятые строки имеют прежние ID/revision/evidence, повторный поиск ограничен явно открытыми операциями.

**Tech Stack:** имеющийся Python/uv, FastAPI/NiceGUI, SQLite, Qdrant, openpyxl, локальная Qwen3.6-35B-A3B-NVFP4 через FreeToken. Новых зависимостей нет.

**Spec:** запрос владельца19.10.2026; образец «ВОР монтаж БАП П1 13.05 (2).pdf»; AGENTS.md; ROADMAP_TO_V1.md; docs/archive/HANDOFF_965_2026-10-17.md.

**Фактическая точка19.10.2026:** технические задачи1–4 выполнены на установленном
966/0.31.238/native5.1.966 (`aca71dc1665e7b45971aa6948b3bb7f1d213a883`).
B0/B1 завершены как замер, **не professional PASS**. Кандидат967 ограничен
тремя измеренными исправлениями ниже; его полный clean gate, точный установщик
и установленная live-приёмка пока не подтверждены. `customer-ready=false`.

## Global Constraints

- Работать в существующем `codex/qwen-finalization`; не изменять чужой primary checkout.
- Никаких норм/объёмов/коэффициентов, выбранных кодом вместо модели; никакой подгонки под имя файла, раздел или конкретный шифр.
- Единая input+evidence граница; B0/B1 с одинаковыми исходником, моделью, профилем32k, областью, reader и исходной задачей.
- Несколько файлов, разные количества строк, нули и неизвестные значения сохраняются. Непрочитанные части обозначаются; графика без reader не объявляется прочитанной.
- Секреты/БД/индексы не читать и не удалять; никаких новых пакетов или cloud вызовов. Установка локального собственного кандидата — только после exact frozen gates, с откатом.
- Частичная ЛСР допустима с конкретными пробелами и продолжением. PRICED — только при полном доказанном расчёте. Точность и покрытие — разные показатели.

## Review Focus

- Несколько одновременных чтений/закреплений одного источника в Windows и разных процессах: исходник не исчезает, metadata остаётся валидной.
- Имя `=…`, кириллица/кавычки и идентичные адреса разных файлов: буквальные значения, разные namespace, без Excel formula injection.
- Печатный лист ВОР при повторном ВОР→ЛСР не создаёт дубликаты; поддельный или изменённый layout не скрывает исходные данные.
- Адрес с `::`/`:` и статусы отсутствующих норм/цен сохраняются в готовности и доборе, закрытые операции не переоткрываются.
- Большой ВОР после stop/restart/continue: тот же job, исходный запрос, книга цен, принятые строки и артефакт; первая порция не выдаётся за полный результат.

### Task1 — безопасное сохранение исходников

**Files:** `proxy/services/chat_attachment_service.py`; `tests/test_chat_attachment_retention_966.py`; существующая concurrent regression в `tests/test_attachment_collection_965.py`.
**Interface:** `retain_read_attachment_for_workbook(attachment_id, expected_sha256=..., root=...)`; прежние resolve/cleanup/consume контракты.

- [x] Воспроизвести WinError5 на неизменённом965: `artifacts/live_966/retention/race_red.xml`.
- [x] Устранить конфликт read/replace на уровне точной identity источника, без broad except и без ослабления теста.
- [x] Проверить два потока/процесса, cleanup/consume и неизменность bytes/SHA; обычный TTL неиспользованных файлов остаётся.
- [x] Запустить связанные attachment suites с workspace-local `--basetemp`; ожидание0fail. Отдельная независимая проверка diff.

Подтверждение: общий OS advisory lock, идемпотентный pin и повторная сверка
identity/SHA. Adjacent349passed/2skipped/39.76s,
`artifacts/live_966/retention/adjacent_final.xml`; затем полный966 V2 gate.

### Task2 — читаемый шаблон ВОР и буквальное происхождение

**Files:** `proxy/services/bor_service.py`; `proxy/services/attachment_source_catalog_service.py`; `tests/test_attachment_collection_965.py`; `tests/test_vor_print_template_966.py`.
**Interfaces:** прежний `source_rows_to_vor_xlsx` и typed `load_tabular_source_catalog`; canonical ВОР/audit и физические ссылки не сдвигаются.

- [x] Прочитать/отрендерить весь образец; пять колонок: №пп, Наименование, Ед.изм., Кол-во, Примечание; разделы, заголовок, Составил/Проверил.
- [x] Получить RED для formula-like filename; минимально закрепить source-cell как literal string без изменения имени/решения.
- [x] Добавить первый печатный лист с пятью колонками; выводить только авторские работы, явные расчётные величины либо исходные unit/qty, сохранять0 и вопросы.
- [x] Сохранить прежний технический реестр, материалы, связи, все решения и аудит. Не придумывать заказчика/объект/подписи.
- [x] Reader пропускает только строго проверенную generated presentation, соответствующую canonical rows. Изменённый/поддельный marker остаётся видимым источником либо явным blocker.
- [x] Проверить XLSX reopen/data_only, roundtrip без дублей, несколько файлов и более30 строк. Визуально проверить сохранённый printable layout.

Подтверждение: template+adjacent82passed/4.97s; related пять файлов после
согласования прежних canonical asserts с новым active print view —124passed/6.47s.
Все прежние raw/source/0/null проверки сохранены на листе «ВОР». Read-only render
sample.xlsx проверен; native Excel print не заявляется. Независимый combined
gate шести файлов —156passed/13.43s (`artifacts/live_966/independent_review.xml`).

### Task3 — добор без потери адреса и принятых решений

**Files:** `proxy/services/lsr_result_readiness_service.py`; `tests/test_lsr_multifile_gap_identity_966.py`; существующие `test_lsr_gap_hint_resume_964`, `test_pending_review_operation_identity`, `test_lsr_supply_retry_962`.
**Interface:** `row:<полный locator>:<status>`; delimiter статуса — последний; locator не интерпретируется предметно.

- [x] Воспроизвести потерю namespace через реальный генератор gaps и readiness.
- [x] Исправить только механическое разделение; сохранить single-file, Unicode, metadata и неизвестные статусы.
- [x] Проверить точные target operation IDs, сохранение closed-row revisions/evidence, исходного price_basis и дословного инженерного hint.
- [x] Проверить conserving retry в связанных offline service-регрессиях: меняются только открытые/явно выбранные операции, принятые строки остаются. Отдельный живой retry перенесён в Task5 и пока не засчитан.

Подтверждение: исходный RED10failed/4passed; related122passed/10.30s.
Механическое исправление и эти регрессии завершены; они не заменяют ещё
предстоящий installed ordinary/multifile retry с реальной моделью.

### Task4 — точный проверенный Windows-кандидат

**Files:** version contract/synchronizer, Makefile CURRENT_TESTS, module docs/ledger/inventory, существующие Windows release CLI и inert operators.

- [x] Проверить все diff, включить новые тесты в canonical gate, синхронизировать product0.31.238/build966/native5.1.966; не менять зависимости.
- [x] Freeze clean commit;9 канонических команд в новом immutable receipt. Ожидание все rc0, без скипа падающих проверок.
- [x] Собрать фактический NSIS; закрепить exact installer/native/runtime manifest SHA, затем dry-run действительного `%LOCALAPPDATA%/Programs/LES`.
- [x] Установка/откат/повторная установка/EXE-only/basic smoke: сохранить bindings,395 factors с направленной поправкой TTL,13 jobs/full cache/evidence и12 артефактов. Внешние модели не перезапускать.

Подтверждение: exact clean966 `aca71dc1…`, девять команд rc0,
325files/6171passed/20skipped/818.65s,
`artifacts/gates_966_final_v2/receipt.json`. Предыдущий RED gate сохранён отдельно.
Actual NSIS SHA67459e65…, packaged native SHA3ce118ce…,517 runtime files aligned.
Upgrade/rollback/reinstall/EXE-only приняты; basic smoke9pass/1warn/0fail.
Техническая установка не объявлена профессиональной приёмкой документов.

### Task5 — профессиональная приёмка результата

**Files:** существующие live-control CLI; новые append-only планы/квитанции `artifacts/live_966/`; отчёт качества по фактическим скачанным документам.

- [x] Снять один B0 и B1 для той же сохранённой ВОР→ЛСР и проверить фактический context/output reserve. Это завершённый замер, не положительный capacity/professional gate: два proof inference B1 не имели собственных Governor receipts.
- [ ] ВОР на разных форматах/разделах и комплекте файлов: работы обоснованы источником, unit/qty воспроизводимы, материалы связаны или имеют явный вопрос. Неизвестные данные не заменены0.
- [ ] ЛСР: скачать реальную ревизию, сверить каждую выбранную норму с прочитанной карточкой по объекту/операции/составу/измерителю/ограничениям; обоснованный аналог допустим с явным статусом.
- [ ] Precision = применимые выбранные нормы / все проверенные выбранные нормы. Непроверенные не засчитываются; coverage и финансовая полнота показываются отдельно. Требование ≥0.90 на проверенной выборке разных разделов, без критических несовместимых работ/единиц. Это измерение выборки, не гарантия любой будущей строки.
- [ ] Добрать незакрытые позиции, подтвердить неизменность принятых решений и непрерывную цепочку скачиваемых ревизий.
- [ ] Installed ordinary/multifile retry без подсказки и с естественным инженерным замечанием: сохранить закрытые операции, evidence, цену/регион/период; проверить фактически доставленные ревизии.
- [ ] Big318 stop/restart/continue; полная построчная сверка, без потерь и ложных зелёных. Отсутствие части норм разрешено, пустая ЛСР вместо результата — нет.
- [ ] Только после свежих доказательств итоговый вердикт: что передаётся, точные ограничения и реальные открытые вопросы. Никакой публичной публикации без отдельного указания.

Замер966: B0/B1 заняли288.407s/588.344s и выдали скачиваемые XLSX с7/8 авторскими
строками; модель выбрала1/3 кандидата нормы. Основные answer/read frames имели
32768 generation reserve при effective/observed/cache context131072; два proof
старта B1 не имели отдельного допуска, поэтому общий capacity verdict — unknown.
Толщина/условия/ресурсы остаются открытыми, ≥90% применимости не доказано.
Rerank во всех восьми B0 поисках был `disabled_by_runtime_policy`; успешная
доставка native RRF не доказывает точный fingerprint embedding weights/index.
Источники: `artifacts/live_966/final_v2/lsr32_comparison/`, включая независимые
`evidence_delivery_review.md`, `retrieval_contract_review.md` и `lower_chain_addendum_967.md`
в `B0_DIRECT/run/`. Новый rerank-on B0/B1, профессиональная оценка, diverse inputs,
ordinary/multifile retry и big318 остаются открытыми.

### Task6 — 967: сохранить штатную настройку общего reranker при Windows bootstrap

**Files:** `tools/windows_runtime.py`; `installers/windows/start-light.ps1`;
`tests/test_windows_reranker_bootstrap_967.py`; существующий installer contract;
`docs/PLATFORMS.md`.

- [x] Воспроизвести исходный override на реальном Python runtime_environment и изолированных штатных PowerShell helpers: RED13failed/8passed.
- [x] Сохранить явные true/false с единым precedence: nonblank persisted GUI → nonblank process → true; не переписывать persistent bytes и остальные настройки.
- [x] Проверить новые случаи и прежние native boot/entrypoint/installer контракты:56passed/9.07s; `artifacts/live_967/reranker_bootstrap/{red.xml,green.xml,receipt.json}`.
- [ ] Подтвердить на установленном967 actual per-search `reranked=true`/`rerank_status=ok` и доставленный evidence; enabled/ready недостаточно.

Операторы967 подготовлены только inert. Их14 jobs/14 artifacts и395 factors
не подменяют будущий полный prepare через `?view=full`. Legacy966 rollback при
cold boot снова может навязать process=false: strict parity не ослабляется,
восстановление GUI true — отдельное действие root с квитанцией.

### Task7 — 967: отличать ссылку на контейнер НР/СП от canonical rule_id

**Files:** `proxy/services/model_rag_grouped_evidence_service.py`;
`proxy/services/model_lsr_result_contract.py`; `tests/test_nrsp_catalog_reference_967.py`;
связанные lossless-render регрессии.

- [x] Закрепить измеренный случай, где hash общего каталога был принят за ID правила.
- [x] Единый marker `catalog_ref=[…] (не rule_id)` и буквальная инструкция копирования rule_id; сохранить исходные правила, ставки, условия и byte-exact восстановление.
- [x] Проверить потерю неоднозначности и прежние контракты: green93passed/0.824s, adjacent235passed/32.176s; `artifacts/live_967/nrsp_catalog_reference/`.
- [ ] Подтвердить правильное чтение model-authored rule_id в новой установленной live-паре; код не выбирает и не исправляет ставку вместо модели.

### Task8 — 967: полный proof-запрос допускается ContextGovernor до inference

**Files:** `proxy/services/chat_evidence_application_service.py`;
`tests/test_sheet_proof_context_admission_967.py`; связанные proof/native-read тесты.

- [x] Воспроизвести два proof старта, которые добавляли предыдущий ответ после первичного admission; отдельно воспроизвести зависание обычного продолжения после overflow.
- [x] Допускать весь предыдущий ответ, запрос proof и текущие карточки существующим Governor с отдельным purpose receipt, прежними резервами/инструментами и measured connection revision.
- [x] При overflow сохранить завершённый ответ/строки и явную техническую причину; не создавать zombie pending READ/паузу, скрытую inference или новый предметный цикл. Обычное «Продолжи» проверено для обоих видов proof.
- [x] Targeted proof gate **6 файлов /127passed/28.53s**, rc0; `artifacts/live_967/proof_context_admission/offline_receipt.json`.
- [x] Root независимо повторил три новые suite: **31passed/12.16s**, `artifacts/live_967/root_independent_final.xml`. Это offline verification, не full release gate и не professional PASS.
- [ ] После exact clean967 gate/install переснять B0/B1 с собственными Governor receipts каждого реально отправленного proof inference и профессионально проверить доставленные документы.

## Skill sources и самопроверка

Использованы skills obra/superpowers на commit `bb92a77741419a4ab5f06e711a283343f1ada0c3`: systematic-debugging, test-driven-development, verification-before-completion, writing-plans. Они установлены в пользовательские Codex skills; инструкция пользователя об автономном исполнении имеет приоритет над общим предложением заново согласовывать план. Проверены также первичные materials anthropics/skills/docx и promptfoo assertions/evals; новых runtime dependencies не добавляем.

Самопроверка: каждому требованию владельца соответствует задача; новый printable layout имеет отдельный roundtrip regression; точность не смешана с заполнением, принятый кодом шифр не считается автоматически профессионально правильным. Установлен966;967 остаётся кандидатом до exact full gate/install/live verification. История ошибок не удаляется, отложенные работы не выдаются за завершённые.
