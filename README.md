# Local Flight

A **local-first Flight Information Display System (FIDS)** that runs on Windows, macOS, or a Raspberry Pi.
Fetches real and simulated flight data, normalises it, and renders it as a proper airport-style departure/arrival board — in your browser, on an LED matrix panel, or on a dedicated HDMI screen.

No cloud. No accounts. No dashboards that want your email.

**Source:** [github.com/tr3y4rch/local-flight](https://github.com/tr3y4rch/local-flight) · **Issues:** [linear.app/local-flight](https://linear.app/local-flight)

---

## What it does

- Fetches live flight data from **AviationStack** (real), **VATSIM** (virtual/sim), or **ADS-B Exchange** (live position via RapidAPI)
- Enriches schedule data with **live aircraft positions** from ADS-B Exchange (primary) or OpenSky Network (fallback)
- Decodes live **METAR weather** for the configured airport — displayed on the FIDS and radar
- Renders a full-featured **FIDS arrivals/departures board** with PAX-friendly flight numbers, coloured status badges, and live updates via WebSocket
- Shows a **live radar** with sweep animation and sweep-linked blip fading
- Provides a **split-view display** (FIDS + Radar side by side) with a draggable divider
- Stores 90 days of flight history in a local **SQLite database** with a browsable history UI and aggregate stats
- Supports **profiles** — save and switch airport configurations instantly
- Displays **UTC and local time** simultaneously, timezone follows the configured airport
- **First-run setup wizard** — guides through airport selection, API keys, and display settings before anything starts
- **Admin hub** — scheduler controls, API budget tracking, connected clients, system status
- Runs as a **system tray app** on Windows/macOS; headless with a separate Chromium kiosk on Pi
- Ships a **MicroPython client** for the Pimoroni Interstate 75 W LED matrix panel
- Includes a **matrix preview** in the browser — see exactly what the LED panel will show, with split-flap animation

---

## Project structure

```
local-flight/
├── src/localflight/
│   ├── __main__.py              # Entry point — dispatches desktop vs headless
│   ├── platform/                # Cross-platform abstraction layer
│   │   ├── detect.py            # Platform detection (Windows / macOS / Pi / Linux)
│   │   ├── browser.py           # Cross-platform kiosk browser launcher
│   │   └── tray.py              # System tray (stub on Pi/Linux)
│   ├── core/
│   │   ├── airports.py          # Airport DB lookup (IATA/ICAO)
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
│   │   │   ├── aviationstack_mock.py
│   │   │   ├── adsbexchange_client.py   # RapidAPI, primary position enrichment
│   │   │   ├── opensky_radar.py         # fetch_radar_blips(), bounding_box()
│   │   │   ├── vatsim_client.py         # VATSIM v3, aircraft type extraction
│   │   │   └── metar_client.py          # aviationweather.gov, 30 min cache
│   │   ├── adsb/
│   │   │   └── adsb_client.py           # dump1090 client (RTL-SDR on Pi)
│   │   └── matrix/
│   │       └── client.py                # MicroPython for Interstate 75 W
│   ├── storage/
│   │   ├── config.py            # AppConfig dataclass, load/save
│   │   ├── flights_store.py     # JSON snapshot storage
│   │   ├── history.py           # SQLite history DB, 90-day retention + stats
│   │   ├── logging_setup.py     # RotatingFileHandler, pruning
│   │   ├── profiles.py          # Airport profiles
│   │   └── state.py             # AppState (last fetch, errors, latency)
│   └── ui/
│       ├── server.py            # FastAPI app, WebSocket, setup gate middleware
│       ├── api.py               # All JSON API endpoints
│       ├── static/
│       │   ├── app.css
│       │   └── skins.css        # 5 skins: standard / technical / neon / cyan / crt
│       └── templates/
│           ├── _nav.html        # Shared nav bar macro (all management pages)
│           ├── base.html        # Base layout — clock, nav CSS, micro-animations
│           ├── fids.html        # FIDS board — status badges, WebSocket live updates
│           ├── radar.html       # Radar canvas + sweep + METAR
│           ├── display.html     # Split-view FIDS+Radar, draggable divider
│           ├── matrix_preview.html  # LED simulator + split-flap animation
│           ├── settings.html    # Airport picker, skins, display outputs
│           ├── admin.html       # Admin hub — scheduler / budget / clients / system
│           ├── history.html     # History browser — table + stats tab
│           ├── setup.html       # First-run setup wizard
│           ├── logs.html        # Live log viewer
│           ├── icons_pictogram.html  # Aircraft SVG icons (standard skin)
│           └── icons_technical.html  # Vector icons (neon / cyan / crt skins)
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

### Key files at a glance

| What | Where |
|---|---|
| Web server + routes | `ui/server.py` |
| JSON API endpoints | `ui/api.py` |
| Flight data model | `core/models.py` |
| Config (AppConfig) | `storage/config.py` |
| Flight history DB | `storage/history.py` |
| Platform detection | `platform/detect.py` |
| Kiosk browser launcher | `platform/browser.py` |
| System tray | `platform/tray.py` |
| AviationStack client (budget guard) | `sources/web/aviationstack_client.py` |
| ADS-B Exchange client | `sources/web/adsbexchange_client.py` |
| OpenSky radar client | `sources/web/opensky_radar.py` |
| METAR client | `sources/web/metar_client.py` |
| VATSIM client | `sources/web/vatsim_client.py` |
| ADS-B / dump1090 client | `sources/adsb/adsb_client.py` |
| MicroPython LED matrix client | `sources/matrix/client.py` |
| Scheduler job (enrichment chain) | `scheduler/jobs.py` |
| App entry point | `__main__.py` |

---

## Data sources

| Source | Type | Key required | Used for |
|---|---|---|---|
| AviationStack | Schedule data | Yes (`AVIATIONSTACK_API_KEY`) | Flight times, gates, status |
| ADS-B Exchange | Live positions | Yes (`RAPIDAPI_KEY`) | Primary position enrichment, aircraft type, registration |
| OpenSky Network | Live positions | Optional (`OPENSKY_CLIENT_ID/SECRET`) | Fallback position enrichment |
| VATSIM | Sim traffic + positions | No | Full source for virtual/sim mode |
| dump1090 / RTL-SDR | Live ADS-B | No (local) | Pi with USB dongle — no rate limits |
| aviationweather.gov | METAR weather | No | Free, cached 30 minutes |

---

## Enrichment chain (real source)

```
AviationStack (schedule: times, gates, status)
    ↓
ADS-B Exchange (primary — position + aircraft type + registration)
    ↓ fallback if unavailable / rate limited
OpenSky Network (position fallback)
    ↓ fallback if both unavailable
Schedule data only (FIDS works, radar shows no blips)
    ↓
Deduplicate codeshares
    ↓
Save JSON snapshot → write SQLite history DB → WebSocket broadcast
```

---

## Running locally

### Windows — quickstart
```
installers\windows\start.bat
```
Or from the project root:
```
start.bat
```
Activates the venv, loads `.env`, checks and installs dependencies, launches the app.
Opens a dedicated Edge app window at `/display`. System tray icon appears — right-click to open views or quit.

### macOS
```bash
./installers/macos/start.sh
```
Or double-click `installers/macos/LocalFlight.command` after running `install.sh` once.

### Raspberry Pi
```bash
# One-time setup
bash installers/pi/install.sh

# Management (start / stop / logs / update)
./lf.sh start
```
The Pi runs headless — the Python app and Chromium kiosk are separate systemd services. Access from any device on the network at `http://localflight.local`.

### Manual start (any platform)
```bash
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
cd src
python -m localflight
```

---

## First-run setup

On first launch, the setup wizard opens automatically at `http://localhost:8000/setup`.

It walks through:
1. Airport selection (IATA/ICAO search)
2. Data source — real (AviationStack) or virtual (VATSIM)
3. API key entry and live validation
4. Display name and timezone
5. Theme and skin selection

The scheduler only starts after setup is complete. A `~/.localflight/setup_complete` marker file is written on finish.

---

## Environment variables (`.env`)

```
# AviationStack — real flight schedule data
AVIATIONSTACK_API_KEY=your_key_here
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90   # default 90 (free tier is 100)

# OpenSky Network — position fallback
OPENSKY_CLIENT_ID=your_id
OPENSKY_CLIENT_SECRET=your_secret

# ADS-B Exchange via RapidAPI — primary position enrichment
RAPIDAPI_KEY=your_rapidapi_key

# Linear issue tracker — optional, files issues on scheduler errors
LINEAR_API_KEY=lin_api_...
LINEAR_TEAM_ID=your_team_uuid
```

All env vars are read lazily at call time — editing `.env` takes effect on the next fetch without restart.

---

## Configuration

Config lives at `~/.localflight/config.json` and is managed via the **Settings** page at `http://localhost:8000`.

| Field | Default | Description |
|---|---|---|
| `airport_iata` | `ZRH` | 3-letter IATA code |
| `airport_icao` | `LSZH` | 4-letter ICAO code |
| `refresh_seconds` | `3600` | Fetch interval (min 900 s) |
| `source` | `real` | `real` (AviationStack + enrichment) or `virtual` (VATSIM) |
| `timezone` | `Europe/Zurich` | IANA timezone for local time display |
| `theme` | `dark` | `dark` or `light` |
| `skin` | `standard` | `standard`, `technical`, `neon`, `cyan`, `crt` |
| `display_name` | `Local Flight` | Shown in the UI header |
| `display_outputs` | `["web"]` | `web`, `matrix`, `hdmi` — multi-select |

---

## Pages

| URL | Description |
|---|---|
| `/display` | Split-view FIDS + Radar with draggable divider (default launch target) |
| `/fids` | FIDS board standalone (`?view=arrivals\|departures`) |
| `/radar` | Radar standalone |
| `/matrix-preview` | Browser LED matrix simulator |
| `/` | Settings — airport, skin, outputs |
| `/admin` | Admin hub — scheduler status, API budgets, connected clients, system info |
| `/history` | Flight history — filterable table + aggregate stats tab |
| `/logs` | Live log viewer |
| `/setup` | First-run setup wizard |

All pages support `?embedded=1` to suppress the nav bar (used by display.html iframes).

---

## API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/fids` | GET | JSON FIDS rows (`?view=arrivals\|departures&limit=20`) |
| `/api/radar` | GET | JSON aircraft positions (`?radius_nm=20`) |
| `/api/metar` | GET | Decoded + raw METAR for configured airport |
| `/api/flights` | GET | Raw flight list from latest snapshot |
| `/api/history` | GET | Recent flights from SQLite (`?hours=24&direction=DEP`) |
| `/api/history/flight` | GET | Callsign history (`?callsign=SWR184&days=7`) |
| `/api/history/stats` | GET | DB row count, oldest/newest, size |
| `/api/history/summary` | GET | Aggregate stats — top airlines, routes, aircraft, on-time rate (`?hours=720`) |
| `/api/config` | GET/PATCH | Read or update config fields |
| `/api/health` | GET | AppState — last fetch, errors, latency |
| `/api/airports/search` | GET | Airport search (`?q=zurich`) |
| `/api/airports/resolve` | GET | Resolve IATA/ICAO to full airport record |
| `/api/admin/system` | GET | Uptime, memory, CPU |
| `/api/admin/budget` | GET | API call budgets and usage |
| `/api/admin/connections` | GET | WebSocket client count + device pings |
| `/api/admin/ping` | POST | Device ping (LED matrix client uses this) |
| `/api/admin/linear/status` | GET | Whether Linear integration is configured |
| `/api/admin/linear/issue` | POST | File a new Linear issue (`{title, description}`) |
| `/api/setup/complete` | POST | Save setup, write `.env`, mark complete |
| `/api/setup/test-aviationstack` | GET | Validate an API key without saving |
| `/api/quit` | POST | Graceful shutdown — terminates browser process then exits |
| `/ws` | WS | WebSocket push endpoint — broadcasts `snapshot_updated` after each fetch |

---

## Skins

| Skin | Style | Icons |
|---|---|---|
| `standard` | Dark/light neutral | Pictogram aircraft silhouettes |
| `technical` | Cool blue monospace | Vector/radar style |
| `neon` | Green phosphor CRT | Vector/radar style |
| `cyan` | Ops centre blue | Vector/radar style |
| `crt` | Amber split-flap | Vector/radar style |

---

## History database

- SQLite at `~/.localflight/history.db`
- 90-day retention, auto-pruned on each write
- Schema: `flights` table — callsign, route, status, gate, position, times, delay, airline
- **Browse tab**: filterable table with detail panel, queryable by direction and time window
- **Stats tab**: top airlines, destinations, origins, aircraft types, on-time percentage, average delay
- Written after every successful scheduler fetch — non-fatal if write fails
- Schema migrations run automatically — adding new columns to an existing DB is safe

---

## API call budgets

AviationStack free tier is 100 calls/month. The client enforces a configurable monthly budget:
- Default limit: 90 calls (10-call safety margin)
- Each scheduler cycle costs 2 calls (departures + arrivals)
- Budget tracked in `~/.localflight/api_usage.json`, resets monthly
- Override: `LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=N` in `.env`
- Recommended refresh interval for real source: 8–12 hours

ADS-B Exchange free tier is 1 000 calls/day — well within limits at any refresh interval.
OpenSky registered tier is 1 000 calls/day — same.

---

## Log management

- Per-session log files in `~/.localflight/logs/`
- Max 10 files, 30-day retention, 1 MB per file before rotation
- Live log viewer at `/logs` with 5-second auto-refresh and log-level colour coding

---

## Hardware targets

| Device | Role | Status |
|---|---|---|
| Windows PC | Dev machine, primary display | ✅ Running |
| macOS | Dev machine / secondary display | ✅ Running |
| Raspberry Pi 5 | Production server, always-on | 🔜 Installer ready, awaiting hardware |
| Pimoroni Interstate 75 W (RP2350) | LED matrix display (up to 384×64) | 🔜 Client written, awaiting hardware |
| RTL-SDR USB dongle | ADS-B receiver for Pi | 🔜 Client written, awaiting hardware |
| 7–10" HDMI screen | Secondary display on Pi | 🔜 Chromium kiosk via `hdmi` output mode |

### LED matrix (Interstate 75 W)
- Connects to home WiFi independently — no Pi GPIO needed
- Polls `/api/fids` every 60 seconds
- Classic split-flap animation — letters cycle before settling
- Button A = departures, Button B = arrivals, A+B = force refresh
- RGB LED: green = ok, blue = fetching, amber = no data, red = no WiFi
- Calls `/api/admin/ping?device=matrix` on boot and every 10 minutes
- Flash `sources/matrix/client.py` with Pimoroni MicroPython firmware
- Supports panel sizes from 64×32 up to 384×64

### ADS-B receiver (Pi + RTL-SDR)
```bash
sudo apt install dump1090-fa
sudo systemctl enable dump1090-fa
sudo systemctl start dump1090-fa
```
Swap enrichment in `jobs.py` from `enrich_flights_with_adsbexchange` to `enrich_flights_with_adsb`.
Both functions have identical signatures — drop-in replacement.

---

## WebSocket live push

- `display.html` holds one WebSocket connection to `/ws` and forwards messages via `postMessage` to the embedded FIDS and Radar iframes
- Embedded pages listen for `postMessage` — no redundant WS connections per iframe
- Scheduler broadcasts `{"type": "snapshot_updated"}` after each successful fetch
- Clients reconnect automatically with exponential backoff (max 30 s)

---

## Platform model

| Platform | Browser | Tray | Scheduler |
|---|---|---|---|
| Windows | Edge/Chrome app window | pystray | ✅ |
| macOS | Chrome/Safari app window | rumps / pystray | ✅ |
| Raspberry Pi / Linux | External Chromium kiosk service | Stub (no-op) | ✅ |

`platform/detect.py` detects the current platform once at startup. `__main__.py` dispatches to `_run_desktop()` (Windows/macOS) or `_run_headless()` (Pi/Linux) accordingly.

---

## Issue tracking

Issues are tracked on **Linear**: [linear.app/local-flight](https://linear.app/local-flight)

The app integrates directly with Linear — scheduler errors are automatically filed as issues (deduplicated per 6 hours), and a manual **Create Issue** form is available in the Admin hub (`/admin` → Linear Issues card). Configure via `.env`:

```
LINEAR_API_KEY=lin_api_...
LINEAR_TEAM_ID=your_team_uuid
```

---

## Philosophy

- Local first — no cloud dependency after initial setup
- Boring by design — standard Python, no framework magic
- Clear data flow — every step is a separate module
- Pi-ready — nothing in the stack requires a GPU or 16 GB RAM
- Graceful degradation — if an enrichment source fails, the next one kicks in
- Budget conscious — AviationStack monthly call counter enforced in code
