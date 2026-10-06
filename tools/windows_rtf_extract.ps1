# Bounded by the checked-in Python caller; never creates a visible app/form.
param(
    [Parameter(Mandatory=$true)][string]$SourcePath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSourceSha256
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$box = $null
$stream = $null
$algorithm = $null
$sourceChanged = $false
try {
    $resolved = [System.IO.Path]::GetFullPath($SourcePath)
    if (-not [System.IO.File]::Exists($resolved)) { throw 'RTF source file unavailable' }
    $sourceBytes = [System.IO.File]::ReadAllBytes($resolved)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $sourceSha = [System.BitConverter]::ToString($algorithm.ComputeHash($sourceBytes)).Replace('-','').ToLowerInvariant()
    if ($sourceSha -cne $ExpectedSourceSha256) {
        $sourceChanged = $true
        throw 'RTF source changed before native rendering'
    }
    Add-Type -AssemblyName System.Windows.Forms
    $box = New-Object System.Windows.Forms.RichTextBox
    $box.Visible = $false
    $box.ReadOnly = $true
    $box.DetectUrls = $false
    $box.AllowDrop = $false
    $box.EnableAutoDragDrop = $false
    $box.MaxLength = [int]::MaxValue
    $handle = $box.Handle
    $stream = [System.IO.MemoryStream]::new([byte[]]$sourceBytes, $false)
    $box.LoadFile($stream, [System.Windows.Forms.RichTextBoxStreamType]::RichText)
    $text = [string]$box.Text
    $result = [ordered]@{
        status='ok'; text=$text; native_reader='windows-richtext';
        source_sha256=$sourceSha;
        text_utf16_units=$text.Length; visible=$box.Visible; hidden_no_form=$true;
        dotnet_version=[Environment]::Version.ToString();
        powershell_version=$PSVersionTable.PSVersion.ToString();
        apartment_state=[System.Threading.Thread]::CurrentThread.GetApartmentState().ToString()
    }
} catch {
    $result = [ordered]@{
        status='error'; error_type=$_.Exception.GetType().FullName;
        error_code=if ($sourceChanged) {'RTF_SOURCE_CHANGED'} else {'RTF_NATIVE_FAILED'};
        inner_error_type=if ($_.Exception.InnerException) {$_.Exception.InnerException.GetType().FullName} else {$null};
        visible=$false; hidden_no_form=$true
    }
} finally {
    if ($box) { $box.Dispose() }
    if ($stream) { $stream.Dispose() }
    if ($algorithm) { $algorithm.Dispose() }
}
$result | ConvertTo-Json -Depth 6 -Compress
