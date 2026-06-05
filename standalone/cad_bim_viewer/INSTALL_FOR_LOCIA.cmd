@echo off
setlocal
set "SCRIPT=%~dp0install_for_locia.ps1"
if not exist "%SCRIPT%" (
  echo [FAIL] install_for_locia.ps1 not found near this file.
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
  echo.
  echo [FAIL] TIM Viewer 2.0 installer failed with code %CODE%.
  pause
  exit /b %CODE%
)
echo.
echo [OK] TIM Viewer 2.0 installer finished.
pause
