# Local Flight — Codex Context

## What this project is

A local-first, self-hosted **Flight Information Display System (FIDS)** that runs on Windows, macOS, and Raspberry Pi. Fetches real and simulated flight data, displays it as a proper airport-style departure/arrival board — in a browser kiosk window, on an LED matrix panel, or on a dedicated HDMI screen.

Built with: Python 3.11+, FastAPI, uvicorn, SQLite, WebSocket, Jinja2, PIL. Mobile companion uses React Native / Expo. pystray on macOS only (Windows uses a ctypes taskbar window).

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
│   │   ├── runtime.py           # run_loop(); stop_event-aware sleeps + crash reporting
│   │   ├── control.py           # In-process scheduler start/status/restart controller
│   │   └── run_scheduler.py
│   ├── sources/
│   │   ├── web/
│   │   │   ├── aviationstack_client.py  # BYOK + community relay budget guard; activation token; lazy env reads
│   │   │   ├── aviationstack_mock.py
│   │   │   ├── adsbexchange_client.py   # RapidAPI + relay radar proxy; primary position enrichment
│   │   │   ├── opensky_radar.py         # fetch_radar_blips(), bounding_box()
│   │   │   ├── vatsim_client.py         # VATSIM v3, aircraft type extraction
│   │   │   ├── metar_client.py          # aviationweather.gov, 30min cache
│   │   │   ├── linear_client.py         # Linear GraphQL API — file_error() (operator auto-filing)
│   │   │   ├── private_keys.py          # Dev-only community key lookup (dev/private/community_keys.json, gitignored)
│   │   │   ├── relay_defaults.py        # Hosted relay URL + admin host constants
│   │   │   ├── aviationstack_files.py   # Local file loading (canonical + legacy paths)
│   │   │   └── bug_reporter.py          # Sanitized report forwarder — powers /feedback + crash reports via relay
│   │   ├── adsb/
│   │   │   └── adsb_client.py           # dump1090 client (RTL-SDR, Pi)
│   │   └── matrix/
│   │       └── client.py                # MicroPython for Interstate 75 W
│   ├── storage/
│   │   ├── config.py            # AppConfig dataclass, load/save
│   │   ├── flights_store.py     # JSON snapshot storage under ~/.localflight, legacy fallback
│   │   ├── history.py           # SQLite history DB, 90-day retention
│   │   ├── install.py           # Machine fingerprint + activation token (get/set_activation_token)
│   │   ├── logging_setup.py     # RotatingFileHandler, pruning
│   │   ├── profiles.py          # Airport profiles
│   │   ├── request_log.py       # Anonymized traffic log (SQLite) — client_type/client_id/platform
│   │   ├── samples/             # Sample AviationStack payloads (mock source)
│   │   └── state.py             # AppState (last fetch, errors, latency)
│   └── ui/
│       ├── server.py            # FastAPI app, WebSocket, setup gate middleware
│       ├── api.py               # All JSON API endpoints
│       ├── events.py            # Non-fatal WebSocket publisher: snapshot/config/scheduler events
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
│           ├── requests.html    # Anonymized local traffic log viewer
│           ├── icons_pictogram.html  # Aircraft SVG icons (standard skin)
│           └── icons_technical.html  # Vector icons (neon/cyan/crt skins)
│
├── mobile/
│   ├── App.tsx                  # Expo companion shell: FIDS/Radar/History/Settings
│   ├── app.json                 # Expo app metadata, splash config, iOS local-network plist
│   ├── assets/
│   │   └── icon_circle.png      # Companion icon + splash image
│   └── src/
│       ├── api/                 # LAN API client + response types
│       ├── app/AppShell.tsx     # Companion coordinator: state, refresh, shell chrome, style factory
│       ├── components/          # Shared chrome/components such as bottom nav and launch overlay
│       ├── crash/               # CrashBoundary + mobile crash reporter
│       ├── device/identity.ts   # Companion identity: companionId, platform, deviceType, appVersion
│       ├── domain/              # Pure mobile helpers/constants for flights, radar, matrix, formatting
│       ├── hooks/               # Launch/bootstrap, flight detail, matrix draft/save/reset hooks
│       ├── screens/             # FIDS/Radar/History/Matrix/Admin/Settings screens and sheets
│       ├── storage/             # SecureStore URL, companionId, pinned flight, profiles
│       └── theme/               # Mobile visual tokens, runtime provider, style bridge
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
- `/api/setup/reset` deletes the marker — triggers re-run wizard. Button in Settings footer.

### API call budget
- AviationStack BYOK default: 90 calls/month, tracked in `~/.localflight/api_usage.json`
- Community relay default: 50 relay schedule accesses/month per install
- Community and managed relay-backed installs now share airport snapshots on the relay; upstream AviationStack pulls are counted separately from per-install accesses
- ADS-B Exchange / RapidAPI default: 10,000 calls/month
- Enforced in `aviationstack_client.py` via `_check_and_increment_budget()` before each request
- All env vars read lazily at call time (not module import time) to avoid race with `_load_dotenv()`

### Linear issue tracker
Two separate integrations — do not confuse them:
- **Operator auto-filing** (`sources/web/linear_client.py`): `file_error()` called from `scheduler/runtime.py` on every cycle error. Uses `LINEAR_API_KEY` / `LINEAR_TEAM_ID` env vars pointing at the operator's own Linear workspace. Optional, completely silent, deduplicates per 6h.
- **User/developer report gateway** (`sources/web/bug_reporter.py` + relay `POST /v1/reports`): local app sanitizes report payloads and forwards them to the hosted relay. The relay owns `LINEAR_REPORTER_API_KEY` plus per-platform team IDs as Fly secrets, applies rate limits/dedupe, then files into Linear. Manual reports are always available. Automatic crash diagnostics are gated by server `diagnostics_mode`; mobile auto-reporting additionally requires the mobile-local diagnostics choice.

### Version
- Single source of truth: `version` field in `pyproject.toml`
- Read at runtime via `importlib.metadata.version("localflight")` with `"0.2.5b3"` fallback
- Injected as `app_version` Jinja2 global in `server.py` → available in all templates
- Shown in nav bar (`v0.2.5b3`) and Admin → System card
- `LocalFlight.spec` reads it from `pyproject.toml` at build time for macOS `CFBundleShortVersionString`

### Auto-update check
- `GET /api/admin/updates` checks GitHub releases API for `tr3y4rch/local-flight`
- 1-hour in-process cache to avoid hammering GitHub
- Admin → System card shows "Up to date" (green) or "vX.Y.Z available ↗" (amber link)

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
- Mobile crash reporting lives in `mobile/src/crash/`; `CrashBoundary` and the global reporter only auto-send `/api/feedback/crash` when the server diagnostics mode allows it.
- Admin mutating controls are still intentionally limited until QR pairing and per-device tokens exist; scheduler restart/config changes are the current trusted-LAN exception.
- Current Windows workspace has no Node/npm; run `npm install`, `npx expo install --fix`, and iOS device checks on the Mac/Xcode machine unless Node is installed on the dev PC.

## Environment variables (.env)

```
# Community relay / activation
LOCALFLIGHT_ACTIVATION_TOKEN=
LOCALFLIGHT_RELAY_URL=https://localflight-community-relay.fly.dev/v1/flights

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

Relay server env vars (relay/.env): `RELAY_ADMIN_PASSWORD`, `DB_PATH`, `RELAY_PUBLIC_HOST`, `RELAY_ADMIN_HOST`, `RELAY_COMMUNITY_SCHEDULE_LIMIT`, `RELAY_RADAR_MONTHLY_LIMIT`, `RELAY_MANAGED_SCHEDULE_LIMIT`, `RELAY_MANAGED_RADAR_LIMIT`, `RELAY_RADAR_CACHE_SECONDS`, `LINEAR_REPORTER_API_KEY`, `LINEAR_TEAM_IOS_ID`, `LINEAR_TEAM_DESKTOP_ID`, `LINEAR_TEAM_SERVER_ID`, `LINEAR_TEAM_RELAY_ID`, `LINEAR_TEAM_DEFAULT_ID`

---

## Hosted relay deployment checklist

Use this when moving back to the Windows dev machine and deploying the relay/reporting gateway directly.

### One-time sanity checks
- Work from a clean/current checkout of `https://github.com/tr3y4rch/local-flight`.
- Confirm Fly CLI is installed and authenticated: `fly auth login`
- Confirm the target app exists: `fly status -a localflight-community-relay`
- Relay deploys from the `relay/` directory because `relay/fly.toml` and `relay/Dockerfile` are scoped there.
- Do not put Linear secrets in `.env`, `fly.toml`, GitHub, desktop code, mobile code, or docs. They belong only in Fly secrets / dashboard env.

### Deploy updated relay code

```powershell
cd relay
fly deploy --remote-only
cd ..
```

If Fly asks which app to use, choose `localflight-community-relay`. If in doubt, use the explicit form:

```powershell
cd relay
fly deploy --remote-only -a localflight-community-relay
cd ..
```

### Add/update Linear reporting secrets

Set these in the Fly dashboard for `localflight-community-relay` or through the CLI. The dashboard path is: app → Secrets / Environment → add secret values → save → restart/redeploy machine if Fly does not do it automatically.

Required report-gateway secrets:
- `LINEAR_REPORTER_API_KEY`
- `LINEAR_TEAM_IOS_ID`
- `LINEAR_TEAM_DESKTOP_ID`
- `LINEAR_TEAM_SERVER_ID`
- `LINEAR_TEAM_RELAY_ID`
- `LINEAR_TEAM_DEFAULT_ID`

PowerShell CLI form:

```powershell
fly secrets set -a localflight-community-relay `
  LINEAR_REPORTER_API_KEY="lin_api_key_here" `
  LINEAR_TEAM_IOS_ID="ios_team_id_here" `
  LINEAR_TEAM_DESKTOP_ID="desktop_team_id_here" `
  LINEAR_TEAM_SERVER_ID="server_team_id_here" `
  LINEAR_TEAM_RELAY_ID="relay_team_id_here" `
  LINEAR_TEAM_DEFAULT_ID="default_team_id_here"
```

PowerShell line-continuation backticks must be the final character on the line; no trailing spaces after them. Confirm the secret names are present with:

```powershell
fly secrets list -a localflight-community-relay
```

Fly secrets are injected as runtime environment variables at machine boot. `fly secrets set` normally restarts/updates Machines; if secrets were staged or added via dashboard without a restart, redeploy from the relay folder:

```powershell
cd relay
fly deploy --remote-only -a localflight-community-relay
cd ..
```

### Verify relay health

```powershell
curl.exe -I --max-time 20 https://localflight-community-relay.fly.dev/health
```

Expected: HTTP `200`.

Optional synthetic report smoke test after secrets are live:

```powershell
$body = @{
  report_type = "manual"
  origin = "desktop"
  install_id = "00000000-0000-4000-8000-000000000001"
  install_fingerprint = "11e594f48195"
  title = "Relay smoke test"
  description = "Safe test from deployment checklist"
  app_version = "0.2.5b1"
  platform = "Windows"
  diagnostics_mode = "manual"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "https://localflight-community-relay.fly.dev/v1/reports" `
  -ContentType "application/json" `
  -Body $body
```

Expected success shape: `{ ok: true, team: "desktop", deduped: false }`. Re-running the same test within 30 minutes should return `deduped: true` and should not create another Linear issue.

### After successful report test
- Rotate/revoke the old Linear key that was previously embedded in shipped code.
- Submit one real desktop `/feedback` report from the local app and confirm it lands in the Desktop Linear team.
- Trigger or simulate one diagnostics-gated crash only after confirming diagnostics mode is `auto` or `auto_logs`.
- Keep `sources/web/linear_client.py` unchanged for optional operator-owned `LINEAR_API_KEY` / `LINEAR_TEAM_ID`; it is separate from developer/user reporting.

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
diagnostics_mode: str = "unset"  # unset | manual | auto | auto_logs
web_row_limit: int = 20
web_rotation_seconds: int = 8
display_grace_minutes: int = 30
display_horizon_hours: int = 12
```

Config lives at `~/.localflight/config.json`

---

## Key API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/config` | Current server config |
| `PATCH /api/config` | Update config fields; broadcasts `config_updated`; restarts scheduler for airport/source/interval changes |
| `GET /api/fids` | JSON FIDS rows |
| `GET /api/fids/detail` | Per-callsign detail — live position + 7-day history |
| `GET /api/radar` | Aircraft positions |
| `GET /api/metar` | Decoded + raw METAR |
| `GET /api/history` | Recent flights from SQLite |
| `GET /api/history/flight` | Callsign history |
| `GET /api/history/stats` | DB size, row count |
| `GET /api/admin/system` | Uptime, memory, CPU, version |
| `GET /api/admin/budget` | API call budgets |
| `GET /api/admin/requests` | Anonymized local traffic log summary (only when network tools are enabled) |
| `GET /api/admin/connections` | WS count + device pings |
| `GET /api/admin/updates` | GitHub release update check (1h cache) |
| `GET /api/admin/scheduler` | Scheduler thread status |
| `POST /api/admin/scheduler/restart` | Stop sleeping scheduler loop, reload config/env, start fresh cycle, broadcast `scheduler_restarted` |
| `POST /api/feedback` | Submit manual bug report `{title, description, client_context}` — sanitizes locally, then forwards to relay `/v1/reports` |
| `POST /api/feedback/crash` | Automatic mobile/server crash route; blocked unless diagnostics settings allow it |
| `POST /api/admin/ping` | Device ping (matrix client) |
| `POST /api/setup/complete` | Save setup, write .env, mark complete |
| `POST /api/setup/reset` | Delete setup_complete marker → re-run wizard |
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
- **Windows:** `dist/LocalFlight-windows.zip` + `.sha256` — unzip, double-click `LocalFlight.exe`
- **macOS:** `dist/LocalFlight.app` plus `dist/LocalFlight-macos.zip` + `.sha256` — upload the zip; users unzip, then drag `LocalFlight.app` to Applications

Optional code signing via env vars:
- Windows: `SIGNTOOL_CERT` (path to .pfx) + `SIGNTOOL_PASS`
- macOS: `CODESIGN_IDENTITY` (Developer ID string) + `NOTARIZE_PROFILE` (notarytool keychain profile)

Without signing: Windows shows SmartScreen "Unknown publisher"; macOS requires right-click → Open on first launch.

Release build notes:
- Build Windows artifacts on Windows: `python build.py --clean` → attach `LocalFlight-windows.zip` and `LocalFlight-windows.zip.sha256`.
- Build macOS artifacts on macOS: `python build.py --clean` → attach `LocalFlight-macos.zip` and `LocalFlight-macos.zip.sha256`.
- Build the Pi source installer bundle on any machine with git available: `python scripts/package_pi_source.py` → attach `LocalFlight-pi-source-<version>.zip` and `.sha256`.
- `installers/windows/install.ps1` and `installers/macos/install.sh` are source-checkout installers; release users should prefer the PyInstaller zip artifacts.

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

# Mobile companion (Mac/Xcode machine)
cd mobile
npm install
npx expo install --fix
npm run ios
```

---

## Current handoff for the dev machine

- Active version is `0.2.5b3`: `pyproject.toml`, runtime fallbacks, mobile package metadata, Expo `extra.localFlightVersion`, and docs should all agree.
- Community relay is live at `https://localflight-community-relay.fly.dev/v1/flights`. The custom domain `relay.localflight.app` is planned once DNS is registered.
- Relay admin panel: access via `RELAY_ADMIN_ON_PUBLIC=1` (already set as a Fly secret) at `https://localflight-community-relay.fly.dev/admin`, or via `fly proxy 8080` (unreliable on Windows) or `fly ssh console` for CLI access.
- Fly deployment: one warm machine in `fra`, one SQLite volume (`relay_data`), host-based public/admin gating in `relay/main.py`. Shared-schedule relay deploys now need the repo-root command `fly deploy --config relay/fly.toml --dockerfile relay/Dockerfile --remote-only` so the image includes `src/localflight`.
- Live shared schedule planner is currently `fair-v3`: date-scoped fair paging, adaptive continuation, and an undated rescue fallback. Cold relay rebuilds may take longer, so relay-backed desktop fetches now allow `60s`.
- `mobile/node_modules` is still absent on the Windows workspace, so Expo/TypeScript validation belongs on the Mac/Xcode side after `npm install` unless Node/npm are installed there.
- Desktop resume on Windows: run `.\start.bat`, confirm Community setup preloads the hosted relay URL, then verify FIDS/radar/admin against the live relay contract.
- Release resume: run `python build.py --clean` separately on Windows and macOS. Upload `dist/LocalFlight-windows.zip`, `dist/LocalFlight-windows.zip.sha256`, `dist/LocalFlight-macos.zip`, and `dist/LocalFlight-macos.zip.sha256` to GitHub release `v0.2.5b3`.
- Pi release resume: run `python scripts/package_pi_source.py` and upload `dist/LocalFlight-pi-source-0.2.5b3.zip` plus `dist/LocalFlight-pi-source-0.2.5b3.zip.sha256`.
- Settings now split install/relay state, flight setup, app controls, and diagnostics/resources into clearer sections; the community relay card now reports active relay usage truthfully, and the docs buttons open bundled local files through `/docs/readme`, `/docs/privacy`, and `/docs/changelog`.
- macOS packaging is confirmed on this workspace: `python build.py --clean` produced `dist/LocalFlight.app`, `dist/LocalFlight-macos.zip`, and `dist/LocalFlight-macos.zip.sha256`, and the packaged app includes bundled README/privacy/changelog files plus the local doc viewer template.
- Mobile companion is now mid-`0.2.5-b2` pass on this workspace: independent mobile appearance, server-backed Matrix runtime editor, landscape split display, responsive radar, and pinch zoom are implemented in code.
- Mobile companion polish pass is in progress on top of that: main nav is now FIDS/Radar/Settings only, History/Matrix/Admin/Docs are Settings-launched tools, the pinned-flight island is compact and theme-aware, Settings is sectioned, docs read inside the app, airport/profile saves request a scheduler restart, and flight details consume the expanded `/api/fids/detail` contract.
- Desktop flight-detail enrichment pass started first: `/api/fids/detail` now returns richer stored snapshot metadata for live track/source coverage without new external calls, and the desktop FIDS drawer renders operations/aircraft, source confidence/freshness, and position fields more clearly.
- VATSIM detail completeness pass keeps useful filed-plan fields in canonical snapshots: flight rules, planned route, cruise altitude/TAS, planned departure/arrival, enroute time, alternate, and assigned transponder. Intentionally does not store pilot names/CIDs.
- Desktop FIDS detail drawer now has real vs virtual modes: real flights show airport operations/aircraft/source freshness, while VATSIM flights show virtual flight plan/network/pilot track labels and suppress real-world-only emphasis.
- Mobile detail communication stays server-mediated: the companion calls `/api/fids/detail` and does not call AviationStack, ADS-B Exchange, RapidAPI, or the hosted relay endpoints directly.
- Mobile automatic diagnostics now includes critical detail communication failures (`5xx` or malformed JSON) through diagnostics-gated `/api/feedback/crash`; feature-specific reports keep companion identity, app version, device type, and server URL in the client context. Mobile also has its own SecureStore diagnostics choice, so auto-reporting requires both mobile and server consent.
- Linear developer reporting now goes through relay `POST /v1/reports`; no developer Linear API key/team ID is shipped in the packaged desktop or companion app. Relay secrets required: `LINEAR_REPORTER_API_KEY`, `LINEAR_TEAM_IOS_ID`, `LINEAR_TEAM_DESKTOP_ID`, `LINEAR_TEAM_SERVER_ID`, `LINEAR_TEAM_RELAY_ID`, and `LINEAR_TEAM_DEFAULT_ID`.
- Mobile structure refactor is complete enough for handoff: `App.tsx` is a provider entrypoint, `src/app/AppShell.tsx` coordinates state/refresh, pure helpers live in `src/domain/`, stateful behavior in `src/hooks/`, and screens/sheets in `src/screens/AppScreens.tsx`.
- Mobile validation: `npm run typecheck` passes; `npm run doctor` is 17/18 after adding `expo-font` and updating Expo to `~55.0.19`. Remaining doctor failure is environment-only: Expo SDK 55 reports Xcode `16.3.0` incompatible and requires Xcode `>=26.0.0`.
- Mobile resume on Mac/Xcode: resolve the Xcode/Expo SDK compatibility issue first, then run `npm run doctor` and `npm run ios`. Expo Go may reject SDK 55 depending on installed Expo Go; simulator/dev build is the safer path.
- Windows-side AviationStack reliability pass is now documented in public/internal docs. Important: the local board/filter bug is fixed, but some live airports can still show sparse future departures because AviationStack itself does not return enough near-term rows even after fair paging plus undated rescue. Current observed example: `ZRH` on `2026-05-01`.
- Sparse-board UX fallback is now active on the client: if a real-data lane has no rows inside the live window, the board shows the nearest available real flights instead of an empty departures page. Current live local check after the patch: `/api/fids?view=departures` returned `20` rows again.
- Verification currently green on Windows side: `python -m compileall -q src relay` and `pytest tests` (`58 passed`) after the AviationStack fairness, relay rescue, and sparse-board fallback changes.

## What was done in the latest session (v0.2.5b3)

- ✅ AviationStack fairness work now applies across all paths: shared date-aware fetch planning, airport-local date windows, `100`-row pages, per-date pagination, and configurable board display windows.
- ✅ Community and managed relay-backed installs now use a shared airport snapshot service instead of raw per-install upstream pass-through. Relay clients receive canonical Local Flight schedule records from `/v1/schedule`, while BYOK and direct local key paths stay unchanged.
- ✅ Relay accounting now separates per-install relay accesses from shared upstream AviationStack pulls, and admin/settings surfaces expose shared snapshot stats, cache-hit rate, and estimated savings.
- ✅ Web and matrix overflow handling now rotate local pages instead of clipping to a single fixed slice, with new config fields for grace window, horizon, web row limit, and web rotation timing.
- ✅ Added `scripts/audit_aviationstack.py` plus regression coverage for request planning, relay coalescing, stale fallback, and direct-vs-relay normalization parity.
- ✅ Version sweep completed to `0.2.5b3` across Python runtime fallbacks, mobile metadata, preview badges, tests, and public docs.
- ✅ Bug reporting now attaches truthful schedule-mode context (BYOK, local community key, managed/community shared relay), includes board-window details for triage, and scopes automatic crash dedupe by context as well as message.
- ✅ Live Fly relay was redeployed after the shared-snapshot rollout, and the relay image now bundles `src/localflight` so `/v1/schedule` works in production instead of crashing with `ModuleNotFoundError: localflight`.
- ✅ FIDS filtering now uses the snapshot timestamp as its reference clock, so valid saved rows do not disappear just because the wall clock moved past the snapshot.
- ✅ AviationStack fetchers now keep paging past the initial production slice when the visible board has not been reached yet, and both the local client and the hosted relay can attempt an undated rescue pass before surfacing an empty real-data board.
- ✅ Relay planner/version was pushed live through `fair-v3`, and relay-backed schedule fetch timeout was raised to `60s` to tolerate heavier cold shared-snapshot rebuilds.
- ✅ Reality check after the fix: the Local Flight fetch/filter bugs were corrected, but live `ZRH` departures on `2026-05-01` still remained sparse after the stronger fetch strategy. That remaining gap is currently documented as upstream AviationStack coverage behavior, not a known unresolved client filter bug.
- ✅ Client FIDS now falls back to the nearest available real rows when a sparse provider window would otherwise render `0` departures or arrivals, so the board stays useful even when AviationStack only returns older rows for that lane.

## What was done in session v0.2.5b2

- ✅ macOS-side mobile companion pass landed on `main`: updated Expo metadata, device identity reporting, crash reporter polish, README notes, and the iOS shell refinements from the Xcode machine work.
- ✅ Mobile review cleanup on Windows: companion version reporting now derives from Expo metadata instead of a duplicated string, and the mobile API config typing now includes the newer board-window fields from the desktop server.

## What was done in session v0.2.5b1

- ✅ Version sweep completed to `0.2.5b1` across Python runtime fallbacks, PyInstaller metadata, mobile metadata, docs, and preview assets.
- ✅ Community relay default centralized to `https://localflight-community-relay.fly.dev/v1/flights`; setup, installers, and client code now point at the same source of truth.
- ✅ Added route-contract regression coverage for core UI/API surfaces and relay public/admin surfaces; current Windows verification passed with `34` tests.
- ✅ Diagnostics/privacy reporting adapted: first-run diagnostics choice, settings control, truthful `/feedback` wording, and crash auto-report gating through `diagnostics_mode`.
- ✅ Mobile crash reporter now respects the server diagnostics setting before auto-sending.
- ✅ Matrix/I75W path hardened: `/api/matrix/config` repaired, `/api/matrix/script` added, browser helper blocks `localhost`, and board-side config intake is sanitized.
- ✅ README / privacy / mobile docs updated to match the current community / BYOK / VATSIM setup and hosted relay story.
- ✅ Settings IA cleaned up: install/relay state is separated from app controls and diagnostics/resources, community relay wording is now accurate, and README/privacy/changelog open inside the app instead of dead external placeholders.
- ✅ PyInstaller/macOS build now bundles the local docs into the app and uses a more reliable `.icns` generation path; `dist/LocalFlight-macos.zip` and `.sha256` were rebuilt successfully on this workspace.
- ✅ Mobile companion now has an independent appearance system (dark/light + 5 skins), a server-backed Matrix runtime editor, and auto landscape split display with responsive pinch-zoom radar. `npm install` and `npm run typecheck` passed on the Mac workspace; simulator/device validation still remains.
- ✅ Mobile companion structure refactor split the former single-file app into provider entrypoint, `AppShell`, domain helpers, state hooks, extracted chrome components, and `AppScreens`. `npm run typecheck` passes; `npm run doctor` is blocked only by local Xcode compatibility.
- ✅ Mobile companion UX polish: longer animated launch overlay, simplified main nav, sectioned Settings, in-app Markdown docs, compact theme-aware pinned-flight island with pin/unpin, richer detail sheet fields, explicit scheduler restart after mobile airport/profile changes, smoother screen transitions, and safer landscape split sizing.
- ✅ Desktop flight detail now exposes and renders richer stored enrichment data: source/enrichment confidence, snapshot age, last contact, geometric/barometric altitude, ICAO24, squawk, coordinates, speed, heading, vertical rate, and surface state. No new RapidAPI/OpenSky/VATSIM calls were added.
- ✅ Detail data model now preserves DAU-important aircraft/plan fields without overdoing it: aircraft registration for ADS-B/AviationStack when available, plus VATSIM filed flight rules, route, cruise altitude/TAS, planned times, enroute duration, alternate, and transponder.
- ✅ `/api/fids/detail` includes `detail_mode` (`real` / `virtual`) plus origin/destination ICAO codes, allowing desktop and companion to render source-specific detail layouts.
- ✅ Mobile detail sheet is aligned with the new server detail contract and guarded auto-reporting now catches critical detail endpoint failures without reporting normal offline/4xx cases.
- ✅ `DEV_README.md` now includes a quick "where to find what" map for relay URLs, network admin entrypoints, bundled docs routes, version sweep files, and release artifact commands; Pi source releases now use `python scripts/package_pi_source.py`.

## What was done in session v0.2.3b2

- ✅ Hosted relay defaults centralized in `relay_defaults.py` and wired through the desktop clients, setup flow, and installers.
- ✅ `relay/main.py` hardened for Fly.io: port `8080`, FastAPI lifespan startup, `/health`, host-based public/admin gating, and reduced relay-side metadata writes.
- ✅ `relay/fly.toml` updated for explicit `relay/` deployment, one warm `fra` machine, and the `relay.localflight.app` / `network.localflight.app` split.
- ✅ Privacy and handoff docs rewritten for the hosted relay model and install-scoped identifiers.
- ✅ `private_keys.py` — dev-only community key lookup from `dev/private/community_keys.json` (gitignored)
- ✅ `install.py` — `get_activation_token()` / `set_activation_token()` for managed install tokens
- ✅ `aviationstack_client.py` — explicit BYOK vs relay split; 30-day rolling community window; activation token forwarding; BYOK default 90/month; community cap 50/month
- ✅ `adsbexchange_client.py` — relay radar proxy path
- ✅ `request_log.py` — `client_type`, `client_id`, `platform` columns + schema migration; companion tracking
- ✅ `api.py` — `POST /api/admin/companion/checkin` endpoint with `CompanionCheckinIn`
- ✅ `server.py` — 6 new relay setup endpoints: client-info, activate, client-status, request-activation, request-activation/status, test-activation
- ✅ `relay/main.py` — full network admin console: provider key storage, token lifecycle/revocation, install access control, API counters, traffic stats, anonymous activation tags
- ✅ `setup.html` — three explicit paths (community / BYOK / VATSIM); managed activation flow; machine identity shown
- ✅ `admin.html` — community vs BYOK budget mode separated
- ✅ `settings.html` — read-only client link card (fingerprint, relay URL, token presence)
- ✅ `mobile/src/device/identity.ts` — companion identity (UUID, platform, deviceType, appVersion)
- ✅ `mobile/src/storage/settings.ts` — companionId persisted in Expo SecureStore
- ✅ `tests/test_relay_admin.py` — relay admin regression tests
- ✅ Version bumped to `0.2.3b2`; CHANGELOG, CLAUDE.md, AGENTS.md updated

## What was done in the macOS app session

- ✅ macOS `.app` bundle — `install.sh` now builds `~/Applications/LocalFlight.app` instead of a `.command` symlink; `scripts/make_app_bundle.py` handles SVG→icns (cairosvg → pre-rendered PNG → PIL fallback) + `Info.plist` + compiled Mach-O stub + baked shell launcher
- ✅ Mach-O stub — macOS Launch Services silently rejects shell scripts as `CFBundleExecutable`; stub is a tiny C program compiled with `cc` at install time that exec's `/bin/bash launcher.sh` in the same `MacOS/` directory
- ✅ `assets/icon_circle.png` — 1024×1024 pre-rendered from SVG and committed; `.gitignore` updated with `!assets/icon_circle.png` exception so the pre-render survives without `cairosvg`
- ✅ `LocalFlight.command` — fixed symlink `$0` resolution bug: when launched via Finder the symlink path was used as `$0`, causing `ROOT` to resolve to `~/..` instead of the project root; fixed with `readlink`
- ✅ `installers/macos/install.sh` — replaced `.command` symlink step with `make_app_bundle.py` call; `.command` file stays as shell-only fallback

## What was done in previous sessions

- ✅ `start.bat` — fixed UTF-8 box-drawing chars in `::` comments causing cmd.exe byte-eating bug on `chcp 65001`; replaced all 7 comment lines with ASCII; added error pause
- ✅ `linear_client.py` — added `test_connection()` with real GraphQL `viewer` query to validate key (not just env var presence); returns specific 401 message
- ✅ `bug_reporter.py` — originally added as the local feedback reporter; current implementation sanitizes locally and forwards developer/user reports through relay `/v1/reports`
- ✅ `feedback.html` — new `/feedback` page with title+description form, system info preview, success/error state
- ✅ `/api/feedback` endpoint — `POST`, `FeedbackIn` Pydantic model, calls `bug_reporter.submit_report()`
- ✅ `/feedback` route in `server.py`
- ✅ ðŸ› Report nav item added to `_nav.html` management group
- ✅ Admin hub Linear Issues card **removed** — replaced by dedicated `/feedback` page (no duplicate reporting)
- ✅ README rewritten from end-user perspective — install-first flow, removed dev-cycle / awaiting-hardware language
- ✅ File consistency sweep — LINEAR vars removed from all 3 installer `.env` templates; `pyproject.toml` Issues URL → GitHub; `CHANGELOG.md` updated; `AGENTS.md` updated
- ✅ Setup wizard — added ADS-B Exchange test endpoint + "Test connection" button for panel 3; POST body is now the preferred path and GET remains only as compatibility fallback
- ✅ Setup wizard — fixed RapidAPI signup URL (`adsbexchange` → `adsbx` provider slug in RapidAPI path); fixed OpenSky registration URL (old Joomla path → `/login?view=registration`)
- ✅ Admin hub — added Buy Me a Coffee strip at bottom (`buymeacoffee.com/localflight`); subtle ghost opacity, not a card
- ✅ Runtime snapshots — moved canonical JSON storage to `~/.localflight/storage/data/<IATA>/snapshots`; legacy source-tree snapshots remain readable
- ✅ Scheduler/runtime — pruning now runs inside snapshot jobs; failed cycles preserve the previous `last_success_utc`
- ✅ Installer/docs sweep — Windows/macOS/Pi source installers clarified; Pi helper path fixed; `.env.example` no longer includes operator Linear vars
- ✅ Desktop beta release prep — `psutil`/`packaging` required; Windows build writes a SHA256 checksum

- ✅ Mobile Phase 1 — created `mobile/` React Native / Expo scaffold with SecureStore settings, API client, WebSocket listener, responsive layout helpers, and iOS-first shell
- ✅ Mobile visual pass — base app followed the supplied airport-board mockup with status bar/dynamic-island-style treatment, airport/METAR header, FIDS tabs, pinned flight card, compact rows, admin/settings screens, and bottom nav
- ✅ Version bump — project moved to `0.2.2b1`; mobile npm metadata used `0.2.2-b1`; Expo metadata carried `extra.localFlightVersion = "0.2.2b1"`

## Pending / next up

- [ ] Create GitHub release `v0.2.5b3` and attach Windows/macOS/Pi artifacts plus all matching `.sha256` files.
- [ ] Attach the Pi source bundle too: `LocalFlight-pi-source-0.2.5b3.zip` and `.sha256`.
- [ ] Register custom domain and wire `relay.localflight.app` + `network.localflight.app` DNS → `localflight-community-relay.fly.dev`; run `fly certs add` for both.
- [ ] End-to-end community client activation test against live relay.
- [ ] Decide the next step for sparse AviationStack airports: second provider merge, sparse-board warning UX, or a deliberate stale-board fallback instead of an empty departures page.
- [ ] Mobile — resolve Expo SDK 55 vs Xcode compatibility, then test in iOS simulator/dev build.
- [ ] Validate the companion runtime flows on-device/simulator: connection setup, FIDS/Radar/History/Settings, appearance persistence, Matrix save/reset, landscape split, radar pinch zoom, feedback, crash gating, and WebSocket refresh.
- [ ] Notification system (Pushover/Telegram) — ~50 lines, hooks into scheduler after `_broadcast_update()`
- [ ] Pi hardware on hand — run systemd services + kiosk validation on the real unit
- [ ] RTL-SDR dongle — test dump1090 integration
- [ ] Interstate 75 W — flash client.py, test WiFi polling
- [ ] Code signing certificates — Developer ID (macOS) + EV cert (Windows SmartScreen)
- [ ] Mobile v2 — QR pairing + per-device tokens before exposing admin mutating controls

## Afternoon handoff (2026-04-30)

- ✅ `AGENTS.md` is the working memory file again for current-state handoff notes.
- ✅ `.gitignore` covers local assistant / dev context files including `.claude/`, `CLAUDE.md`, `DEV_README.md`, and `AGENTS.md`. Important: `AGENTS.md` is still tracked by git right now, so the ignore rule only protects future untracked state.
- ✅ Windows side is currently verified for the hosted-relay desktop app: `build.py --clean`, `compileall`, `py_compile`, and `pytest tests` passed in the latest release sweep.
- ✅ Pi / I75W prep is staged in code: Pi installer plus `lf` helper are ready, matrix preview is safer for DAU use, and the board download path rejects `localhost` in favor of LAN-safe server targets.
- ✅ Mobile companion remains version-synced but still WIP; runtime validation still belongs on the Mac/Xcode side after dependency install.
- 🔜 Next physical test focus: Raspberry Pi service / kiosk pass, Interstate 75 W flash plus matrix polling check, and later the macOS PyInstaller validation for the release app.

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
- Separation-of-power rule: keep internal/operator references out of public docs and UI copy. Public-facing surfaces such as `README.md`, `PRIVACY.md`, `CHANGELOG.md`, release text, and user-visible templates should not mention `DEV_README.md`, `AGENTS.md`, relay admin hostnames, or other operator-only paths unless there is a real end-user need.
