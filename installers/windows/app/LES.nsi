; Legacy/reference NSIS kept in sync with Tauri product UX.
; Production LES-Setup.exe is built by Tauri (tools/build_windows_installer.py).
; This script must never abort with cryptic "error 1" because stop/deps failed.

!ifndef VERSION
  !define VERSION "0.1.0"
!endif
!ifndef SRCDIR
  !define SRCDIR "..\..\..\dist\windows\LES"
!endif

!define APPNAME "LES"
!define LAUNCHER "$INSTDIR\installers\windows\app\launcher.vbs"
!define APPICON  "$INSTDIR\installers\windows\app\LES.ico"
!define HELPER   "$INSTDIR\installers\windows\app\les-setup-helpers.ps1"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

Name "ЛЕС · Совушка"
OutFile "..\..\..\dist\LES-Setup.exe"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
SetCompressor /SOLID lzma
Unicode true
BrandingText "ЛЕС · Совушка — локальный ИИ для стройки"

!include "MUI2.nsh"
!include "LogicLib.nsh"

Var LesWipeUserData
Var LesHelperExit

!define MUI_ICON   "${SRCDIR}\installers\windows\app\LES.ico"
!define MUI_UNICON "${SRCDIR}\installers\windows\app\LES.ico"
!define MUI_ABORTWARNING

!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Запустить ЛЕС · Совушку"
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchLES"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Russian"

Function LaunchLES
  Exec 'wscript.exe "${LAUNCHER}"'
FunctionEnd

Function LesRunHelper
  Pop $R7 ; action
  ClearErrors
  ${If} ${FileExists} "${HELPER}"
    nsExec::ExecToLog 'cmd.exe /c set LES_SETUP_INSTALL_ROOT=$INSTDIR&& set LES_WINDOWS_STATE_ROOT=$LOCALAPPDATA\LES&& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "${HELPER}" $R7 & exit /b 0'
    Pop $LesHelperExit
  ${Else}
    nsExec::ExecToLog 'cmd.exe /c taskkill.exe /IM les-desktop.exe /F & exit /b 0'
    Pop $LesHelperExit
  ${EndIf}
  ClearErrors
FunctionEnd

Section "Install"
  ClearErrors
  Push "preflight-install"
  Call LesRunHelper
  SetOutPath "$INSTDIR"
  File /r "${SRCDIR}\*"

  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\ЛЕС · Совушка.lnk" "wscript.exe" '"${LAUNCHER}"' "${APPICON}" 0
  CreateShortCut "$DESKTOP\ЛЕС · Совушка.lnk" "wscript.exe" '"${LAUNCHER}"' "${APPICON}" 0

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "ЛЕС · Совушка"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "${APPICON}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "LES"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  Push "deps"
  Call LesRunHelper
  ${If} ${FileExists} "$LOCALAPPDATA\LES\logs\setup-deps-missing.txt"
    MessageBox MB_OK|MB_ICONINFORMATION \
      "ЛЕС установлен успешно.$\r$\n$\r$\nНекоторых программ ещё нет — см. %LOCALAPPDATA%\LES\logs\setup-deps-missing.txt$\r$\nУстановите их и откройте ЛЕС. Это не ошибка Setup."
  ${EndIf}
  ClearErrors
SectionEnd

Section "Uninstall"
  ClearErrors
  Push "stop"
  Call un.LesRunHelper
  StrCpy $LesWipeUserData "0"
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Удалить пользовательские данные ЛЕС (%LOCALAPPDATA%\LES)?$\r$\n$\r$\nДа = полное удаление$\r$\nНет = только программа, данные сохранить" \
    IDYES les_nsi_wipe_yes IDNO les_nsi_wipe_no
  les_nsi_wipe_yes:
    StrCpy $LesWipeUserData "1"
    Goto les_nsi_wipe_done
  les_nsi_wipe_no:
    StrCpy $LesWipeUserData "0"
  les_nsi_wipe_done:

  ClearErrors
  RMDir /r "$INSTDIR"
  ${If} ${Errors}
    ClearErrors
    Sleep 1500
    RMDir /r "$INSTDIR"
  ${EndIf}
  ${If} ${Errors}
    ClearErrors
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Не удалось удалить часть файлов программы.$\r$\nЗакройте ЛЕС и удалите вручную:$\r$\n$INSTDIR$\r$\nУдаление при этом считается завершённым."
  ${EndIf}

  Delete "$SMPROGRAMS\${APPNAME}\ЛЕС · Совушка.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\ЛЕС · Совушка.lnk"
  DeleteRegKey HKCU "${UNINST_KEY}"

  ${If} $LesWipeUserData == "1"
    Push "wipe-state"
    Call un.LesRunHelper
  ${EndIf}
  ClearErrors
SectionEnd

Function un.LesRunHelper
  Pop $R7
  ClearErrors
  ${If} ${FileExists} "${HELPER}"
    nsExec::ExecToLog 'cmd.exe /c set LES_SETUP_INSTALL_ROOT=$INSTDIR&& set LES_WINDOWS_STATE_ROOT=$LOCALAPPDATA\LES&& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "${HELPER}" $R7 & exit /b 0'
    Pop $LesHelperExit
  ${Else}
    nsExec::ExecToLog 'cmd.exe /c taskkill.exe /IM les-desktop.exe /F & exit /b 0'
    Pop $LesHelperExit
  ${EndIf}
  ClearErrors
FunctionEnd
