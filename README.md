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
- Includes an early **React Native mobile companion** for iOS-first LAN viewing on iPhone/iPad
- Stores 90 days of flight history in a local **SQLite database** with a browsable history UI and aggregate stats
- Supports **profiles** — save and switch airport configurations instantly
- Displays **UTC and local time** simultaneously, timezone follows the configured airport
- **First-run setup wizard** guides through airport selection, API keys, and display settings
- **Admin hub** — scheduler controls, API budget tracking, connected clients, system status
- Runs as a **system tray app** on Windows and macOS; headless on Raspberry Pi with a Chromium kiosk
- Ships a **MicroPython client** for the Pimoroni Interstate 75 W LED matrix panel
- **In-browser matrix preview** — see exactly what the LED panel will show, with split-flap animation

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

The macOS script is for a source checkout. If a packaged `.app` is attached to a release, use that instead.

```bash
# One-time setup
bash installers/macos/install.sh

# Launch
open installers/macos/LocalFlight.command
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

The Phase 1 React Native / Expo app lives in `mobile/`. It is iOS-first for now and treats the Python/FastAPI app as the server of record.

```bash
cd mobile
npm install
npx expo install --fix
npm run ios
```

For a physical iPhone or iPad, use the Local Flight server's LAN address in the app settings, for example `http://192.168.1.42:8000`. Do not use `localhost` on the phone, because that points at the phone itself.

---

## First-run setup

On first launch Local Flight briefly shows a versioned splash screen, then opens the setup wizard at `http://localhost:8000/setup`.

It walks through:
1. Airport selection (IATA/ICAO search — 8 000+ airports)
2. Data source — **real** (AviationStack) or **virtual** (VATSIM/sim)
3. AviationStack API key — with live connection test
4. ADS-B Exchange key via RapidAPI — with live connection test (optional)
5. OpenSky Network credentials (optional)

The scheduler only starts after setup completes. You can re-run the wizard any time from **Settings → Re-run setup wizard**.

---

## Data sources

| Source | Key required | Used for |
|---|---|---|
| AviationStack | Yes (`AVIATIONSTACK_API_KEY`) | Flight schedules, gates, status |
| ADS-B Exchange | Yes (`RAPIDAPI_KEY`) | Live positions, aircraft type, registration |
| OpenSky Network | Optional (`OPENSKY_CLIENT_ID` / `SECRET`) | Position fallback (anonymous works, lower rate limits) |
| VATSIM | No | Full data source for flight sim / virtual mode |
| aviationweather.gov | No | METAR weather — free, no key needed |

---

## Environment variables (`.env`)

The setup wizard writes these for you. You can also edit `.env` directly — changes take effect on the next fetch without restart.

```
# AviationStack — real flight schedule data
AVIATIONSTACK_API_KEY=your_key_here
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90   # free tier is 100; 90 leaves a safety margin

# ADS-B Exchange via RapidAPI — live aircraft positions
RAPIDAPI_KEY=your_rapidapi_key

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

AviationStack free tier is 100 calls/month. Local Flight enforces a configurable monthly budget:

- Default limit: 90 calls (10-call safety margin)
- Each scheduler cycle costs 2 calls (departures + arrivals)
- Budget tracked in `~/.localflight/api_usage.json`, resets monthly
- Recommended refresh interval: **8–12 hours** (fits within 90 calls/month)

ADS-B Exchange and OpenSky free tiers are both 1 000 calls/day — well within limits at any reasonable refresh interval.

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
| `/api/admin/connections` | GET | WebSocket client count + device pings |
| `/api/admin/updates` | GET | Latest GitHub release check |
| `/api/admin/ping` | POST | Device ping (LED matrix client) |
| `/api/feedback` | POST | Submit a bug report (`{title, description}`) |
| `/api/setup/complete` | POST | Save setup, write `.env`, mark complete |
| `/api/setup/reset` | POST | Re-run setup wizard |
| `/api/setup/test-aviationstack` | GET | Validate an API key without saving |
| `/api/setup/test-rapidapi` | GET | Validate an ADS-B Exchange RapidAPI key without saving |
| `/api/quit` | POST | Graceful shutdown |
| `/ws` | WS | WebSocket push — broadcasts after each fetch |

---

## Philosophy

- Local first — no cloud dependency after initial setup
- Boring by design — standard Python, no framework magic
- Clear data flow — every step is a separate module
- Pi-ready — nothing in the stack requires a GPU or significant RAM
- Graceful degradation — if an enrichment source fails, the next one kicks in
- Budget conscious — AviationStack monthly call counter enforced in code
