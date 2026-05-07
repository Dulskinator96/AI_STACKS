@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM run_tests.bat — AI_MONITOR test gate (offline-capable).
REM Invokes pytest against the local tests/ directory.
REM Exit code is propagated from pytest so this script can serve as a
REM pre-commit hook target once git is initialised.
REM ─────────────────────────────────────────────────────────────────────────────
setlocal
cd /d "%~dp0"
python -m pytest tests
exit /b %ERRORLEVEL%
