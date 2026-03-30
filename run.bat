@echo off
cd /d %~dp0
chcp 65001 > nul

python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

set "PYTHON_EXE=python"
if exist venv\Scripts\python.exe (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
    echo Using virtual environment Python...
)

%PYTHON_EXE% -c "import rich, requests, aiohttp, bs4, cloudscraper" > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Required CLI dependencies are missing. Please run install.bat first.
    pause
    exit /b 1
)

echo Starting Comic Downloader CLI...
%PYTHON_EXE% -m core.main
pause
