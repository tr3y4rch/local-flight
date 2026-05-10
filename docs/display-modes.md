# Local Flight Display Modes

Local Flight is one local server with several client surfaces. The important idea is simple: choose where the board should be seen, and Local Flight keeps the same data, setup, history, diagnostics, and APIs underneath.

---

## Recommended Default

For Windows and macOS, use the **native Qt desktop shell**.

It is the recommended primary desktop client because it opens a real app window without depending on Chrome, Edge, Chromium, browser profiles, browser sync, extensions, cookies, browsing history, webviews, online fonts, or CDN assets.

The native app still starts the same local FastAPI server. That means the LAN browser UI, mobile companion, Matrix board, and API clients continue to work while the native shell is running.

---

## Choose A Mode

| Need | Recommended path |
|---|---|
| Normal Windows/macOS desktop use | Native Qt desktop shell |
| View/control from another device on the same network | LAN browser UI |
| Always-on Pi server with no screen | Pi headless |
| Pi attached to an HDMI display without a browser process | Native Qt kiosk |
| Pi attached to an HDMI display using the web board | Chromium kiosk display |
| iPhone or iPad companion | Mobile companion |
| LED passenger board | Interstate 75 W Matrix client |

---

## Native Qt Desktop Shell

Use this for everyday desktop use on Windows and macOS.

What it gives you:

- Display, FIDS, Radar, Matrix, Settings, Admin, History, Logs, and Report pages
- Native first-run setup
- Native FIDS and radar drawing with the same current-source detail model as the LAN browser UI
- History dashboard analytics, Matrix board configuration, and user-facing Settings cards
- Local docs and diagnostics
- Same local API and WebSocket events as the browser UI

Use it when you want the full Local Flight app on the machine that runs the server.

---

## LAN Browser UI

The browser UI is a supported access and display surface. It is not being removed.

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

---

## Pi Headless Server

Headless is the recommended Pi server mode when the Pi has no dedicated display.

It runs:

- Local FastAPI server
- Scheduler
- WebSocket updates
- LAN browser UI
- Mobile companion API
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

## Mobile Companion

The mobile companion is a LAN client for iPhone, iPad, and simulator testing.

It talks only to your Local Flight server. It does not call AviationStack, ADS-B Exchange, RapidAPI, OpenSky, VATSIM, or the hosted relay directly.

Use it for:

- FIDS and pinned flight view
- Radar with mobile-owned range rings
- History
- Guided Settings
- Matrix/Admin status
- Server-mediated docs
- Manual feedback and diagnostics, with mobile/server double-consent for automatic reports

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

---

## Privacy Philosophy

Local Flight keeps the display shell separate from the aviation data sources you choose.

- Native Qt is recommended for desktop because it avoids extra browser-vendor surfaces for the main app window.
- LAN browser UI remains supported because it is useful for headless installs, remote viewing, kiosk displays, and recovery.
- Mobile and Matrix stay server-mediated through your Local Flight instance.
- Diagnostics are consent-based and sanitized before leaving the machine.

For install commands, see [Install Guide](install.md).
