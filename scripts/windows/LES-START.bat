@echo off
setlocal
title LES START
cd /d "%~dp0..\.."
if not exist "scripts\windows\LES-START.ps1" (
  echo ERROR: missing scripts\windows\LES-START.ps1
  echo Project update may have removed local start scripts.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\windows\LES-START.ps1"
set ERR=%errorlevel%
if not "%ERR%"=="0" (
  echo.
  echo LES START failed with exit code %ERR%
  pause
  exit /b %ERR%
)
echo.
pause
exit /b 0
