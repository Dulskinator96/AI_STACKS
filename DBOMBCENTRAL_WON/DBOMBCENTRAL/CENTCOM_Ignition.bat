@echo off
chcp 65001 >nul
TITLE DBOMBCENTRAL | CENTCOM CORTEX -- WON

SET "WON_DIR=%~dp0"
cd /d "%WON_DIR%" || (
    echo ERROR: Cannot navigate to WON directory.
    pause & exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo ERROR: venv not found. Run install_won.bat first.
    pause & exit /b 1
)

if not exist "won.py" (
    echo ERROR: won.py missing.
    pause & exit /b 1
)

if not exist "configs\won_settings.yaml" (
    echo ERROR: configs\won_settings.yaml missing.
    pause & exit /b 1
)

tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if %errorlevel% neq 0 (
    echo [*] Starting Ollama...
    start /B ollama serve >nul 2>&1
    timeout /t 3 >nul
)

venv\Scripts\python.exe won.py

if %errorlevel% neq 0 (
    echo.
    echo WON exited with error code %errorlevel%
)
pause
