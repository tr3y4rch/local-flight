# Local Flight — Codex Context

## What this project is

A local-first, self-hosted **Flight Information Display System (FIDS)** that runs on Windows, macOS, and Raspberry Pi. Fetches real and simulated flight data, displays it as a proper airport-style departure/arrival board — in a browser kiosk window, on an LED matrix panel, or on a dedicated HDMI screen.

Built with: Python 3.11+, FastAPI, uvicorn, SQLite, WebSocket, Jinja2, PIL. pystray on macOS only (Windows uses a ctypes taskbar window).

**Repo:** https://github.com/tr3y4rch/local-flight  
**Issues:** https://github.com/tr3y4rch/local-flight/issues

---

## Project structure

```
local-flight/
├── build.py                     # PyInstaller build script — icons, signing, zip
├── LocalFlight.spec             # PyInstaller spec — datas, hiddenimports, BUNDLE
├── LICENSE                      # MIT — Philipp Schumacher 2025
├── CHANGELOG.md
├── .gitattributes               # LF for sh/command, CRLF for bat/ps1
├── src/localflight/
│   ├── __main__.py              # Entry point — platform-aware startup; installs sys/threading crash hooks
│   ├── platform/                # Cross-platform abstraction layer
│   │   ├── detect.py            # Platform detection (Windows/macOS/Pi/Linux)
│   │   ├── browser.py           # Cross-platform kiosk browser launcher
│   │   └── tray.py              # Windows: ctypes taskbar window; macOS: pystray; Pi: stub
│   ├── core/
│   │   ├── airports.py          # Airport DB lookup (IATA/ICAO)
│   │   ├── config.py
│   │   └── models.py            # Flight, FlightPosition, FlightDirection, etc.
│   ├── decode/
│   │   ├── dedupe.py            # Codeshare deduplication
│   │   ├── normalize.py         # Raw records → Flight objects
│   │   ├── opensky.py           # OpenSky enrichment
│   │   └── mappings/
│   │       └── aviationstack.py
│   ├── display/
│   │   └── fids_from_flights.py # PAX-friendly flight number formatting
│   ├── render/
│   │   └── fids.py              # Build Jinja2 template context
│   ├── scheduler/
│   │   ├── jobs.py              # Main fetch job — AviationStack + enrichment chain
│   │   ├── runtime.py           # run_loop(); operator Linear + developer crash report on error
│   │   └── run_scheduler.py
│   ├── sources/
│   │   ├── web/
│   │   │   ├── aviationstack_client.py  # Monthly budget guard, lazy env reads
│   │   │   ├── aviationstack_mock.py
│   │   │   ├── adsbexchange_client.py   # RapidAPI, primary position enrichment
│   │   │   ├── opensky_radar.py         # fetch_radar_blips(), bounding_box()
│   │   │   ├── vatsim_client.py         # VATSIM v3, aircraft type extraction
│   │   │   ├── metar_client.py          # aviationweather.gov, 30min cache
│   │   │   ├── linear_client.py         # Linear GraphQL API — file_error() (operator auto-filing)
│   │   │   └── bug_reporter.py          # Hardcoded developer reporter — powers /feedback
│   │   ├── adsb/
│   │   │   └── adsb_client.py           # dump1090 client (RTL-SDR, Pi)
│   │   └── matrix/
│   │       └── client.py                # MicroPython for Interstate 75 W
│   ├── storage/
│   │   ├── config.py            # AppConfig dataclass, load/save
│   │   ├── flights_store.py     # JSON snapshot storage under ~/.localflight, legacy fallback
│   │   ├── history.py           # SQLite history DB, 90-day retention
│   │   ├── logging_setup.py     # RotatingFileHandler, pruning
│   │   ├── profiles.py          # Airport profiles
│   │   ├── samples/             # Sample AviationStack payloads (mock source)
│   │   └── state.py             # AppState (last fetch, errors, latency)
│   └── ui/
│       ├── server.py            # FastAPI app, WebSocket, setup gate middleware
│       ├── api.py               # All JSON API endpoints
│       ├── static/
│       │   ├── app.css
│       │   ├── skins.css        # 5 skins: standard/technical/neon/cyan/crt
│       │   └── splash_mark.svg  # Versioned launch splash mark
│       └── templates/
│           ├── _nav.html        # Shared nav macro — version badge, quit modal
│           ├── base.html        # Base layout, clock, nav CSS
│           ├── fids.html        # FIDS board — error banner, detail drawer, WebSocket
│           ├── radar.html       # Radar canvas + sweep + METAR
│           ├── display.html     # Split-view FIDS+Radar, draggable divider
│           ├── matrix_preview.html  # LED simulator + split-flap animation
│           ├── settings.html    # Airport picker, skins, re-run setup button
│           ├── admin.html       # Admin hub — scheduler/budget/updates/system
│           ├── feedback.html    # Bug reporter form — title, description, auto-attached system info
│           ├── history.html     # History browser — filterable table + detail panel
│           ├── setup.html       # First-run setup wizard (strict gate)
│           ├── splash.html      # Short versioned launch splash -> setup/display
│           ├── logs.html        # Live log viewer
│           ├── icons_pictogram.html  # Aircraft SVG icons (standard skin)
│           └── icons_technical.html  # Vector icons (neon/cyan/crt skins)
│
├── installers/
│   ├── windows/
│   │   ├── install.ps1          # Windows source checkout installer
│   │   └── LocalFlight.bat      # Windows source checkout launcher
│   ├── macos/
│   │   ├── install.sh
│   │   ├── LocalFlight.command  # Double-clickable launcher
│   │   └── start.sh
│   └── pi/
│       ├── install.sh           # Full Pi setup — venv, systemd, mDNS
│       ├── localflight.service  # Python app systemd service
│       ├── localflight-kiosk.service  # Chromium kiosk systemd service
│       └── lf.sh                # Management helper (start/stop/logs/update)
│
└── start.bat                    # Dev launcher (Windows, project root)
```

---

## Architecture decisions

### Platform model
- `platform/detect.py` — `detect()` returns `Platform` enum, cached. `is_desktop()` / `is_headless()` helpers.
- Desktop (Windows/macOS): kiosk browser window + system tray + full GUI
- Headless (Pi/Linux): uvicorn + scheduler only, no window management. Chromium kiosk is a separate systemd service.
- `__main__.py` dispatches to `_run_desktop()` or `_run_headless()` based on platform.
- Desktop launch and Pi kiosk first hit `/splash?next=/display`; first-run desktop uses `/splash?next=/setup`.

### Data enrichment chain (source=real)
```
AviationStack (schedule: times, gates, status) [90 calls/month budget guard]
    ↓
ADS-B Exchange via RapidAPI (primary: position + aircraft type + registration)
    ↓ fallback
OpenSky Network (position fallback)
    ↓ fallback
Schedule data only
    ↓
Dedupe codeshares → save JSON snapshot → write SQLite history → WebSocket broadcast
    ↓ on error
Linear issue filed (deduplicated per 6h via ~/.localflight/linear_dedup.json)
```

### WebSocket live push
- `ConnectionManager` in `server.py` tracks connections, drains async queue
- Scheduler calls `_broadcast_update()` after each snapshot via `loop.call_soon_threadsafe()`
- `display.html` holds one WS connection, forwards via `postMessage` to iframes
- Clients reconnect with exponential backoff

### Setup gate
- `SetupGateMiddleware` in `server.py` redirects all routes to `/setup` until `~/.localflight/setup_complete` exists
- Exempt paths: `/setup`, `/api/setup/*`, `/api/airports/search`, `/static`, `/health`, `/ws`
- On first launch, scheduler is deferred. Setup watcher thread polls for `setup_complete` and auto-starts scheduler when detected.
- `/api/setup/reset` deletes the marker — triggers re-run wizard. Button in Settings footer.

### API call budget
- AviationStack: 90 calls/month default limit, tracked in `~/.localflight/api_usage.json`
- Enforced in `aviationstack_client.py` via `_check_and_increment_budget()` before each request
- All env vars read lazily at call time (not module import time) to avoid race with `_load_dotenv()`

### Linear issue tracker
Two separate integrations — do not confuse them:
- **Operator auto-filing** (`sources/web/linear_client.py`): `file_error()` called from `scheduler/runtime.py` on every cycle error. Uses `LINEAR_API_KEY` / `LINEAR_TEAM_ID` env vars pointing at the operator's own Linear workspace. Optional, completely silent, deduplicates per 6h.
- **User bug reporter** (`sources/web/bug_reporter.py`): hardcoded developer credentials for a dedicated "Local Flight Reports" workspace. Powers `/feedback` page and `POST /api/feedback`. Always-on, no user config required. Worst case if credentials are compromised: spam to an isolated inbox, easy to rotate.

### Version
- Single source of truth: `version` field in `pyproject.toml`
- Read at runtime via `importlib.metadata.version("localflight")` with `"0.2.1b2"` fallback
- Injected as `app_version` Jinja2 global in `server.py` → available in all templates
- Shown in nav bar (`v0.2.1b2`) and Admin → System card
- `LocalFlight.spec` reads it from `pyproject.toml` at build time for macOS `CFBundleShortVersionString`

### Auto-update check
- `GET /api/admin/updates` checks GitHub releases API for `tr3y4rch/local-flight`
- 1-hour in-process cache to avoid hammering GitHub
- Admin → System card shows "Up to date" (green) or "vX.Y.Z available ↗" (amber link)

---

## Environment variables (.env)

```
AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=

RAPIDAPI_KEY=
```

---

## AppConfig schema

```python
airport_iata: str = "ZRH"
airport_icao: str = "LSZH"
refresh_seconds: int = 3600
display_name: str = "Local Flight"
theme: str = "dark"
source: str = "real"          # "real" | "virtual"
timezone: str = "Europe/Zurich"
skin: str = "standard"        # standard | technical | neon | cyan | crt
display_outputs: List[str] = ["web"]  # web | matrix | hdmi
```

Config lives at `~/.localflight/config.json`

---

## Key API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/fids` | JSON FIDS rows |
| `GET /api/fids/detail` | Per-callsign detail — live position + 7-day history |
| `GET /api/radar` | Aircraft positions |
| `GET /api/metar` | Decoded + raw METAR |
| `GET /api/history` | Recent flights from SQLite |
| `GET /api/history/flight` | Callsign history |
| `GET /api/history/stats` | DB size, row count |
| `GET /api/admin/system` | Uptime, memory, CPU, version |
| `GET /api/admin/budget` | API call budgets |
| `GET /api/admin/connections` | WS count + device pings |
| `GET /api/admin/updates` | GitHub release update check (1h cache) |
| `POST /api/feedback` | Submit bug report `{title, description}` — routes to developer's Linear |
| `POST /api/admin/ping` | Device ping (matrix client) |
| `POST /api/setup/complete` | Save setup, write .env, mark complete |
| `POST /api/setup/reset` | Delete setup_complete marker → re-run wizard |
| `GET /api/setup/test-aviationstack` | Test AviationStack key without saving |
| `GET /api/setup/test-rapidapi` | Test RapidAPI key without saving |
| `POST /api/quit` | Graceful shutdown (terminates browser proc + os._exit) |
| `WS /ws` | WebSocket push endpoint |

---

## Building (PyInstaller)

```bash
python build.py           # generate icons + build + zip
python build.py --clean   # wipe dist/ and build/ first
```

Output:
- **Windows:** `dist/LocalFlight-windows.zip` + `.sha256` — unzip, double-click `LocalFlight.exe`
- **macOS:** `dist/LocalFlight.app` — drag to Applications

Optional code signing via env vars:
- Windows: `SIGNTOOL_CERT` (path to .pfx) + `SIGNTOOL_PASS`
- macOS: `CODESIGN_IDENTITY` (Developer ID string) + `NOTARIZE_PROFILE` (notarytool keychain profile)

Without signing: Windows shows SmartScreen "Unknown publisher"; macOS requires right-click → Open on first launch.

---

## Hardware targets

| Device | Role | Status |
|---|---|---|
| Windows PC | Dev machine | ✅ Running |
| Raspberry Pi 5 | Production server | 🔜 Installer ready, awaiting hardware |
| Pimoroni Interstate 75 W (RP2350) | LED matrix 256×64 | 🔜 MicroPython client written |
| RTL-SDR USB dongle | ADS-B receiver for Pi | 🔜 dump1090 client written |

### LED matrix client (`sources/matrix/client.py`)
- MicroPython, polls `/api/fids` over WiFi every 60s
- Button A = departures, Button B = arrivals, A+B = force refresh
- RGB LED: green=ok, blue=fetching, amber=no data, red=no WiFi
- Calls `/api/admin/ping?device=matrix` on boot and every 10min

### ADS-B on Pi
```bash
sudo apt install dump1090-fa
sudo systemctl enable dump1090-fa
```
Swap `enrich_flights_with_adsbexchange` → `enrich_flights_with_adsb` in `jobs.py`

---

## Running locally

```bash
# Windows
.\start.bat

# macOS
./installers/macos/start.sh

# Manual (any platform)
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
cd src
python -m localflight
```

---

## What was done in the last session

- ✅ `start.bat` — fixed UTF-8 box-drawing chars in `::` comments causing cmd.exe byte-eating bug on `chcp 65001`; replaced all 7 comment lines with ASCII; added error pause
- ✅ `linear_client.py` — added `test_connection()` with real GraphQL `viewer` query to validate key (not just env var presence); returns specific 401 message
- ✅ `bug_reporter.py` — new hardcoded developer reporter (`sources/web/bug_reporter.py`); dedicated "Local Flight Reports" Linear workspace; `_system_context()` auto-attaches version/platform/airport
- ✅ `feedback.html` — new `/feedback` page with title+description form, system info preview, success/error state
- ✅ `/api/feedback` endpoint — `POST`, `FeedbackIn` Pydantic model, calls `bug_reporter.submit_report()`
- ✅ `/feedback` route in `server.py`
- ✅ 🐛 Report nav item added to `_nav.html` management group
- ✅ Admin hub Linear Issues card **removed** — replaced by dedicated `/feedback` page (no duplicate reporting)
- ✅ README rewritten from end-user perspective — install-first flow, removed dev-cycle / awaiting-hardware language
- ✅ File consistency sweep — LINEAR vars removed from all 3 installer `.env` templates; `pyproject.toml` Issues URL → GitHub; `CHANGELOG.md` updated; `AGENTS.md` updated
- ✅ Setup wizard — added `GET /api/setup/test-rapidapi` endpoint + "Test connection" button for ADS-B Exchange key (panel-3); mirrors AviationStack test pattern
- ✅ Setup wizard — fixed RapidAPI signup URL (`adsbexchange` → `adsbx` provider slug in RapidAPI path); fixed OpenSky registration URL (old Joomla path → `/login?view=registration`)
- ✅ Admin hub — added Buy Me a Coffee strip at bottom (`buymeacoffee.com/localflight`); subtle ghost opacity, not a card
- ✅ Runtime snapshots — moved canonical JSON storage to `~/.localflight/storage/data/<IATA>/snapshots`; legacy source-tree snapshots remain readable
- ✅ Scheduler/runtime — pruning now runs inside snapshot jobs; failed cycles preserve the previous `last_success_utc`
- ✅ Installer/docs sweep — Windows/macOS/Pi source installers clarified; Pi helper path fixed; `.env.example` no longer includes operator Linear vars
- ✅ Release prep — version bumped to `0.2.1b2`; `psutil`/`packaging` required; Windows build writes a SHA256 checksum

## Pending / next up

- [ ] Create GitHub release v0.2.1b2 — attach `dist/LocalFlight-windows.zip` and `.sha256`, mark as pre-release
- [ ] Add screenshot to README (FIDS board)
- [ ] Notification system (Pushover/Telegram) — ~50 lines, hooks into scheduler after `_broadcast_update()`
- [ ] Pi hardware arrives — test systemd services + kiosk
- [ ] RTL-SDR dongle — test dump1090 integration
- [ ] Interstate 75 W — flash client.py, test WiFi polling
- [ ] Code signing certificates — Developer ID (macOS) + EV cert (Windows SmartScreen)

---

## Code style / conventions

- Python 3.11+, type hints throughout, `from __future__ import annotations`
- FastAPI for the web layer, Jinja2 for templates
- No module-level env var reads — always read lazily inside functions
- Non-fatal pattern: wrap risky operations in try/except, log warning, continue
- History writes, enrichment failures, WS broadcasts, Linear calls are all non-fatal
- `os._exit(0)` for hard shutdown (bypasses uvicorn's signal handling)
- Jinja2 templates use `{% from "_nav.html" import topnav %}` for consistent nav
- Nav active state passed as `active="pagename"` string parameter
- `app_version` available in all templates as a Jinja2 global (injected in `server.py`)
