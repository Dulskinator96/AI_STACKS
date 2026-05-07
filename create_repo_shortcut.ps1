$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $root "AIMonitor.exe"
if (-not (Test-Path -LiteralPath $exe)) { exit 0 }
$lnk = Join-Path $root "Open AI Monitor.lnk"
$ico = Join-Path $root "assets\app_icon.ico"
if (-not (Test-Path -LiteralPath $ico)) { $ico = Join-Path $root "app_icon.ico" }
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($lnk)
$s.TargetPath = $exe
$s.WorkingDirectory = $root
$s.Description = "Start AI Monitor"
if (Test-Path -LiteralPath $ico) { $s.IconLocation = "$ico,0" }
$s.Save()
Write-Host "Repo launcher: $lnk"
