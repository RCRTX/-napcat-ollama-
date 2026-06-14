@echo off
title QQ Monitor
cd /d "%~dp0"

echo ========================================
echo   QQ Monitor
echo ========================================
echo.

if not exist "config\config.json" (
    echo Config file not found: config\config.json
    echo Please copy config\config.example.json to config\config.json and edit it first.
    pause
    exit /b 1
)

start http://localhost:8080
python src\main.py -c config\config.json

echo.
echo Exited.
pause
