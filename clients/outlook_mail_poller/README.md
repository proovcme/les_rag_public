# ЛЕС — поллер почты (классический Outlook, Windows)

Авто-сборщик входящей почты в ЛЕС **без IMAP/OAuth/паролей и без COM-надстройки**. Отдельное
приложение, которое цепляется к УЖЕ ЗАЛОГИНЕННОМУ Outlook (COM-автоматизация, late binding),
по таймеру (задача планировщика, каждые N минут) сканит «Входящие» и шлёт новые письма (позже
чекпойнта) в `POST {LES}/api/mail/push` (тема/отправитель/дата/тело; вложения — задел v2).

## Почему так (а не аддин / IMAP)

На корпоративном Outlook все «прямые» пути отвалились (проверено на реальной машине):
- **Office.js-аддин** (`../outlook_addin`) — не сайдлоадится, в Outlook только COM-надстройки;
- **managed-COM-надстройка** (`../outlook_com_addin`) — не активируется на современном Outlook/.NET4
  (шимлесс managed-COM фактически депрекейтнут, `CoCreateInstance → 0x80070002`);
- **IMAP** — на Exchange Online выключен Basic Auth, а ЛЕС ходит логином+паролем.

Поллер обходит всё: едет на текущей сессии Outlook, ничего не логинит. Запуск — задачей
планировщика в **сессии пользователя** (COM-объект Outlook виден только в его сессии; служба
из сессии 0 к нему не достучится).

## Установка

```powershell
cd clients\outlook_mail_poller
powershell -ExecutionPolicy Bypass -File setup_task.ps1        # собрать + поставить задачу (каждые 3 мин)
```

Без PowerShell-политики — голым `csc` + `schtasks` (cmd):

```bat
"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe ^
  /out:LesMailPoller.exe /r:System.dll /r:System.Core.dll /r:Microsoft.CSharp.dll LesMailPoller.cs
schtasks /create /tn "LES Mail Poller" /tr "%CD%\LesMailPoller.exe" /sc minute /mo 3 /ru "%COMPUTERNAME%\%USERNAME%" /it /f
```

Снять: `setup_task.ps1 -Remove` (или `schtasks /delete /tn "LES Mail Poller" /f`).

## Диагностика

- Лог: `%LOCALAPPDATA%\LES\logs\mail_poller.log` — строки `run done: scanned=N pushed=M`, `pushed [200]: …`.
- Чекпойнт: `%LOCALAPPDATA%\LES\mail_poller_checkpoint.txt` (первый запуск — окно −30 мин, старое не заливает).
- URL ЛЕС по умолчанию `http://localhost:8050/api/mail/push`; переопределить — `%LOCALAPPDATA%\LES\mail_addin_url.txt`.
- ЛЕС :8050 должен быть запущен. Пользователь должен быть залогинен (задача interactive).

## Архитектура

`LesMailPoller.cs` — консоль (`winexe`), `Marshal.GetActiveObject("Outlook.Application")`
(fallback — `CreateInstance`), late binding (`dynamic`) поверх Outlook → без Office-PIA при
компиляции (голый csc). `.exe` в гит не кладём — артефакт сборки. Контракт `/api/mail/push`
тот же, что у Office.js-аддина.
