@echo off
setlocal
title LES STOP
cd /d "%~dp0..\.."
if not exist "scripts\windows\LES-STOP.ps1" (
  echo ERROR: missing scripts\windows\LES-STOP.ps1
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\windows\LES-STOP.ps1"
exit /b %errorlevel%
