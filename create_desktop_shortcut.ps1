$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $root "AIMonitor.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Host "Run build_app.bat first (missing: $exe)"
    exit 1
}
$ico = Join-Path $root "assets\app_icon.ico"
if (-not (Test-Path -LiteralPath $ico)) {
    $ico = Join-Path $root "app_icon.ico"
}
$desk = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desk "ai-monitor.lnk"
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnkPath)
$s.TargetPath = $exe
$s.WorkingDirectory = $root
$s.Description = "AI Monitor - desktop hub"
if (Test-Path -LiteralPath $ico) {
    $s.IconLocation = "$ico,0"
}
$s.Save()

foreach ($orphan in @("AI Monitor.exe", "ai-monitor.exe")) {
    $p = Join-Path $desk $orphan
    if (Test-Path -LiteralPath $p -PathType Leaf) {
        Remove-Item -LiteralPath $p -Force
        Write-Host "Removed old Desktop file: $orphan"
    }
}

Write-Host "Desktop shortcut: $lnkPath"
