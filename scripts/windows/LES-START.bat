@echo off
title LES START
cd /d "C:\Users\MVBul\Projects\les_rag_public"
if not exist "scripts\windows\LES-START.ps1" (
  echo ERROR: missing scripts\windows\LES-START.ps1
  echo Project update may have removed local start scripts. Ask agent to restore them.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\windows\LES-START.ps1"
if errorlevel 1 pause
