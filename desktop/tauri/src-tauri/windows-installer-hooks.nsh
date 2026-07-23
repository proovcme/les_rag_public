; Keep the visible Russian product name while using an ASCII-only physical path.
; Existing Tauri installations are upgraded in place so an update never orphans
; the previous executable or its uninstaller registration.
!macro NSIS_HOOK_PREINSTALL
  ${If} $INSTDIR == "$LOCALAPPDATA\${PRODUCTNAME}"
    ${IfNot} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
      StrCpy $INSTDIR "$LOCALAPPDATA\Programs\LES"
      SetOutPath "$INSTDIR"
    ${EndIf}
  ${EndIf}
!macroend
