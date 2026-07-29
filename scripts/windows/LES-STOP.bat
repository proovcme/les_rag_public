@echo off
title LES STOP
cd /d "C:\Users\MVBul\Projects\les_rag_public"
if not exist "scripts\windows\LES-STOP.ps1" (
  echo ERROR: missing scripts\windows\LES-STOP.ps1
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\windows\LES-STOP.ps1"
