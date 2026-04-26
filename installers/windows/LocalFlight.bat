@echo off
setlocal

set "ROOT=%~dp0..\.."
set "PYTHON=%ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%ROOT%\.venv\Scripts\python.exe"

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

cd /d "%ROOT%\src"
start "" "%PYTHON%" -m localflight
exit /b 0
