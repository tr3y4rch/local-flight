# Local Flight Display Modes

Local Flight is one local server with several client surfaces. The important idea is simple: choose where the board should be seen, and Local Flight keeps the same data, setup, history, diagnostics, and APIs underneath.

Public project docs live at [beacontools.cc/local-flight](https://beacontools.cc/local-flight). The hosted relay used by Community Relay, Remote Companion fallback, and Mobile Standalone is `https://relay.beacontools.cc`.

---

## Recommended Default

For Windows, macOS, and supported Linux desktops, use the **native Qt desktop shell**.

It is the recommended primary desktop client because it opens a real app window without depending on Chrome, Edge, Chromium, browser profiles, browser sync, extensions, cookies, browsing history, webviews, online fonts, or CDN assets.

The native app still starts the same local FastAPI server. That means the LAN browser UI, mobile Companion, Matrix board, and API clients continue to work while the native shell is running.

---

## Choose A Mode

| Need | Recommended path |
|---|---|
| Normal Windows/macOS/Linux desktop use | Native Qt desktop shell |
| Portable Linux desktop use | AppImage |
| Integrated Ubuntu/Debian desktop use | Desktop `.deb` |
| Always-on Ubuntu/Debian server with no screen | Headless server `.deb` |
| View/control from another device on the same network | LAN browser UI |
| View on a phone | LAN browser UI — auto mobile shell |
| Always-on Pi server with no screen | Pi headless |
| Pi attached to a 7" touch screen (800×480 or 1024×600) | LAN browser UI — auto compact layout |
| Pi attached to an HDMI display without a browser process | Native Qt kiosk |
| Pi attached to an HDMI display using the web board | Chromium kiosk display |
| iPhone or iPad paired to your Local Flight server | Mobile Companion with Remote Companion fallback |
| iPhone or Android simplified board | Mobile Standalone |
| LED passenger board | Interstate 75 W Matrix client |

---

## Native Qt Desktop Shell

Use this for everyday desktop use on Windows, macOS, and supported 64-bit Linux systems. Normal Linux desktop launches are resizable; fullscreen is reserved for Pi or an explicit kiosk setting.

What it gives you:

- Display, FIDS, Radar, Matrix, Settings, Admin, History, Logs, and Report pages
- Native first-run setup
- Native FIDS with city/country airport headers, passenger-friendly weather, four switchable board styles (Classic / PAX / VATSIM / Nerd), and the same current-source detail model as the LAN browser UI
- Settings page built from disclosure cards (clickable header bars with emoji, title, summary, and chevron) instead of opaque checkbox-titled groups
- Native radar drawing with the same layered blip/status/surface behavior and sweep timing as the LAN browser UI and mobile app
- History dashboard analytics, Matrix board configuration, and user-facing Settings cards
- Local docs and diagnostics
- Same local API and WebSocket events as the browser UI

Radar presentation follows one cross-platform contract. North is `0°`, the
leading line moves clockwise once every 15 seconds, and the 72-degree phosphor
trail fades behind it. A blip appears only after the leading line reaches its
bearing. Hovered, keyboard-focused, or selected traffic remains visible for
inspection; clicking the same target, empty scope, Close, or Escape clears the
native selection. These animations use already-loaded traffic and never cause
provider or terrain requests.

Use it when you want the full Local Flight app on the machine that runs the server.

---

## LAN Browser UI

The browser UI is a supported access and display surface. It is not being removed.

In `0.5.2`, the browser UI follows the same visual and information hierarchy as
the native Qt shell: airport-local and UTC clocks, Display/FIDS/Radar/Matrix
navigation, readable cards and status labels, appearance choices, and grouped
Settings. It also provides the same fingerprint-bound Companion QR/manual
pairing path and paired-device reset tools.

Use it when:

- You run Local Flight headless on a Pi.
- You run the Ubuntu/Debian headless server package.
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

Opening the LAN URL on a phone automatically switches to a touch-friendly
layout. Navigation moves within thumb reach, flight rows become readable cards,
multi-column pages stack vertically, and device safe areas are respected.

### 7-inch Raspberry Pi screens

Common 800×480 and 1024×600 Pi touch panels use a compact layout that keeps the
board readable without horizontal page overflow. Lower-priority columns and
secondary controls collapse automatically when space is limited.

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
- Mobile Companion API
- Matrix feed/API

It does not open a local window on the Pi.

On first launch, the server and setup pages are available immediately, but the
scheduler waits until setup is complete before contacting a flight-data source.

---

## Ubuntu/Debian Headless Server

The `localflight-server` package is the regular Linux equivalent of a headless
Pi installation. It is useful for a small home server, virtual machine, or
always-on ARM64 board that should serve other displays without running a local
desktop session.

It provides the same LAN UI, setup, APIs, WebSocket updates, mobile Companion,
Matrix feed, history, and reports as the desktop host. The service uses a locked
`localflight` account, keeps state under `/var/lib/localflight`, and listens on
port 8000. It does not rename the machine or install a kiosk browser.

The server package and desktop `.deb` cannot be installed together because each
represents one Local Flight host and both would use the same local port.

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

The mobile app runs on iPhone, iPad, and Android and has two modes. TestFlight iOS build 9 and Google Play Android versionCode 12 use the same `0.5.2` data and privacy contract as desktop, Linux server, and Pi hosts.

### Companion

Companion talks to your Local Flight server over your Wi-Fi/LAN first. After a phone pairs from the host's Pair Mobile screen, Remote Companion can also be granted for relay-linked installs so the same Companion experience keeps working away from Wi-Fi through encrypted relay envelopes.

Use Companion for:

- Board/FIDS and pinned flight view
- Radar with mobile-owned range rings
- History
- Control for host status plus airport/source/refresh changes
- Help, troubleshooting, and manual feedback from the Help & Reports card inside Control
- Safe Matrix live-remote controls from Control
- Automatic diagnostics only when both mobile and host allow them

Pair from the native Qt Settings page or the LAN browser Settings page. Both
surfaces show a reusable QR code, the preferred LAN URL, manual fallbacks, and a
server fingerprint. Keep the `:8000` port in manual URLs.

Remote Companion still requires the host to be online. It is not Standalone mode, not a cloud admin panel, and not a public tunnel to the host. The relay can route install/grant refs, request ids, status, latency, and byte sizes, but it cannot read the encrypted Companion path/body or response.

### Standalone

Standalone talks directly to the hosted Beacon Tools relay and does not need your own Local Flight host online. Its careful refresh limits keep the shared service reliable and fairly available.

Use Standalone for:

- Board/FIDS
- Radar
- Local on-device History
- Lightweight Settings
- Manual reports and diagnostics consent

Standalone limits:

- Airline schedule target: about 1 hour
- Open Radar traffic target: about 3 minutes
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
- connected-board mirror mode with renderer/geometry warnings so stale `main.py` files are visible before the physical board and preview drift

---

## Data Access Is Separate From Display Mode

Display mode decides where Local Flight appears. Data access decides where flight data comes from.

You can use any display mode with:

- **Local Flight Relay** for shared real-world schedule snapshots
- **Use your own keys** for direct provider access from your own machine
- **VATSIM** for virtual network traffic

Changing display mode does not change your data source by itself.

Mobile Standalone is the one special case: because there is no paired local server, it always uses the hosted relay's current shared real-data policy and local on-device history. It does not expose BYOK or VATSIM controls.

The hosted relay's current real-data path is cache-first and can use AeroDataBox primary schedule data with AviationStack sparse fill/fallback where configured. That provider mix is separate from the display mode you choose.

---

## Privacy Philosophy

Local Flight keeps the display shell separate from the aviation data sources you choose.

- Native Qt is recommended for desktop because it avoids extra browser-vendor surfaces for the main app window.
- LAN browser UI remains supported because it is useful for headless installs, remote viewing, kiosk displays, and recovery.
- Companion and Matrix stay server-mediated through your Local Flight instance. Companion uses LAN first and can fall back to encrypted Remote Companion only for paired relay-linked hosts.
- Mobile Standalone is relay-mediated, simplified, and rate-limited by design.
- Diagnostics are consent-based and sanitized before leaving the machine.

For install commands, see [Install Guide](install.md).
