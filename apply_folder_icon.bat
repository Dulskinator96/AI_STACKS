@echo off
:: Writes desktop.ini and marks folder System so Explorer shows the custom icon.
cd /d "%~dp0"
if not exist "assets\app_icon.ico" (
  echo Run: python generate_icon.py  or  build_app.bat  first.
  pause
  exit /b 1
)
> "%~dp0desktop.ini" (
  echo [.ShellClassInfo]
  echo InfoTip=AI Monitor — double-click AIMonitor.exe to start
  echo IconFile=%~dp0assets\app_icon.ico
  echo IconIndex=0
)
attrib +s "%~dp0."
echo Done. Refresh Explorer ^(F5^) if the icon does not update.
