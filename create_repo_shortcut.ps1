$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe  = Join-Path $root "DBOMBLOCAL.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    $legacy = Join-Path $root "AIMonitor.exe"
    if (Test-Path -LiteralPath $legacy) { $exe = $legacy } else { exit 0 }
}
$lnk = Join-Path $root "Open DBOMBLOCAL.lnk"
$icoCandidates = @(
    (Join-Path $root "assets\stratum_icon.ico"),
    (Join-Path $root "stratum_icon.ico"),
    (Join-Path $root "assets\app_icon.ico"),
    (Join-Path $root "app_icon.ico")
)
$ico = $null
foreach ($candidate in $icoCandidates) {
    if (Test-Path -LiteralPath $candidate) { $ico = $candidate; break }
}
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnk)
$s.TargetPath = $exe
$s.WorkingDirectory = $root
$s.Description = "Start DBOMBLOCAL"
if ($ico -and (Test-Path -LiteralPath $ico)) { $s.IconLocation = "$ico,0" }
$s.Save()
Write-Host "Repo launcher: $lnk"
