# Алгоритм: Е.Ж.И.К. — локальный read-only сборщик почты

## Граница продукта

Е.Ж.И.К. не является почтовым клиентом и не меняет исходный ящик. Он сохраняет локальный
evidence-снимок писем, индексирует его штатным RAG-контрактом LES и показывает письма во вкладке
«Почта». Ответ, пересылка, SMTP и создание черновика не реализованы. Для Outlook доступно только
«Открыть в Outlook».

Главный data-contract: **один почтовый ящик = один отдельный P0-датасет**. Новые аккаунты никогда
не смешиваются в общем `MAIL_Index`. Старый `MAIL_Index` остаётся legacy-датасетом совместимости;
его файлы можно аддитивно назначить выбранному аккаунту через targeted migration, без глобального
reindex и без удаления legacy-источника.

## Источники

### Классический Outlook на Legion

`clients/outlook_mail_poller/LesMailPoller.cs` — Windows-sidecar без Office PIA. Он подключается к
уже запущенному и авторизованному классическому Outlook через COM, обходит все `Session.Stores` и
папки, исключая Deleted Items, Drafts и Junk по `OlDefaultFolders` identifiers `3/16/23`.

Для каждого `MailItem` sidecar:

1. сохраняет Unicode `.msg` через `SaveAs(..., olMSGUnicode)` вместе с вложениями;
2. передаёт multipart на loopback `POST /api/mail/collector/import`, который подтверждает
   долговечное сохранение снимка, не дожидаясь его загрузки и разбора в RAG;
3. передаёт `StoreID`, `EntryID`, `PR_INTERNET_MESSAGE_ID`, folder id/path и received time;
4. двигает per-store/per-folder newest+oldest cursor только после HTTP 2xx.

Backfill идёт возобновляемыми порциями не более 10 писем и с общим бюджетом прохода 12 секунд.
Один уже начатый `SaveAs` не прерывается, но после исчерпания бюджета sidecar не открывает следующий
`MailItem`. Per-folder cursor отдельно фиксирует
`backfill_complete`: после достижения старейшего письма последующие запуски вообще не перечисляют
старую часть `Items`, а проверяют только новые письма. Старые cursor-файлы без этого флага проходят
один завершающий backfill и автоматически обновляются. Task Scheduler запускает sidecar каждые
десять минут в interactive user session; интервал остаётся настраиваемым. Плановая задача не
стартует Outlook сама. Команда
`--open <base64-store> <base64-entry>` вызывает `Session.GetItemFromID(...).Display()`.

### IMAP

Каждый IMAP-аккаунт хранит несекретные настройки в `mail_accounts`, а app-password — в Windows
Credential Manager (на Mac dev — Keychain). Синхронизация делает `SELECT readonly=True` и
`FETCH (BODY.PEEK[])`; флаг `Seen` не меняется. Папки Junk/Trash/Drafts исключаются по IMAP
special-use flags, а не по локализованным именам.

Курсор хранится для `account_id + folder + UIDVALIDITY`. Смена UIDVALIDITY сбрасывает UID-курсор и
повторно сверяет папку с дедупликацией. UID подтверждается после сохранения `.eml` и регистрации
письма; ошибка посередине batch не пропускает более старые UID.

## Exact registry и snapshot-policy

`proxy/services/mail_registry_service.py` владеет SQLite-таблицами:

- `mail_accounts`: adapter, label, private `dataset_id/dataset_name`, безопасный config, sync state;
- `mail_folders`: native id/path, special-use, UIDVALIDITY, cursor, backfill state;
- `mail_messages`: identity, checksum, raw path, thread, Outlook locator, index status;
- `mail_message_locations`: папки и история видимости;
- `mail_attachment_provenance`: дедуп одинаковых attachment SHA-256 с сохранением ссылок писем.

Идентичность внутри аккаунта: normalized Internet Message-ID, иначе native id, иначе SHA-256.
Одинаковое письмо в нескольких папках остаётся одной записью с несколькими locations. Исчезновение
из источника помечает location неактуальной, но raw `.msg/.eml`, запись и RAG evidence автоматически
не удаляются.

## Индексация

Loopback intake сначала атомарно сохраняет raw message и регистрирует его exact provenance. Загрузка
в dataset выполняется отдельной последовательной очередью на ящик; HTTP-вызов sidecar не ждёт RAG.
Parser запускается после опустошения очереди, поэтому не конкурирует с очередной регистрацией за
файлы/SQLite и не удерживает Outlook во время тяжёлого разбора. Ошибка фоновой регистрации видна как
`index_status=error` и не откатывает сохранённый evidence-снимок.

Каждый raw message загружается только в датасет своего аккаунта. Общий parser создаёт:

- `mail_message` nodes: заголовки, участники, тело, thread и exact registry provenance;
- `mail_attachment` nodes: читаемое содержимое каждого обычного вложения до 20 МБ.

Payload включает account/dataset/message/thread identity, folders, source locator и SHA-256. Далее
работает общий immutable named `dense + bm25_sparse` contract, native RRF, rerank и context expansion.
CID/hidden inline-логотипы остаются в raw message, но не OCR-ятся. Большое вложение получает
`skipped_large` и MISSING-причину. Одинаковый attachment SHA-256 создаёт attachment context один раз;
message-node каждого письма сохраняет собственную provenance-ссылку и checksum.

## API и UI

- `GET/POST /api/mail/accounts`, `PATCH /api/mail/accounts/{id}`;
- `POST /api/mail/accounts/{id}/test`;
- `POST /api/mail/accounts/{id}/sync` (`full|incremental`);
- `POST /api/mail/accounts/{id}/migrate-legacy` — только выбранная папка → выбранный mailbox dataset;
- `POST /api/mail/collector/import` — loopback multipart intake Outlook-sidecar;
- `GET /api/mail/messages` с account/folder/participant/date/index-status filters;
- `GET /api/mail/messages/{id}`, `POST /api/mail/messages/{id}/open`.

Старые `/import-imap`, `/messages`, `/threads`, `/push` остаются совместимыми legacy-путями.
Вкладка «Почта» показывает ящики/папки, цепочки, тело, вложения, provenance и index status. Кнопка
«Спросить в LES» открывает чат со scope `ds:<dataset_id>` именно этого ящика.

## Windows install и acceptance

`clients/outlook_mail_poller/setup_task.ps1` компилирует sidecar в persistent state `bin` и создаёт
interactive task. `installers/windows/app/bootstrap.ps1` устанавливает его вместе с Tauri/NSIS при
наличии classic Outlook. Live Windows gate обязан проверить повторный запуск без дублей, folder
probe без мутаций, `INDEXED`, правильный original и отсутствие секрета в API/log/machine report.
Так как SSH-процесс не видит COM-объект Outlook из desktop session, release probe запускается
одноразовой interactive Scheduled Task под тем же пользователем; проверяется её `LastTaskResult`,
после чего задача всегда удаляется.

Mac unit/static checks доказывают кодовый контракт, но не заменяют установленный Windows-выпуск на
Legion. Release выполняется только штатными Windows gates и `make patch-release` из чистого pushed
`main`.

## Legacy push

`POST /api/mail/push` и `mail_push_service` сохранены для старых Outlook add-in/COM-addin: они
классифицируют переданные вложения (КП → КАЦ, смета/документ → RAG, скан → приёмка). Это не основной
путь настройки Е.Ж.И.К. и не участвует в фоновом read-only сборе полного ящика.
