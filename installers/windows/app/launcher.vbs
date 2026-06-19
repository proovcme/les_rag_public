' LES launcher — runs bootstrap.ps1 fully hidden (no console flash).
' This is the target of the Start Menu / Desktop shortcut.
Dim shell, here, ps1
Set shell = CreateObject("WScript.Shell")
here = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
ps1 = here & "bootstrap.ps1"
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """", 0, False
