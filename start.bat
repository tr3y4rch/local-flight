@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Local Flight

echo.
echo  =========================================
echo   LOCAL FLIGHT - starting up
echo  =========================================
echo.

:: Prefer stable Python versions (3.13, 3.12, 3.11) over pre-release 3.14
set "PYTHON="
py -3.13 --version >nul 2>&1
if not errorlevel 1 set "PYTHON=py -3.13"
if "%PYTHON%"=="" py -3.12 --version >nul 2>&1
if "%PYTHON%"=="" if not errorlevel 1 set "PYTHON=py -3.12"
if "%PYTHON%"=="" py -3.11 --version >nul 2>&1
if "%PYTHON%"=="" if not errorlevel 1 set "PYTHON=py -3.11"
if "%PYTHON%"=="" py -3 --version >nul 2>&1
if "%PYTHON%"=="" if not errorlevel 1 set "PYTHON=py -3"
if "%PYTHON%"=="" python --version >nul 2>&1
if "%PYTHON%"=="" if not errorlevel 1 set "PYTHON=python"

if "%PYTHON%"=="" (
    echo  ERROR: Python 3.11 or newer not found.
    echo  Install Python 3.13 from https://www.python.org/downloads/
    pause
    exit /b 1
)
echo  Python found (%PYTHON%)
set "LF_REQUESTED_GUI_MODE=%LOCALFLIGHT_GUI_MODE%"

:: -- Create venv if missing ----------------------------------------------------------
if not exist "%~dp0.venv\Scripts\activate.bat" (
    echo  Creating virtual environment...
    %PYTHON% -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo  ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo  Virtual environment created
)

:: -- Activate venv -------------------------------------------------------------------
call "%~dp0.venv\Scripts\activate.bat"
echo  Venv activated

:: -- Install / update dependencies --------------------------------------------------
echo  Checking dependencies...
cd /d "%~dp0"
if "%LOCALFLIGHT_GUI_MODE%"=="" set "LOCALFLIGHT_GUI_MODE=native"
echo  GUI mode: %LOCALFLIGHT_GUI_MODE%

if /i "%LOCALFLIGHT_GUI_MODE%"=="native" (
    echo  Installing native GUI dependencies...
    python -m pip install -e ".[native]" -q
) else (
    python -m pip install -e . -q
)
if errorlevel 1 (
    echo  ERROR: Dependency installation failed.
    echo  Native GUI mode needs PySide6. If you want the old browser fallback for dev only:
    echo    set LOCALFLIGHT_GUI_MODE=browser
    echo    start.bat
    pause
    exit /b 1
)
if /i "%LOCALFLIGHT_GUI_MODE%"=="native" (
    python -c "from PySide6.QtCore import qVersion; print(' PySide6/Qt OK: Qt ' + qVersion())"
    if errorlevel 1 (
        echo  ERROR: PySide6/Qt is not importable after dependency installation.
        pause
        exit /b 1
    )
)
echo  Dependencies OK

:: -- Load .env -----------------------------------------------------------------------
if exist "%~dp0.env" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0.env") do (
        set "lf_key=%%A"
        set "lf_val=%%B"
        if not "!lf_key!"=="" (
            set "firstchar=!lf_key:~0,1!"
            if not "!firstchar!"=="#" (
                set "%%A=%%B"
            )
        )
    )
    echo  Loaded .env
) else (
    echo  WARNING: No .env file found - API calls may fail.
    echo  Copy .env.example to .env and fill in your keys.
    echo.
)
if not "%LF_REQUESTED_GUI_MODE%"=="" set "LOCALFLIGHT_GUI_MODE=%LF_REQUESTED_GUI_MODE%"
if "%LOCALFLIGHT_GUI_MODE%"=="" set "LOCALFLIGHT_GUI_MODE=native"

:: -- Launch Local Flight -------------------------------------------------------------
echo  Launching Local Flight...
if /i "%LOCALFLIGHT_GUI_MODE%"=="native" (
    echo  Native Qt GUI will open. Local LAN web UI remains available at http://localhost:8000
) else (
    echo  Browser fallback will open. Right-click tray icon to open UI or quit.
)
echo.
python -m localflight

:: -- If we get here, app exited cleanly ---------------------------------------------
echo.
echo  Local Flight stopped.
if errorlevel 1 (
    echo.
    echo  NOTE: Local Flight exited with an error.
    pause
)
