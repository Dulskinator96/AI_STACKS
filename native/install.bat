@echo off
setlocal EnableDelayedExpansion

echo === AI Chat Monitor Setup ===
echo.

:: This script lives in ai-monitor\native\ — repo root is one level up
set "NATIVE_HERE=%~dp0"
if "%NATIVE_HERE:~-1%"=="\" set "NATIVE_HERE=%NATIVE_HERE:~0,-1%"
for %%I in ("%NATIVE_HERE%\..") do set "REPO_ROOT=%%~fI"

set "MONITOR_DIR=%USERPROFILE%\Documents\AI_Monitor"
set "NATIVE_DIR=%MONITOR_DIR%\native"

mkdir "%MONITOR_DIR%" 2>nul
mkdir "%NATIVE_DIR%" 2>nul
mkdir "%MONITOR_DIR%\history" 2>nul
echo [OK] Folders at %MONITOR_DIR%

copy /Y "%NATIVE_HERE%\host.py" "%NATIVE_DIR%\host.py"
copy /Y "%NATIVE_HERE%\host.json" "%NATIVE_DIR%\host.json"
echo [OK] Native host scripts

copy /Y "%REPO_ROOT%\pipeline.py" "%MONITOR_DIR%\pipeline.py"
copy /Y "%REPO_ROOT%\note_builder.py" "%MONITOR_DIR%\note_builder.py"
if exist "%REPO_ROOT%\perception.py" copy /Y "%REPO_ROOT%\perception.py" "%MONITOR_DIR%\perception.py"
echo [OK] Pipeline bridge files

powershell -NoProfile -Command "$t = Get-Content '%NATIVE_DIR%\host.json' -Raw; $t = $t.Replace('YOURUSERNAME', $env:USERNAME); Set-Content '%NATIVE_DIR%\host.json' -Value $t -NoNewline"
echo [OK] host.json Windows username

set "WON_DEFAULT=%REPO_ROOT%\DBOMBCENTRAL_WON\DBOMBCENTRAL"
(
echo @echo off
echo set "WON_PATH=%WON_DEFAULT%"
echo set "WON_VAULT=%USERPROFILE%\Documents\WON-Vault"
echo if not defined OBSIDIAN_API_KEY set "OBSIDIAN_API_KEY="
) > "%NATIVE_DIR%\host_env.bat"
echo [OK] host_env.bat ^(WON_PATH^)

(
echo @echo off
echo call "%%~dp0host_env.bat" 2^>nul
echo python "%%~dp0host.py" %%*
) > "%NATIVE_DIR%\host.bat"

powershell -NoProfile -Command "(Get-Content '%NATIVE_DIR%\host.json' -Raw) -replace 'host.py','host.bat' | Set-Content '%NATIVE_DIR%\host.json' -NoNewline"
echo [OK] host.json -^> host.bat

reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.aimonitor.host" /ve /t REG_SZ /d "%NATIVE_DIR%\host.json" /f
echo [OK] Chrome registry

reg add "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.aimonitor.host" /ve /t REG_SZ /d "%NATIVE_DIR%\host.json" /f
echo [OK] Edge registry

echo.
echo === Setup Complete ===
echo Edit Extension ID in: %NATIVE_DIR%\host.json
echo If WON is elsewhere, edit: %NATIVE_DIR%\host_env.bat
echo.
pause
