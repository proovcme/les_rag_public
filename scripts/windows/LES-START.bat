@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0LES-START.ps1"
exit /b %errorlevel%

