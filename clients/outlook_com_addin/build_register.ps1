# Сборка + per-user регистрация COM-надстройки «ЛЕС — сборщик почты» (классический Outlook, Win).
#
#   powershell -ExecutionPolicy Bypass -File build_register.ps1            # собрать + зарегистрировать
#   powershell -ExecutionPolicy Bypass -File build_register.ps1 -Unregister
#
# Без админа: всё в HKCU. После — ПЕРЕЗАПУСТИ Outlook и включи надстройку в
# Файл → Параметры → Надстройки → COM-надстройки. Лог аддина: %LOCALAPPDATA%\LES\logs\mail_addin.log.
# Эквивалент без PowerShell — csc + `reg add` (см. README); политика Bypass тут не обязательна.

param([switch]$Unregister)
$ErrorActionPreference = "Stop"
$here   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$guid   = "{7E9A1C40-3D2B-4E55-9F12-8A6C0B3D5E71}"
$progid = "LES.MailCollector"
$dll    = Join-Path $here "LesMailCollector.dll"
$asm    = "LesMailCollector, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null"
$clsid  = "HKCU:\Software\Classes\CLSID\$guid"
$addin  = "HKCU:\Software\Microsoft\Office\Outlook\Addins\$progid"

if ($Unregister) {
  Remove-Item -Recurse -Force $clsid -EA SilentlyContinue
  Remove-Item -Recurse -Force "HKCU:\Software\Classes\$progid" -EA SilentlyContinue
  Remove-Item -Recurse -Force $addin -EA SilentlyContinue
  "unregistered $progid"; return
}

# 1) Сборка (голый csc .NET Framework — без Office-PIA, late binding)
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc /nologo /target:library /out:"$dll" /r:System.dll /r:System.Core.dll /r:Microsoft.CSharp.dll (Join-Path $here "Connect.cs")
if ($LASTEXITCODE -ne 0) { throw "csc failed ($LASTEXITCODE)" }

# 2) Managed-COM регистрация (mscoree-shim), per-user
$cb = "file:///" + $dll.Replace('\','/')
foreach ($k in @("$clsid\InprocServer32", "$clsid\InprocServer32\1.0.0.0")) {
  New-Item -Force -Path $k | Out-Null
  Set-ItemProperty $k "Class" "LesMailCollector.Connect"
  Set-ItemProperty $k "Assembly" $asm
  Set-ItemProperty $k "RuntimeVersion" "v4.0.30319"
  Set-ItemProperty $k "CodeBase" $cb
}
Set-ItemProperty "$clsid\InprocServer32" "(default)" "mscoree.dll"
Set-ItemProperty "$clsid\InprocServer32" "ThreadingModel" "Both"
New-Item -Force -Path "$clsid\ProgId" | Out-Null
Set-ItemProperty "$clsid\ProgId" "(default)" $progid
New-Item -Force -Path "HKCU:\Software\Classes\$progid\CLSID" | Out-Null
Set-ItemProperty "HKCU:\Software\Classes\$progid\CLSID" "(default)" $guid

# 3) Регистрация в Outlook (LoadBehavior=3 — грузить при старте)
New-Item -Force -Path $addin | Out-Null
Set-ItemProperty $addin "LoadBehavior" 3 -Type DWord
Set-ItemProperty $addin "FriendlyName" "ЛЕС — сборщик почты"
Set-ItemProperty $addin "Description"  "Шлёт новые письма в локальный ЛЕС (/api/mail/push)"
"registered $progid -> $dll  (перезапусти Outlook)"
