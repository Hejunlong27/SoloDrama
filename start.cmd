@echo off
chcp 65001 >nul 2>&1
setlocal
title SoloDrama Studio
cd /d "%~dp0"

set "VENV=%~dp0envs\solodrama-web\Scripts\python.exe"
set "APP=%~dp0web\launcher.py"

if exist "%VENV%" (
  "%VENV%" "%APP%" %*
  set "RC=%ERRORLEVEL%"
  goto :done
)

py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3 "%APP%" %*
  set "RC=%ERRORLEVEL%"
  goto :done
)

python -c "import sys" >nul 2>&1
if not errorlevel 1 (
  python "%APP%" %*
  set "RC=%ERRORLEVEL%"
  goto :done
)

echo.
echo   [NG] Python not found.
echo        Install Python 3.10+ and tick "Add Python to PATH":
echo          https://www.python.org/downloads/
echo.
pause
exit /b 2

:done
if not "%RC%"=="0" (
  echo.
  echo   Launcher exit code: %RC%
  echo   Read the messages above before closing this window.
  echo.
  pause
)
endlocal
exit /b %RC%
