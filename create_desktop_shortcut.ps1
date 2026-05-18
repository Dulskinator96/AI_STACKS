$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe  = Join-Path $root "DBOMBLOCAL.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    # Fall back to legacy name if the rebuild hasn't run yet
    $legacy = Join-Path $root "AIMonitor.exe"
    if (Test-Path -LiteralPath $legacy) {
        $exe = $legacy
    } else {
        Write-Host "Run build_app.bat first (missing: $exe)"
        exit 1
    }
}

# Prefer stratum_icon.ico (rename 2026-05-17); fall back to legacy app_icon.ico.
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

$desk = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desk "DBOMBLOCAL.lnk"
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnkPath)
$s.TargetPath = $exe
$s.WorkingDirectory = $root
$s.Description = "DBOMBLOCAL - desktop hub (STRATUM substrate)"
if ($ico -and (Test-Path -LiteralPath $ico)) {
    $s.IconLocation = "$ico,0"
}
$s.Save()

# Clean up legacy desktop artifacts so only the new shortcut remains.
foreach ($orphan in @("AI Monitor.exe", "ai-monitor.exe", "ai-monitor.lnk")) {
    $p = Join-Path $desk $orphan
    if (Test-Path -LiteralPath $p -PathType Leaf) {
        Remove-Item -LiteralPath $p -Force
        Write-Host "Removed old Desktop file: $orphan"
    }
}

Write-Host "Desktop shortcut: $lnkPath"
