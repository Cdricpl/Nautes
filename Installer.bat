@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Installation - Transcription audio
echo ============================================
echo.

set "PYTHON="
where py >nul 2>nul && set "PYTHON=py -3"
if not defined PYTHON where python >nul 2>nul && set "PYTHON=python"

if not defined PYTHON (
  echo Python n'est pas installe sur cet ordinateur.
  echo.
  echo   1. Ouvrez le Microsoft Store
  echo   2. Installez "Python 3.12"
  echo   3. Relancez ce fichier Installer.bat
  echo.
  pause
  exit /b 1
)

echo Creation de l'environnement...
%PYTHON% -m venv .venv
if errorlevel 1 goto error

echo Installation des composants (quelques minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error

echo.
echo ============================================
echo   Installation terminee.
echo   Lancez maintenant Transcrire.bat
echo ============================================
echo.
pause
exit /b 0

:error
echo.
echo L'installation a echoue. Verifiez votre connexion internet, puis reessayez.
echo.
pause
exit /b 1
