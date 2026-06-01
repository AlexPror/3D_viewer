@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
  echo Creating venv...
  python -m venv .venv
)

echo Installing requirements...
call ".\.venv\Scripts\pip.exe" install -r requirements.txt -q
if errorlevel 1 (
  echo [ERROR] pip install failed
  pause
  exit /b 1
)

echo Starting server on http://127.0.0.1:8000 ...
rem uvicorn.exe --reload can exit silently on Windows when project path contains non-ASCII chars.
rem Always launch via python -m uvicorn. Pass --reload as first arg to enable hot reload.
set "UVICORN_ARGS=main:app --host 127.0.0.1 --port 8000"
if /I "%~1"=="--reload" set "UVICORN_ARGS=main:app --host 127.0.0.1 --port 8000 --reload"

call ".\.venv\Scripts\python.exe" -m uvicorn %UVICORN_ARGS%
if errorlevel 1 (
  echo [ERROR] Server failed. Is port 8000 already in use?
  pause
  exit /b 1
)

