; LES Windows installer (NSIS, Modern UI 2) — per-user, no admin required.
; Build:  makensis -DVERSION=0.1.0 -DSRCDIR=<staged tree> installers\windows\app\LES.nsi
; SRCDIR must contain the clean runtime export (see tools/build_windows_installer.py),
; which includes installers\windows\app\{launcher.vbs,bootstrap.ps1,LES.ico}.

!ifndef VERSION
  !define VERSION "0.1.0"
!endif
!ifndef SRCDIR
  !define SRCDIR "..\..\..\dist\windows\LES"
!endif

!define APPNAME "LES"
!define LAUNCHER "$INSTDIR\installers\windows\app\launcher.vbs"
!define APPICON  "$INSTDIR\installers\windows\app\LES.ico"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

Name "ЛЕС · Совушка"
OutFile "..\..\..\dist\LES-Setup.exe"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
SetCompressor /SOLID lzma
Unicode true
BrandingText "ЛЕС · Совушка — локальный ИИ для стройки"

!include "MUI2.nsh"

; Красивая иконка на сам installer .exe и на uninstaller (не дефолтная NSIS).
!define MUI_ICON   "${SRCDIR}\installers\windows\app\LES.ico"
!define MUI_UNICON "${SRCDIR}\installers\windows\app\LES.ico"
!define MUI_ABORTWARNING

; Финальная страница: опция «запустить ЛЕС» (галочка) — первый запуск ставит окружение.
; Через кастомную функцию (RUN+PARAMETERS ломает Exec на аргументе с пробелами/кавычками).
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Запустить ЛЕС · Совушку"
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchLES"

; Страницы мастера установки.
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Страницы мастера удаления.
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Russian"

; Запуск приложения с финальной страницы (скрытый VBS-лаунчер → bootstrap).
Function LaunchLES
  Exec 'wscript.exe "${LAUNCHER}"'
FunctionEnd

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${SRCDIR}\*"

  ; Ярлыки запускают скрытый VBS-обёртку (без окна консоли), иконка — наша.
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\ЛЕС · Совушка.lnk" "wscript.exe" '"${LAUNCHER}"' "${APPICON}" 0
  CreateShortCut "$DESKTOP\ЛЕС · Совушка.lnk" "wscript.exe" '"${LAUNCHER}"' "${APPICON}" 0

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Запись в «Установка и удаление программ» — с иконкой.
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "ЛЕС · Совушка"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "${APPICON}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "LES"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  ; Удаляем файлы программы (экспорт рантайма + venv, созданный при первом запуске).
  RMDir /r "$INSTDIR"
  Delete "$SMPROGRAMS\${APPNAME}\ЛЕС · Совушка.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\ЛЕС · Совушка.lnk"
  DeleteRegKey HKCU "${UNINST_KEY}"
  ; Пользовательские данные (%LOCALAPPDATA%\LES) и кэш моделей оставляем намеренно.
SectionEnd
