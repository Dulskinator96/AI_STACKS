@echo off
chcp 65001 >nul
TITLE DBOMBCENTRAL | WON INSTALL

echo.
echo  WON  --  DBOMB ASCENDENT
echo  INSTALL SCRIPT
echo.

:: Always pause on error — set this up first
SET "WON_DIR=%~dp0"
cd /d "%WON_DIR%"
if %errorlevel% neq 0 goto :err_dir

echo [*] Location: %WON_DIR%
echo.

:: Python check
python --version >nul 2>&1
if %errorlevel% neq 0 goto :err_python
echo [OK] Python found.

:: venv
if not exist "venv\Scripts\python.exe" (
    echo [*] Creating virtual environment...
    python -m venv venv
    if %errorlevel% neq 0 goto :err_venv
    echo [OK] venv created.
) else (
    echo [OK] venv already exists.
)

:: pip upgrade
echo [*] Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip --quiet

:: Install requirements
if not exist "requirements.txt" goto :err_req
echo [*] Installing requirements...
venv\Scripts\python.exe -m pip install -r requirements.txt
if %errorlevel% neq 0 goto :err_pip
echo [OK] All packages installed.

:: data folder
if not exist "data" mkdir data
echo [OK] data\ folder ready.

:: Ollama
echo.
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Ollama NOT found.
    echo     Get it free at: https://ollama.com
    echo     After install run:  ollama pull llama3.2
    echo     WON will work in template mode until then.
) else (
    echo [OK] Ollama found. Pulling llama3.2 model...
    ollama pull llama3.2
    echo [OK] Model ready.
)

:: Auto-set vault path
SET "VAULT=%USERPROFILE%\Documents\WON-Vault"
powershell -Command "(Get-Content 'configs\won_settings.yaml') -replace 'C:/Users/dulsk/Documents/WON-Vault', '%VAULT:\=/%' | Set-Content 'configs\won_settings.yaml'" >nul 2>&1
echo [OK] Vault path: %VAULT%

echo.
echo  ====================================================
echo    INSTALLATION COMPLETE
echo    Run CENTCOM_Ignition.bat to start WON.
echo  ====================================================
echo.
pause
exit /b 0

:: ---- ERROR HANDLERS ----

:err_dir
echo.
echo ERROR: Could not find install directory.
echo Make sure you are running this from inside the DBOMBCENTRAL folder.
pause & exit /b 1

:err_python
echo.
echo ERROR: Python not found on this machine.
echo Download it free at: https://www.python.org/downloads/
echo IMPORTANT: Check the box "Add Python to PATH" during install.
echo Then re-run this script.
pause & exit /b 1

:err_venv
echo.
echo ERROR: Failed to create virtual environment.
echo Try running this script as Administrator (right-click - Run as administrator).
pause & exit /b 1

:err_req
echo.
echo ERROR: requirements.txt not found in %WON_DIR%
echo Make sure you extracted the full DBOMBCENTRAL zip, not just this file.
pause & exit /b 1

:err_pip
echo.
echo ERROR: pip install failed.
echo Check your internet connection and try again.
echo If the issue persists, run manually:
echo   venv\Scripts\pip install rich requests beautifulsoup4 pyyaml
pause & exit /b 1
