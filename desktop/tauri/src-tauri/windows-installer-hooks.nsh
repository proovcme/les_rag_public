; Tauri NSIS hooks — AnythingLLM-style install/upgrade/uninstall that must not
; die with cryptic "error 1". Stop/deps/docker are best-effort; missing pieces
; are explained in Russian (and installed via winget when possible).

Var LesWipeUserData
Var LesHelperExit
Var LesStateRoot

!macro LesRunHelper Action
  ; Prefer already-installed helper (upgrade/uninstall), then freshly staged copy.
  StrCpy $R8 ""
  ${If} ${FileExists} "$INSTDIR\resources\runtime\installers\windows\app\les-setup-helpers.ps1"
    StrCpy $R8 "$INSTDIR\resources\runtime\installers\windows\app\les-setup-helpers.ps1"
  ${ElseIf} ${FileExists} "$INSTDIR\runtime\installers\windows\app\les-setup-helpers.ps1"
    StrCpy $R8 "$INSTDIR\runtime\installers\windows\app\les-setup-helpers.ps1"
  ${ElseIf} ${FileExists} "$INSTDIR\installers\windows\app\les-setup-helpers.ps1"
    StrCpy $R8 "$INSTDIR\installers\windows\app\les-setup-helpers.ps1"
  ${EndIf}

  ClearErrors
  ${If} $R8 != ""
    StrCpy $LesStateRoot "$LOCALAPPDATA\LES"
    ReadEnvStr $R7 "LES_WINDOWS_STATE_ROOT"
    ${If} $R7 != ""
      StrCpy $LesStateRoot $R7
    ${EndIf}
    DetailPrint "LES helper: ${Action}"
    ; cmd wrapper forces exit 0 so a PowerShell non-zero never aborts NSIS.
    nsExec::ExecToLog 'cmd.exe /c set LES_SETUP_INSTALL_ROOT=$INSTDIR&& set LES_WINDOWS_STATE_ROOT=$LesStateRoot&& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$R8" ${Action} & exit /b 0'
    Pop $LesHelperExit
  ${Else}
    DetailPrint "LES helper отсутствует — делаю минимальную остановку"
    nsExec::ExecToLog 'cmd.exe /c taskkill.exe /IM les-desktop.exe /F & exit /b 0'
    Pop $LesHelperExit
  ${EndIf}
  ClearErrors
!macroend

!macro LesRemoveTree PathLabel PathValue
  ClearErrors
  ${If} ${FileExists} "${PathValue}"
    DetailPrint "Удаляю ${PathLabel}..."
    RMDir /r "${PathValue}"
    ${If} ${Errors}
      ClearErrors
      ; One retry after a short wait (Defender / file lock).
      Sleep 1500
      RMDir /r "${PathValue}"
    ${EndIf}
    ${If} ${Errors}
      ClearErrors
      MessageBox MB_OK|MB_ICONEXCLAMATION \
        "Не удалось полностью удалить ${PathLabel}:$\r$\n${PathValue}$\r$\n$\r$\nЗакройте ЛЕС и проводник с этой папкой, затем удалите её вручную.$\r$\nУдаление программы при этом считается завершённым."
    ${EndIf}
  ${EndIf}
  ClearErrors
!macroend

!macro NSIS_HOOK_PREINSTALL
  ; Canonical ASCII install path for new trees.
  ReadEnvStr $R7 "LES_RELEASE_SMOKE"
  ${If} $R7 != "1"
    ${If} $INSTDIR == "$LOCALAPPDATA\${PRODUCTNAME}"
      ${IfNot} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
        StrCpy $INSTDIR "$LOCALAPPDATA\Programs\LES"
        SetOutPath "$INSTDIR"
      ${EndIf}
    ${EndIf}
    ${If} $INSTDIR != "$LOCALAPPDATA\Programs\LES"
      ${IfNot} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
        StrCpy $INSTDIR "$LOCALAPPDATA\Programs\LES"
        SetOutPath "$INSTDIR"
      ${EndIf}
    ${EndIf}
  ${EndIf}

  ClearErrors
  ; Kill every les-desktop + LES python, drop LES-removed/purge zombies, fix shortcuts.
  !insertmacro LesRunHelper "preflight-install"
  ClearErrors
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ClearErrors
  !insertmacro LesRunHelper "deps"
  ${If} ${FileExists} "$LOCALAPPDATA\LES\logs\setup-deps-missing.txt"
    ; Read first lines via type into detail log; show actionable Russian dialog.
    nsExec::ExecToLog 'cmd.exe /c type "%LOCALAPPDATA%\LES\logs\setup-deps-missing.txt" & exit /b 0'
    Pop $LesHelperExit
    MessageBox MB_OK|MB_ICONINFORMATION \
      "ЛЕС установлен успешно.$\r$\n$\r$\nНекоторых программ на машине ещё нет — список в окне журнала установки и в файле:$\r$\n%LOCALAPPDATA%\LES\logs\setup-deps-missing.txt$\r$\n$\r$\nУстановите их, затем откройте ЛЕС. Setup из-за этого не считается ошибочным."
  ${EndIf}
  ClearErrors
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ClearErrors
  !insertmacro LesRunHelper "stop"
  StrCpy $LesWipeUserData "0"
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "Удалить ЛЕС · Совушку?$\r$\n$\r$\nУдалить также пользовательские данные (%LOCALAPPDATA%\LES) — сметы, документы, настройки?$\r$\n$\r$\nДа = полное удаление$\r$\nНет = только программа, данные сохранить" \
    IDYES les_wipe_yes IDNO les_wipe_no
  les_wipe_yes:
    StrCpy $LesWipeUserData "1"
    Goto les_wipe_done
  les_wipe_no:
    StrCpy $LesWipeUserData "0"
  les_wipe_done:
  ClearErrors
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ClearErrors
  ${If} $LesWipeUserData == "1"
    !insertmacro LesRunHelper "wipe-state"
    !insertmacro LesRemoveTree "данные ЛЕС" "$LOCALAPPDATA\LES"
  ${EndIf}
  ClearErrors
!macroend
