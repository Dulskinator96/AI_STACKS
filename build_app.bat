@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY=py -3"
%PY% -c "import sys" 2>nul || set "PY=python"
%PY% -c "import sys" 2>nul || (
  echo [ERROR] Python not found. Install Python 3 and ensure "py" or "python" is on PATH.
  pause
  exit /b 1
)

echo [1/4] Icon...
%PY% -m pip install -q pillow
%PY% generate_icon.py
if errorlevel 1 (
  echo Icon step failed.
  pause
  exit /b 1
)

echo [2/4] Stop running copies ^(so Windows unlocks the .exe^)...
taskkill /IM AIMonitor.exe /F >nul 2>&1
taskkill /IM "AI Monitor.exe" /F >nul 2>&1
ping -n 3 127.0.0.1 >nul

echo [3/4] PyInstaller ^(writes to build\release first — avoids locked-file overwrite^)...
%PY% -m pip install -q "pyinstaller>=6.0"
set "STAGE=%~dp0build\release"
if exist "%STAGE%" rmdir /s /q "%STAGE%" 2>nul
mkdir "%STAGE%" 2>nul
%PY% -m PyInstaller --noconfirm --distpath "%STAGE%" --workpath "%~dp0build\pyinstaller" ai_monitor.spec
if errorlevel 1 (
  echo PyInstaller failed.
  pause
  exit /b 1
)
if not exist "%STAGE%\AIMonitor.exe" (
  echo Expected "%STAGE%\AIMonitor.exe" missing.
  pause
  exit /b 1
)

echo [4/4] Install into project folder...
copy /Y "%STAGE%\AIMonitor.exe" "%~dp0AIMonitor.exe"
if errorlevel 1 (
  echo COPY failed. Close AIMonitor from the system tray, then run this script again.
  pause
  exit /b 1
)
:: Remove old spaced-name build if present
if exist "%~dp0AI Monitor.exe" del /f /q "%~dp0AI Monitor.exe" 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_repo_shortcut.ps1" 2>nul

echo.
echo  OK — run:  AIMonitor.exe
echo  Desktop:  create_shortcut.bat  ^(updates ai-monitor.lnk^)
echo.
pause
