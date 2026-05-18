@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY=py -3"
%PY% -c "import sys" 2>nul || set "PY=python"
%PY% -c "import sys" 2>nul || (
  echo [ERROR] Python not found. Install Python 3 and ensure "py" or "python" is on PATH.
  exit /b 1
)

echo [1/5] Icon...
:: stratum_icon.ico / app_icon.ico are committed; skip regen if either is present.
if exist "%~dp0stratum_icon.ico" goto icon_ok
if exist "%~dp0app_icon.ico"    goto icon_ok
if exist "%~dp0assets\stratum_icon.ico" goto icon_ok
if exist "%~dp0assets\app_icon.ico"    goto icon_ok
%PY% -m pip install -q pillow
if exist "%~dp0generate_icon.py" (
  %PY% generate_icon.py
  if errorlevel 1 (
    echo Icon step failed.
    exit /b 1
  )
) else (
  echo No icon file present and no generate_icon.py — continuing with default exe icon.
)
:icon_ok

echo [2/5] Stop running copies ^(so Windows unlocks the .exe^)...
taskkill /IM DBOMBLOCAL.exe /F >nul 2>&1
taskkill /IM AIMonitor.exe /F >nul 2>&1
taskkill /IM "AI Monitor.exe" /F >nul 2>&1
ping -n 3 127.0.0.1 >nul

echo [3/5] PyInstaller ^(writes to build\release first — avoids locked-file overwrite^)...
%PY% -m pip install -q "pyinstaller>=6.0"
set "STAGE=%~dp0build\release"
if exist "%STAGE%" rmdir /s /q "%STAGE%" 2>nul
mkdir "%STAGE%" 2>nul
%PY% -m PyInstaller --noconfirm --distpath "%STAGE%" --workpath "%~dp0build\pyinstaller" ai_monitor.spec
if errorlevel 1 (
  echo PyInstaller failed.
  exit /b 1
)
if not exist "%STAGE%\DBOMBLOCAL.exe" (
  echo Expected "%STAGE%\DBOMBLOCAL.exe" missing.
  exit /b 1
)

echo [4/5] Install into project folder...
copy /Y "%STAGE%\DBOMBLOCAL.exe" "%~dp0DBOMBLOCAL.exe"
if errorlevel 1 (
  echo COPY failed. Close DBOMBLOCAL from the system tray, then run this script again.
  exit /b 1
)
:: Remove old spaced-name + legacy AIMonitor builds if present
if exist "%~dp0AI Monitor.exe" del /f /q "%~dp0AI Monitor.exe" 2>nul
if exist "%~dp0AIMonitor.exe"   del /f /q "%~dp0AIMonitor.exe"   2>nul

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_repo_shortcut.ps1" 2>nul

echo [5/5] Archive immutable release with receipts + sha256...
%PY% "%~dp0_build_emit_release.py"
if errorlevel 1 (
  echo Release archival failed ^(exe is still in project folder^).
)

echo.
echo  OK - run:  DBOMBLOCAL.exe
echo  Desktop:  create_shortcut.bat  ^(updates DBOMBLOCAL.lnk^)
echo  Releases: releases\^<YYYYMMDDTHHMMSSZ^>-build-NNN\  ^(immutable archive^)
echo.
