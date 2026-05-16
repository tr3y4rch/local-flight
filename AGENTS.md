# Local Flight — Codex Context

## What this project is

A local-first, self-hosted **Flight Information Display System (FIDS)** that runs on Windows, macOS, and Raspberry Pi. Fetches real and simulated flight data, displays it as a proper airport-style departure/arrival board — in the Chrome-free native Qt shell, supported LAN browser UI, an LED matrix panel, or a dedicated HDMI screen.

Built with: Python 3.11+, FastAPI, uvicorn, SQLite, WebSocket, Jinja2, PIL, and PySide6/Qt for the primary native desktop/display UI. Mobile companion uses React Native / Expo. pystray on macOS only (Windows uses a ctypes taskbar window).

**Repo:** https://github.com/tr3y4rch/local-flight  
**Issues:** https://github.com/tr3y4rch/local-flight/issues

---

## Current 0.2.7 handoff snapshot (2026-05-14)

- Active package target: `0.2.7` as the client-polish/release-candidate line. `pyproject.toml` remains the source of truth; keep runtime fallbacks, native docs, mobile metadata, and preview/release docs aligned with it.
- Current Windows workspace validation after the Matrix display-integrity repack: `python -m compileall -q src relay installers scripts tests` passed and `python -m pytest tests -q` returned `376 passed`.
- Windows and Pi artifacts have been rebuilt from the current Windows workspace:
  - `dist/LocalFlight-windows.zip` — SHA256 `a0d64c8c272800507a5ee9d8c771cc2e10a63d7c253f9092ba0f725259af66d8`
  - `dist/LocalFlight-pi-source-0.2.7.zip` — SHA256 `67bb84b3fe8be0d5a260f147c5a8e3a394dbe2332d4e4b0f6b2274e7fa24dcd3`
- macOS still needs its own pull/validation/package pass from the same `0.2.7` source state before publishing the GitHub release. Do not reuse stale `0.2.5b5` or `0.2.6` macOS/Pi handoff notes.
- Recent client-facing changes to preserve in Mac/Pi smoke tests: native shell top-bar grouping and footer support icons, city/country FIDS title, passenger-friendly weather hero, long-title clamping, native/browser History analytics dashboard, Matrix configurator parity, compact Matrix weather header, Matrix display-contract labels/weather icons in Qt/LAN/MicroPython, real-only Matrix gate labels, Settings/setup dashboard polish, FIDS/Radar current-source intelligence details, and LAN radar parity with Qt radar behavior.
- Schedule-provider work to preserve in relay/client smoke tests: AeroDataBox primary FIDS source, AviationStack sparse fill/fallback, hard upstream caps, 24h stale-cache serving, source-cache re-merge, canonical provider meta, and fused rows compiling through both `/api/fids` and Qt `FlightBoardModel`.
- Separation of power still applies: public docs stay user-focused; relay operator/admin details belong only in `AGENTS.md`, `DEV_README.md`, `CLAUDE.md`, and operator tooling.

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
│   │   ├── metar.py             # Local Flight semantic METAR mood/icon decorator
│   │   ├── normalize.py         # Raw records → Flight objects
│   │   ├── opensky.py           # OpenSky enrichment
│   │   └── mappings/
│   │       ├── aviationstack.py
│   │       └── aerodatabox.py
│   ├── display/
│   │   └── fids_from_flights.py # PAX-friendly flight number formatting
│   ├── render/
│   │   └── fids.py              # Build Jinja2 template context
│   ├── scheduler/
│   │   ├── jobs.py              # Main fetch job — AeroDataBox/AviationStack + enrichment chain
│   │   ├── runtime.py           # run_loop(); stop_event-aware sleeps + crash reporting
│   │   ├── control.py           # In-process scheduler start/status/restart controller
│   │   └── run_scheduler.py
│   ├── sources/
│   │   ├── web/
│   │   │   ├── aviationstack_client.py  # BYOK + community relay budget guard; activation token; lazy env reads
│   │   │   ├── aerodatabox_client.py    # BYOK AeroDataBox FIDS client + local atomic budget guard
│   │   │   ├── schedule_fusion.py       # AeroDataBox primary + AviationStack fill merge policy
│   │   │   ├── local_usage.py           # Local SQLite usage counters for direct provider caps
│   │   │   ├── aviationstack_mock.py
│   │   │   ├── adsbexchange_client.py   # RapidAPI + relay radar proxy; primary position enrichment
│   │   │   ├── opensky_radar.py         # fetch_radar_blips(), bounding_box()
│   │   │   ├── airport_surface.py       # OSM/Overpass airport surface normalization + payload schema
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
│           ├── radar.html       # Radar canvas + sweep + METAR + optional surface overlay
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
├── start.bat                    # Native-first dev launcher (Windows, project root)
└── start_network.bat            # Local ignored native operator Network Admin launcher
```

Native/Chrome-free additions:
- `src/localflight/platform/gui_mode.py` parses `LOCALFLIGHT_GUI_MODE=auto|native|browser|headless` with native as the blank/invalid default.
- `src/localflight/platform/gui_launcher.py` makes the final platform launch decision from requested mode, platform, display availability, and PySide6/Qt availability.
- `src/localflight/native/app.py` is now the thin public compatibility facade for native launch/test imports. The current extracted native runtime lives across `bootstrap.py`, `shell.py`, `async_tools.py`, `loader.py`, `pages/`, `canvas/`, and private compatibility code in `_legacy_app.py` while the behavior-preserving split continues.
- `src/localflight/native/network_admin.py` is the separate operator-only Network Admin Qt shell, pointed at redacted relay `/admin/api/*` JSON plus admin action endpoints. It now has a fleet/dev operations console shape with Overview, Fleet, Traffic, Schedules, Surfaces, Activations, Reports, Providers, and Maintenance.
- `src/localflight/native/design.py` and `routes.py` hold browser-parity Qt theme/skin tokens, shared styling/widgets, native media/doc resolution, bundled public doc metadata, and declared native HTTP actions so buttons do not drift from real routes.
- `src/localflight/native/api_client.py` and `qt_compat.py` keep HTTP access and PySide6 imports lazy so non-native builds keep working.
- `start.bat`, Windows/macOS source installers, macOS app-bundle launcher, and PyInstaller builds install/verify the `native` extra so PySide6/Qt is present before native launch.
- `start_network.bat` is a local ignored operator launcher that opens the native operator console against the hosted relay by default. Keep relay runtime secrets in Fly/dashboard secrets, not in repo-tracked files.

---

## Architecture decisions

### Platform model
- `platform/detect.py` — `detect()` returns `Platform` enum, cached. `is_desktop()` / `is_headless()` helpers.
- `LOCALFLIGHT_GUI_MODE=auto|native|browser|headless` is parsed by `gui_mode.py`; `gui_launcher.py` then resolves the actual launch shell. Blank or invalid values fall back to `native`.
- Native is the product default: Windows/macOS open the PySide6/Qt shell when available, Pi/Linux with a display can open native fullscreen when Qt is installed, desktop falls back to browser only when Qt is unavailable, and display-less Pi/Linux remains headless.
- Desktop browser mode (Windows/macOS): supported LAN browser UI in a kiosk-style browser window + system tray + full GUI.
- Native mode: starts the same local FastAPI backend, then opens the Qt shell instead of Chrome/Edge/Chromium. Browser UI remains reachable manually at `http://localhost:8000`.
- Headless (Pi/Linux): uvicorn + scheduler only, no window management. Chromium kiosk is a separate systemd service; native Qt kiosk is explicit via `installers/pi/install.sh --native-kiosk` and now runs as split services: backend stays headless in `localflight.service`, while a user-session `localflight-native-kiosk.service` owns the fullscreen Qt display.
- `__main__.py` logs the full `GuiLaunchDecision` and dispatches to `_run_native_gui()`, `_run_desktop()`, or `_run_headless()` based on the resolved platform launch layer.
- Browser/LAN UI and Chromium Pi kiosk first hit `/splash?next=/display`; first-run browser mode uses `/splash?next=/setup`. Native first-run uses the standalone setup window before creating the main shell.

### Data enrichment chain (source=real)
```
AeroDataBox FIDS (primary schedule: dense airport board, times/status, gates/terminals/aircraft when present)
    ↓ sparse/missing-field fill
AviationStack (conditional schedule fill/fallback; fills empty board fields without overwriting AeroDataBox times/status)
    ↓
Schedule fusion (canonical Local Flight rows; deterministic flight identity; source evidence kept in meta)
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

Provider selection stays inside `source=real`: `LOCALFLIGHT_REAL_SCHEDULE_PROVIDER` / `RELAY_SCHEDULE_PROVIDER` can be `auto`, `aerodatabox`, or `aviationstack`. `auto` prefers AeroDataBox when configured/enabled and uses AviationStack only as sparse fill or fallback. The public app mode remains `real|virtual`.

### WebSocket live push
- `ConnectionManager` in `server.py` tracks connections, drains async queue
- `ui/events.py` is the shared non-fatal publisher for `snapshot_updated`, `config_updated`, and `scheduler_restarted`
- Scheduler calls `_broadcast_update()` after each snapshot; settings/API/profile/setup saves call `notify_config_updated()`
- Scheduler-relevant config changes (`airport_iata`, `airport_icao`, `refresh_seconds`, `source`) queue `restart_scheduler_and_notify()` so the new interval takes effect immediately
- `display.html` holds one WS connection, reloads on `config_updated`, and forwards other messages via `postMessage` to iframes
- FIDS/Radar/Admin/mobile refresh on push events and still keep lightweight fallback polling
- Clients reconnect with exponential backoff

### Relay heartbeat and Network Admin routing
- This is an operator-only visibility path, not a user-facing feature and not a billing/usage signal. Keep details in `AGENTS.md`, `DEV_README.md`, `CLAUDE.md`, tests, and operator tooling only.
- Local app startup creates the async heartbeat task from `ui/server.py` lifespan. The sender lives in `sources/web/relay_beat.py`; the safe metadata builder lives in `sources/web/relay_heartbeat.py`.
- Normal heartbeat cadence is intentionally low: one startup attempt after roughly 45s plus jitter, then about every 30 minutes with ±5 minutes jitter. Do not shorten this interval for convenience; we do not want a hobbyist app hammering Fly.io or the relay with keepalive traffic.
- Heartbeats should stay silent-failure, fire-and-forget, and non-blocking. A failed relay heartbeat must never break setup, FIDS, radar, scheduler, matrix, mobile, or local LAN browser behavior.
- Heartbeats are meant for real-source community relay installs after setup is complete. BYOK users, virtual/VATSIM-only users, and incomplete setup should not need periodic relay presence pings.
- Current immediate heartbeat triggers exist after first-run setup completion and desktop settings saves so Network Admin can notice changed client shape sooner. They must pass the same local eligibility gate as the periodic loop and a sender-side 5-minute debounce before any outbound call reaches Fly.
- The relay endpoint is `POST /v1/heartbeat`. It validates the raw install UUID, records only coarse install-profile metadata, and has a relay-side cooldown of 5 minutes per install via `_HEARTBEAT_MIN_INTERVAL_S`. It does not write to `request_log` and does not count as schedule/radar/report usage.
- Heartbeat payload metadata is intentionally coarse: app version, OS family/version, arch, requested/effective GUI mode, source mode, diagnostics mode, companion count, matrix count, and matrix online count. Never add raw IPs, raw activation tokens, local paths, API keys, flight history, airport history, logs, report bodies, or companion device IDs to heartbeat payloads.
- Relay stores heartbeat freshness in `install_profiles.last_seen`. Network Admin reads this through redacted `/admin/api/fleet` and `/admin/api/overview` payloads; it shows public install fingerprints/action refs only, never raw install IDs.
- Network Admin routing stays split from the public relay. Public clients use `/v1/*` endpoints such as schedule, radar, airport surface, reports, activation, client check-in, and heartbeat. Operator UI uses Basic-Auth/admin-host-gated `/admin/api/*` read/action endpoints and must remain redacted.
- Fleet "active" means seen within roughly 24 hours from heartbeat, relay usage, client interest, activation token, or activation request timestamps. Treat it as coarse operational presence, not an exact online status.
- Heartbeat hardening test coverage currently lives in `tests/test_relay_beat.py` and `tests/test_heartbeat_relay.py`: local eligibility/debounce, silent client failures, relay cooldown, install-profile writes, malformed install rejection, and "do not log heartbeat to request_log".

### Setup gate
- `SetupGateMiddleware` in `server.py` redirects all routes to `/setup` until `~/.localflight/setup_complete` exists
- Exempt paths: `/setup`, `/api/setup/*`, `/api/airports/search`, `/static`, `/health`, `/ws`
- On first launch, scheduler is deferred. Setup watcher thread polls for `setup_complete` and auto-starts scheduler when detected.
- Native first launch opens a standalone setup window first, not the main shell. It asks for airport/source/provider keys plus the diagnostics/reporting mode, posts `diagnostics_mode` through `/api/setup/complete`, saves it in `AppConfig`, clears stale native API cache, and only then opens the Display shell.
- `/api/setup/reset` deletes the marker — triggers re-run wizard. Button in Settings footer.

### API call budget
- Local direct-provider budgets are enforced before outbound calls. New code uses SQLite counters in `~/.localflight/api_usage.sqlite` and keeps legacy `~/.localflight/api_usage.json` readable for display/backward compatibility.
- AeroDataBox BYOK default: enabled only when `AERODATABOX_API_KEY` and `LOCALFLIGHT_AERODATABOX_ENABLED=1` are present. API.Market is the default gateway (`LOCALFLIGHT_AERODATABOX_MARKETPLACE=apimarket`); existing RapidAPI subscriptions can use `rapidapi`. Default local monthly unit cap is `LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT=24000`, with daily cap defaulting to `ceil(monthly/30)` unless `LOCALFLIGHT_AERODATABOX_DAILY_UNITS_LIMIT` is set. FIDS Tier 2 requests count as 2 units each.
- AviationStack BYOK default: 90 calls/month unless `LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT` is set. Local direct calls are now guarded atomically per request/page.
- Community relay default: 50 relay schedule accesses/month per install
- Community and managed relay-backed installs share airport snapshots on the relay; upstream AeroDataBox units/requests and AviationStack pages are counted separately from per-install accesses and guarded before each upstream call.
- ADS-B Exchange / RapidAPI default: 10,000 calls/month
- Relay schedule admission is cache-first and fail-closed: unknown airports are rejected, windows are bucketed, cheap RPM/new-key limits run before DB-heavy work, provider monthly/daily caps are checked before upstream, and cap exhaustion is handled like an upstream outage so stale cache can serve.
- All env vars read lazily at call time (not module import time) to avoid race with `_load_dotenv()`

### Linear issue tracker
Two separate integrations — do not confuse them:
- **Operator auto-filing** (`sources/web/linear_client.py`): `file_error()` called from `scheduler/runtime.py` on every cycle error. Uses `LINEAR_API_KEY` / `LINEAR_TEAM_ID` env vars pointing at the operator's own Linear workspace. Optional, completely silent, deduplicates per 6h.
- **User/developer report gateway** (`sources/web/bug_reporter.py` + relay `POST /v1/reports`): local app sanitizes report payloads and forwards them to the hosted relay. The relay owns `LINEAR_REPORTER_API_KEY` plus per-platform team IDs as Fly secrets, applies rate limits/dedupe, then files into Linear. Manual reports are always available. First-run setup must ask for diagnostics/reporting mode and save it locally. Automatic crash diagnostics are gated by server `diagnostics_mode`; mobile auto-reporting additionally requires the mobile-local diagnostics choice. Local reports include requested/effective GUI shell context so native GUI, browser/LAN UI, and headless service runs stay distinguishable without creating new Linear routing paths.

### Version
- Single source of truth: `version` field in `pyproject.toml`
- Read at runtime via `importlib.metadata.version("localflight")` with `"0.2.7"` fallback
- Injected as `app_version` Jinja2 global in `server.py` → available in all templates
- Shown in the native footer/brand surfaces and Admin → System card (`v0.2.7`)
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
LOCALFLIGHT_RELAY_URL=https://localflight-community-relay.fly.dev
LOCALFLIGHT_GUI_MODE=native

# BYOK AviationStack (leave blank to use community relay)
AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90
LOCALFLIGHT_RELAY_MONTHLY_LIMIT=50

# BYOK AeroDataBox schedule provider
AERODATABOX_API_KEY=
LOCALFLIGHT_AERODATABOX_MARKETPLACE=apimarket
LOCALFLIGHT_AERODATABOX_ENABLED=0
LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT=24000
LOCALFLIGHT_REAL_SCHEDULE_PROVIDER=auto

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=

RAPIDAPI_KEY=
LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=10000
```

Optional local direct-provider daily caps: `LOCALFLIGHT_AERODATABOX_DAILY_UNITS_LIMIT` and `LOCALFLIGHT_AVIATIONSTACK_DAILY_LIMIT`; both default to `ceil(monthly/30)`.

Relay server env vars (relay/.env / Fly secrets): `RELAY_ADMIN_PASSWORD`, `DB_PATH`, `RELAY_PUBLIC_HOST`, `RELAY_ADMIN_HOST`, `AERODATABOX_API_KEY`, `RELAY_AERODATABOX_MARKETPLACE`, `AVIATIONSTACK_API_KEY`, `RELAY_SCHEDULE_PROVIDER`, `RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT`, `RELAY_AERODATABOX_UPSTREAM_DAILY_UNITS_LIMIT`, `RELAY_AERODATABOX_FIDS_TIER2_UNITS`, `RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT`, `RELAY_AVIATIONSTACK_UPSTREAM_DAILY_LIMIT`, `RELAY_SCHEDULE_STALE_IF_ERROR_HOURS`, `RELAY_SCHEDULE_NETWORK_RPM_LIMIT`, `RELAY_SCHEDULE_INSTALL_RPM_LIMIT`, `RELAY_SCHEDULE_GLOBAL_RPM_LIMIT`, `RELAY_SCHEDULE_NEW_KEYS_NETWORK_DAILY_LIMIT`, `RELAY_SCHEDULE_NEW_KEYS_GLOBAL_DAILY_LIMIT`, `RELAY_PROVIDER_FAILURE_COOLDOWN_SECONDS`, `RELAY_COMMUNITY_SCHEDULE_LIMIT`, `RELAY_RADAR_MONTHLY_LIMIT`, `RELAY_MANAGED_SCHEDULE_LIMIT`, `RELAY_MANAGED_RADAR_LIMIT`, `RELAY_RADAR_CACHE_SECONDS`, `RELAY_AIRPORT_SURFACE_ENABLED`, `RELAY_AIRPORT_SURFACE_CACHE_HOURS`, `RELAY_AIRPORT_SURFACE_STALE_DAYS`, `RELAY_OVERPASS_URL`, `RELAY_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT`, `RELAY_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT`, `LINEAR_REPORTER_API_KEY`, `LINEAR_TEAM_IOS_ID`, `LINEAR_TEAM_DESKTOP_ID`, `LINEAR_TEAM_SERVER_ID`, `LINEAR_TEAM_RELAY_ID`, `LINEAR_TEAM_DEFAULT_ID`

---

## Hosted relay deployment checklist

Use this when moving back to the Windows dev machine and deploying the relay/reporting gateway directly.

### One-time sanity checks
- Work from a clean/current checkout of `https://github.com/tr3y4rch/local-flight`.
- Confirm Fly CLI is installed and authenticated: `fly auth login`
- Confirm the target app exists: `fly status -a localflight-community-relay`
- Relay deploys from the repo root with explicit config/dockerfile paths. Do not deploy from inside `relay/`; the Dockerfile copies `src/localflight`, so the build context must be the repo root.
- Do not put provider or Linear secrets in `.env`, `fly.toml`, GitHub, desktop code, mobile code, or docs. They belong only in Fly secrets / dashboard env.
- Do not publish operator-only relay/admin routes, provider quotas, or Fly secret names in public docs. Public docs may say the hosted relay uses cached shared schedule snapshots and multiple providers.

### Deploy updated relay code

```powershell
fly deploy --remote-only --config relay/fly.toml --dockerfile relay/Dockerfile -a localflight-community-relay
```

If Fly asks which app to use, choose `localflight-community-relay`. The GitHub Actions deploy workflow must use the same repo-root shape:

```yaml
flyctl deploy --remote-only --config relay/fly.toml --dockerfile relay/Dockerfile
```

### Add/update schedule provider secrets

Set these in the Fly dashboard for `localflight-community-relay` or through the CLI. Values are examples for the current paid tiers; keep the actual provider keys only in Fly secrets.

Required/expected schedule-provider secrets:
- `AERODATABOX_API_KEY`
- `RELAY_AERODATABOX_MARKETPLACE=apimarket` for API.Market keys, or `rapidapi` for RapidAPI subscriptions
- `RELAY_SCHEDULE_PROVIDER=auto`
- `RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT=24000`
- `RELAY_AERODATABOX_FIDS_TIER2_UNITS=2`
- `RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT=10000`
- `RELAY_SCHEDULE_STALE_IF_ERROR_HOURS=24`

Optional hardening overrides:
- `RELAY_AERODATABOX_UPSTREAM_DAILY_UNITS_LIMIT` default `ceil(monthly/30)`
- `RELAY_AVIATIONSTACK_UPSTREAM_DAILY_LIMIT` default `ceil(monthly/30)`
- `RELAY_SCHEDULE_NETWORK_RPM_LIMIT=120`
- `RELAY_SCHEDULE_INSTALL_RPM_LIMIT=30`
- `RELAY_SCHEDULE_GLOBAL_RPM_LIMIT=600`
- `RELAY_SCHEDULE_NEW_KEYS_NETWORK_DAILY_LIMIT=20`
- `RELAY_SCHEDULE_NEW_KEYS_GLOBAL_DAILY_LIMIT=200`
- `RELAY_PROVIDER_FAILURE_COOLDOWN_SECONDS=600`

PowerShell CLI form:

```powershell
fly secrets set -a localflight-community-relay `
  AERODATABOX_API_KEY="<aerodatabox-api-key>" `
  RELAY_AERODATABOX_MARKETPLACE="apimarket" `
  RELAY_SCHEDULE_PROVIDER="auto" `
  RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT="24000" `
  RELAY_AERODATABOX_FIDS_TIER2_UNITS="2" `
  RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT="10000" `
  RELAY_SCHEDULE_STALE_IF_ERROR_HOURS="24"
```

Confirm secret names are present without printing values:

```powershell
fly secrets list -a localflight-community-relay
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
  LINEAR_REPORTER_API_KEY="<linear-api-key>" `
  LINEAR_TEAM_IOS_ID="<ios-team-id>" `
  LINEAR_TEAM_DESKTOP_ID="<desktop-team-id>" `
  LINEAR_TEAM_SERVER_ID="<server-team-id>" `
  LINEAR_TEAM_RELAY_ID="<relay-team-id>" `
  LINEAR_TEAM_DEFAULT_ID="<default-team-id>"
```

PowerShell line-continuation backticks must be the final character on the line; no trailing spaces after them. Confirm the secret names are present with:

```powershell
fly secrets list -a localflight-community-relay
```

Fly secrets are injected as runtime environment variables at machine boot. `fly secrets set` normally restarts/updates Machines; if secrets were staged or added via dashboard without a restart, redeploy from the repo root:

```powershell
fly deploy --remote-only --config relay/fly.toml --dockerfile relay/Dockerfile -a localflight-community-relay
```

### Verify relay health

```powershell
curl.exe -I --max-time 20 https://localflight-community-relay.fly.dev/health
```

Expected: HTTP `200`.

Then smoke a fresh schedule lane. If an old cached lane already exists, either choose another known airport/window bucket or clear shared schedule snapshots through the operator maintenance flow before testing provider selection.

```powershell
$installId = [guid]::NewGuid().ToString()
$uri = "https://localflight-community-relay.fly.dev/v1/schedule?airport_iata=ZRH&timezone=Europe%2FZurich&display_grace_minutes=120&display_horizon_hours=24&refresh_seconds=3600&install_id=$installId&app_version=0.2.7-smoke&os_family=windows&requested_gui=native&effective_gui=native&source_mode=real&diagnostics_mode=manual"
$schedule = Invoke-RestMethod -Method Get -Uri $uri
$schedule.provider
$schedule.cache_state
$schedule.meta.schedule_provider_mode
$schedule.meta.provider_record_counts
```

Expected after the AeroDataBox relay build is live: provider is `aerodatabox` or `aerodatabox+aviationstack`, `meta.schedule_provider_mode` is `auto`, and `meta.provider_record_counts` is present. If a cache miss still returns `provider=aviationstack` with `planner_version=fair-v3` and no provider-fusion meta, the app is still serving the older AviationStack-only relay build.

Optional synthetic report smoke test after secrets are live:

```powershell
$body = @{
  report_type = "manual"
  origin = "desktop"
  install_id = "00000000-0000-4000-8000-000000000001"
  install_fingerprint = "11e594f48195"
  title = "Relay smoke test"
  description = "Safe test from deployment checklist"
  app_version = "0.2.7"
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
radar_surface_enabled: bool = False
```

Config lives at `~/.localflight/config.json`

---

## Key API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/config` | Current server config |
| `PATCH /api/config` | Update config fields; broadcasts `config_updated`; restarts scheduler for airport/source/interval changes |
| `GET /api/fids` | JSON FIDS rows |
| `GET /api/fids/detail` | Per-callsign detail — live position + 7-day history + additive `flight-intel-v1` evidence model |
| `GET /api/radar` | Aircraft positions plus normalized safe display fields for real/VATSIM blips |
| `GET /api/radar/surface` | Airport surface geometry for the configured airport, capped to 1-5 NM; relay-cached OSM when available, labeled local estimate when not |
| `GET /api/metar` | Decoded + raw METAR plus Local Flight semantic weather mood/icon fields |
| `GET /api/history` | Recent flights from SQLite; supports `hours`, `direction`, `status`, `callsign`, `airline_iata`, and `limit` filters |
| `GET /api/history/flight` | Callsign history |
| `GET /api/history/summary` | Shared native/browser History analytics: delay buckets, status mix, airline delay quotas, routes, daily/hourly volume, aircraft stats |
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

Internal relay admin JSON endpoints, Basic Auth and admin-surface gated only: `GET /admin/api/overview`, `/admin/api/usage`, `/admin/api/fleet`, `/admin/api/schedules`, `/admin/api/surfaces`, `/admin/api/activations`, `/admin/api/reports`. Read payloads must stay redacted: no raw provider keys, raw activation tokens, report contexts/log tails, or raw install IDs. Operator write endpoints live under `/admin/api/providers/*`, `/admin/api/activation/*`, `/admin/api/counters/*`, `/admin/api/install/access`, and `/admin/api/maintenance/clean-trial`; token/install actions use opaque `action_ref` values from the redacted read payloads while request actions use `request_id`, and the relay resolves private hashes/IDs server-side.

---

## Building (PyInstaller)

```bash
python build.py           # generate icons + build + zip
python build.py --clean   # wipe dist/ and build/ first
```

Desktop release packaging now requires PySide6 and `LocalFlight.spec` explicitly collects PySide6 plus `localflight.native.*`, so Windows/macOS artifacts are native-GUI capable instead of depending on Chrome/Edge/Chromium.

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
- `installers/windows/install.ps1` and `installers/macos/install.sh` are source-checkout installers with explicit display-mode choices; release users should prefer the PyInstaller zip artifacts.

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
# Windows native-first dev launcher
.\start.bat

# Windows operator Network Admin
.\start_network.bat

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

## Current handoff for macOS / dev machine

- **macOS handoff focus (2026-05-13 / 0.2.7):** get the Mac onto the exact same source state as this Windows workspace before running the installer or packaging. If the Windows workspace still has uncommitted/unpushed native FIDS, radar, Matrix, Settings, installer, or docs changes, `git pull` on macOS will not see them. Push the branch/commit first, or transfer an explicit patch bundle; otherwise the Mac installer can rebuild an old app with missing FIDS details, missing radar ground/context drawings, stale Matrix/settings screens, or stale docs.
- **Stale Mac artifact warning:** do not trust an existing `~/Applications/LocalFlight.app`, old `.venv`, old `dist/LocalFlight.app`, or a previous editable install when validating current UI. If the Mac shows old FIDS behavior, no radar ground/context drawing, or old Settings layout, stop and confirm the Mac `git rev-parse --short HEAD` matches the expected Windows/current branch before debugging UI code.
- Start the Mac session with:
  ```bash
  git pull --ff-only
  git rev-parse --short HEAD
  git status --short
  rm -rf dist build ~/Applications/LocalFlight.app
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -e ".[native]"
  python -m compileall -q src relay installers scripts tests
  python -m pytest tests -q
  ```
- Native GUI is the recommended primary desktop shell now. On macOS, test `LOCALFLIGHT_GUI_MODE=native python -m localflight` or `./installers/macos/start.sh`; browser mode remains supported for LAN/browser display validation via `LOCALFLIGHT_GUI_MODE=browser`. The native window title should be `Local Flight`, not `Local Flight Native`.
- Native first-run setup is intentionally a standalone guided window before the main Display shell. It must keep the Diagnostics step, save `diagnostics_mode` through `/api/setup/complete`, preload the hosted relay root, and avoid exposing `/v1/flights` to users.
- Latest Windows-side native/browser polish to carry forward on Mac: setup/settings are dashboard-card based, the native shell uses the current grouped navbar/footer icon layout, FIDS displays city/country titles with passenger-friendly weather, FIDS and Radar details consume the shared current-source intelligence model, LAN radar matches the Qt layering/status behavior, History now shares the browser/native `/api/history/summary` analytics contract for filters, KPIs, delay buckets, status mix, airline delay quotas, route/aircraft stats, daily/hourly volume, and sortable recent rows, Matrix has panel presets/live preview feedback/compact weather header/gate display parity, stable Matrix flight labels/weather icons, and VATSIM Matrix hides unreliable gate placeholders. Focused verification after this pass: `.venv\Scripts\python.exe -m compileall -q src relay installers scripts tests` passed and `.venv\Scripts\python.exe -m pytest tests -q` returned `376 passed`.
- Native UI freshness checks on Mac after install/build:
  - FIDS must show city/country titles, passenger-friendly weather, airport-local row time labels, and the current styled/detail behavior, not the old host-clock/debug-table layout.
  - Radar must expose the current ground/context drawing path and surface-aware rendering; if the canvas lacks the current ground layer entirely, the Mac app is stale.
  - Matrix must show panel-preset choices, live preview feedback, compact weather header behavior, and real-only gate display controls; if it looks like the old long technical form, the Mac app is stale.
  - Settings must show the current dashboard-card/user-facing sections and display-mode wording; if it looks like the old crowded/dev Settings page, the Mac app is stale.
  - The macOS source installer should be run as `bash installers/macos/install.sh --display native` after the source is verified current; release users should use the rebuilt `LocalFlight.app`/zip, not an older source-built app in `~/Applications`.
- macOS packaging runbook:
  ```bash
  bash installers/macos/install.sh --display native
  python build.py --clean
  test -d dist/LocalFlight.app
  test -f dist/LocalFlight-macos.zip
  shasum -a 256 -c dist/LocalFlight-macos.zip.sha256
  ```
- Pi source release was rebuilt from the current tree as `dist/LocalFlight-pi-source-0.2.7.zip`. The Pi bundle intentionally excludes `AGENTS.md`, `CLAUDE.md`, and `DEV_README.md`.
- Mobile companion validation belongs on the Mac/Xcode machine: `cd mobile`, `npm install`, `npx expo install --fix`, `npm run typecheck`, `npm run doctor`, then `npm run ios`. Use a LAN server URL such as `http://localflight.local:8000` or the desktop/Pi IP; do not use phone-local `localhost`.
- Keep public/internal separation intact during the Mac pass: public docs may describe the native privacy-first GUI and user reporting, but should not expose operator Network Admin routes, Fly secrets, `DEV_README.md`, `AGENTS.md`, or raw relay admin paths.
- Active desktop/server version is `0.2.7`: `pyproject.toml`, runtime fallbacks, bundled release notes, and docs should all agree. Mobile companion metadata is still a separate developer-preview follow-up unless deliberately swept for the same release.
- Community relay root is live at `https://localflight-community-relay.fly.dev`. The client derives `/v1/schedule`, `/v1/radar`, `/v1/airport-surface`, `/v1/reports`, and activation routes internally; `/v1/flights` is raw-provider debug only.
- Relay admin panel: prefer Fly dashboard/CLI or `fly ssh console`. The local `start_network.bat` helper is operator-only and gitignored. Public admin access is optional and must stay password-protected; do not publish operator-only entrypoints in public docs.
- Chrome-free GUI foundation is now native-first by default: blank/invalid `LOCALFLIGHT_GUI_MODE` resolves to `native`, `platform/gui_launcher.py` verifies PySide6/Qt before native launch, display-attached Pi/Linux can use native fullscreen when installed through `--native-kiosk`, and browser/kiosk mode remains a supported LAN/browser display path for users who prefer or need it. Source installers now expose the display choice directly: Windows `install.ps1 -DisplayMode Native|Browser|Headless`, macOS `install.sh --display native|browser|headless`, and Pi `install.sh` prompts when no flag is passed while preserving `--headless`, `--native-kiosk`, and `--kiosk`. The native client now mirrors the browser/LAN UI structure with a top nav and user pages, loads the shared SVG splash/brand/preview media, embeds the public README/privacy/changelog reader inside Settings, has native setup/matrix/logs/traffic/report controls wired to declared local routes, connects to local `/ws` via QtWebSockets, and includes a required first-run Diagnostics step that saves `diagnostics_mode` through `/api/setup/complete` before the Display shell opens. Its design layer maps the same dark/light theme plus standard/technical/neon/cyan/crt skins into Qt styling and native canvas painters, so FIDS/Radar/Matrix no longer drift into a single debug palette. Native local API calls use a short TTL cache for duplicate-safe GET routes, mutate actions clear that cache, hidden canvases pause animation timers, and active-page polling is intentionally lighter than the browser UI. Network Admin remains a separate operator-only Qt shell backed by styled `/admin/api/*` relay read/action endpoints.
- Fly deployment: one warm machine in `fra`, one SQLite volume (`relay_data`), host-based public/admin gating in `relay/main.py`. Shared-schedule relay deploys must use the repo-root command `fly deploy --config relay/fly.toml --dockerfile relay/Dockerfile --remote-only -a localflight-community-relay` so the image includes `src/localflight`.
- AeroDataBox relay handoff: local code and tests now support AeroDataBox primary schedule, AviationStack sparse fill/fallback, hard upstream caps, provider source caches, stale merged cache serving, and web/Qt canonical FIDS compilation. The deployed Fly relay was last observed still serving the older AviationStack-only `fair-v3` shape; after redeploy, verify a fresh cache lane returns `provider=aerodatabox` or `aerodatabox+aviationstack` plus `meta.schedule_provider_mode=auto`.
- Mobile Expo/TypeScript validation belongs on the Mac/Xcode side after `npm install` unless Node/npm are installed on the current dev machine.
- Desktop resume on Windows: run `.\start.bat`, confirm Community setup preloads the hosted relay URL, then verify FIDS/radar/admin against the live relay contract.
- Release resume: Windows and Pi artifacts were rebuilt from the current `0.2.7` Windows checkout; macOS still needs a fresh Mac build before creating GitHub release `v0.2.7`. Older `0.2.6` artifacts and checksums are stale after the native shell/FIDS polish.
- Windows/Pi release installer policy: Windows source installs are native Qt first unless `-DisplayMode Browser|Headless` is selected and always write a client-only `.env`; Pi installs default/prompt to headless, write `LOCALFLIGHT_GUI_MODE=native` only for `--native-kiosk`, and keep the backend service forced headless while the user-session Qt service uses `LOCALFLIGHT_NATIVE_FULLSCREEN=1` plus `LOCALFLIGHT_NATIVE_UI_ONLY=1`. `--kiosk` starts only the Chromium browser display service while the Python app stays headless.
- `scripts/package_pi_source.py` now excludes internal handoff-only files (`AGENTS.md`, `CLAUDE.md`, `DEV_README.md`) from the Pi source zip even if they are tracked locally, and includes non-ignored local additions so pre-release hardware bundles do not miss newly added modules before commit.
- Settings now split install/relay state, flight setup, app controls, and diagnostics/resources into clearer sections; the community relay card now reports active relay usage truthfully, and the docs buttons open bundled local files through `/docs/readme`, `/docs/install`, `/docs/display-modes`, `/docs/privacy`, and `/docs/changelog`.
- macOS packaging still needs a fresh `0.2.7` pass on the Mac workspace: `python build.py --clean`, verify `dist/LocalFlight.app`, `dist/LocalFlight-macos.zip`, and `.sha256`, then smoke the native app for the latest History/Matrix/Settings/FIDS/Radar behavior. The macOS artifact is expected to be unsigned Apple Silicon/ARM64 unless signing/universal packaging is deliberately added later.
- Mobile companion metadata remains at `0.2.6` until the companion gets its own release sweep; independent mobile appearance, server-backed Matrix runtime editor, landscape split display, responsive radar, and pinch zoom are implemented in code.
- Mobile companion polish pass is in progress on top of that: main nav is now FIDS/Radar/Settings only, History/Matrix/Admin/Docs are Settings-launched tools, the pinned-flight island is compact and theme-aware, Settings is sectioned, docs read inside the app, airport/profile saves request a scheduler restart, and flight details consume the expanded `/api/fids/detail` contract.
- Desktop flight-detail enrichment pass started first: `/api/fids/detail` now returns richer stored snapshot metadata for live track/source coverage without new external calls, and the desktop FIDS drawer renders operations/aircraft, source confidence/freshness, and position fields more clearly.
- VATSIM detail completeness pass keeps useful filed-plan fields in canonical snapshots: flight rules, planned route, cruise altitude/TAS, planned departure/arrival, enroute time, alternate, and assigned transponder. Intentionally does not store pilot names/CIDs.
- VATSIM privacy rule is explicit: use virtual-network data as flight information only. Do not store/display pilot names, controller names, CIDs/account IDs, server names, or other person-identifying VATSIM fields; callsign, aircraft, filed route/plan, airport/timing data, and aircraft position are okay.
- Desktop FIDS detail drawer now has real vs virtual modes: real flights show airport operations/aircraft/source freshness, while VATSIM flights show virtual flight plan/network/aircraft track labels and suppress real-world-only emphasis.
- Mobile detail communication stays server-mediated: the companion calls `/api/fids/detail` and does not call AviationStack, ADS-B Exchange, RapidAPI, or the hosted relay endpoints directly.
- Mobile automatic diagnostics now includes critical detail communication failures (`5xx` or malformed JSON) through diagnostics-gated `/api/feedback/crash`; feature-specific reports keep companion identity, app version, device type, and server URL in the client context. Mobile also has its own SecureStore diagnostics choice, so auto-reporting requires both mobile and server consent.
- Linear developer reporting now goes through relay `POST /v1/reports`; no developer Linear API key/team ID is shipped in the packaged desktop or companion app. Relay secrets required: `LINEAR_REPORTER_API_KEY`, `LINEAR_TEAM_IOS_ID`, `LINEAR_TEAM_DESKTOP_ID`, `LINEAR_TEAM_SERVER_ID`, `LINEAR_TEAM_RELAY_ID`, and `LINEAR_TEAM_DEFAULT_ID`.
- Security sweep hardening is now staged in code: relay community schedule/radar access has network/global daily caps, Fly client IP handling no longer trusts spoofable `X-Forwarded-For`, admin Basic auth has failed-login throttling, local setup relay URLs are validated before server-side calls, and browser cross-origin local mutations are blocked.
- Mobile structure refactor is complete enough for handoff: `App.tsx` is a provider entrypoint, `src/app/AppShell.tsx` coordinates state/refresh, pure helpers live in `src/domain/`, stateful behavior in `src/hooks/`, and screens/sheets in `src/screens/AppScreens.tsx`.
- Mobile validation: `npm run typecheck` passes; `npm run doctor` is 17/18 after adding `expo-font` and updating Expo to `~55.0.19`. Remaining doctor failure is environment-only: Expo SDK 55 reports Xcode `16.3.0` incompatible and requires Xcode `>=26.0.0`.
- Mobile resume on Mac/Xcode: resolve the Xcode/Expo SDK compatibility issue first, then run `npm run doctor` and `npm run ios`. Expo Go may reject SDK 55 depending on installed Expo Go; simulator/dev build is the safer path.
- Windows-side AviationStack reliability pass is now documented in public/internal docs. Important: the local board/filter bug is fixed, but some live airports can still show sparse future departures because AviationStack itself does not return enough near-term rows even after fair paging plus undated rescue. Current observed example: `ZRH` on `2026-05-01`.
- Sparse-board UX fallback is now active on the client: if a real-data lane has no rows inside the live window, the board shows the nearest available real flights instead of an empty departures page. Current live local check after the patch: `/api/fids?view=departures` returned `20` rows again.
- Verification after the `0.2.7` native shell/FIDS polish and Matrix display-integrity repack is green on this Windows workspace: `.venv\Scripts\python.exe -m compileall -q src relay installers scripts tests`, `.venv\Scripts\python.exe -m pytest tests -q` (`376 passed`), `pip check`, and `pip list --outdated --format=json` (`[]`). Windows and Pi artifacts were rebuilt after this sweep; macOS remains the missing platform artifact.

## What was done in the latest session (v0.2.8b1 — GUI visual refresh)

> Dated 2026-05-16. No data flow, route, or content changes — pure chrome /
> motion / iconography upgrade on top of the 0.2.7 baseline. Versioned as
> `0.2.8b1` in CHANGELOG.md so 0.2.7 stays the released line until this beta
> is verified on every platform. `pyproject.toml` is still pinned to `0.2.7`;
> bump to `0.2.8b1` when the next packaging pass kicks off.

- **Setup wizard (native first-run)** — `pages/setup.py` + new `pages/setup_widgets.py`. The numbered step buttons became an animated stepper widget (numbered circles + fill-line + pulsing current-step halo + ✓ for done). Welcome page now shows a floating logo with concentric radar rings and a tagline that fades in. Page transitions fade in ~200 ms. The thin marquee progress bar was replaced with a rotating-glyph (◐◓◑◒) spinner whose caption syncs to the live busy status. Every form field has an inline `ⓘ` info bubble. All four masked secret fields gained a 👁/🙈 eye toggle. Nav/action buttons carry emoji prefixes (🚀 Start · ▶ Next · ◀ Back · ✅ Finish · 🌐 LAN setup · 📨 Request · 🔄 Check · 🧪 Test). Finish plays a 260 ms ✅ celebration overlay before handoff.
- **Main shell — unified design language** — new `shell_widgets.py` module exposing `make_pill`, `set_pill`, `make_spinner`, `make_info_button`, `make_page_hero`, `show_toast`, `fade_swap`. The shell's `_show_page` now uses `fade_swap` so pages fade in/out instead of swapping instantly. The shared `_loading_indicator` factory returns the same rotating-glyph spinner the setup wizard uses (six pages now use it: Admin / Requests / History / Logs / Feedback / Settings / Radar / FIDS). Admin / History / Logs / Feedback / Requests adopted a unified `PageHero` band (emoji + title + subtitle + ⓘ helper + "Last refreshed HH:MM:SS" pill + status pill + action buttons). Toasts slide in bottom-right on refresh / send completions.
- **FIDS board styles** — new `pages/fids_styles.py` with four `FidsStyle` descriptors. **Classic** (default — unchanged behavior), **PAX** (big rows, friendly verbs like "Boarding now" / "Running late"), **VATSIM** (callsign-first, flight rules, phase TAXI/CLIMB/CRUISE/DESCENT, alt/GS compact field), **Nerd** (dense operator view: every column, monospace, code-style tokens BRD/DEP/LND/CXL). 4-segment selector in the FIDS header (🛬 Classic · 🧳 PAX · 🛩 VATSIM · 🤓 Nerd). Persists per-install via `QSettings("LocalFlight","Native").value("fids/style")`. `FlightBoardModel` is now style-aware: takes `columns` + `status_vocabulary` per instance, gained `set_columns()` and `set_status_vocabulary()`. `_display_value` handles new column keys (`callsign`, `flight_display`, `registration`, `altitude_ft`, `ground_speed_kt`, `alt_speed`, `squawk`, `flight_rules`, `phase`, `delay_label`, `source`). Status text routes through `translate_status` to produce friendly / phase / code variants per style.
- **Centralised emoji language** — `design.py` now owns three dicts: `NAV_GLYPHS` (page nav), `WEATHER_EMOJI` (single source replacing three duplicates across `fids.py`/`radar.py`/`_legacy_app.py`), `SECTION_EMOJI` (31 entries for section headers / status cards / FIDS row icons / setup options). Plus a `paint_emoji` helper for QPainter rendering. Result: every page nav, every weather strip, every FIDS row icon, every Settings status card, and every section header on Admin/History/Logs/Feedback/Requests now uses color emoji. Nav glyphs swapped from obscure Unicode (`◴` / `≡` / `▣` / `≋` / `⇁`) to readable emoji (📺 / 🛫 / 🛰 / 🟩 / ⚙️ / 🛠 / 📅 / 📜 / 💬 / 🔧).
- **Official brand assets** — replaced ad-hoc folder/cup icons with official SVGs from GitHub and Buy Me a Coffee. `support-repository.svg` = white GitHub Invertocat (used on dark theme), `support-repository-dark.svg` = black GitHub Invertocat (used on light theme); `_apply_design_from_config` swaps the right variant live on theme change. `support-coffee.svg` = official BMC cup logo. `support-coffee-button.svg` = official BMC button (available for any future larger CTA).
- **QSS additions in `design.py`** — `Pill[tone="*"]`, `PageHero` + `PageHeroEmoji/Title/Subtitle`, `ShellSpinner` / `SetupSpinner`, `ShellInfoButton` / `SetupInfoButton`, `SetupEyeButton`, `ShellToast[tone="*"]`, `PrimaryCTA` / `SetupPrimary`, `FidsStyleButton` (segmented), `SetupOptionCard:hover` with deeper `[selected="true"]:hover`, `SetupStepCaption`, `SetupFieldLabel`.
- **Files added** — `src/localflight/native/shell_widgets.py`, `src/localflight/native/pages/setup_widgets.py`, `src/localflight/native/pages/fids_styles.py`, plus four official brand SVGs in `src/localflight/ui/static/`.
- **Files modified** — `src/localflight/native/design.py` (emoji dicts + paint_emoji + many new QSS rules), `src/localflight/native/models.py` (FlightBoardModel column/vocabulary parameterisation), `src/localflight/native/_legacy_app.py` (`_show_page` uses fade_swap, `_loading_indicator` returns shared spinner, PageHero applied to Admin/Requests/History/Logs/Feedback, theme-aware GitHub icon, More button glyph `⋯`, brand-mark fallback `🛫`, section labels and panel titles gained emoji prefixes, duplicate weather glyph dict deleted), `src/localflight/native/pages/fids.py` (emoji `_draw_icon`, style selector, `set_fids_style`), `src/localflight/native/pages/radar.py` (uses central WEATHER_EMOJI), `src/localflight/native/pages/settings.py` (status-card icons render emoji), `src/localflight/native/pages/setup.py` (full wizard refresh), `src/localflight/ui/setup_guidance.py` (option icons → emoji).
- **Phase 4 deferred polish** (intentionally NOT in this beta — see "Pending / next up — Native GUI refresh Phase 4 (deferred polish)" below): animated KPI counters on Admin/History cards; matrix flap-board boot animation; top-nav sliding underline; per-page empty-state cards; per-column custom paint methods for the VATSIM/Nerd-only columns (currently they fall back to plain text); honoring `style.row_height` and `style.font_scale` in the delegate's `sizeHint`; broader toast coverage (theme change, save, network status).
- **Verification** — `python -m py_compile` clean across every touched file. Generated stylesheet contains all new selectors (`Pill[tone="good"]`, `PageHero`, `ShellSpinner`, `ShellInfoButton`, `ShellToast`, `PrimaryCTA`, `FidsStyleButton`, plus the setup-side `SetupSpinner` / `SetupInfoButton` / `SetupEyeButton` / `SetupPrimary` / `SetupOptionCard:hover`). FIDS style registry exposes `['classic', 'pax', 'vatsim', 'nerd']` with `classic` as default — existing users see zero behavior change unless they opt in.
- **Cross-platform handoff for this beta** — Windows workspace is the source of truth for the 0.2.8b1 diff. macOS + Pi need fresh source pulls and fresh packaging passes; the rebuilt artifacts from 0.2.7 do NOT include any of this refresh. Mobile companion is untouched by this work — it stays on its independent track.
- **Re-run the pytest suite + package builds** before tagging 0.2.8 final: `.venv\Scripts\python.exe -m compileall -q src relay installers scripts tests`, `.venv\Scripts\python.exe -m pytest tests -q`, then Windows / macOS / Pi packaging runs as usual.

## What was done in the previous session (v0.2.7)

- Native shell composition was polished around grouped nav, centered UTC/LT clocks, tooltip-only sync status, icon-only support links, and a compact version/privacy footer.
- FIDS header behavior now uses city/country display names only, passenger-friendly weather, readable ARR/DEP/Refresh actions, long-label clamping, operating-first flight identity, and compact aircraft codes on the board.
- Native and browser/LAN History, Matrix, Settings, Setup, FIDS details, Radar details, and Matrix generated MicroPython paths remain the release-candidate parity areas.
- Current-source flight intelligence remains the shared detail direction for FIDS/Radar/History: current schedule, live motion, aircraft, airport ops, weather context, source evidence, and recent history are merged from existing sources without new paid calls.
- Public release notes, README, install/display-mode docs, and handoff docs were refreshed for the `0.2.7` client-polish release candidate.
- Verification from the Windows workspace: `python -m compileall -q src relay installers scripts tests` passed and `python -m pytest tests -q` returned `376 passed`.
- Windows and Pi artifacts were rebuilt after the final `0.2.7` polish; macOS still needs a fresh package pass before a full cross-platform GitHub release.

## Archived latest-session notes from v0.2.6

- ✅ Version sweep completed to `0.2.6` across Python metadata/runtime fallbacks, PyInstaller fallback/spec docs, mobile metadata/package lock, preview/release docs, README, privacy notes, changelog, and bundled docs.
- ✅ Native and browser/LAN History now share a richer analytics contract: filters, KPIs, delay buckets, status mix, airline delay quotas, top routes/aircraft, daily/hourly volume, sortable recent rows, and cleaner detail surfaces.
- ✅ Native and browser/LAN Matrix now share panel presets, live preview overrides, friendlier setup/apply/generate feedback, compact weather header behavior, and real-source gate/stand display. VATSIM Matrix presets intentionally hide gate placeholders.
- ✅ Current-source flight intelligence is now the shared detail direction for FIDS/Radar/History: current schedule, live motion, aircraft, airport ops, weather context, source evidence, and recent history are merged from existing sources without new paid calls.
- ✅ Native and browser/LAN Settings/setup were polished around dashboard-card controls, safer theme/skin contrast, cleaner brand/icon usage, and hidden advanced sections.
- ✅ Dependency refresh completed in the Windows venv; `pip check` passed and no outdated packages remained before packaging.
- ✅ Rebuilt release artifacts from the Windows workspace: `dist/LocalFlight-windows.zip` plus `.sha256`, and `dist/LocalFlight-pi-source-0.2.6.zip` plus `.sha256`. Zip content and version metadata were verified.

## What was done in the latest session (v0.2.5)

- ✅ Version sweep completed to `0.2.5` across Python metadata/runtime fallbacks, mobile metadata, preview badges, README, privacy notes, changelog, and tests.
- ✅ Matrix b5 work is now separated from the b4 native/relay/radar pass in the changelog. b4 remains the boundary for features that landed before the Matrix polish wave; b5 owns the Matrix updates.
- ✅ Matrix public presets are cleaned to exactly three profiles: `real_fids`, `vatsim_pilot`, and `vatsim_atc`. Legacy names remain accepted as config aliases.
- ✅ Matrix VATSIM presets are source-guarded. `vatsim_pilot` and `vatsim_atc` require app source `virtual`, do not fetch real FIDS, and do not fall back to real METAR.
- ✅ Matrix feed now carries route-safe fields, passenger-friendly airport city labels, decoded weather display fields, page-aware VATSIM ATC payloads, and a weather toggle (`options.show_metar` / `show_weather`).
- ✅ Web and native Matrix tooling now save/generate the same current MicroPython client assumptions, including the native Generate main.py button path.
- ✅ Generated `main.py` supports small-panel-safe rows, rectangular HUB75 layouts, codeshare cycling, route-code preservation, status breathing, decoded weather glyphs, VATSIM ATC page rotation, server-synced clocks, and board check-in/config assignment.

## What was done in session v0.2.5b4

- ✅ Version sweep started for `0.2.5b4` across Python metadata/runtime fallbacks, mobile metadata, setup defaults, source installers, README, changelog, dev reference, and tests.
- ✅ Community relay setup now shows the human-friendly root URL `https://localflight-community-relay.fly.dev`; the client still derives `/v1/schedule`, `/v1/radar`, `/v1/reports`, and activation routes internally.
- ✅ Relay admin can now clean setup-trial clutter without wiping provider keys, managed tokens, blocked installs, or monthly usage counters. The cleanup clears transient request logs, activation-request rows, live client lanes, shared schedule snapshots, and report event/dedupe noise.
- ✅ Relay admin live-lane crash fix remains included: snapshot stats tolerate missing counter fields and older relay DBs get migration-safe schedule snapshot counter columns.
- ✅ Fly relay redeployed on image `deployment-01KQJM7HKYXMF8EDRKFY24A7S9`; live `/health` returned ok, live admin HTML rendered with the cleanup button, and the live setup-trial cleanup was run. Transient tables now read `0` rows each; monthly usage counters were preserved (`usage` count was `30` after cleanup).
- ✅ FIDS row ordering now uses full airport-local datetimes instead of visible `HH:MM` text, so cross-midnight arrivals/departures stay in real chronological order during page rotation.
- ✅ FIDS now labels the board column as `Time (LT)` and shows a neutral schedule-fetching/relay-warmup hint when the table is empty while data may still be loading.
- ✅ Real-data radar now filters surface/ground aircraft from `/api/radar`; the radar status line reports how many ground blips were hidden. VATSIM still keeps virtual ground aircraft visible by design, but now uses exact circular range cropping.
- ✅ Tiny real-data radar views now request the shortest practical ADS-B provider radius (`5 NM`) and crop locally for 1 / 2 / 3 NM display rings, avoiding empty provider responses while keeping the visual range tight.
- ✅ VATSIM radar uses the same exact circular local range crop for 1 / 2 / 3 NM views. It still fetches the whole public VATSIM feed once and does not need a provider-radius funnel.
- ✅ Ground radar surface overlay is staged but policy-safe by default: Settings exposes `radar_surface_enabled` defaulting off, local `/api/radar/surface` can serve cached OSM-derived geometry capped to 1-5 NM, relay `/v1/airport-surface` coalesces/caches Overpass requests only when `RELAY_AIRPORT_SURFACE_ENABLED=1`, and `radar.html` draws airport boundary/runways/taxiways/aprons/terminals plus selected terminal/hangar-style building outlines with visible OpenStreetMap attribution. The browser only calls the surface endpoint when the setting is enabled, and the visible radar now offers tight 1/2/3 NM ground ranges with skin-aware overlay colors. Clean first-run installs now get a clearly labeled `localflight-estimated` fallback surface if the relay cache is disabled/empty and no stale local OSM cache exists.
- ✅ Standalone Radar now auto-fills the available viewport below the actual nav height instead of using fixed chrome math. The shared nav can horizontally scroll compact button groups on narrow screens, and the radar controls/weather strip compact for 7-10 inch Pi panels while still scaling up cleanly on wall displays.
- ✅ METAR weather decoration now stays aviation-native: `metar_client.py` still fetches AviationWeather METAR, `decode/metar.py` derives Local Flight condition/icon/tone/summary/hazards/chips, and FIDS/Radar/Admin render the additive weather mood without touching the mobile companion yet.
- ✅ `/api/metar` now uses VATSIM ATIS/METAR first when `source=virtual`, falls back to real AviationWeather METAR when unavailable, and only extracts the METAR line so controller names/CIDs are not exposed.
- ✅ FIDS weather now renders icon + temperature + decoded summary only; Radar keeps icon/category/temperature/summary plus raw METAR for the scope view.
- ✅ 1-5 NM radar views now behave as surface radar and hide airborne/overflying aircraft for both real ADS-B and VATSIM; wider real-data radar views still hide ground targets and focus airborne.
- ✅ FIDS rows now decode common airline IATA/ICAO/callsign prefixes into readable airline names, format the public flight number consistently, and preserve deduped codeshare partners as `Also ...` rows/detail metadata.
- ✅ New airline/codeshare helpers live in `src/localflight/decode/mappings/airlines.py`; the FIDS API now includes `airline_display`, `codeshare_display`, and detail-level `codeshares`.
- ✅ VATSIM privacy guard is now tested/documented: virtual traffic ingestion drops person-identifying feed fields such as names, CIDs/account IDs, and server names; the desktop detail label now says “Aircraft Track” instead of “Pilot Track.”
- ✅ Native GUI launch is now platform-layered: `gui_mode.py` parses the requested mode, `gui_launcher.py` resolves native/browser/headless from platform + display + PySide6/Qt availability, and `__main__.py` logs the resulting `GuiLaunchDecision` before dispatch.
- ✅ Windows/macOS source launchers and PyInstaller builds now install/verify PySide6/Qt for native mode, while Pi stays headless by default and adds an explicit `installers/pi/install.sh --native-kiosk` path for experimental Qt HDMI kiosk testing.
- ✅ Native Qt parity pass replaced the side-list/debug shell with a browser-like top nav, Display-first split/FIDS/Radar views, native setup wizard, Matrix canvas/runtime/script tooling, Logs file selector/live tail, traffic log tool, sectioned Settings/Admin/History/Feedback pages, shared native design tokens, and a route registry that validates every client/operator button path in tests. FIDS/Radar refreshes now run off the Qt UI thread so slow local API/provider calls do not freeze the native shell. Native Radar projects API `center` + `lat/lon` blips like the browser canvas and has a sweep animation; native Settings/Setup use `/api/airports/search` for the airport picker and fill IATA/ICAO/timezone instead of asking for manual entry. Native Qt uses PySide6 QtWebSockets for the same `/ws` live-push contract as the browser/LAN UI. The latest UI/UX parity refinement maps browser theme/skin choices into Qt, reloads styling from `/api/config`, applies skin palettes to FIDS/Radar/Matrix renderers, gives the top nav horizontal compact scrolling for small Pi-sized displays, caches duplicate-safe native GET calls briefly, dedupes repeated airport searches, pauses hidden Radar/Matrix animation timers, backs active refresh polling off to 30 seconds, and makes first-run diagnostics/reporting consent a saved setup step instead of a loose later prompt.
- ✅ Native GUI polish for Mac handoff: main window title now reads `Local Flight`; the setup wizard has centered, narrower, branded pages instead of huge fullscreen-dependent fields; FIDS labels/updates airport-local time; FIDS columns adapt better to window width; Client Admin removed the crowded Quick Tools block and keeps the support link in a quiet footer; History now combines filters, callsign lookup, statistics, and capped recent rows in one user-facing view; Logs now highlights retained log-file browsing plus live-tail state.
- ✅ Native History stats no longer clears the live period selector during refreshes, fixing a Qt lifecycle crash risk. Native `/api/logs` metadata now lets the Logs page match the web log selector without scraping HTML.
- ✅ Linear/reporting pass confirmed no new GUI/kiosk/headless route families are needed. Native Qt manual reports now post to local `/api/feedback` with richer `native/gui` context, `_NativeCrashReporter` sends diagnostics-gated Qt/Python UI exceptions through local `/api/feedback/crash`, and both `bug_reporter.py` plus relay `main.py` normalize `native/gui` into the desktop/user report bucket. Live relay smoke on 2026-05-02 created `LOC-45` in `Local Flight Reports` and the repeat returned `deduped=true`.

## What was done in session v0.2.5b3

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
- ✅ Relay admin was updated and redeployed from Windows so the operator page now shows `/v1/reports` gateway health, 24h report filed/deduped counts, recent report events, and report dedupe groups. Fly deploy succeeded on image `deployment-01KQJF7D3NH7CTWQQWYKHBN8FM`; `/health` returned ok and public `/v1/flights` still returns `404`.
- ✅ Relay admin live-lane crash fixed and redeployed after Pi clean-install testing exposed a no-snapshot lane: `_snapshot_shared_stats()` now tolerates missing snapshot counters, `schedule_snapshots` counter columns are migration-safe, and auto-activation network burst caps can be tuned through Fly secrets (`RELAY_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT`, `RELAY_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT`). Fly deploy succeeded on image `deployment-01KQJK5R9JZDY7W6Q125F9GPZ3`; `/health` returned ok and live admin HTML rendered against the production volume.
- ✅ Reality check after the fix: the Local Flight fetch/filter bugs were corrected, but live `ZRH` departures on `2026-05-01` still remained sparse after the stronger fetch strategy. That remaining gap is currently documented as upstream AviationStack coverage behavior, not a known unresolved client filter bug.
- ✅ Client FIDS now falls back to the nearest available real rows when a sparse provider window would otherwise render `0` departures or arrivals, so the board stays useful even when AviationStack only returns older rows for that lane.
- ✅ Security/privacy abuse sweep pass: relay community traffic now has daily network/global caps in addition to install quotas; relay admin login attempts are throttled; setup-provided relay URLs are restricted to official/default roots unless custom/private dev flags are set; local browser cross-origin mutations are rejected; report routing now honors explicit platform origins before iOS inference; diagnostics wording now describes the hosted relay reporting gateway.
- ✅ macOS release packaging for `0.2.5b3` is complete on the Mac side: clean PyInstaller build, checksum verification, `Info.plist` version check, ARM64 executable check, on-disk codesign verification, and macOS installer script syntax checks passed.
- ✅ Pi source package for `0.2.5b3` is complete on the Mac side and no longer includes internal handoff files in the generated release zip.
- ✅ Windows release EXE silent-start failure fixed: PyInstaller windowed builds now bootstrap writable stdio to a local `~/.localflight/logs/bootstrap_<pid>.log`, preventing uvicorn/logging startup from failing before `/health` and the browser window come up. Fresh ZIP smoke test passed.

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
- ✅ `DEV_README.md` is present again as the private operator/dev reference; keep it aligned with `AGENTS.md` and `CLAUDE.md` for AI handoff context. Pi source releases still use `python scripts/package_pi_source.py` and exclude internal handoff docs.

## What was done in session v0.2.3b2

- ✅ Hosted relay defaults centralized in `relay_defaults.py` and wired through the desktop clients, setup flow, and installers.
- ✅ `relay/main.py` hardened for Fly.io: port `8080`, FastAPI lifespan startup, `/health`, host-based public/admin gating, and reduced relay-side metadata writes.
- ✅ `relay/fly.toml` updated for explicit `relay/` deployment, one warm `fra` machine, and a public/operator hostname split.
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

- [x] Build the Windows artifact on the Windows dev machine for `v0.2.7`: `python build.py --clean`, verify `dist/LocalFlight-windows.zip.sha256`, and confirm the zip carries `localflight-0.2.7.dist-info`.
- [x] Build the Pi source artifact for `v0.2.7`: `python scripts/package_pi_source.py`, verify `dist/LocalFlight-pi-source-0.2.7.zip.sha256`, and confirm internal handoff docs are excluded.
- [ ] Build the macOS artifact from the same `0.2.7` source state, then create the GitHub release `v0.2.7` and attach Windows, macOS, and Pi artifacts plus all matching `.sha256` files.
- [ ] Register custom domain and wire the public relay hostname plus operator admin hostname DNS to `localflight-community-relay.fly.dev`; run `fly certs add` for both.
- [ ] End-to-end community client activation test against live relay.
- [x] Sparse AviationStack airport next step is implemented as the AeroDataBox/fusion/cache-hardening path: AeroDataBox is primary when configured, AviationStack is sparse fill/fallback, and stale merged cache can serve instead of replacing a healthy board with suspiciously thin data.
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

## Pending / next up — Native GUI refresh Phase 4 (deferred polish)

Phases 1–3 of the Qt main-shell visual refresh shipped on 2026-05-16:
- Phase 1: shell_widgets.py (Pill, Spinner, InfoButton, PageHero, Toast, fade_swap) + design.py QSS
- Phase 2: PageHero/Pill/Toast applied to Admin / History / Logs / Feedback / Requests
- Phase 3: fids_styles.py with CLASSIC / PAX / VATSIM / NERD descriptors, style-aware FlightBoardModel, 4-segment selector in FIDS header, persistence via `QSettings("display/fids_style")`. Default = CLASSIC.
- Plus: official GitHub Invertocat + Buy Me a Coffee SVGs swapped in for the footer icons (with theme-aware switching between black/white invertocat).

Phase 4 (NOT yet implemented — pick up later):
1. **Animated KPI counters** on Admin + History KPI cards — tween the numeric value when it changes (QPropertyAnimation on a custom `value` property of a small QLabel subclass).
2. **Matrix flap-board boot animation** — stagger each character on first paint, then settle to live data.
3. **Top nav sliding underline** — paint-only animated underline that glides between active nav buttons on `_show_page`.
4. **Empty-state cards** — when a page returns no data, show a big emoji + guidance text + "Refresh" button (e.g. FIDS "no departures in the window", Logs "no log files retained").
5. **Per-column paint methods in `_FidsBoardDelegate`** for the new VATSIM/Nerd columns (callsign, registration, alt_speed, phase, squawk, delay_label, source). Currently those columns fall back to `_paint_plain` which draws DisplayRole text — functional but not styled per-column. Adding `_paint_callsign`, `_paint_alt_speed`, `_paint_phase` etc. would give NERD/VATSIM the same level of polish CLASSIC already has.
6. **Honor `style.row_height` and `style.font_scale` in the delegate sizeHint** — currently `sizeHint` returns a fixed 48/62/70 height. Reading from the active style would make NERD truly dense and PAX truly chunky.
7. **Toast notifications on more events** — saved settings, theme change, network status changes. Right now toasts only fire for history/logs/feedback/requests/admin refresh.

Files involved (for orientation):
- `src/localflight/native/shell_widgets.py` — shared visual primitives
- `src/localflight/native/pages/fids_styles.py` — FIDS style descriptors
- `src/localflight/native/pages/fids.py` — board page, has the style selector + `set_fids_style()` method
- `src/localflight/native/models.py` — FlightBoardModel: now takes `columns` + `status_vocabulary` per-instance, gained `set_columns()` / `set_status_vocabulary()`
- `src/localflight/native/design.py` — QSS for Pill / PageHero / ShellSpinner / ShellInfoButton / ShellToast / PrimaryCTA / FidsStyleButton
- `src/localflight/native/_legacy_app.py` — `_show_page` uses fade_swap, `_loading_indicator` returns the new spinner, footer GitHub icon picks theme-aware variant
