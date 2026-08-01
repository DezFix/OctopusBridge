@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM Сборка OctopusBridge в .exe (обёртка над build_app.py)
REM Минимальная сборка:  build.bat
REM Полная (с NLLB):     build.bat --full
REM + тесты:             build.bat --tests
REM + установщик:        build.bat --installer

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

%PY% build_app.py %*
if errorlevel 1 (
    echo.
    echo ОШИБКА сборки! Смотрите вывод выше.
    pause
    exit /b 1
)

echo.
echo Готово! EXE: dist\OctopusBridge.exe
pause
