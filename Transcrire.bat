@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo L'application n'est pas encore installee.
  echo Lancez d'abord Installer.bat
  echo.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "transcrire.py"
