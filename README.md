# Local Flight

A **local-first Flight Information Display System (FIDS)** that runs on Windows, macOS, or a Raspberry Pi.
Fetches real and simulated flight data and renders it as a proper airport-style departure/arrival board — in your browser, on an LED matrix panel, or on a dedicated HDMI screen.

No cloud. No accounts. No dashboards that want your email.

**Source:** [github.com/tr3y4rch/local-flight](https://github.com/tr3y4rch/local-flight)

---

## What it does

- Fetches live flight data from **AviationStack** (real schedules), **VATSIM** (flight sim traffic), or **ADS-B Exchange** (live positions via RapidAPI)
- Enriches schedule data with **live aircraft positions** from ADS-B Exchange (primary) or OpenSky Network (fallback)
- Decodes live **METAR weather** for the configured airport — shown on the FIDS board and radar
- Renders a full-featured **FIDS arrivals/departures board** with PAX-friendly flight numbers, coloured status badges, and live WebSocket updates
- Shows a **live radar** with sweep animation and blip fading
- Provides a **split-view display** (FIDS + Radar) with a draggable divider
- Shows a short **versioned splash screen** on launch before opening setup or the display
- Includes an early **mobile companion prototype** for LAN viewing and control experiments; public iOS and Android releases are planned for a later milestone
- Stores 90 days of flight history in a local **SQLite database** with a browsable history UI and aggregate stats
- Supports **profiles** — save and switch airport configurations instantly
- Displays **UTC and local time** simultaneously, timezone follows the configured airport
- **First-run setup wizard** guides through airport selection, optional API keys, and display settings
- **Admin hub** — scheduler controls, API budget tracking, anonymized traffic log, connected clients, system status
- Runs as a **system tray app** on Windows and macOS; headless on Raspberry Pi with a Chromium kiosk
- Ships a **MicroPython client** for the Pimoroni Interstate 75 W LED matrix panel
- **In-browser matrix preview** — see exactly what the LED panel will show, with split-flap animation

---

## Preview

These are lightweight illustrative previews with sample data, not live telemetry screenshots. They show the current desktop and mobile companion direction so the README has useful example pictures even before someone runs the app.

Open [docs/previews/index.html](docs/previews/index.html) locally for the standalone HTML gallery.

<p align="center">
  <img src="docs/previews/fids-preview.svg" alt="Local Flight FIDS preview" width="32%">
  <img src="docs/previews/radar-preview.svg" alt="Local Flight radar preview" width="32%">
  <img src="docs/previews/settings-preview.svg" alt="Local Flight settings preview" width="32%">
</p>

<p align="center">
  <img src="docs/previews/mobile-fids-preview.svg" alt="Local Flight companion FIDS preview" width="32%">
  <img src="docs/previews/mobile-radar-preview.svg" alt="Local Flight companion radar preview" width="32%">
  <img src="docs/previews/mobile-settings-preview.svg" alt="Local Flight companion settings preview" width="32%">
</p>

---

## Install

### Windows

1. Download `LocalFlight-windows.zip` from the [latest release](https://github.com/tr3y4rch/local-flight/releases)
2. Unzip to any folder
3. Double-click `LocalFlight.exe`
4. Complete the setup wizard

> Windows SmartScreen may warn "Unknown publisher" — click **More info → Run anyway**.

The Windows release zip is self-contained. It bundles Python and the app dependencies, so `installers/windows/install.ps1` is only for running Local Flight from a source checkout.

Release builds also produce `LocalFlight-windows.zip.sha256` so the downloaded zip can be verified before running.

### macOS

1. Download `LocalFlight-macos.zip` from the [latest release](https://github.com/tr3y4rch/local-flight/releases)
2. Unzip it
3. Drag `LocalFlight.app` to Applications
4. Right-click → Open on first launch if macOS Gatekeeper warns about an unsigned app

Release builds also produce `LocalFlight-macos.zip.sha256` so the downloaded zip can be verified before running.

The macOS source installer is only for running Local Flight from a source checkout:

```bash
bash installers/macos/install.sh
```

### Raspberry Pi

Run these from a source checkout on the Pi. The installer creates the venv, `.env`, systemd app service, Chromium kiosk service, and mDNS hostname.

```bash
# One-time setup
bash installers/pi/install.sh

# Management
./installers/pi/lf.sh start   # start
./installers/pi/lf.sh stop    # stop
./installers/pi/lf.sh logs    # tail logs
./installers/pi/lf.sh update  # pull latest + restart
```

The Pi runs headless — access the UI from any device on your network at `http://localflight.local`.

---

## Mobile companion

The mobile companion is an **iOS-first beta companion** for Local Flight. It is not required to use the main app, and there is still no App Store, TestFlight, Play Store, or APK release yet.

Today it runs from the `mobile/` folder with React Native / Expo and connects to the Local Flight desktop or Pi server over your local network. The current beta already covers the core use cases well enough for simulator checks, UI review, and real LAN companion testing.

If you only want the main FIDS display, install the Windows, macOS, or Raspberry Pi app above and skip this section. If you want the companion on an iPhone, iPad, or simulator, this is the current path.

### What works now

- FIDS, radar, history, and settings screens
- Live sync over WebSocket with fallback refresh polling
- Pinned flights and the Flight Island focus card
- Airport, source, and update-interval changes against the local server
- Matrix preview and config helper
- Admin summary access from Settings
- Manual feedback plus mobile crash-report routing
- Animated branded launch overlay matching the desktop splash direction

### What it looks like

<p align="center">
  <img src="docs/previews/mobile-fids-preview.svg" alt="Local Flight companion FIDS preview" width="32%">
  <img src="docs/previews/mobile-radar-preview.svg" alt="Local Flight companion radar preview" width="32%">
  <img src="docs/previews/mobile-settings-preview.svg" alt="Local Flight companion settings preview" width="32%">
</p>

### Requirements

- macOS with Xcode for iOS simulator/device testing
- Node.js 20 LTS or newer
- Local Flight already running on the same WiFi/LAN
- The LAN URL of your Local Flight server, for example `http://192.168.1.42:8000`

### Run the companion

```bash
cd mobile
npm install
npx expo install --fix
npm run doctor
npm run ios
```

For a physical iPhone or iPad:

```bash
cd mobile
npm run ios:device
```

In the app settings, enter the Local Flight server's LAN address. Do **not** use `localhost` on a phone; `localhost` means the phone itself, not your Mac or Windows machine.

Android support is planned later; the current companion testing flow is still iOS-first.

---

## First-run setup

On first launch Local Flight briefly shows a versioned splash screen, then opens the setup wizard at `http://localhost:8000/setup`.

It walks through:
1. Airport selection (IATA/ICAO search — 8 000+ airports)
2. Data source — **real** (AviationStack) or **virtual** (VATSIM/sim)
3. AviationStack path — three options:
   - **Community relay** — no key needed; uses a shared quota (50 calls/month per install, enforced server-side)
   - **BYOK** — bring your own AviationStack key (free plan gives 100 calls/month; 90 used by default to keep a reserve)
   - **VATSIM** — no API key; uses live flight-sim traffic instead of real schedules
4. ADS-B Exchange key via RapidAPI — live aircraft positions with live connection test (optional)
5. OpenSky Network credentials — position fallback (optional, anonymous also works)

The scheduler only starts after setup completes. You can re-run the wizard any time from **Settings → Re-run setup wizard**.

---

## Data sources

| Source | Key required | Used for |
|---|---|---|
| AviationStack | Optional (`AVIATIONSTACK_API_KEY`) | Flight schedules, gates, status; without a key Local Flight uses the community relay quota |
| ADS-B Exchange | Optional (`RAPIDAPI_KEY`) | Live positions, aircraft type, registration |
| OpenSky Network | Optional (`OPENSKY_CLIENT_ID` / `SECRET`) | Position fallback (anonymous works, lower rate limits) |
| VATSIM | No | Full data source for flight sim / virtual mode |
| aviationweather.gov | No | METAR weather — free, no key needed |

---

## Environment variables (`.env`)

The setup wizard writes these for you. You can also edit `.env` directly — changes take effect on the next fetch without restart.

```
# Managed install (written by setup wizard on activation)
LOCALFLIGHT_ACTIVATION_TOKEN=
LOCALFLIGHT_RELAY_URL=

# BYOK AviationStack — leave blank to use the community relay instead
AVIATIONSTACK_API_KEY=your_key_here
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90
LOCALFLIGHT_RELAY_MONTHLY_LIMIT=50

# ADS-B Exchange via RapidAPI — live aircraft positions
RAPIDAPI_KEY=your_rapidapi_key
LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=10000

# OpenSky Network — position fallback (optional)
OPENSKY_CLIENT_ID=your_id
OPENSKY_CLIENT_SECRET=your_secret
```

---

## Configuration

Config lives at `~/.localflight/config.json` and is managed via the **Settings** page at `http://localhost:8000`.

Runtime data is also kept outside the source tree:

- Snapshots: `~/.localflight/storage/data/<IATA>/snapshots`
- History DB: `~/.localflight/history.db`
- Logs: `~/.localflight/logs`
- API usage: `~/.localflight/api_usage.json`

| Field | Default | Description |
|---|---|---|
| `airport_iata` | `ZRH` | 3-letter IATA code |
| `airport_icao` | `LSZH` | 4-letter ICAO code |
| `refresh_seconds` | `3600` | Fetch interval (min 900 s) |
| `source` | `real` | `real` (AviationStack) or `virtual` (VATSIM) |
| `timezone` | `Europe/Zurich` | IANA timezone for local time display |
| `theme` | `dark` | `dark` or `light` |
| `skin` | `standard` | `standard`, `technical`, `neon`, `cyan`, `crt` |
| `display_name` | `Local Flight` | Shown in the UI header |
| `display_outputs` | `["web"]` | `web`, `matrix`, `hdmi` |

---

## Pages

| URL | Description |
|---|---|
| `/splash` | Short launch splash screen with version badge, then redirects to setup/display |
| `/display` | Split-view FIDS + Radar with draggable divider (default on launch) |
| `/fids` | FIDS board standalone (`?view=arrivals\|departures`) |
| `/radar` | Radar standalone |
| `/matrix-preview` | Browser LED matrix simulator with split-flap animation |
| `/` | Settings — airport, skin, outputs |
| `/admin` | Admin hub — scheduler status, API budgets, connected clients, system info |
| `/admin/requests` | Traffic log — local, anonymized request counters by endpoint/client type |
| `/history` | Flight history — filterable table + aggregate stats |
| `/logs` | Live log viewer |
| `/feedback` | Report a problem — sends directly to the developer |

---

## Skins

| Skin | Style |
|---|---|
| `standard` | Dark/light neutral with pictogram aircraft silhouettes |
| `technical` | Cool blue monospace, radar-style vector icons |
| `neon` | Green phosphor CRT |
| `cyan` | Ops-centre blue |
| `crt` | Amber split-flap |

---

## API call budgets

AviationStack and RapidAPI usage is tracked locally in `~/.localflight/api_usage.json` and resets monthly.

- AviationStack BYOK default: 90 calls/month (free-plan default; developer's community pool is 10 000/month shared across all relay installs)
- Community relay default: 50 calls/month per install (enforced relay-side, rolling 30-day window)
- ADS-B Exchange / RapidAPI default: 10 000 calls/month
- Each real scheduler cycle normally costs 2 AviationStack calls (departures + arrivals)

Scheduler restarts and config changes do not burn a new schedule call while the current snapshot is still fresh.

---

## Supported hardware

| Device | Role |
|---|---|
| Windows PC | Full desktop app — system tray, Edge/Chrome kiosk window |
| macOS | Full desktop app — system tray, Chrome/Safari kiosk window |
| Raspberry Pi 5 | Headless server — systemd services, Chromium kiosk, mDNS (`localflight.local`) |
| Pimoroni Interstate 75 W | LED matrix display (64×32 up to 384×64) — MicroPython client |
| RTL-SDR USB dongle | Local ADS-B receiver on Pi — no API key or rate limits |
| 7–10" HDMI screen | Secondary display via Chromium kiosk (`hdmi` output mode) |

### LED matrix (Interstate 75 W)

The board connects to your WiFi independently and polls the FIDS API every 60 seconds:

- Classic split-flap letter animation
- Button A = departures, Button B = arrivals, A+B = force refresh
- RGB status LED: green = ok, blue = fetching, amber = no data, red = no WiFi
- Flash `sources/matrix/client.py` with Pimoroni MicroPython firmware

### RTL-SDR / ADS-B on Pi

```bash
sudo apt install dump1090-fa
sudo systemctl enable --now dump1090-fa
```

Provides unlimited local ADS-B reception with no API key or monthly limits.

---

## Reporting issues

Hit the **🐛 Report** button in the nav bar from anywhere in the app. Your report — along with your Local Flight version, platform, and airport — goes directly to the developer. No account required.

---

## API reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/fids` | GET | FIDS rows (`?view=arrivals\|departures&limit=20`) |
| `/api/fids/detail` | GET | Callsign detail with live position + 7-day history |
| `/api/radar` | GET | Aircraft positions (`?radius_nm=20`) |
| `/api/metar` | GET | Decoded + raw METAR |
| `/api/flights` | GET | Raw flight list from latest snapshot |
| `/api/history` | GET | Recent flights (`?hours=24&direction=dep`) |
| `/api/history/flight` | GET | Callsign history (`?callsign=SWR184&days=7`) |
| `/api/history/stats` | GET | DB row count, size, oldest/newest |
| `/api/history/summary` | GET | Top airlines, routes, aircraft, on-time rate |
| `/api/config` | GET / PATCH | Read or update config |
| `/api/health` | GET | Scheduler state — last fetch, errors, latency |
| `/api/airports/search` | GET | Airport search (`?q=zurich`) |
| `/api/airports/resolve` | GET | Resolve IATA/ICAO to full record |
| `/api/admin/system` | GET | Uptime, memory, CPU, version |
| `/api/admin/budget` | GET | API call budgets and usage |
| `/api/admin/requests` | GET | Anonymized local request log summary |
| `/api/admin/connections` | GET | WebSocket client count + device pings |
| `/api/admin/updates` | GET | Latest GitHub release check |
| `/api/admin/scheduler` | GET | Scheduler thread status |
| `/api/admin/scheduler/restart` | POST | Restart scheduler and run a fresh fetch cycle |
| `/api/admin/ping` | POST | Device ping (LED matrix client) |
| `/api/feedback` | POST | Submit a bug report (`{title, description, client_context}`) |
| `/api/feedback/crash` | POST | Auto-file crash report with deduplication |
| `/api/setup/complete` | POST | Save setup, write `.env`, mark complete |
| `/api/setup/reset` | POST | Re-run setup wizard |
| `/api/setup/test-aviationstack` | POST | Validate an API key without saving |
| `/api/setup/test-rapidapi` | POST | Validate an ADS-B Exchange RapidAPI key without saving |
| `/api/quit` | POST | Graceful shutdown |
| `/ws` | WS | WebSocket push — broadcasts snapshot, config, and scheduler events |

---

## Philosophy

- **Local first** — flight data, history, config, and logs all live on your own machine. Nothing is uploaded, synced to a cloud, or shared with third parties beyond the configured data source.
- **Private by design** — no accounts, no email, no analytics SDK, no tracking. The local traffic log anonymizes IPs before storage and is only visible to you. See [PRIVACY.md](PRIVACY.md) for the full breakdown.
- **Boring by design** — standard Python, no framework magic
- **Clear data flow** — every step is a separate module
- **Pi-ready** — nothing in the stack requires a GPU or significant RAM
- **Graceful degradation** — if an enrichment source fails, the next one kicks in
- **Budget conscious** — AviationStack, relay, and RapidAPI monthly call counters enforced in code
