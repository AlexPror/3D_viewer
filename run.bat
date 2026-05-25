@echo off
setlocal
cd /d "%~dp0"

echo.
echo DeskReview — локальный запуск (сервер + фронт)
echo.

echo [1/2] Сервер чата и API: http://localhost:8000
start "DeskReview Server" cmd /k "%~dp0server\run-server.bat"

echo      Ожидание старта сервера...
timeout /t 4 /nobreak >nul

echo [2/2] Фронтенд Vite: http://localhost:5173
start "DeskReview Frontend" cmd /k "%~dp0run-frontend.bat"

echo.
echo Готово. Два окна: Server и Frontend. Закройте окно — процесс остановится.
echo   API:   http://localhost:8000
echo   Сайт:  http://localhost:5173
echo.
