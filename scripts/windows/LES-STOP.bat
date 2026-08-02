@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0LES-STOP.ps1"
exit /b %errorlevel%
