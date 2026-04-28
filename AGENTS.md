# Local Flight â€” Codex Context

## What this project is

A local-first, self-hosted **Flight Information Display System (FIDS)** that runs on Windows, macOS, and Raspberry Pi. Fetches real and simulated flight data, displays it as a proper airport-style departure/arrival board â€” in a browser kiosk window, on an LED matrix panel, or on a dedicated HDMI screen.

Built with: Python 3.11+, FastAPI, uvicorn, SQLite, WebSocket, Jinja2, PIL. Mobile companion uses React Native / Expo. pystray on macOS only (Windows uses a ctypes taskbar window).

**Repo:** https://github.com/tr3y4rch/local-flight  
**Issues:** https://github.com/tr3y4rch/local-flight/issues

---

## Project structure

```
local-flight/
â”œâ”€â”€ build.py                     # PyInstaller build script â€” icons, signing, zip
â”œâ”€â”€ LocalFlight.spec             # PyInstaller spec â€” datas, hiddenimports, BUNDLE
â”œâ”€â”€ LICENSE                      # MIT â€” Philipp Schumacher 2025
â”œâ”€â”€ CHANGELOG.md
â”œâ”€â”€ .gitattributes               # LF for sh/command, CRLF for bat/ps1
â”œâ”€â”€ src/localflight/
â”‚   â”œâ”€â”€ __main__.py              # Entry point â€” platform-aware startup; installs sys/threading crash hooks
â”‚   â”œâ”€â”€ platform/                # Cross-platform abstraction layer
â”‚   â”‚   â”œâ”€â”€ detect.py            # Platform detection (Windows/macOS/Pi/Linux)
â”‚   â”‚   â”œâ”€â”€ browser.py           # Cross-platform kiosk browser launcher
â”‚   â”‚   â””â”€â”€ tray.py              # Windows: ctypes taskbar window; macOS: pystray; Pi: stub
â”‚   â”œâ”€â”€ core/
â”‚   â”‚   â”œâ”€â”€ airports.py          # Airport DB lookup (IATA/ICAO)
â”‚   â”‚   â”œâ”€â”€ config.py
â”‚   â”‚   â””â”€â”€ models.py            # Flight, FlightPosition, FlightDirection, etc.
â”‚   â”œâ”€â”€ decode/
â”‚   â”‚   â”œâ”€â”€ dedupe.py            # Codeshare deduplication
â”‚   â”‚   â”œâ”€â”€ normalize.py         # Raw records â†’ Flight objects
â”‚   â”‚   â”œâ”€â”€ opensky.py           # OpenSky enrichment
â”‚   â”‚   â””â”€â”€ mappings/
â”‚   â”‚       â””â”€â”€ aviationstack.py
â”‚   â”œâ”€â”€ display/
â”‚   â”‚   â””â”€â”€ fids_from_flights.py # PAX-friendly flight number formatting
â”‚   â”œâ”€â”€ render/
â”‚   â”‚   â””â”€â”€ fids.py              # Build Jinja2 template context
â”‚   â”œâ”€â”€ scheduler/
â”‚   â”‚   â”œâ”€â”€ jobs.py              # Main fetch job â€” AviationStack + enrichment chain
â”‚   â”‚   â”œâ”€â”€ runtime.py           # run_loop(); stop_event-aware sleeps + crash reporting
â”‚   â”‚   â”œâ”€â”€ control.py           # In-process scheduler start/status/restart controller
â”‚   â”‚   â””â”€â”€ run_scheduler.py
â”‚   â”œâ”€â”€ sources/
â”‚   â”‚   â”œâ”€â”€ web/
â”‚   â”‚   â”‚   â”œâ”€â”€ aviationstack_client.py  # BYOK + community relay budget guard; activation token; lazy env reads
â”‚   â”‚   â”‚   â”œâ”€â”€ aviationstack_mock.py
â”‚   â”‚   â”‚   â”œâ”€â”€ adsbexchange_client.py   # RapidAPI + relay radar proxy; primary position enrichment
â”‚   â”‚   â”‚   â”œâ”€â”€ opensky_radar.py         # fetch_radar_blips(), bounding_box()
â”‚   â”‚   â”‚   â”œâ”€â”€ vatsim_client.py         # VATSIM v3, aircraft type extraction
â”‚   â”‚   â”‚   â”œâ”€â”€ metar_client.py          # aviationweather.gov, 30min cache
â”‚   â”‚   â”‚   â”œâ”€â”€ linear_client.py         # Linear GraphQL API â€” file_error() (operator auto-filing)
â”‚   â”‚   â”‚   â”œâ”€â”€ private_keys.py          # Dev-only community key lookup (dev/private/community_keys.json, gitignored)
â”‚   â”‚   â”‚   â””â”€â”€ bug_reporter.py          # Hardcoded developer reporter â€” powers /feedback
â”‚   â”‚   â”œâ”€â”€ adsb/
â”‚   â”‚   â”‚   â””â”€â”€ adsb_client.py           # dump1090 client (RTL-SDR, Pi)
â”‚   â”‚   â””â”€â”€ matrix/
â”‚   â”‚       â””â”€â”€ client.py                # MicroPython for Interstate 75 W
â”‚   â”œâ”€â”€ storage/
â”‚   â”‚   â”œâ”€â”€ config.py            # AppConfig dataclass, load/save
â”‚   â”‚   â”œâ”€â”€ flights_store.py     # JSON snapshot storage under ~/.localflight, legacy fallback
â”‚   â”‚   â”œâ”€â”€ history.py           # SQLite history DB, 90-day retention
â”‚   â”‚   â”œâ”€â”€ install.py           # Machine fingerprint + activation token (get/set_activation_token)
â”‚   â”‚   â”œâ”€â”€ logging_setup.py     # RotatingFileHandler, pruning
â”‚   â”‚   â”œâ”€â”€ profiles.py          # Airport profiles
â”‚   â”‚   â”œâ”€â”€ request_log.py       # Anonymized traffic log (SQLite) â€” client_type/client_id/platform
â”‚   â”‚   â”œâ”€â”€ samples/             # Sample AviationStack payloads (mock source)
â”‚   â”‚   â””â”€â”€ state.py             # AppState (last fetch, errors, latency)
â”‚   â””â”€â”€ ui/
â”‚       â”œâ”€â”€ server.py            # FastAPI app, WebSocket, setup gate middleware
â”‚       â”œâ”€â”€ api.py               # All JSON API endpoints
â”‚       â”œâ”€â”€ events.py            # Non-fatal WebSocket notifications: snapshot/config/scheduler
â”‚       â”œâ”€â”€ static/
â”‚       â”‚   â”œâ”€â”€ app.css
â”‚       â”‚   â”œâ”€â”€ skins.css        # 5 skins: standard/technical/neon/cyan/crt
â”‚       â”‚   â””â”€â”€ splash_mark.svg  # Versioned launch splash mark
â”‚       â””â”€â”€ templates/
â”‚           â”œâ”€â”€ _nav.html        # Shared nav macro â€” version badge, quit modal
â”‚           â”œâ”€â”€ base.html        # Base layout, clock, nav CSS
â”‚           â”œâ”€â”€ fids.html        # FIDS board â€” error banner, detail drawer, WebSocket
â”‚           â”œâ”€â”€ radar.html       # Radar canvas + sweep + METAR
â”‚           â”œâ”€â”€ display.html     # Split-view FIDS+Radar, draggable divider
â”‚           â”œâ”€â”€ matrix_preview.html  # LED simulator + split-flap animation
â”‚           â”œâ”€â”€ settings.html    # Airport picker, skins, re-run setup button
â”‚           â”œâ”€â”€ admin.html       # Admin hub â€” scheduler/budget/updates/system
â”‚           â”œâ”€â”€ feedback.html    # Bug reporter form â€” title, description, auto-attached system info
â”‚           â”œâ”€â”€ history.html     # History browser â€” filterable table + detail panel
â”‚           â”œâ”€â”€ setup.html       # First-run setup wizard (strict gate)
â”‚           â”œâ”€â”€ splash.html      # Short versioned launch splash -> setup/display
â”‚           â”œâ”€â”€ logs.html        # Live log viewer
â”‚           â”œâ”€â”€ icons_pictogram.html  # Aircraft SVG icons (standard skin)
â”‚           â””â”€â”€ icons_technical.html  # Vector icons (neon/cyan/crt skins)
â”‚
â”œâ”€â”€ mobile/
â”‚   â”œâ”€â”€ App.tsx                  # Expo companion shell: FIDS/Radar/History/Settings
â”‚   â”œâ”€â”€ app.json                 # Expo app metadata, splash config, iOS local-network plist
â”‚   â”œâ”€â”€ assets/
â”‚   â”‚   â””â”€â”€ icon_circle.png      # Companion icon + splash image
â”‚   â””â”€â”€ src/
â”‚       â”œâ”€â”€ api/                 # LAN API client + response types
â”‚       â”œâ”€â”€ crash/               # CrashBoundary + mobile crash reporter
â”‚       â”œâ”€â”€ device/identity.ts   # Companion identity: companionId, platform, deviceType, appVersion
â”‚       â”œâ”€â”€ storage/             # SecureStore URL, companionId, pinned flight, profiles
â”‚       â””â”€â”€ theme/               # Mobile visual tokens
â”‚
â”œâ”€â”€ installers/
â”‚   â”œâ”€â”€ windows/
â”‚   â”‚   â”œâ”€â”€ install.ps1          # Windows source checkout installer
â”‚   â”‚   â””â”€â”€ LocalFlight.bat      # Windows source checkout launcher
â”‚   â”œâ”€â”€ macos/
â”‚   â”‚   â”œâ”€â”€ install.sh
â”‚   â”‚   â”œâ”€â”€ LocalFlight.command  # Double-clickable launcher
â”‚   â”‚   â””â”€â”€ start.sh
â”‚   â””â”€â”€ pi/
â”‚       â”œâ”€â”€ install.sh           # Full Pi setup â€” venv, systemd, mDNS
â”‚       â”œâ”€â”€ localflight.service  # Python app systemd service
â”‚       â”œâ”€â”€ localflight-kiosk.service  # Chromium kiosk systemd service
â”‚       â””â”€â”€ lf.sh                # Management helper (start/stop/logs/update)
â”‚
â””â”€â”€ start.bat                    # Dev launcher (Windows, project root)
```

---

## Architecture decisions

### Platform model
- `platform/detect.py` â€” `detect()` returns `Platform` enum, cached. `is_desktop()` / `is_headless()` helpers.
- Desktop (Windows/macOS): kiosk browser window + system tray + full GUI
- Headless (Pi/Linux): uvicorn + scheduler only, no window management. Chromium kiosk is a separate systemd service.
- `__main__.py` dispatches to `_run_desktop()` or `_run_headless()` based on platform.
- Desktop launch and Pi kiosk first hit `/splash?next=/display`; first-run desktop uses `/splash?next=/setup`.

### Data enrichment chain (source=real)
```
AviationStack (schedule: times, gates, status) [90 calls/month budget guard]
    â†“
ADS-B Exchange via RapidAPI (primary: position + aircraft type + registration)
    â†“ fallback
OpenSky Network (position fallback)
    â†“ fallback
Schedule data only
    â†“
Dedupe codeshares â†’ save JSON snapshot â†’ write SQLite history â†’ WebSocket broadcast
    â†“ on error
Linear issue filed (deduplicated per 6h via ~/.localflight/linear_dedup.json)
```

### WebSocket live push
- `ConnectionManager` in `server.py` tracks connections, drains async queue
- `ui/events.py` is the shared non-fatal publisher for `snapshot_updated`, `config_updated`, and `scheduler_restarted`
- Scheduler calls `_broadcast_update()` after each snapshot; settings/API/profile/setup saves call `notify_config_updated()`
- Scheduler-relevant config changes (`airport_iata`, `airport_icao`, `refresh_seconds`, `source`) queue `restart_scheduler_and_notify()` so the new interval takes effect immediately
- `display.html` holds one WS connection, reloads on `config_updated`, and forwards other messages via `postMessage` to iframes
- FIDS/Radar/Admin/mobile refresh on push events and still keep lightweight fallback polling
- Clients reconnect with exponential backoff

### Setup gate
- `SetupGateMiddleware` in `server.py` redirects all routes to `/setup` until `~/.localflight/setup_complete` exists
- Exempt paths: `/setup`, `/api/setup/*`, `/api/airports/search`, `/static`, `/health`, `/ws`
- On first launch, scheduler is deferred. Setup watcher thread polls for `setup_complete` and auto-starts scheduler when detected.
- `/api/setup/reset` deletes the marker â€” triggers re-run wizard. Button in Settings footer.

### API call budget
- AviationStack BYOK default: 90 calls/month, tracked in `~/.localflight/api_usage.json`
- Community relay default: 50 calls/month per install
- ADS-B Exchange / RapidAPI default: 10,000 calls/month
- Enforced in `aviationstack_client.py` via `_check_and_increment_budget()` before each request
- All env vars read lazily at call time (not module import time) to avoid race with `_load_dotenv()`

### Linear issue tracker
Two separate integrations â€” do not confuse them:
- **Operator auto-filing** (`sources/web/linear_client.py`): `file_error()` called from `scheduler/runtime.py` on every cycle error. Uses `LINEAR_API_KEY` / `LINEAR_TEAM_ID` env vars pointing at the operator's own Linear workspace. Optional, completely silent, deduplicates per 6h.
- **User bug reporter** (`sources/web/bug_reporter.py`): hardcoded developer credentials for a dedicated "Local Flight Reports" workspace. Powers `/feedback`, `POST /api/feedback`, and `POST /api/feedback/crash`; accepts optional mobile `client_context`. Always-on, no user config required. Worst case if credentials are compromised: spam to an isolated inbox, easy to rotate.

### Version
- Single source of truth: `version` field in `pyproject.toml`
- Read at runtime via `importlib.metadata.version("localflight")` with `"0.2.3b2"` fallback
- Injected as `app_version` Jinja2 global in `server.py` â†’ available in all templates
- Shown in nav bar (`v0.2.3b2`) and Admin â†’ System card
- `LocalFlight.spec` reads it from `pyproject.toml` at build time for macOS `CFBundleShortVersionString`

### Auto-update check
- `GET /api/admin/updates` checks GitHub releases API for `tr3y4rch/local-flight`
- 1-hour in-process cache to avoid hammering GitHub
- Admin â†’ System card shows "Up to date" (green) or "vX.Y.Z available â†—" (amber link)

---

### Mobile companion
- Mobile beta lives in `mobile/` as an iOS-first React Native / Expo app.
- The Python/FastAPI desktop/Pi app remains the server of record; mobile is a LAN client.
- Mobile stores the Local Flight server URL with Expo SecureStore and expects a reachable LAN URL, not phone-local `localhost`.
- Mobile reads `/api/health`, `/api/config`, `/api/admin/system`, `/api/admin/budget`, `/api/admin/connections`, `/api/admin/updates`, `/api/fids`, `/api/radar`, `/api/history`, `/api/metar`, and `/api/fids/detail`.
- Mobile listens to `/ws` for `snapshot_updated`, `config_updated`, and `scheduler_restarted`; it refreshes on push and uses the server update interval as a capped fallback poll.
- Main bottom nav intentionally contains only FIDS, RADAR, HISTORY, and SETTINGS. Matrix preview and Admin are launched from Settings.
- Current shell follows the iOS airport-board mockup: Flight Island, departure-airport/live header, UTC/local clock, METAR strip, FIDS tabs, pinned flight, compact rows, and bottom nav.
- Mobile Settings can edit airport/source/update interval via `PATCH /api/config`, save local airport profiles, restart the scheduler, open Matrix/Admin, submit feedback, and open Buy Me a Coffee.
- Mobile now ships with a longer branded launch overlay that mirrors the desktop splash direction with progress/status messaging.
- Mobile crash reporting lives in `mobile/src/crash/`; `CrashBoundary` and the global reporter send `/api/feedback/crash` with mobile reporter context.
- Admin mutating controls are still intentionally limited until QR pairing and per-device tokens exist; scheduler restart/config changes are the current trusted-LAN exception.
- Current Windows workspace has no Node/npm; run `npm install`, `npx expo install --fix`, and iOS device checks on the Mac/Xcode machine unless Node is installed on the dev PC.

## Environment variables (.env)

```
# Community relay / activation
LOCALFLIGHT_ACTIVATION_TOKEN=
LOCALFLIGHT_RELAY_URL=https://relay.localflight.app/v1/flights

# BYOK AviationStack (leave blank to use community relay)
AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90
LOCALFLIGHT_RELAY_MONTHLY_LIMIT=50

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=

RAPIDAPI_KEY=
LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=10000
```

Relay server env vars (relay/.env): `RELAY_ADMIN_PASSWORD`, `DB_PATH`, `RELAY_PUBLIC_HOST`, `RELAY_ADMIN_HOST`, `RELAY_COMMUNITY_SCHEDULE_LIMIT`, `RELAY_RADAR_MONTHLY_LIMIT`, `RELAY_MANAGED_SCHEDULE_LIMIT`, `RELAY_MANAGED_RADAR_LIMIT`, `RELAY_RADAR_CACHE_SECONDS`

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
| `GET /api/config` | Current server config |
| `PATCH /api/config` | Update config fields; broadcasts `config_updated`; restarts scheduler for airport/source/interval changes |
| `GET /api/fids` | JSON FIDS rows |
| `GET /api/fids/detail` | Per-callsign detail â€” live position + 7-day history |
| `GET /api/radar` | Aircraft positions |
| `GET /api/metar` | Decoded + raw METAR |
| `GET /api/history` | Recent flights from SQLite |
| `GET /api/history/flight` | Callsign history |
| `GET /api/history/stats` | DB size, row count |
| `GET /api/admin/system` | Uptime, memory, CPU, version |
| `GET /api/admin/budget` | API call budgets |
| `GET /api/admin/requests` | Anonymized local traffic log summary |
| `GET /api/admin/connections` | WS count + device pings |
| `GET /api/admin/updates` | GitHub release update check (1h cache) |
| `GET /api/admin/scheduler` | Scheduler thread status |
| `POST /api/admin/scheduler/restart` | Stop sleeping scheduler loop, reload config/env, start fresh cycle, broadcast `scheduler_restarted` |
| `POST /api/feedback` | Submit bug report `{title, description, client_context}` â€” routes to developer's Linear |
| `POST /api/feedback/crash` | Auto-file mobile/server crash report with deduplication |
| `POST /api/admin/ping` | Device ping (matrix client) |
| `POST /api/setup/complete` | Save setup, write .env, mark complete |
| `POST /api/setup/reset` | Delete setup_complete marker â†’ re-run wizard |
| `POST /api/setup/test-aviationstack` | Test AviationStack key (body) without saving |
| `POST /api/setup/test-rapidapi` | Test RapidAPI key (body) without saving |
| `GET /api/setup/client-info` | Machine fingerprint, relay URL, token presence, managed status |
| `POST /api/setup/activate` | Store managed activation token |
| `POST /api/setup/client-status` | Check relay client status |
| `POST /api/setup/request-activation` | Request activation from relay |
| `POST /api/setup/request-activation/status` | Poll activation request status |
| `POST /api/setup/test-activation` | Test an activation token without saving |
| `POST /api/admin/companion/checkin` | Mobile companion check-in (companionId, platform, appVersion) |
| `POST /api/quit` | Graceful shutdown (terminates browser proc + os._exit) |
| `WS /ws` | WebSocket push endpoint |

---

## Building (PyInstaller)

```bash
python build.py           # generate icons + build + zip
python build.py --clean   # wipe dist/ and build/ first
```

Output:
- **Windows:** `dist/LocalFlight-windows.zip` + `.sha256` â€” unzip, double-click `LocalFlight.exe`
- **macOS:** `dist/LocalFlight.app` plus `dist/LocalFlight-macos.zip` + `.sha256` â€” upload the zip; users unzip, then drag `LocalFlight.app` to Applications

Optional code signing via env vars:
- Windows: `SIGNTOOL_CERT` (path to .pfx) + `SIGNTOOL_PASS`
- macOS: `CODESIGN_IDENTITY` (Developer ID string) + `NOTARIZE_PROFILE` (notarytool keychain profile)

Without signing: Windows shows SmartScreen "Unknown publisher"; macOS requires right-click â†’ Open on first launch.

Release build notes:
- Build Windows artifacts on Windows: `python build.py --clean` â†’ attach `LocalFlight-windows.zip` and `LocalFlight-windows.zip.sha256`.
- Build macOS artifacts on macOS: `python build.py --clean` â†’ attach `LocalFlight-macos.zip` and `LocalFlight-macos.zip.sha256`.
- `installers/windows/install.ps1` and `installers/macos/install.sh` are source-checkout installers; release users should prefer the PyInstaller zip artifacts.

---

## Hardware targets

| Device | Role | Status |
|---|---|---|
| Windows PC | Dev machine | âœ… Running |
| Raspberry Pi 5 | Production server | ðŸ”œ Installer ready, awaiting hardware |
| Pimoroni Interstate 75 W (RP2350) | LED matrix 256Ã—64 | ðŸ”œ MicroPython client written |
| RTL-SDR USB dongle | ADS-B receiver for Pi | ðŸ”œ dump1090 client written |

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
Swap `enrich_flights_with_adsbexchange` â†’ `enrich_flights_with_adsb` in `jobs.py`

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

# Mobile companion (Mac/Xcode machine)
cd mobile
npm install
npx expo install --fix
npm run ios
```

---

## Current handoff for the dev machine

- Active version is `0.2.3b2`: `pyproject.toml`, runtime fallbacks, mobile package metadata, Expo `extra.localFlightVersion`, and docs should all agree.
- Public community relay default is `https://relay.localflight.app/v1/flights`.
- Operator admin host is `https://network.localflight.app`.
- Fly deployment now expects one warm machine in `fra`, one SQLite volume, and host-based public/admin gating in `relay/main.py`.
- `mobile/node_modules` is still absent on this Windows workspace, so Expo/TypeScript validation belongs on the Mac/Xcode side after `npm install`.
- Desktop resume on Windows: run `.\start.bat`, confirm Community setup preloads the hosted relay URL, then verify FIDS/radar/admin against the live relay contract.
- Release resume: run `python build.py --clean` separately on Windows and macOS. Upload `dist/LocalFlight-windows.zip`, `dist/LocalFlight-windows.zip.sha256`, `dist/LocalFlight-macos.zip`, and `dist/LocalFlight-macos.zip.sha256` to GitHub release `v0.2.3b2`.
- Mobile resume on Mac/Xcode: from `mobile/`, run `npm install`, `npx expo install --fix`, `npm run doctor`, then `npm run ios`. Expo Go may reject SDK 55 depending on installed Expo Go; simulator/dev build is the safer path.
- Verification to rerun after the version bump: `python -m pip install -e .`, `python -m compileall -q src relay`, `pytest tests`, plus installer shell syntax checks.

## What was done in the latest session (v0.2.3b2)

- ✅ Hosted relay defaults centralized in `relay_defaults.py` and wired through the desktop clients, setup flow, and installers.
- ✅ `relay/main.py` hardened for Fly.io: port `8080`, FastAPI lifespan startup, `/health`, host-based public/admin gating, and reduced relay-side metadata writes.
- ✅ `relay/fly.toml` and `.github/workflows/fly-deploy.yml` updated for explicit `relay/` deployment, one warm `fra` machine, and the `relay.localflight.app` / `network.localflight.app` split.
- ✅ Privacy and handoff docs rewritten for the hosted relay model and install-scoped identifiers.
- âœ… `private_keys.py` â€” dev-only community key lookup from `dev/private/community_keys.json` (gitignored)
- âœ… `install.py` â€” `get_activation_token()` / `set_activation_token()` for managed install tokens
- âœ… `aviationstack_client.py` â€” explicit BYOK vs relay split; 30-day rolling community window; activation token forwarding; BYOK default 90/month; community cap 50/month
- âœ… `adsbexchange_client.py` â€” relay radar proxy path
- âœ… `request_log.py` â€” `client_type`, `client_id`, `platform` columns + schema migration; companion tracking
- âœ… `api.py` â€” `POST /api/admin/companion/checkin` endpoint with `CompanionCheckinIn`
- âœ… `server.py` â€” 6 new relay setup endpoints: client-info, activate, client-status, request-activation, request-activation/status, test-activation
- âœ… `relay/main.py` â€” full network admin console: provider key storage, token lifecycle/revocation, install access control, API counters, traffic stats, anonymous activation tags
- âœ… `setup.html` â€” three explicit paths (community / BYOK / VATSIM); managed activation flow; machine identity shown
- âœ… `admin.html` â€” community vs BYOK budget mode separated
- âœ… `settings.html` â€” read-only client link card (fingerprint, relay URL, token presence)
- âœ… `mobile/src/device/identity.ts` â€” companion identity (UUID, platform, deviceType, appVersion)
- âœ… `mobile/src/storage/settings.ts` â€” companionId persisted in Expo SecureStore
- âœ… `tests/test_relay_admin.py` â€” relay admin regression tests
- âœ… Version bumped to `0.2.3b2`; CHANGELOG, CLAUDE.md, AGENTS.md updated

## What was done in the macOS app session

- âœ… macOS `.app` bundle â€” `install.sh` now builds `~/Applications/LocalFlight.app` instead of a `.command` symlink; `scripts/make_app_bundle.py` handles SVGâ†’icns (cairosvg â†’ pre-rendered PNG â†’ PIL fallback) + `Info.plist` + compiled Mach-O stub + baked shell launcher
- âœ… Mach-O stub â€” macOS Launch Services silently rejects shell scripts as `CFBundleExecutable`; stub is a tiny C program compiled with `cc` at install time that exec's `/bin/bash launcher.sh` in the same `MacOS/` directory
- âœ… `assets/icon_circle.png` â€” 1024Ã—1024 pre-rendered from SVG and committed; `.gitignore` updated with `!assets/icon_circle.png` exception so the pre-render survives without `cairosvg`
- âœ… `LocalFlight.command` â€” fixed symlink `$0` resolution bug: when launched via Finder the symlink path was used as `$0`, causing `ROOT` to resolve to `~/..` instead of the project root; fixed with `readlink`
- âœ… `installers/macos/install.sh` â€” replaced `.command` symlink step with `make_app_bundle.py` call; `.command` file stays as shell-only fallback

## What was done in previous sessions

- âœ… `start.bat` â€” fixed UTF-8 box-drawing chars in `::` comments causing cmd.exe byte-eating bug on `chcp 65001`; replaced all 7 comment lines with ASCII; added error pause
- âœ… `linear_client.py` â€” added `test_connection()` with real GraphQL `viewer` query to validate key (not just env var presence); returns specific 401 message
- âœ… `bug_reporter.py` â€” new hardcoded developer reporter (`sources/web/bug_reporter.py`); dedicated "Local Flight Reports" Linear workspace; `_system_context()` auto-attaches version/platform/airport
- âœ… `feedback.html` â€” new `/feedback` page with title+description form, system info preview, success/error state
- âœ… `/api/feedback` endpoint â€” `POST`, `FeedbackIn` Pydantic model, calls `bug_reporter.submit_report()`
- âœ… `/feedback` route in `server.py`
- âœ… ðŸ› Report nav item added to `_nav.html` management group
- âœ… Admin hub Linear Issues card **removed** â€” replaced by dedicated `/feedback` page (no duplicate reporting)
- âœ… README rewritten from end-user perspective â€” install-first flow, removed dev-cycle / awaiting-hardware language
- âœ… File consistency sweep â€” LINEAR vars removed from all 3 installer `.env` templates; `pyproject.toml` Issues URL â†’ GitHub; `CHANGELOG.md` updated; `AGENTS.md` updated
- âœ… Setup wizard â€” added ADS-B Exchange test endpoint + "Test connection" button for panel 3; POST body is now the preferred path and GET remains only as compatibility fallback
- âœ… Setup wizard â€” fixed RapidAPI signup URL (`adsbexchange` â†’ `adsbx` provider slug in RapidAPI path); fixed OpenSky registration URL (old Joomla path â†’ `/login?view=registration`)
- âœ… Admin hub â€” added Buy Me a Coffee strip at bottom (`buymeacoffee.com/localflight`); subtle ghost opacity, not a card
- âœ… Runtime snapshots â€” moved canonical JSON storage to `~/.localflight/storage/data/<IATA>/snapshots`; legacy source-tree snapshots remain readable
- âœ… Scheduler/runtime â€” pruning now runs inside snapshot jobs; failed cycles preserve the previous `last_success_utc`
- âœ… Installer/docs sweep â€” Windows/macOS/Pi source installers clarified; Pi helper path fixed; `.env.example` no longer includes operator Linear vars
- âœ… Desktop beta release prep â€” `psutil`/`packaging` required; Windows build writes a SHA256 checksum

- âœ… Mobile Phase 1 â€” created `mobile/` React Native / Expo scaffold with SecureStore settings, API client, WebSocket listener, responsive layout helpers, and iOS-first shell
- âœ… Mobile visual pass â€” base app followed the supplied airport-board mockup with status bar/dynamic-island-style treatment, airport/METAR header, FIDS tabs, pinned flight card, compact rows, admin/settings screens, and bottom nav
- âœ… Version bump â€” project moved to `0.2.2b1`; mobile npm metadata used `0.2.2-b1`; Expo metadata carried `extra.localFlightVersion = "0.2.2b1"`

## Pending / next up

- [ ] Create GitHub release `v0.2.3b2` and attach Windows/macOS artifacts plus both `.sha256` files.
- [ ] Deploy the Fly relay, set production secrets, and wire `relay.localflight.app` plus `network.localflight.app`.
- [ ] Run hosted relay smoke tests: `/health`, public `/v1/*`, admin `/admin`, and one end-to-end community client activation.
- [ ] Mobile â€” `npm install` + `npx expo install --fix` on Mac; test in iOS simulator/dev build
- [ ] Validate the companion on the Mac/Xcode side after installing `mobile/` dependencies (`npm install`, `npm run doctor`, `npm run ios`)
- [ ] Notification system (Pushover/Telegram) â€” ~50 lines, hooks into scheduler after `_broadcast_update()`
- [ ] Pi hardware arrives â€” test systemd services + kiosk
- [ ] RTL-SDR dongle â€” test dump1090 integration
- [ ] Interstate 75 W â€” flash client.py, test WiFi polling
- [ ] Code signing certificates â€” Developer ID (macOS) + EV cert (Windows SmartScreen)
- [ ] Mobile v2 â€” QR pairing + per-device tokens before exposing admin mutating controls

---

## Code style / conventions

- Python 3.11+, type hints throughout, `from __future__ import annotations`
- FastAPI for the web layer, Jinja2 for templates
- No module-level env var reads â€” always read lazily inside functions
- Non-fatal pattern: wrap risky operations in try/except, log warning, continue
- History writes, enrichment failures, WS broadcasts, Linear calls are all non-fatal
- `os._exit(0)` for hard shutdown (bypasses uvicorn's signal handling)
- Jinja2 templates use `{% from "_nav.html" import topnav %}` for consistent nav
- Nav active state passed as `active="pagename"` string parameter
- `app_version` available in all templates as a Jinja2 global (injected in `server.py`)
