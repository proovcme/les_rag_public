$ErrorActionPreference = "Stop"
$path = $args[0]
$tokens = $null
$errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
if ($errors -and $errors.Count -gt 0) {
  $errors | ForEach-Object { Write-Output $_.ToString() }
  exit 1
}
Write-Output "PARSE_OK $path"
