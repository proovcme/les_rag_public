# COM-надстройка «ЛЕС — сборщик почты» (классический Outlook, Windows)

Авто-сборщик входящей почты в ЛЕС **без IMAP/OAuth/паролей** — едет внутри уже залогиненного
Outlook. По таймеру (60с) сканит «Входящие», новые письма (позже чекпойнта) шлёт
`POST {LES}/api/mail/push` (тема/отправитель/дата/тело; вложения — задел v2).

Зачем COM, а не Office.js/IMAP:
- веб-аддин (Office.js, `../outlook_addin`) на корпоративном Outlook не сайдлоадится — только COM;
- IMAP на Exchange Online отключён (Microsoft вырубил Basic Auth), а ЛЕС ходит логином+паролем.

COM-надстройка обходит оба: работает на текущей сессии Outlook.

## Сборка и регистрация (per-user, без админа)

```powershell
cd clients\outlook_com_addin
powershell -ExecutionPolicy Bypass -File build_register.ps1
# затем ПЕРЕЗАПУСТИ Outlook; включи в Файл → Параметры → Надстройки → COM-надстройки
```

Без PowerShell-политики — то же голым `csc` + `reg add` (cmd):

```bat
"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:library ^
  /out:LesMailCollector.dll /r:System.dll /r:System.Core.dll /r:Microsoft.CSharp.dll Connect.cs
:: затем reg add HKCU\...\CLSID\{7E9A1C40-...}\InprocServer32 (mscoree-shim) + ...\Outlook\Addins\LES.MailCollector LoadBehavior=3
```

Снять: `build_register.ps1 -Unregister`.

## Настройка / диагностика

- URL ЛЕС по умолчанию `http://localhost:8050/api/mail/push`. Переопределить — файлом
  `%LOCALAPPDATA%\LES\mail_addin_url.txt`.
- Лог: `%LOCALAPPDATA%\LES\logs\mail_addin.log` (`OnConnection`, `pushed […]`, ошибки).
- Чекпойнт: `%LOCALAPPDATA%\LES\mail_addin_checkpoint.txt` (ReceivedTime последнего; старое не заливает).
- Не грузится? Outlook сам гасит сбойные аддины: Файл → Параметры → Надстройки → «Отключённые
  объекты» / COM-надстройки → галка. LoadBehavior должен быть 3.

## Контракт

Тот же, что у Office.js-аддина:
`{ "subject", "from", "date" (ISO8601 UTC), "body", "attachments": [] }` → ответ `routed[]`/`kac`.

## Архитектура

`Connect.cs` — `IDTExtensibility2`, late binding (`dynamic`) поверх `Outlook.Application` → без
Office-PIA при компиляции (собирается голым csc). Поэтому артефакт сборки (`.dll`) в гит не
кладём — собирается на машине из `Connect.cs`.
