# Local Flight

Local Flight is a local-first Flight Information Display System (FIDS) for Windows, macOS, Raspberry Pi, the mobile app, HDMI displays, LAN browsers, and LED matrix boards.

It fetches real or virtual flight data, keeps a local history, and renders airport-style departures, arrivals, radar, weather, and Matrix feeds without accounts or a signup wall.

The recommended desktop client is now the native Qt app. The LAN browser UI, Pi display modes, Matrix board, and LAN Companion mode all use the same local server underneath, so you can pick the display style that fits your setup without splitting the app into different products. The same Expo mobile app can also run in a simplified Standalone mode through the hosted relay when you only want a light phone board.

**Source:** [github.com/tr3y4rch/local-flight](https://github.com/tr3y4rch/local-flight)

---

## Status

`0.2.7` is the current client-polish release-candidate target on top of the `0.2.6` beta baseline. It is still beta software, but this pass treats Local Flight as a working multi-client app:

- Native desktop app for Windows and macOS
- LAN browser UI for remote viewing, headless installs, and browser-mode displays
- Raspberry Pi headless server, native Qt HDMI kiosk, or Chromium HDMI kiosk
- iOS-first mobile developer preview with LAN Companion and Standalone setup modes
- Interstate 75 W / HUB75 Matrix client and preview tools

---

## Which Path Should I Choose?

| If you want... | Use this |
|---|---|
| The normal desktop app | Native Qt app on Windows or macOS |
| A small always-on home server | Raspberry Pi headless |
| A Pi plugged into an HDMI display | Native Qt kiosk or Chromium kiosk |
| Viewing from another device | LAN browser UI at `http://localflight.local:8000` |
| iPhone/iPad controls for your desktop/Pi server | Mobile LAN Companion from `mobile/` |
| A simplified phone board without running your own server | Mobile Standalone from `mobile/` |
| A small LED board | Matrix page + Interstate 75 W client |

Read the detailed guides:

- [Install Guide](docs/install.md)
- [Display Modes](docs/display-modes.md)
- [Privacy & Diagnostics](PRIVACY.md)
- [0.2.7 Client Notes](docs/release-notes-0.2.7.md)
- [Full Changelog](CHANGELOG.md)

---

## What It Does

- Guided setup with **Community Relay**, **Bring your own keys**, and **VATSIM** paths
- Real schedule support designed around cached shared snapshots, AeroDataBox/AviationStack provider compatibility, and stale-safe serving when live providers are slow or capped
- Passenger-style FIDS boards with city/country airport headers, arrivals/departures, airport-local time, status/gate chips, codeshare grouping, pinned flights, and live refresh
- Radar with real/VATSIM traffic, METAR weather, range controls, optional runway/surface/map/terrain context, and richer aircraft/status detail
- Native Qt desktop shell with Display, FIDS, Radar, Matrix, Settings, Admin, History, Logs, Report, and local docs
- LAN browser UI for headless installs, remote screens, tablets, and browser-mode displays
- Mobile app with a first-run choice between **LAN Companion** and **Standalone**: Companion keeps the full desktop/Pi pairing flow; Standalone offers a simpler FIDS/Radar/History/Settings experience through the hosted relay with slower refreshes and no server-control tools
- History dashboard with filters, delay buckets, airline delay quotas, route/aircraft stats, sortable recent flights, and detail panels
- Matrix tooling for Interstate 75 W / HUB75 boards, including panel presets, live preview, optional real-world gate/stand display, compact weather headers, runtime settings, and generated MicroPython `main.py`
- Shared flight detail intelligence for FIDS, Radar, History, Matrix, native Qt, and LAN browser views, using current local snapshots, radar data, weather, and history without new per-click provider calls
- Local history, local logs, local settings, and install-scoped diagnostics

---

## Preview

These are lightweight illustrative previews with sample data, not live telemetry screenshots.

Open [docs/previews/index.html](docs/previews/index.html) locally for the standalone HTML gallery.

<p align="center">
  <img src="docs/previews/fids-preview.svg" alt="Local Flight FIDS preview" width="48%">
  <img src="docs/previews/radar-preview.svg" alt="Local Flight radar preview" width="48%">
</p>

<p align="center">
  <img src="docs/previews/settings-preview.svg" alt="Local Flight native settings preview" width="48%">
  <img src="docs/previews/matrix-preview.svg" alt="Local Flight LED matrix preview" width="48%">
</p>

<p align="center">
  <img src="docs/previews/mobile-fids-preview.svg" alt="Local Flight companion FIDS preview" width="48%">
  <img src="docs/previews/mobile-radar-preview.svg" alt="Local Flight companion radar preview" width="48%">
</p>

<p align="center">
  <img src="docs/previews/mobile-settings-preview.svg" alt="Local Flight companion settings preview" width="48%">
</p>

---

## Quick Install

### Windows

Download `LocalFlight-windows.zip`, unzip it, and run `LocalFlight.exe`.

### macOS

Download `LocalFlight-macos.zip`, unzip it, drag `LocalFlight.app` to Applications, then right-click **Open** the first time if Gatekeeper warns.

### Raspberry Pi

Download the Pi source bundle or clone the repo, then run:

```bash
bash installers/pi/install.sh
```

The Pi installer asks how the Pi should run and defaults to headless.

### Mobile App

```bash
cd mobile
npm install
npx expo install --fix
npm run verify
npm run ios
```

For full setup details, see [docs/install.md](docs/install.md).

---

## First Launch

First launch opens setup before the normal app.

Setup guides you through:

1. Welcome
2. Airport
3. Flight data
4. Optional provider keys
5. Diagnostics choice
6. Review and launch

Community Relay is the recommended first path. It uses cached shared schedule snapshots so many installs can watch the same airport without each one calling a paid provider. Community Relay schedule refresh choices are hourly-or-slower in the client UI; BYOK and VATSIM can still use the standard local refresh choices. BYOK is for users who already have provider keys such as AeroDataBox through API.Market or RapidAPI, AviationStack, RapidAPI ADS-B Exchange, or OpenSky. VATSIM is the no-key virtual traffic path.

---

## Local Data And Privacy

Local Flight stores runtime data under `~/.localflight/`:

- Config
- Snapshots
- History database
- Logs
- API usage counters

Manual reports are always user-triggered. Automatic diagnostics require consent and are sanitized before leaving the device. LAN Companion mode requires both the phone-local diagnostics choice and the connected server diagnostics mode to allow automatic reports. Standalone mobile automatic reports require the phone-local diagnostics choice only, because there is no paired local server in that mode.

See [PRIVACY.md](PRIVACY.md) for the detailed privacy model.

---

## Source Checkout

For development or source testing:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[native]"
cd src
python -m localflight
```

Windows, macOS, and Pi source installers are documented in [docs/install.md](docs/install.md).

---

## Project Philosophy

- **Local first:** your config, snapshots, history, and logs live on your machine.
- **No accounts:** Local Flight does not require a login or email address.
- **Native by default on desktop:** the main desktop app does not need a browser profile, webview, online font, CDN, extension, or sync surface.
- **LAN browser UI stays supported:** useful for headless installs, remote viewing, kiosk displays, and recovery.
- **Flexible mobile:** the same mobile app can be a LAN Companion for your desktop/Pi server or a simplified Standalone relay client with stricter refresh limits.
- **Server-mediated hardware:** Matrix talks through your Local Flight server and never receives provider keys.
- **Budget-aware:** provider and relay usage is cached, tracked, and guarded before paid calls are made.

For display-choice philosophy, see [docs/display-modes.md](docs/display-modes.md).
