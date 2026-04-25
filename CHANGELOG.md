# Changelog

All notable changes to Local Flight are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.1b1] — 2026-04-26

### Added
- **Platform abstraction layer** (`platform/`) — unified Windows, macOS, Pi/Linux startup
- **Cross-platform kiosk browser launcher** — Edge/Chrome app window on desktop, Chromium kiosk service on Pi
- **Cross-platform system tray** — pystray on Windows/macOS, no-op stub on Pi/Linux
- **Raspberry Pi installer** (`installers/pi/install.sh`) — venv, two systemd services, mDNS (`localflight.local`)
- **Pi management helper** (`lf.sh`) — start/stop/logs/update in one command
- **Shared nav bar** (`_nav.html`) — consistent navigation macro across all pages
- **FIDS board improvements** — ARR/DEP toggle visible in all modes including split-view embedded iframes
- **Flight detail drawer** — click any FIDS row for a slide-in panel with times, position, ops data, and 7-day history
- **Settings page** — active skin highlighted on load, compact status line in header
- **Admin hub** — scheduler status, API budget, WebSocket client count, history DB stats, METAR, live log tail
- **History database** — SQLite, 90-day retention, browse tab + aggregate stats tab
- **5 skins** — standard, technical, neon, cyan, crt
- **PyInstaller bundle** — `python build.py` produces `dist/LocalFlight-windows.zip` (Windows) or `dist/LocalFlight.app` (macOS)
- **Version field** — `v{version}` shown in nav bar and Admin → System card, sourced from package metadata
- **Bad API key banner** — FIDS board shows a red warning banner when the scheduler has a persistent error
- **Quit button modal** — inline confirmation dialog replacing native `confirm()`, with "Shutting down…" feedback state
- **Bug reporter** — 🐛 Report nav button on every page; `/feedback` form auto-attaches version, platform, airport; routes to developer's Linear (no user config required)
- **Setup wizard — RapidAPI key validation** — "Test connection" button for ADS-B Exchange key mirrors AviationStack step; `GET /api/setup/test-rapidapi` endpoint validates key without saving
- **Admin — Buy Me a Coffee** — subtle attribution strip at bottom of Admin hub
- **`/api/fids/detail`** — per-callsign detail endpoint with live position + 7-day history
- **Setup re-run** — "Re-run setup wizard" button in Settings to reset configuration from scratch
- **Auto-update check** — Admin hub shows a notice when a newer GitHub release is available

### Changed
- README rewritten from end-user perspective — install-first flow, removed dev-cycle language
- Installer structure reorganised into `installers/windows|macos|pi/`
- `__main__.py` split into `_run_desktop()` / `_run_headless()` paths
- Terminal closes automatically on quit (no `pause` in launcher scripts)
- Quit endpoint uses `os._exit(0)` after terminating the browser process

### Fixed
- `start.bat` — UTF-8 box-drawing chars in `::` comments caused cmd.exe byte-eating bug on `chcp 65001`; replaced with ASCII dashes
- Setup wizard — RapidAPI signup URL corrected (`adsbexchange` → `adsbx` provider slug); OpenSky registration URL updated from stale Joomla path to `/login?view=registration`
- VATSIM aircraft type extraction now handles `H/B748/L` heavy-prefix format
- Jinja2 `TemplateSyntaxError` in `_nav.html` (unclosed block comment)
- `UnicodeEncodeError` on Windows console (cp1252) in build script output

---

## [0.1.0] — 2025-03-01

### Added
- Initial release — FastAPI web server, FIDS board, WebSocket live push
- AviationStack schedule data source with monthly budget guard
- ADS-B Exchange position enrichment (RapidAPI)
- OpenSky Network position fallback
- VATSIM virtual/sim source
- METAR weather bar
- Radar view with sweep animation
- Split-view display with draggable divider
- Matrix preview (LED simulator + split-flap animation)
- MicroPython client for Pimoroni Interstate 75 W
- First-run setup wizard
- SQLite flight history (90 days)
- dump1090 / RTL-SDR ADS-B client for Pi
