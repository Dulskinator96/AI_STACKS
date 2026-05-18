@echo off
:: DBOMBLOCAL — Living AI Orchestration (STRATUM substrate)

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install from python.org and try again.
    pause
    exit /b 1
)

echo.
echo  DBOMBLOCAL  ^|  orchestrate -^> perceive -^> synthesize -^> act
echo  Root: %SCRIPT_DIR%
echo.

python "%SCRIPT_DIR%\app.py"
if %errorlevel% neq 0 (
    echo.
    echo [DBOMBLOCAL] App exited with error %errorlevel% — falling back to pipeline UI
    python "%SCRIPT_DIR%\stratum_ui.py"
)
pause
