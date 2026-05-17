# Local Flight Display Modes

Local Flight is one local server with several client surfaces. The important idea is simple: choose where the board should be seen, and Local Flight keeps the same data, setup, history, diagnostics, and APIs underneath.

---

## Recommended Default

For Windows and macOS, use the **native Qt desktop shell**.

It is the recommended primary desktop client because it opens a real app window without depending on Chrome, Edge, Chromium, browser profiles, browser sync, extensions, cookies, browsing history, webviews, online fonts, or CDN assets.

The native app still starts the same local FastAPI server. That means the LAN browser UI, mobile LAN Companion, Matrix board, and API clients continue to work while the native shell is running.

---

## Choose A Mode

| Need | Recommended path |
|---|---|
| Normal Windows/macOS desktop use | Native Qt desktop shell |
| View/control from another device on the same network | LAN browser UI |
| View on a phone | LAN browser UI — auto mobile shell |
| Always-on Pi server with no screen | Pi headless |
| Pi attached to a 7" touch screen (800×480 or 1024×600) | LAN browser UI — auto compact layout |
| Pi attached to an HDMI display without a browser process | Native Qt kiosk |
| Pi attached to an HDMI display using the web board | Chromium kiosk display |
| iPhone or iPad paired to your Local Flight server | Mobile LAN Companion |
| iPhone-only simplified board | Mobile Standalone |
| LED passenger board | Interstate 75 W Matrix client |

---

## Native Qt Desktop Shell

Use this for everyday desktop use on Windows and macOS.

What it gives you:

- Display, FIDS, Radar, Matrix, Settings, Admin, History, Logs, and Report pages
- Native first-run setup
- Native FIDS with city/country airport headers, passenger-friendly weather, four switchable board styles (Classic / PAX / VATSIM / Nerd), and the same current-source detail model as the LAN browser UI
- Settings page built from disclosure cards (clickable header bars with emoji, title, summary, and chevron) instead of opaque checkbox-titled groups
- Native radar drawing with the same layered blip/status/surface behavior as the LAN browser UI
- History dashboard analytics, Matrix board configuration, and user-facing Settings cards
- Local docs and diagnostics
- Same local API and WebSocket events as the browser UI

Use it when you want the full Local Flight app on the machine that runs the server.

---

## LAN Browser UI

The browser UI is a supported access and display surface. It is not being removed.

As of the 2026-05-18 follow-up in the `0.2.7` cycle, the browser UI
mirrors the native Qt shell — same top nav layout (brand mark, UTC/LT
clock chips, segmented Display / FIDS / Radar / Matrix tabs, operator
icon-chip bar, Power button), same colour tokens, same shared
components (panels, cards, kicker labels, disclosure cards, status
pills, buttons). Picking a theme or skin in Settings retints both
surfaces the same way.

Use it when:

- You run Local Flight headless on a Pi.
- You want to view the board from another computer, tablet, or phone browser.
- You intentionally prefer the browser board on an attached display.
- You need a recovery path if a native desktop dependency is unavailable.

Open:

```text
http://localhost:8000
```

from the machine running Local Flight, or:

```text
http://localflight.local:8000
```

from another device on your LAN.

### Phone view

Opening the LAN URL on a phone automatically switches to a mobile
shell. The top nav docks to the bottom edge as a thumb-reachable bar,
FIDS rows reflow into per-flight cards (large time on the left,
flight + airline + route stacked, status pill top-right, gate badge
on a meta row, status colour rail on the left), Settings / Admin /
Setup grids stack to a single column, and inputs become iOS-friendly
sizes. iPhone home-indicator and notch safe-areas are honoured.

You can preview the mobile shell on desktop by appending `?mobile=1`
to any page URL; `?mobile=0` clears the preview.

### 7-inch Raspberry Pi screens

Both common 7" Pi touch panels — the official 800×480 screen and
1024×600 IPS panels — get a dedicated compact layout that keeps the
Qt-shell look but tightens every dimension. The top nav drops
secondary clock chips and low-priority operator icons; FIDS row
height drops to 40 px and the A/C column hides at 800×480. Net
effect: **8 flights visible at 800×480** (was 5), **11 at 1024×600**.

These rules trigger automatically based on viewport height. No kiosk
configuration is required — just point the Pi's browser at the LAN
URL.

---

## Pi Headless Server

Headless is the recommended Pi server mode when the Pi has no dedicated display.

It runs:

- Local FastAPI server
- Scheduler
- WebSocket updates
- LAN browser UI
- Mobile LAN Companion API
- Matrix feed/API

It does not open a local window on the Pi.

---

## Native Qt HDMI Kiosk

Native Qt kiosk is for a Pi connected to an HDMI display where you want a Chrome-free fullscreen board.

The backend still runs as the system service. A separate user-session service owns the fullscreen native Qt display. This keeps the server alive even if the display session needs attention.

Install with:

```bash
bash installers/pi/install.sh --native-kiosk
```

---

## Chromium HDMI Kiosk

Chromium kiosk is for a Pi connected to an HDMI display where you want the LAN browser board fullscreen on that display.

Install with:

```bash
bash installers/pi/install.sh --kiosk
```

This is useful when the browser UI fits your display setup better or native Qt kiosk is not the right fit for the Pi image.

---

## Mobile App

The mobile app is an iOS-first developer preview for iPhone, iPad, and simulator testing. It has two modes.

### LAN Companion

LAN Companion talks to your Local Flight server over your Wi-Fi/LAN. It does not call AviationStack, ADS-B Exchange, RapidAPI, OpenSky, VATSIM, or the hosted relay directly.

Use LAN Companion for:

- FIDS and pinned flight view
- Radar with mobile-owned range rings
- History
- Guided Settings
- Matrix/Admin status
- Server-mediated docs
- Manual feedback and diagnostics, with mobile/server double-consent for automatic reports

### Standalone

Standalone talks directly to the hosted Local Flight relay and does not need your own desktop/Pi server online. It is simplified on purpose so a phone install cannot burn through shared relay/provider tokens.

Use Standalone for:

- FIDS/Board
- Radar
- Local on-device History
- Lightweight Settings
- Manual reports and diagnostics consent

Standalone limits:

- FIDS auto-refresh: 3 hours minimum
- Radar refresh: 5 minutes minimum
- Radar ranges: `1`, `3`, `5`, and `10` NM
- No Matrix, Admin, scheduler restart, server URL controls, LAN check-in, or WebSocket connection

---

## Matrix Client

The Interstate 75 W / HUB75 Matrix client is a small display client.

It connects over WiFi, reads only the display feed/config it needs, and never receives provider keys, relay secrets, or admin credentials.

Use the Matrix page in the native app or LAN browser UI to configure runtime settings and generate the MicroPython `main.py` file.

Matrix configuration is shared across the native app and LAN browser UI:

- common panel presets from `64x32` through larger HUB75 combinations
- live preview for brightness, zoom, row count, weather, palette, animation, startup lane, and page rotation
- compact weather headers that keep small boards such as `128x128` readable
- optional real-world gate/stand display when the schedule source provides it
- VATSIM presets that hide gate placeholders and focus on virtual callsign, aircraft, route/status, flight-plan, and weather/ATIS information

---

## Data Access Is Separate From Display Mode

Display mode decides where Local Flight appears. Data access decides where flight data comes from.

You can use any display mode with:

- **Community Relay** for shared real-world schedule snapshots
- **Bring your own keys** for direct provider access from your own machine
- **VATSIM** for virtual network traffic

Changing display mode does not change your data source by itself.

Mobile Standalone is the one special case: because there is no paired local server, it always uses the hosted relay's current shared real-data policy and local on-device history. It does not expose BYOK or VATSIM controls in this first pass.

---

## Privacy Philosophy

Local Flight keeps the display shell separate from the aviation data sources you choose.

- Native Qt is recommended for desktop because it avoids extra browser-vendor surfaces for the main app window.
- LAN browser UI remains supported because it is useful for headless installs, remote viewing, kiosk displays, and recovery.
- LAN Companion and Matrix stay server-mediated through your Local Flight instance.
- Mobile Standalone is relay-mediated, simplified, and rate-limited by design.
- Diagnostics are consent-based and sanitized before leaving the machine.

For install commands, see [Install Guide](install.md).
