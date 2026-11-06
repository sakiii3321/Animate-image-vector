@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Source edition: create .venv and install requirements.txt first. See PACKAGING_README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "app\main.py"
if errorlevel 1 pause
