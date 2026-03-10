@echo off
setlocal
cd /d "%~dp0"

echo Starting local metadata server...
start "3D Viewer Server" cmd /k "%~dp0server\run-server.bat"

echo Starting frontend (Vite)...
start "3D Viewer Frontend" cmd /k "%~dp0run-frontend.bat"

echo Done. Close windows to stop.
