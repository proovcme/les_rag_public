param(
  [int]$Port = 8095
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Prefix = "http://127.0.0.1:$Port/"
$Listener = [System.Net.HttpListener]::new()
$Listener.Prefixes.Add($Prefix)
$Listener.Start()

Write-Host "LES CAD/BIM standalone: $Prefix"
Write-Host "Press Ctrl+C to stop."

function Get-MimeType([string]$Path) {
  switch ([System.IO.Path]::GetExtension($Path).ToLowerInvariant()) {
    ".html" { "text/html; charset=utf-8"; break }
    ".js" { "text/javascript; charset=utf-8"; break }
    ".mjs" { "text/javascript; charset=utf-8"; break }
    ".css" { "text/css; charset=utf-8"; break }
    ".json" { "application/json; charset=utf-8"; break }
    ".wasm" { "application/wasm"; break }
    ".ifc" { "application/octet-stream"; break }
    default { "application/octet-stream" }
  }
}

try {
  while ($Listener.IsListening) {
    $Context = $Listener.GetContext()
    $RequestPath = [Uri]::UnescapeDataString($Context.Request.Url.AbsolutePath.TrimStart("/"))
    if ([string]::IsNullOrWhiteSpace($RequestPath)) {
      $RequestPath = "index.html"
    }
    $FullPath = [System.IO.Path]::GetFullPath((Join-Path $Root $RequestPath))
    if (-not $FullPath.StartsWith([System.IO.Path]::GetFullPath($Root))) {
      $Context.Response.StatusCode = 403
      $Context.Response.Close()
      continue
    }
    if (-not [System.IO.File]::Exists($FullPath)) {
      $Context.Response.StatusCode = 404
      $Context.Response.Close()
      continue
    }
    $Bytes = [System.IO.File]::ReadAllBytes($FullPath)
    $Context.Response.ContentType = Get-MimeType $FullPath
    $Context.Response.ContentLength64 = $Bytes.Length
    $Context.Response.OutputStream.Write($Bytes, 0, $Bytes.Length)
    $Context.Response.OutputStream.Close()
  }
}
finally {
  $Listener.Stop()
}
