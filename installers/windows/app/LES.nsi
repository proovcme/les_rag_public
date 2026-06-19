; LES Windows installer (NSIS) — per-user, no admin required.
; Build:  makensis -DVERSION=0.1.0 -DSRCDIR=<staged tree> installers\windows\app\LES.nsi
; SRCDIR must contain the clean runtime export (see tools/build_windows_installer.py),
; which includes installers\windows\app\{launcher.vbs,bootstrap.ps1}.

!ifndef VERSION
  !define VERSION "0.1.0"
!endif
!ifndef SRCDIR
  !define SRCDIR "..\..\..\dist\windows\LES"
!endif

!define APPNAME "LES"
!define LAUNCHER "$INSTDIR\installers\windows\app\launcher.vbs"

Name "ЛЕС · Совушка"
OutFile "..\..\..\dist\LES-Setup.exe"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
SetCompressor /SOLID lzma
Unicode true

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "${SRCDIR}\*"

  ; Shortcuts launch the hidden VBS wrapper (no console window).
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\ЛЕС · Совушка.lnk" "wscript.exe" '"${LAUNCHER}"' "$INSTDIR\installers\windows\app\LES.ico" 0
  CreateShortCut "$DESKTOP\ЛЕС · Совушка.lnk" "wscript.exe" '"${LAUNCHER}"' "$INSTDIR\installers\windows\app\LES.ico" 0

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Add/Remove Programs entry.
  !define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "ЛЕС · Совушка"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "LES"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  ; Remove installed program files (runtime export + venv created on first run).
  RMDir /r "$INSTDIR"
  Delete "$SMPROGRAMS\${APPNAME}\ЛЕС · Совушка.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\ЛЕС · Совушка.lnk"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
  ; Note: user data (%LOCALAPPDATA%\LES) and model cache are left in place on purpose.
SectionEnd
