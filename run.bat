@echo off
setlocal
cd /d "%~dp0"

echo.
echo 3D Viewer — один запуск: сервер + фронтенд
echo.

echo [1/2] Сервер API и конвертация STEP: http://localhost:8000
start "3D Viewer Server" cmd /k "%~dp0server\run-server.bat"

echo      Ожидание старта сервера...
timeout /t 4 /nobreak >nul

echo [2/2] Фронтенд Vite: http://localhost:5173
start "3D Viewer Frontend" cmd /k "%~dp0run-frontend.bat"

echo.
echo Готово. Два окна консоли (Server и Frontend). Закройте окно — процесс остановится.
echo   API и STEP:  http://localhost:8000
echo   Просмотр:    http://localhost:5173
echo   Повторный запуск: снова run.bat из корня проекта.
echo.
