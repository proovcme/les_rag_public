# Сборка LesMailPoller.exe + регистрация задачи планировщика (классический Outlook, Win).
#
#   powershell -ExecutionPolicy Bypass -File setup_task.ps1                 # собрать + поставить задачу
#   powershell -ExecutionPolicy Bypass -File setup_task.ps1 -EveryMinutes 5
#   powershell -ExecutionPolicy Bypass -File setup_task.ps1 -Remove
#
# Задача interactive ("/it") — исполняется в сессии пользователя, где живёт Outlook (только так
# COM-объект Outlook виден). Без админа. Эквивалент без PowerShell — csc + schtasks (см. README).
# Log: %LOCALAPPDATA%\LES\logs\mail_poller.log. URL ЛЕС — %LOCALAPPDATA%\LES\mail_addin_url.txt.

param([int]$EveryMinutes = 3, [switch]$Remove)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$exe  = Join-Path $here "LesMailPoller.exe"
$task = "LES Mail Poller"

if ($Remove) { schtasks /delete /tn $task /f; return }

# 1) Сборка (голый csc .NET Framework, winexe — без окна)
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc /nologo /target:winexe /out:"$exe" /r:System.dll /r:System.Core.dll /r:Microsoft.CSharp.dll (Join-Path $here "LesMailPoller.cs")
if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }

# 2) Задача: каждые N минут, в сессии текущего пользователя (interactive)
$me = "$env:COMPUTERNAME\$env:USERNAME"
schtasks /create /tn $task /tr "`"$exe`"" /sc minute /mo $EveryMinutes /ru $me /it /f
schtasks /run /tn $task   # разовый прогон сейчас
"task '$task' каждые $EveryMinutes мин, ru=$me; log: %LOCALAPPDATA%\LES\logs\mail_poller.log"
