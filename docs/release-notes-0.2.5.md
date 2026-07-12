# Local Flight 0.2.5 Beta Client Notes

> Historical archive. For the current release line, see [0.5.1 Release Overview](release-notes-0.5.1.md).

`0.2.5` is still a beta. It is not being presented as a polished stable release yet.

It is, however, the first Local Flight build where the base client story is meant to work end to end across the main display paths: native desktop, LAN browser UI, Raspberry Pi server/kiosk, mobile companion, and Matrix.

If earlier builds felt like separate experiments, this one is the first real multi-client baseline.

---

## What This Beta Is

Local Flight is a local-first Flight Information Display System for hobbyist/home airport-board setups.

The app runs a local server on your Windows PC, Mac, or Raspberry Pi. Every client talks to that local server:

- The native desktop app
- The LAN browser UI
- The Raspberry Pi display modes
- The mobile companion
- The LED Matrix client

That means setup, config, history, diagnostics, docs, FIDS rows, radar, weather, and reports all come from one local source of truth.

---

## Base Client Paths In This Build

### Native Desktop App

The native Qt app is now the recommended desktop client for Windows and macOS.

It includes:

- First-run setup before the normal app opens
- FIDS board
- Radar
- Matrix tools
- Settings
- Admin summary
- History dashboard with delay quotas, airline/route/aircraft stats, filters, sortable recent flights, and local detail panels
- Logs
- Manual report screen
- Bundled local docs

The native app still starts the same local FastAPI backend, so the LAN browser UI and companion clients remain available while it runs.

### LAN Browser UI

The browser UI is a supported access and display path, not a leftover.

Use it for:

- Headless Pi installs
- Viewing Local Flight from another device on the same network
- Browser-mode display/kiosk setups
- Recovery if a native desktop dependency is unavailable

### Raspberry Pi

The Pi installer now has three clear paths:

- `--headless`: server only, good for LAN/mobile/Matrix access
- `--native-kiosk`: fullscreen native Qt display on HDMI
- `--kiosk`: fullscreen Chromium display using the LAN browser UI

The default Pi path remains headless because that is the safest option for SSH and server-first installs.

### Mobile Companion

The mobile companion is still a developer/test client, not an App Store or TestFlight release.

It now has the expected base companion flow:

- Forced first-launch setup
- LAN server pairing
- Mobile diagnostics consent
- FIDS
- Radar
- History
- Settings hub
- Matrix and Admin entry points
- Server-mediated docs
- Feedback/crash reporting through the connected Local Flight server

Landscape mode is display-first: rotating the device shows fullscreen FIDS from wherever you are, hides app chrome, and restores the previous screen when rotating back.

### Matrix

The Matrix tooling now has a clearer current baseline:

- Runtime config from the Local Flight server
- Native and LAN browser preview tools
- Generated MicroPython `main.py`
- Rectangular HUB75 layouts
- Small-panel rotation
- Weather/status toggles
- VATSIM pilot/ATC-oriented display presets

---

## Core Functions Available Now

### Setup And Data Sources

First launch guides you through the important choices:

- Airport
- Community Relay, Bring Your Own Keys, or VATSIM
- Optional provider keys
- Diagnostics/reporting mode

Community Relay is the easiest first path. BYOK is for users who already have provider keys. VATSIM is the no-key virtual traffic path.

### FIDS

FIDS now has a more complete passenger-board baseline:

- Departures and arrivals
- Airport-local time handling
- Status chips
- Gate/terminal fields when available
- Codeshare-aware rows
- Airline/callsign display cleanup
- Nearest-useful schedule rows when a live window would otherwise look empty
- Native, browser, mobile, and Matrix presentation contracts kept closer together

### Radar

Radar now supports the practical baseline:

- Real ADS-B-backed traffic when available
- VATSIM traffic in virtual mode
- Range controls
- METAR/weather context
- Runway and surface drawing
- Server-mediated ground geometry for mobile
- Local fallback/estimated geometry when no better airport surface data is available

The radar is a display aid, not certified navigation or controller-grade traffic.

### Weather

Weather is still based on aviation weather data, but the UI is friendlier:

- FIDS gets compact passenger-readable weather
- Radar gets richer METAR context
- Mobile can choose friendly, light, or raw display modes
- VATSIM mode can use VATSIM weather text where available

### Docs, Privacy, And Diagnostics

The app now bundles the important docs locally:

- README
- Install Guide
- Display Modes
- Privacy
- Changelog
- Third-party notices

Diagnostics remain consent-based. Manual reports are always user-triggered. Automatic reports require diagnostics consent, and mobile automatic reports require both the mobile choice and the connected server choice.

---

## Install Choices

For normal users:

- Windows: use `LocalFlight-windows.zip`
- macOS: use `LocalFlight-macos.zip`
- Raspberry Pi: use `LocalFlight-pi-source-0.2.5.zip`

For developers or source-checkout testers:

- Windows source installer: `installers/windows/install.ps1`
- macOS source installer: `installers/macos/install.sh`
- Pi installer: `installers/pi/install.sh`
- Mobile companion: `mobile/` with Expo/Xcode

Detailed instructions live in:

- [Install Guide](install.md)
- [Display Modes](display-modes.md)
- [Privacy](../PRIVACY.md)

---

## Known Beta Boundaries

This is still beta software.

Known boundaries:

- macOS artifacts are unsigned/not notarized unless a signing identity is provided, so users may need right-click -> Open.
- Mobile companion is not distributed through the App Store or TestFlight yet.
- Android is present as an Expo target but not the validated primary companion path.
- QR pairing and per-device auth tokens are not in this build.
- Broader admin permissions are intentionally limited until trusted pairing/auth exists.
- Provider coverage varies by airport and data source.
- Radar surface/map data is visual-only and may be estimated when public geometry is unavailable.

---

## Why This Version Matters

`0.2.5` is the first beta where Local Flight feels like one product instead of a pile of display experiments.

The native app, LAN browser UI, Pi modes, mobile companion, and Matrix board now share a clearer model:

- One local server
- Multiple supported clients
- Local-first setup
- Consent-based diagnostics
- Plain install/display choices
- Bundled docs
- Consistent FIDS/radar contracts

That is the baseline this project can now build on.
