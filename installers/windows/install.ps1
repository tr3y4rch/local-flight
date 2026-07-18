# Local Flight - Windows source installer
#
# This script is for running Local Flight from a source checkout.
# End users should prefer the LocalFlight-<version>-Setup.exe release wizard.
# The release app is native Qt first; the local browser UI remains available
# at localhost.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -DisplayMode Native
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -DisplayMode Browser
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -DisplayMode Headless
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -Launch
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -NoShortcut
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -SkipDependencyInstall
#   powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -NoPause

[CmdletBinding()]
param(
    [string]$DisplayMode = "",
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

function Resolve-DisplayMode {
    param([string]$RequestedMode)

    $mode = "$RequestedMode".Trim()
    if ($mode) {
        switch -Regex ($mode) {
            "^(?i:native)$" { return "native" }
            "^(?i:browser)$" { return "browser" }
            "^(?i:headless)$" { return "headless" }
            default {
                Write-Host " Invalid -DisplayMode '$RequestedMode'. Use Native, Browser, or Headless." -ForegroundColor Red
                Stop-Installer 1
            }
        }
    }

    if ([Environment]::UserInteractive -and -not $NoPause) {
        Write-Host " Choose how this source install should open:" -ForegroundColor Cyan
        Write-Host "   1) Native Qt GUI   - recommended Chrome-free desktop shell"
        Write-Host "   2) Browser/LAN UI  - open the supported local browser interface"
        Write-Host "   3) Headless server - backend only for LAN/mobile/matrix"
        $choice = Read-Host " Select 1/2/3, or press Enter for Native"
        switch ($choice.Trim()) {
            "2" { return "browser" }
            "3" { return "headless" }
            default { return "native" }
        }
    }

    return "native"
}

function Set-ClientEnvValue {
    param(
        [string]$EnvPath,
        [string]$Key,
        [string]$Value
    )

    if (-not (Test-Path $EnvPath)) {
        return
    }

    $lines = Get-Content -LiteralPath $EnvPath -ErrorAction SilentlyContinue
    $updated = $false
    $newLines = foreach ($line in $lines) {
        if ($line -match "^$([regex]::Escape($Key))=") {
            $updated = $true
            "$Key=$Value"
        } else {
            $line
        }
    }
    if (-not $updated) {
        $newLines += "$Key=$Value"
    }
    Set-Content -LiteralPath $EnvPath -Value $newLines -Encoding UTF8
}

function Write-Launcher {
    param(
        [string]$LauncherPath,
        [string]$DefaultGuiMode
    )

    $launcher = @"
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

if "%LOCALFLIGHT_GUI_MODE%"=="" set "LOCALFLIGHT_GUI_MODE=$DefaultGuiMode"
cd /d "%ROOT%"
"%PYTHON%" -m localflight
set "LF_EXIT=%ERRORLEVEL%"
if not "%LF_EXIT%"=="0" pause
exit /b %LF_EXIT%
"@

    Set-Content -LiteralPath $LauncherPath -Value $launcher -Encoding ASCII
}

function Write-ClientEnv {
    param(
        [string]$EnvPath,
        [string]$GuiMode
    )

    @"
# Local Flight - client environment
# The setup wizard writes these on first launch.

LOCALFLIGHT_ACTIVATION_TOKEN=
LOCALFLIGHT_RELAY_URL=https://relay.beacontools.cc
LOCALFLIGHT_GUI_MODE=$GuiMode

AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90
LOCALFLIGHT_RELAY_MONTHLY_LIMIT=50

RAPIDAPI_KEY=
LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=10000

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=
"@ | Set-Content -LiteralPath $EnvPath -Encoding UTF8
}

Write-Section "LOCAL FLIGHT - Source Installer"

Write-Host " Source root: $ROOT" -ForegroundColor Gray
Write-Host " Release wizard: run LocalFlight-<version>-Setup.exe for the normal Windows install." -ForegroundColor Gray
Write-Host " GUI default: native Qt shell; LAN browser UI stays at http://localhost:8000." -ForegroundColor Gray
Write-Host ""

$resolvedDisplayMode = Resolve-DisplayMode -RequestedMode $DisplayMode
$installNative = $resolvedDisplayMode -eq "native"
Write-Host " Selected display mode: $resolvedDisplayMode" -ForegroundColor Cyan
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
$venvPythonw = Join-Path $venvPath "Scripts\pythonw.exe"

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
    $installTarget = $ROOT
    if ($installNative) {
        $installTarget = "${ROOT}[native]"
    }
    & $venvPython -m pip install -e $installTarget -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host " FAILED" -ForegroundColor Red
        Stop-Installer 1
    }
    Write-Host " Done" -ForegroundColor Green

    if ($installNative) {
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
        Write-Host " PySide6/Qt check skipped for $resolvedDisplayMode mode" -ForegroundColor Gray
    }
} else {
    Write-Host " Dependency install skipped by -SkipDependencyInstall" -ForegroundColor Yellow
}

$envFile = Join-Path $ROOT ".env"
if (-not (Test-Path $envFile)) {
    Write-Host " Creating .env..." -NoNewline
    Write-ClientEnv -EnvPath $envFile -GuiMode $resolvedDisplayMode
    Write-Host " Done" -ForegroundColor Green
} else {
    Write-Host " .env already exists - updating GUI mode" -ForegroundColor Gray
    Set-ClientEnvValue -EnvPath $envFile -Key "LOCALFLIGHT_GUI_MODE" -Value $resolvedDisplayMode
}

$launcherPath = Join-Path $ROOT "installers\windows\LocalFlight.bat"
Write-Host " Writing source launcher..." -NoNewline
Write-Launcher -LauncherPath $launcherPath -DefaultGuiMode $resolvedDisplayMode
Write-Host " Done" -ForegroundColor Green

$silentTarget = $venvPythonw
$silentArguments = "-m localflight"
if (-not (Test-Path $silentTarget)) {
    $silentTarget = $launcherPath
    $silentArguments = ""
}

if (-not $NoShortcut) {
    Write-Host " Creating desktop shortcut..." -NoNewline
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $shortcut = Join-Path $desktop "Local Flight.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($shortcut)
        $lnk.TargetPath = $silentTarget
        $lnk.Arguments = $silentArguments
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
    if ($silentArguments) {
        Start-Process -FilePath $silentTarget -ArgumentList $silentArguments -WorkingDirectory $ROOT
    } else {
        Start-Process -FilePath $silentTarget -WorkingDirectory $ROOT
    }
}

Write-Section "Installation complete"
Write-Host " Source launcher: $launcherPath" -ForegroundColor White
Write-Host " Display mode: $resolvedDisplayMode" -ForegroundColor Gray
Write-Host " LAN browser UI remains available at http://localhost:8000 when the backend is running." -ForegroundColor Gray
Write-Host " Release users should run LocalFlight-<version>-Setup.exe, or use LocalFlight.exe from the portable zip." -ForegroundColor Gray
Write-Host ""
if (-not $NoPause) {
    Read-Host " Press Enter to exit"
}
