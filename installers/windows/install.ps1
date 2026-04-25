# ═══════════════════════════════════════════════════════════════════════════════
# Local Flight — Windows Installer
#
# Run from the project root:
#   Right-click install.ps1 → Run with PowerShell
#   or: powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1
# ═══════════════════════════════════════════════════════════════════════════════

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ROOT = (Resolve-Path (Join-Path $SCRIPT_DIR "..\..")).Path

Write-Host ""
Write-Host " ==========================================" -ForegroundColor Cyan
Write-Host "   LOCAL FLIGHT - Windows Installer" -ForegroundColor Cyan
Write-Host " ==========================================" -ForegroundColor Cyan
Write-Host ""

# ── Find Python (prefer stable 3.13/3.12/3.11 over pre-release 3.14) ──────────
Write-Host " Checking Python..." -NoNewline
$pyExe = $null
$pyArgs = @()
foreach ($ver in @("3.13", "3.12", "3.11")) {
    $pyver = & py "-$ver" --version 2>&1
    if ($LASTEXITCODE -eq 0) { $pyExe = "py"; $pyArgs = @("-$ver"); break }
}
if (-not $pyExe) {
    $pyver = & python --version 2>&1
    if ($LASTEXITCODE -eq 0 -and "$pyver" -match "Python 3") {
        $pyExe = "python"
    }
}
if (-not $pyExe) {
    Write-Host " NOT FOUND" -ForegroundColor Red
    Write-Host ""
    Write-Host " Python 3.11 or newer is required." -ForegroundColor Yellow
    Write-Host " Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host " Check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    Write-Host ""
    Read-Host " Press Enter to exit"
    exit 1
}
Write-Host " $pyver" -ForegroundColor Green

# ── Create virtual environment ─────────────────────────────────────────────────
$venvPath = Join-Path $ROOT ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path (Join-Path $venvPath "Scripts\activate.bat"))) {
    Write-Host " Creating virtual environment..." -NoNewline
    & $pyExe @pyArgs -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host " FAILED" -ForegroundColor Red
        Read-Host " Press Enter to exit"; exit 1
    }
    Write-Host " Done" -ForegroundColor Green
} else {
    Write-Host " Virtual environment exists - skipping" -ForegroundColor Gray
}

# ── Install dependencies (use venv python directly, no activation needed) ──────
Write-Host " Installing dependencies..." -NoNewline
Set-Location $ROOT
& $venvPython -m pip install -e . -q
if ($LASTEXITCODE -ne 0) {
    Write-Host " FAILED" -ForegroundColor Red
    Read-Host " Press Enter to exit"; exit 1
}
Write-Host " Done" -ForegroundColor Green

# ── Create .env if missing ─────────────────────────────────────────────────────
$envFile = Join-Path $ROOT ".env"
if (-not (Test-Path $envFile)) {
    Write-Host " Creating .env..." -NoNewline
    $envExample = Join-Path $ROOT ".env.example"
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
    } else {
        @"
# Local Flight - environment variables
# Fill these in via the setup wizard on first launch.

AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=

RAPIDAPI_KEY=

# Linear issue tracker (optional)
LINEAR_API_KEY=
LINEAR_TEAM_ID=
"@ | Set-Content $envFile -Encoding UTF8
    }
    Write-Host " Done" -ForegroundColor Green
} else {
    Write-Host " .env already exists - skipping" -ForegroundColor Gray
}

# ── Create LocalFlight.bat launcher ───────────────────────────────────────────
$launcherPath = Join-Path $ROOT "installers\windows\LocalFlight.bat"
Write-Host " Creating launcher..." -NoNewline
@"
@echo off
powershell -ExecutionPolicy Bypass -WindowStyle Hidden -Command "& '%~dp0..\..\.venv\Scripts\Activate.ps1'; cd '%~dp0..\..\src'; python -m localflight"
"@ | Set-Content $launcherPath -Encoding ASCII
Write-Host " Done" -ForegroundColor Green

# ── Create desktop shortcut ────────────────────────────────────────────────────
Write-Host " Creating desktop shortcut..." -NoNewline
try {
    $desktop  = [Environment]::GetFolderPath("Desktop")
    $shortcut = Join-Path $desktop "Local Flight.lnk"
    $shell    = New-Object -ComObject WScript.Shell
    $lnk      = $shell.CreateShortcut($shortcut)
    $lnk.TargetPath       = $launcherPath
    $lnk.WorkingDirectory = $ROOT
    $lnk.Description      = "Local Flight - Airport FIDS Display"
    $lnk.WindowStyle      = 1
    $pythonExe = Join-Path $venvPath "Scripts\python.exe"
    if (Test-Path $pythonExe) { $lnk.IconLocation = "$pythonExe,0" }
    $lnk.Save()
    Write-Host " Done" -ForegroundColor Green
} catch {
    Write-Host " Skipped ($($_.Exception.Message))" -ForegroundColor Yellow
}

# ── Done ───────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host " ==========================================" -ForegroundColor Cyan
Write-Host "   Installation complete!" -ForegroundColor Green
Write-Host " ==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host " Double-click 'Local Flight' on your desktop to start." -ForegroundColor White
Write-Host " Or run start.bat for the dev launcher with console output." -ForegroundColor Gray
Write-Host ""
Read-Host " Press Enter to exit"
