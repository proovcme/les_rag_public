# Финализация инженерных документов ЛЕС — Implementation Plan

> **For agentic workers:** исполнение task-by-task с независимой проверкой изменений; системная диагностика, RED/GREEN и verification-before-completion из obra/superpowers. Пользователь прямо поручил автономное исполнение; дополнительного согласования плана не требуется.

**Goal:** выдавать проверяемую ВОР в структуре образца и возобновляемую ЛСР, сохраняя правильные решения и добирая незакрытые позиции; подтвердить не менее90% применимости выбранных норм на проверенной выборке.

**Architecture:** сохраняем текущий model-owned маршрут, единый RAG и механический расчёт/экспорт. Исправляем только доказанные транспортные/экспортные дефекты, границы допуска и передачи evidence; модель выбирает работы, нормы и аналоги. Принятые строки имеют прежние ID/revision/evidence, повторный поиск ограничен явно открытыми операциями.

**Tech Stack:** имеющийся Python/uv, FastAPI/NiceGUI, SQLite, Qdrant, openpyxl, локальная Qwen3.6-35B-A3B-NVFP4 через FreeToken. Новых зависимостей нет.

**Spec:** запрос владельца19.10.2026; образец «ВОР монтаж БАП П1 13.05 (2).pdf»; AGENTS.md; ROADMAP_TO_V1.md; docs/archive/HANDOFF_965_2026-10-17.md.

**Точка19.10.2026:** задачи1–4 завершены. Установлен968/`68f71f44…`: все9команд V4 и exact NSIS/rollback/reinstall/EXE-only приняты; baseline после live измерен18jobs/18artifacts. B0 не создал файл из-за structural_error; B1 доставил partial ЛСР, multifile — неполную ВОР. Ни один из этих live-результатов не является professional PASS. Source969 — кандидат0.31.241/native5.1.969 с четырьмя измеренными техническими исправлениями и explicit-operation инструкцией (Task9). Полный frozen gate/install/live969 и ≥90% профессиональной применимости ещё не подтверждены; `customer-ready=false`.

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

Подтверждение:349passed/2skipped/39.76s, `artifacts/live_966/retention/adjacent_final.xml`, затем полный966 V2 gate.

### Task2 — читаемый шаблон ВОР и буквальное происхождение

**Files:** `proxy/services/bor_service.py`; `proxy/services/attachment_source_catalog_service.py`; `tests/test_attachment_collection_965.py`; `tests/test_vor_print_template_966.py`.
**Interfaces:** прежний `source_rows_to_vor_xlsx` и typed `load_tabular_source_catalog`; canonical ВОР/audit и физические ссылки не сдвигаются.

- [x] Прочитать/отрендерить весь образец; пять колонок: №пп, Наименование, Ед.изм., Кол-во, Примечание; разделы, заголовок, Составил/Проверил.
- [x] Получить RED для formula-like filename; минимально закрепить source-cell как literal string без изменения имени/решения.
- [x] Добавить первый печатный лист с пятью колонками; выводить только авторские работы, явные расчётные величины либо исходные unit/qty, сохранять0 и вопросы.
- [x] Сохранить прежний технический реестр, материалы, связи, все решения и аудит. Не придумывать заказчика/объект/подписи.
- [x] Reader пропускает только строго проверенную generated presentation, соответствующую canonical rows. Изменённый/поддельный marker остаётся видимым источником либо явным blocker.
- [x] Проверить XLSX reopen/data_only, roundtrip без дублей, несколько файлов и более30 строк. Визуально проверить сохранённый printable layout.

Подтверждение: related124passed/6.47s, все canonical raw/source/0/null asserts сохранены; independent156passed/13.43s (`artifacts/live_966/independent_review.xml`). Read-only render проверен, native Excel print не заявляется.

### Task3 — добор без потери адреса и принятых решений

**Files:** `proxy/services/lsr_result_readiness_service.py`; `tests/test_lsr_multifile_gap_identity_966.py`; существующие `test_lsr_gap_hint_resume_964`, `test_pending_review_operation_identity`, `test_lsr_supply_retry_962`.
**Interface:** `row:<полный locator>:<status>`; delimiter статуса — последний; locator не интерпретируется предметно.

- [x] Воспроизвести потерю namespace через реальный генератор gaps и readiness.
- [x] Исправить только механическое разделение; сохранить single-file, Unicode, metadata и неизвестные статусы.
- [x] Проверить точные target operation IDs, сохранение closed-row revisions/evidence, исходного price_basis и дословного инженерного hint.
- [x] Проверить conserving retry в связанных offline service-регрессиях: меняются только открытые/явно выбранные операции, принятые строки остаются. Отдельный живой retry перенесён в Task5 и пока не засчитан.

Подтверждение: RED10failed/4passed → related122passed/10.30s. Installed ordinary/multifile retry остаётся в Task5.

### Task4 — точный проверенный Windows-кандидат

**Files:** version contract/synchronizer, Makefile CURRENT_TESTS, module docs/ledger/inventory, существующие Windows release CLI и inert operators.

- [x] Проверить все diff, включить новые тесты в canonical gate, синхронизировать product0.31.238/build966/native5.1.966; не менять зависимости.
- [x] Freeze clean commit;9 канонических команд в новом immutable receipt. Ожидание все rc0, без скипа падающих проверок.
- [x] Собрать фактический NSIS; закрепить exact installer/native/runtime manifest SHA, затем dry-run действительного `%LOCALAPPDATA%/Programs/LES`.
- [x] Установка/откат/повторная установка/EXE-only/basic smoke: сохранить bindings,395 factors с направленной поправкой TTL,13 jobs/full cache/evidence и12 артефактов. Внешние модели не перезапускать.

Подтверждение:325files/6171passed/20skipped/818.65s, все9команд rc0 (`artifacts/gates_966_final_v2/receipt.json`); NSIS SHA67459e65…, native3ce118ce…,517files aligned. Upgrade/rollback/reinstall/EXE-only приняты, smoke9pass/1warn/0fail. Предыдущий RED сохранён отдельно.

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

Замер966: B0/B1 —288.407s/588.344s, скачиваемые XLSX с7/8 авторскими строками,
1/3 кандидата нормы; ≥90% применимости не доказано. Основные frames: reserve32768/context131072,
два proof старта B1 без собственного admission → capacity unknown; rerank B0 отключён.
Квитанции и reviews: `artifacts/live_966/final_v2/lsr32_comparison/`.

### Task6 — 967: сохранить штатную настройку общего reranker при Windows bootstrap

- [x] `tools/windows_runtime.py` и `installers/windows/start-light.ps1`: явные true/false сохраняются; precedence nonblank persisted → process → true, без переписывания state. RED13failed/8passed →56passed/9.07s (`artifacts/live_967/reranker_bootstrap/`).
- [ ] Installed per-search `reranked=true`/`rerank_status=ok` и delivered evidence; enabled/ready недостаточно. Legacy966 rollback может вернуть process=false: strict parity не ослаблять, GUI восстановление только root с receipt.

### Task7 — 967: отличать ссылку на контейнер НР/СП от canonical rule_id

- [x] `model_rag_grouped_evidence_service.py` / `model_lsr_result_contract.py`: marker `catalog_ref=[…] (не rule_id)`, буквальное копирование canonical ID, byte-exact каталог без выбора ставки кодом. Green93passed/0.824s, adjacent235passed/32.176s (`artifacts/live_967/nrsp_catalog_reference/`).
- [ ] Подтвердить model-authored rule_id в новой установленной live-паре.

### Task8 — 967: полный proof-запрос допускается ContextGovernor до inference

- [x] `chat_evidence_application_service.py`: оба proof старта проходят общий admission с предыдущим ответом/карточками и отдельным Governor receipt; прежние резервы/инструменты сохраняются.
- [x] Overflow сохраняет завершённые строки, явную техническую причину и terminal/repack; оба обычных продолжения проверены без zombie pending/паузы или скрытой inference. Targeted **6 файлов /127passed/28.53s**, rc0 (`artifacts/live_967/proof_context_admission/offline_receipt.json`).
- [x] Root: три новые suite **31passed/12.16s** (`artifacts/live_967/root_independent_final.xml`); offline verification, не full release gate/professional PASS.
- [ ] Exact clean967 full gate/install, затем свежий rerank-on B0/B1 с proof receipts, diverse inputs, ordinary/multifile retry и big318; проверить качество доставленных документов.

### Task9 — 969: четыре измеренные технические границы, затем новая приёмка

- [x] History follow обещает файл только по текущему регистрируемому artifact; no-artifact/plaintext/legacy VOR не создают ложный banner, partial файл сохраняется.
- [x] Source-confirmed literal0 без начисляемых действий сохраняется информационной строкой без norm/price/retry долга; неизвестные/ненулевые/авторские перерасчёты не освобождаются от проверки.
- [x] Совместимые numeric price measures: исходная округлённая quote до конверсии, без раннего округления переведённой цены; два калькулятора и видимые XLSX формулы/precision. HALF_UP только новой ветки; old SI/quote приоритеты сохраняются.
- [x] norm_components сохраняется literal/deep-copy с norm_components_not_calculated и owner-operation аудитом; код не считает/не разворачивает состав. Добавочная норма запрашивается отдельной model-authored операцией с evidence.
- [x] Четыре focused969 test files и смежные проверки включены в canonical inventory; byte pins948/950 сохраняют старые контракты точным обратным удалением новых instruction literals. Actual итоговые числа root добавляет по квитанциям.
- [ ] Новый exact frozen969 full9 gate; canonical NSIS, actual extraction/pins, upgrade/rollback/reinstall/native-only/basic с неизменным18/18 baseline,395факторами и r12.
- [ ] Свежие installed969 B0/B1/multifile и реальный operation-level retry; проверить сохранение закрытых операций, evidence/price basis и скачиваемых ревизий. Внутренний field-lock открытой операции не обещается.
- [ ] Big318 stop/restart/plain continue и построчный контроль; затем независимая precision≥90% на проверенной разнородной выборке. Результат не объявлять готовым только по числу тестов/доставленных строк.

## Skill sources и самопроверка

Использованы skills obra/superpowers на commit `bb92a77741419a4ab5f06e711a283343f1ada0c3`: systematic-debugging, test-driven-development, verification-before-completion, writing-plans. Они установлены в пользовательские Codex skills; инструкция пользователя об автономном исполнении имеет приоритет над общим предложением заново согласовывать план. Проверены также первичные materials anthropics/skills/docx и promptfoo assertions/evals; новых runtime dependencies не добавляем.

Самопроверка: каждому требованию владельца соответствует задача; новый printable layout имеет отдельный roundtrip regression; точность не смешана с заполнением, принятый кодом шифр не считается автоматически профессионально правильным. Установлен968;969 остаётся кандидатом до нового exact full gate/install/live verification и профессиональной приёмки. История ошибок не удаляется, отложенные работы не выдаются за завершённые.
