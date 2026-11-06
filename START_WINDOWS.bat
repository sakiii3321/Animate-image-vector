@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist "runtime\python.exe" (
  echo Missing runtime\python.exe. Extract the entire ZIP before starting.
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" "%~dp0app\main.py"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo The application exited with code %RESULT%. Copy the error above for support.
  pause
)
exit /b %RESULT%
