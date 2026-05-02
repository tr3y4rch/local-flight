# Local Flight - Windows source installer
#
# This script is for running Local Flight from a source checkout.
# End users who download LocalFlight-windows.zip do not need this script:
# unzip the release and double-click LocalFlight.exe.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -Launch
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -NoShortcut
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -SkipDependencyInstall
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -NoPause

[CmdletBinding()]
param(
    [switch]$NoShortcut,
    [switch]$SkipDependencyInstall,
    [switch]$Launch,
    [switch]$NoPause
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ROOT = (Resolve-Path (Join-Path $SCRIPT_DIR "..\..")).Path

function Write-Section($Message) {
    Write-Host ""
    Write-Host " ==========================================" -ForegroundColor Cyan
    Write-Host "   $Message" -ForegroundColor Cyan
    Write-Host " ==========================================" -ForegroundColor Cyan
    Write-Host ""
}

function Stop-Installer($ExitCode) {
    if (-not $NoPause) {
        Read-Host " Press Enter to exit"
    }
    exit $ExitCode
}

function Test-PythonCandidate {
    param(
        [string]$Exe,
        [string[]]$Args = @()
    )

    $cmd = Get-Command $Exe -ErrorAction SilentlyContinue
    if (-not $cmd) {
        return $null
    }

    try {
        $versionText = & $Exe @Args --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        if ("$versionText" -notmatch "Python\s+(\d+)\.(\d+)") {
            return $null
        }
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
            return $null
        }
        return [pscustomobject]@{
            Exe = $Exe
            Args = $Args
            Version = "$versionText"
        }
    } catch {
        return $null
    }
}

function Find-Python {
    foreach ($candidate in @(
        @{ Exe = "py"; Args = @("-3.13") },
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3.11") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() }
    )) {
        $found = Test-PythonCandidate -Exe $candidate.Exe -Args $candidate.Args
        if ($found) {
            return $found
        }
    }
    return $null
}

function Write-Launcher {
    param([string]$LauncherPath)

    $launcher = @'
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

if "%LOCALFLIGHT_GUI_MODE%"=="" set "LOCALFLIGHT_GUI_MODE=native"
cd /d "%ROOT%"
start "" "%PYTHON%" -m localflight
exit /b 0
'@

    Set-Content -LiteralPath $LauncherPath -Value $launcher -Encoding ASCII
}

Write-Section "LOCAL FLIGHT - Source Installer"

Write-Host " Source root: $ROOT" -ForegroundColor Gray
Write-Host " Release zip: unzip LocalFlight-windows.zip and run LocalFlight.exe; no installer needed." -ForegroundColor Gray
Write-Host ""

Write-Host " Checking Python..." -NoNewline
$python = Find-Python
if (-not $python) {
    Write-Host " NOT FOUND" -ForegroundColor Red
    Write-Host ""
    Write-Host " Python 3.11 or newer is required for source installs." -ForegroundColor Yellow
    Write-Host " Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host " Check 'Add python.exe to PATH' during installation." -ForegroundColor Yellow
    Write-Host ""
    Stop-Installer 1
}
Write-Host " $($python.Version)" -ForegroundColor Green

$venvPath = Join-Path $ROOT ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host " Creating virtual environment..." -NoNewline
    & $python.Exe @($python.Args) -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host " FAILED" -ForegroundColor Red
        Stop-Installer 1
    }
    Write-Host " Done" -ForegroundColor Green
} else {
    Write-Host " Virtual environment exists - skipping" -ForegroundColor Gray
}

if (-not $SkipDependencyInstall) {
    Write-Host " Installing Python dependencies..." -NoNewline
    Set-Location $ROOT
    & $venvPython -m pip install -e "${ROOT}[native]" -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host " FAILED" -ForegroundColor Red
        Stop-Installer 1
    }
    Write-Host " Done" -ForegroundColor Green

    Write-Host " Confirming PySide6/Qt..." -NoNewline
    $qtVersion = & $venvPython -c "from PySide6.QtCore import qVersion; print(qVersion())" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host ""
        Write-Host $qtVersion -ForegroundColor Yellow
        Stop-Installer 1
    }
    Write-Host " Qt $qtVersion" -ForegroundColor Green
} else {
    Write-Host " Dependency install skipped by -SkipDependencyInstall" -ForegroundColor Yellow
}

$envFile = Join-Path $ROOT ".env"
if (-not (Test-Path $envFile)) {
    Write-Host " Creating .env..." -NoNewline
    $envExample = Join-Path $ROOT ".env.example"
    if (Test-Path $envExample) {
        Copy-Item -LiteralPath $envExample -Destination $envFile
    } else {
        @"
# Local Flight - environment variables
# Fill these in via the setup wizard on first launch.

LOCALFLIGHT_ACTIVATION_TOKEN=
LOCALFLIGHT_RELAY_URL=https://localflight-community-relay.fly.dev
LOCALFLIGHT_GUI_MODE=native

AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90
LOCALFLIGHT_RELAY_MONTHLY_LIMIT=50

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=

RAPIDAPI_KEY=
LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=10000
"@ | Set-Content -LiteralPath $envFile -Encoding UTF8
    }
    Write-Host " Done" -ForegroundColor Green
} else {
    Write-Host " .env already exists - skipping" -ForegroundColor Gray
}

$launcherPath = Join-Path $ROOT "installers\windows\LocalFlight.bat"
Write-Host " Writing source launcher..." -NoNewline
Write-Launcher -LauncherPath $launcherPath
Write-Host " Done" -ForegroundColor Green

if (-not $NoShortcut) {
    Write-Host " Creating desktop shortcut..." -NoNewline
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shortcut = Join-Path $desktop "Local Flight.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($shortcut)
        $lnk.TargetPath = $launcherPath
        $lnk.WorkingDirectory = $ROOT
        $lnk.Description = "Local Flight - Airport FIDS Display"
        $lnk.WindowStyle = 1

        $iconPath = Join-Path $ROOT "assets\icon.ico"
        if (Test-Path $iconPath) {
            $lnk.IconLocation = $iconPath
        } elseif (Test-Path $venvPython) {
            $lnk.IconLocation = "$venvPython,0"
        }

        $lnk.Save()
        Write-Host " Done" -ForegroundColor Green
    } catch {
        Write-Host " Skipped ($($_.Exception.Message))" -ForegroundColor Yellow
    }
} else {
    Write-Host " Desktop shortcut skipped by -NoShortcut" -ForegroundColor Yellow
}

if ($Launch) {
    Write-Host " Launching Local Flight..." -ForegroundColor Cyan
    Start-Process -FilePath $launcherPath -WorkingDirectory $ROOT
}

Write-Section "Installation complete"
Write-Host " Source launcher: $launcherPath" -ForegroundColor White
Write-Host " Release users should run LocalFlight.exe from the downloaded zip." -ForegroundColor Gray
Write-Host ""
if (-not $NoPause) {
    Read-Host " Press Enter to exit"
}
