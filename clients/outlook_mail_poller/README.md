# ЛЕС — сборщик почты classic Outlook (Windows)

Ручной локальный сборщик для уже открытого classic Outlook. Он не хранит пароль, не использует
IMAP/OAuth и не отправляет разобранный текст письма. Каждое новое письмо сохраняется через Outlook
как полный Unicode `.msg` (`olMSGUnicode`, вместе с вложениями), кладётся в durable spool и
регистрируется в `POST http://127.0.0.1:8050/api/mail/collector/import`.

Сбор запускается кнопкой «Забрать ещё» в Совушке. Постоянного расписания нет: задача Windows
зарегистрирована как `LES E.ZH.I.K. Outlook Collector`, но запускается только по явному запросу
пользователя. Один запуск имеет рабочий бюджет 12 секунд и hard stop 15 секунд, поэтому не может
зависнуть на часы.

## Почему отдельный сборщик

- Он использует текущую пользовательскую сессию Outlook через COM late binding.
- ЛЕС получает исходный `.msg`, а извлечение, дедупликация, provenance и индексирование остаются
  в одном серверном workflow.
- Если proxy временно недоступен, запись остаётся в spool и будет повторно отправлена при следующем
  ручном запуске.
- Сборщик не удаляет и не меняет письма в Outlook.

## Установка

```powershell
cd clients\outlook_mail_poller
powershell -ExecutionPolicy Bypass -File setup_task.ps1
```

Скрипт компилирует `LesMailPoller.exe`, устанавливает его в `%LOCALAPPDATA%\LES\bin` и регистрирует
интерактивную задачу без расписания. Удаление:

```powershell
powershell -ExecutionPolicy Bypass -File setup_task.ps1 -Remove
```

## Диагностика

- Состояние и spool: `%LOCALAPPDATA%\LES\mail`.
- URL импорта: `%LOCALAPPDATA%\LES\mail\collector_url.txt`.
- Локальный API: `POST /api/mail/collector/run`, затем `GET /api/mail/status`.
- В Совушке видны последний сбор, число писем в индексе, ожидающих записей и ошибок.

`LesMailPoller.cs` компилируется штатным .NET Framework `csc`, Office PIA не требуется. Собранный
`.exe` в Git не хранится.
