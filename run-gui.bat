@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul

set "ROOT=%~dp0"
set "VENV_PYTHON=%ROOT%venv\Scripts\python.exe"
set "PYTHON_EXE=python"

if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" --version > nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Virtual environment is broken. Please run install.bat to recreate it.
        pause
        exit /b 1
    )

    set "PYTHON_EXE=%VENV_PYTHON%"
    echo Using virtual environment Python...
) else (
    python --version > nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found.
        pause
        exit /b 1
    )
)

"%PYTHON_EXE%" -c "import PySide6, PIL" > nul 2>&1
if errorlevel 1 (
    echo [ERROR] GUI dependencies are missing in the selected Python environment. Please run install.bat first.
    pause
    exit /b 1
)

echo Starting Comic Downloader GUI...
"%PYTHON_EXE%" -m core.qt_gui
pause
