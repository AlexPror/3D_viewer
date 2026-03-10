@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
  echo Creating venv...
  python -m venv .venv
)

echo Installing requirements...
call ".\.venv\Scripts\pip.exe" install -r requirements.txt

echo Starting server on http://localhost:8000 ...
call ".\.venv\Scripts\uvicorn.exe" main:app --reload --port 8000

