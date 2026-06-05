param(
  [int]$Port = 8095,
  [string]$Bind = "+"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Prefix = "http://$Bind`:$Port/"
$Listener = [System.Net.HttpListener]::new()
$Listener.Prefixes.Add($Prefix)
$Listener.Start()

Write-Host "LES CAD/BIM standalone: $Prefix"
Write-Host "For LAN clients set Locia TIM_VIEWER_2_URL to http://SERVER:$Port/"
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
    ".ifczip" { "application/octet-stream"; break }
    default { "application/octet-stream" }
  }
}

function Write-JsonResponse($Context, [object]$Body, [int]$StatusCode = 200) {
  $Json = $Body | ConvertTo-Json -Depth 6 -Compress
  $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)
  $Context.Response.StatusCode = $StatusCode
  $Context.Response.ContentType = "application/json; charset=utf-8"
  $Context.Response.ContentLength64 = $Bytes.Length
  $Context.Response.OutputStream.Write($Bytes, 0, $Bytes.Length)
  $Context.Response.OutputStream.Close()
}

function Get-DefaultModelInfo {
  $ModelsRoot = Join-Path $Root "models"
  if (-not (Test-Path -LiteralPath $ModelsRoot)) {
    return $null
  }

  $SupportedExtensions = @(".ifc", ".ifczip", ".json")
  $File = Get-ChildItem -LiteralPath $ModelsRoot -File -ErrorAction SilentlyContinue |
    Where-Object { $SupportedExtensions -contains $_.Extension.ToLowerInvariant() } |
    Sort-Object LastWriteTimeUtc, Name -Descending |
    Select-Object -First 1

  if (-not $File) {
    return $null
  }

  $Extension = $File.Extension.ToLowerInvariant()
  $Kind = if ($Extension -eq ".json") { "json" } else { "ifc" }
  return @{
    found = $true
    name = $File.Name
    kind = $Kind
    url = "models/$([Uri]::EscapeDataString($File.Name))"
    updated_at = $File.LastWriteTimeUtc.ToString("o")
    size = $File.Length
  }
}

try {
  while ($Listener.IsListening) {
    $Context = $Listener.GetContext()
    $RequestPath = [Uri]::UnescapeDataString($Context.Request.Url.AbsolutePath.TrimStart("/"))
    if ($RequestPath -ieq "api/default-model") {
      $Model = Get-DefaultModelInfo
      if ($Model) {
        Write-JsonResponse $Context $Model
      } else {
        Write-JsonResponse $Context @{ found = $false; message = "В папке models нет файлов .ifc, .ifczip или .json." } 404
      }
      continue
    }

    if ([string]::IsNullOrWhiteSpace($RequestPath)) {
      $RequestPath = "index.html"
    }
    $FullPath = [System.IO.Path]::GetFullPath((Join-Path $Root $RequestPath))
    $RootFullPath = [System.IO.Path]::GetFullPath($Root).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $FullPath.StartsWith($RootFullPath)) {
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
