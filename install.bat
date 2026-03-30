@echo off
setlocal
cd /d "%~dp0"
chcp 65001 > nul

set "ROOT=%~dp0"
set "VENV_DIR=%ROOT%venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "BOOTSTRAP_PYTHON="

echo [1/4] Checking Python environment...
python --version > nul 2>&1
if not errorlevel 1 set "BOOTSTRAP_PYTHON=python"

if not defined BOOTSTRAP_PYTHON (
    py -3 --version > nul 2>&1
    if not errorlevel 1 set "BOOTSTRAP_PYTHON=py -3"
)

if not defined BOOTSTRAP_PYTHON (
    echo [ERROR] Python not found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

echo [2/4] Preparing virtual environment (venv)...
call :ensure_venv
if errorlevel 1 (
    echo [ERROR] Failed to prepare venv.
    pause
    exit /b 1
)

echo [3/4] Installing dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to upgrade pip inside the virtual environment.
    pause
    exit /b 1
)

"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo [4/4] Installing Playwright (Chromium)...
"%VENV_PYTHON%" -m playwright install chromium
if errorlevel 1 (
    echo [WARNING] Playwright installation might be incomplete.
)

echo.
echo ==================================================
echo [SUCCESS] Installation complete!
echo You can now run run-gui.bat.
echo ==================================================
echo.
pause
exit /b 0

:ensure_venv
if exist "%VENV_PYTHON%" (
    "%VENV_PYTHON%" --version > nul 2>&1
    if not errorlevel 1 (
        echo Using existing virtual environment.
        exit /b 0
    )

    echo Existing venv is invalid. Recreating it...
    rmdir /s /q "%VENV_DIR%"
)

echo Creating virtual environment (venv)...
call %BOOTSTRAP_PYTHON% -m venv "%VENV_DIR%"
if errorlevel 1 exit /b 1

if not exist "%VENV_PYTHON%" exit /b 1
"%VENV_PYTHON%" --version > nul 2>&1
if errorlevel 1 exit /b 1

exit /b 0
