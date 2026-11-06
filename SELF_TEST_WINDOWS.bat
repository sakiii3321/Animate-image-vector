@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist "runtime\python.exe" (
  echo Missing runtime\python.exe. Extract the entire ZIP before starting.
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" -X utf8 "%~dp0app\main.py" --self-test > "%~dp0diagnostics.json" 2>&1
set "RESULT=%ERRORLEVEL%"
type "%~dp0diagnostics.json"
echo.
echo Diagnostic report saved to diagnostics.json. Exit code: %RESULT%
pause
exit /b %RESULT%
