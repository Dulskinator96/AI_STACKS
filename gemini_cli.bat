@echo off
:: ──────────────────────────────────────────────────────────────────────────────
:: Gemini CLI — AI Monitor Bridge Launcher
:: Edit the paths below, then double-click to run.
:: ──────────────────────────────────────────────────────────────────────────────

:: 1. Path to your DBOMBCENTRAL folder
set WON_PATH=C:\Users\dulsk\Desktop\DBOMBCENTRAL

:: 2. Your Obsidian vault path (Optional if API key is set)
set WON_VAULT=C:\Users\dulsk\Documents\WON-Vault

:: 3. Obsidian Local REST API Key
set OBSIDIAN_API_KEY=b2f34648ef3f449beeb328e07a1e98cad091e81dc90922bf83d0a56d41a6b9e4

:: 4. MemPalace palace path
set PALACE_PATH=%USERPROFILE%\.mempalace\palace

:: 4. Gemini CLI command (change if not on PATH)
::    npm install -g @google/gemini-cli  →  then "gemini" works
set GEMINI_CMD=gemini

:: 5. Ground server port (default 7734)
set GROUND_PORT=7734

:: ──────────────────────────────────────────────────────────────────────────────
set SCRIPT_DIR=%~dp0

echo.
echo  AI Monitor — Gemini CLI Bridge
echo  ──────────────────────────────
echo  WON     = %WON_PATH%
echo  Vault   = %WON_VAULT%
echo  Palace  = %PALACE_PATH%
echo  Ground  = http://127.0.0.1:%GROUND_PORT%
echo.

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found.
    pause & exit /b 1
)

:: Check Gemini CLI
where %GEMINI_CMD% >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Gemini CLI not found on PATH — attempting npx fallback.
    echo [INFO] To install: npm install -g @google/gemini-cli
    echo.
)

:: Check MemPalace
python -c "import mempalace" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing MemPalace...
    pip install mempalace
    echo.
)

:: Init palace if missing
if not exist "%PALACE_PATH%" (
    echo [INFO] Initialising MemPalace palace at %PALACE_PATH%...
    mempalace init "%PALACE_PATH%"
    echo.
)

:: Parse argument
if "%1"=="--server" goto start_server
if "%1"=="--peek"   goto peek
if "%1"=="--search" goto search

:: Default: start bridge
python "%SCRIPT_DIR%gemini_bridge.py"
goto end

:start_server
echo [INFO] Starting Ground Server on port %GROUND_PORT%...
start "AI Monitor Ground Server" python "%SCRIPT_DIR%ground_server.py"
timeout /t 2 /nobreak >nul
python "%SCRIPT_DIR%gemini_bridge.py"
goto end

:peek
python "%SCRIPT_DIR%gemini_bridge.py" --peek
goto end

:search
python "%SCRIPT_DIR%gemini_bridge.py" --search %2 %3 %4 %5
goto end

:end
pause
