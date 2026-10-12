param(
    [Parameter(Mandatory = $true)][string]$TestRoot,
    [Parameter(Mandatory = $true)][string]$LinkPath,
    [Parameter(Mandatory = $true)][string]$TargetPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$fixtureRoot = (Resolve-Path -LiteralPath $TestRoot).ProviderPath.TrimEnd('\')
$fixturePrefix = $fixtureRoot + '\'
$junctionPath = [System.IO.Path]::GetFullPath($LinkPath)
$junctionParent = (Resolve-Path -LiteralPath ([System.IO.Path]::GetDirectoryName($junctionPath))).ProviderPath
$junctionTarget = (Resolve-Path -LiteralPath $TargetPath).ProviderPath
foreach ($candidatePath in @($junctionPath, $junctionParent, $junctionTarget)) {
    if (-not $candidatePath.StartsWith($fixturePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Junction fixture must remain inside its temporary directory.'
    }
}
if (Test-Path -LiteralPath $junctionPath) {
    throw 'Junction fixture path already exists.'
}
New-Item -ItemType Junction -Path $junctionPath -Target $junctionTarget | Out-Null
