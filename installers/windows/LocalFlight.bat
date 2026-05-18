@echo off
setlocal

set "ROOT=%~dp0..\.."
set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%ROOT%\.venv\Scripts\pythonw.exe"

if not exist "%PYTHON%" (
    echo Local Flight source install is incomplete.
    echo Run installers\windows\install.ps1 from the project root.
    pause
    exit /b 1
)

if not exist "%ROOT%\src\localflight\__main__.py" (
    echo Local Flight source tree was not found.
    echo Expected: %ROOT%\src\localflight\__main__.py
    pause
    exit /b 1
)

if "%LOCALFLIGHT_GUI_MODE%"=="" set "LOCALFLIGHT_GUI_MODE=native"
cd /d "%ROOT%"
"%PYTHON%" -m localflight
set "LF_EXIT=%ERRORLEVEL%"
if not "%LF_EXIT%"=="0" pause
exit /b %LF_EXIT%
