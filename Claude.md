# Local Flight — Claude Code Context

## What this project is

A local-first, self-hosted **Flight Information Display System (FIDS)** that runs on Windows, macOS, and Raspberry Pi. Fetches real and simulated flight data, displays it as a proper airport-style departure/arrival board — in a browser kiosk window, on an LED matrix panel, or on a dedicated HDMI screen.

Built with: Python 3.11+, FastAPI, uvicorn, SQLite, WebSocket, Jinja2, pystray, PIL.

---

## Project structure

```
local-flight/
├── src/localflight/
│   ├── __main__.py              # Entry point — platform-aware startup
│   ├── tray.py                  # DEPRECATED — use platform/tray.py
│   ├── platform/                # NEW — cross-platform abstraction layer
│   │   ├── __init__.py
│   │   ├── detect.py            # Platform detection (Windows/macOS/Pi/Linux)
│   │   ├── browser.py           # Cross-platform kiosk browser launcher
│   │   └── tray.py              # Cross-platform tray (stub on Pi/Linux)
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
│   │   ├── runtime.py           # run_loop(), run_multi_airport()
│   │   └── run_scheduler.py
│   ├── sources/
│   │   ├── web/
│   │   │   ├── aviationstack_client.py  # Monthly budget guard, lazy env reads
│   │   │   ├── aviationstack_files.py
│   │   │   ├── aviationstack_mock.py
│   │   │   ├── adsbexchange_client.py   # RapidAPI, primary position enrichment
│   │   │   ├── opensky_radar.py         # fetch_radar_blips(), bounding_box()
│   │   │   ├── vatsim_client.py         # VATSIM v3, aircraft type extraction
│   │   │   └── metar_client.py          # aviationweather.gov, 30min cache
│   │   ├── adsb/
│   │   │   └── adsb_client.py           # dump1090 client (RTL-SDR, Pi)
│   │   └── matrix/
│   │       └── client.py                # MicroPython for Interstate 75 W
│   ├── storage/
│   │   ├── config.py            # AppConfig dataclass, load/save
│   │   ├── flights_store.py     # JSON snapshot storage
│   │   ├── history.py           # SQLite history DB, 90-day retention
│   │   ├── logging_setup.py     # RotatingFileHandler, pruning
│   │   ├── profiles.py          # Airport profiles
│   │   └── state.py             # AppState (last fetch, errors, latency)
│   └── ui/
│       ├── server.py            # FastAPI app, WebSocket, setup gate middleware
│       ├── api.py               # All JSON API endpoints
│       ├── static/
│       │   ├── app.css
│       │   └── skins.css        # 5 skins: standard/technical/neon/cyan/crt
│       └── templates/
│           ├── _nav.html        # Shared nav macro (all management pages)
│           ├── base.html        # Base layout, clock, nav CSS
│           ├── fids.html        # FIDS board + METAR bar + WebSocket
│           ├── radar.html       # Radar canvas + sweep + METAR
│           ├── display.html     # Split-view FIDS+Radar, draggable divider
│           ├── matrix_preview.html  # LED simulator + split-flap animation
│           ├── settings.html    # Airport picker, skins, display outputs
│           ├── admin.html       # Admin hub — scheduler/budget/clients/system
│           ├── history.html     # History browser — filterable table + detail panel
│           ├── setup.html       # First-run setup wizard (strict gate)
│           ├── logs.html        # Live log viewer
│           ├── icons_pictogram.html  # Aircraft SVG icons (standard skin)
│           └── icons_technical.html  # Vector icons (neon/cyan/crt skins)
│
├── installers/
│   ├── windows/
│   │   ├── install.ps1          # One-time installer
│   │   ├── LocalFlight.bat      # End-user launcher
│   │   └── start.bat            # Dev launcher
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
└── start.bat                    # Legacy dev launcher (Windows, project root)
```

---

## Architecture decisions

### Platform model
- `platform/detect.py` — `detect()` returns `Platform` enum, cached. `is_desktop()` / `is_headless()` helpers.
- Desktop (Windows/macOS): kiosk browser window + system tray + full GUI
- Headless (Pi/Linux): uvicorn + scheduler only, no window management. Chromium kiosk is a separate systemd service.
- `__main__.py` dispatches to `_run_desktop()` or `_run_headless()` based on platform.

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

### API call budget
- AviationStack: 90 calls/month default limit, tracked in `~/.localflight/api_usage.json`
- Enforced in `aviationstack_client.py` via `_check_and_increment_budget()` before each request
- All env vars read lazily at call time (not module import time) to avoid race with `_load_dotenv()`

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
| `GET /api/radar` | Aircraft positions |
| `GET /api/metar` | Decoded + raw METAR |
| `GET /api/history` | Recent flights from SQLite |
| `GET /api/history/flight` | Callsign history |
| `GET /api/history/stats` | DB size, row count |
| `GET /api/admin/system` | Uptime, memory, CPU |
| `GET /api/admin/budget` | API call budgets |
| `GET /api/admin/connections` | WS count + device pings |
| `POST /api/admin/ping` | Device ping (matrix client) |
| `POST /api/setup/complete` | Save setup, write .env, mark complete |
| `GET /api/setup/test-aviationstack` | Test AS key without saving |
| `POST /api/quit` | Graceful shutdown (terminates browser proc + os._exit) |
| `WS /ws` | WebSocket push endpoint |

---

## Hardware targets

| Device | Role | Status |
|---|---|---|
| Windows PC | Dev machine | ✅ Running |
| Raspberry Pi 5 | Production server | 🔜 Planned — installer ready |
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
.\installers\windows\start.bat

# macOS
./installers/macos/start.sh

# Manual (any platform)
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
cd src
python -m localflight
```

---

## What was done in the last session

- ✅ Platform abstraction layer (`platform/` module)
- ✅ Cross-platform browser detection and launch
- ✅ Cross-platform tray with headless stub for Pi
- ✅ `__main__.py` split into `_run_desktop()` / `_run_headless()`
- ✅ Installer reorganisation into `installers/windows|macos|pi/`
- ✅ Pi systemd services (`localflight.service`, `localflight-kiosk.service`)
- ✅ Pi management helper (`lf.sh`)
- ✅ mDNS setup (`localflight.local`) in Pi installer
- ✅ Shared nav bar (`_nav.html`) across all management pages
- ✅ Consistent emoji icon system across all pages
- ✅ FIDS/Radar embedded mode fix (`?embedded=1`) for display.html iframes
- ✅ Quit button in nav (`⏻`) calling `/api/quit`
- ✅ `/api/quit` terminates browser proc then `os._exit(0)`
- ✅ Terminal closes automatically on quit (no `pause` in start.bat)
- ✅ VATSIM aircraft type extraction fixed (handles `H/B748/L` heavy format)

## Pending / next up

- [ ] Test full clean install flow on Windows with new installer structure
- [ ] Pi hardware arrives — test systemd services + kiosk
- [ ] RTL-SDR dongle — test dump1090 integration
- [ ] Interstate 75 W — flash client.py, test WiFi polling
- [ ] Notification system (Pushover/Telegram) — ~50 lines, hooks into scheduler
- [ ] PyInstaller bundle (deferred — wait for Python 3.14 support)
- [ ] Public demo instance

---

## Code style / conventions

- Python 3.11+, type hints throughout, `from __future__ import annotations`
- FastAPI for the web layer, Jinja2 for templates
- No module-level env var reads — always read lazily inside functions
- Non-fatal pattern: wrap risky operations in try/except, log warning, continue
- History writes, enrichment failures, WS broadcasts are all non-fatal
- `os._exit(0)` for hard shutdown (bypasses uvicorn's signal handling)
- Jinja2 templates use `{% from "_nav.html" import topnav %}` for consistent nav
- Nav active state passed as `active="pagename"` string parameter