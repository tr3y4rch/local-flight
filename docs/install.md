# Local Flight Install Guide

Local Flight can run as a desktop app, a Raspberry Pi server, a kiosk display, a LAN browser board, a mobile companion, and an LED matrix feed. Pick the path that matches where you want the board to live.

If you are unsure, use the packaged Windows or macOS app on a desktop first. It gives you the native GUI, the local server, browser access, mobile access, and Matrix support from one install.

---

## Before You Start

- Local Flight is meant for your own trusted LAN, not the open internet.
- First launch opens a guided setup wizard before the normal app.
- You can choose **Community Relay**, **Bring your own keys**, or **VATSIM**.
- Diagnostics are optional. Manual reports stay available even if automatic diagnostics are off.
- The current client target is `0.2.7`. It is still beta software, but the client paths are now intended to work across the supported display types.

---

## Windows

Use this path for the easiest Windows desktop setup.

1. Download `LocalFlight-windows.zip` from the latest GitHub release.
2. Unzip it to any folder.
3. Double-click `LocalFlight.exe`.
4. Complete the setup wizard.

Windows may show a SmartScreen warning because the app is not signed yet. Click **More info**, then **Run anyway** if you trust the download source.

The release zip is self-contained. You do not need Python, Node, or the source installer for normal use.

### Windows Source Checkout

Use the source installer only if you are developing Local Flight or testing from a checkout:

```powershell
powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1
powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -DisplayMode Native
powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -DisplayMode Browser
powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -DisplayMode Headless
```

`Native` opens the Qt desktop shell. `Browser` opens the local browser UI. `Headless` runs only the local server for LAN/mobile/Matrix clients.

---

## macOS

Use this path for the easiest macOS desktop setup.

1. Download `LocalFlight-macos.zip` from the latest GitHub release.
2. Unzip it.
3. Drag `LocalFlight.app` to Applications.
4. Right-click **LocalFlight.app** and choose **Open** the first time if Gatekeeper warns about an unsigned app.
5. Complete the setup wizard.

The app launches the native Qt desktop shell. The LAN browser UI remains available from the local server while the app is running.

### macOS Source Checkout

Use the source installer only if you are developing Local Flight or testing from a checkout:

```bash
bash installers/macos/install.sh --display native
bash installers/macos/install.sh --display browser
bash installers/macos/install.sh --display headless
```

Use `native` for the normal desktop shell, `browser` when you specifically want the browser UI to open, or `headless` when this Mac should only serve other clients.

---

## Raspberry Pi

The Pi is best when you want Local Flight to run as a small always-on server or display box.

You can clone the repo on the Pi or download the versioned Pi source bundle from the latest release, for example:

```text
LocalFlight-pi-source-<version>.zip
```

For this target, that package name is expected to look like `LocalFlight-pi-source-0.2.7.zip` once the release bundle is built.

Unzip or clone on the Pi, then run:

```bash
bash installers/pi/install.sh
```

With no flag, the installer asks how the Pi should run and defaults to headless when you press Enter.

### Pi Modes

```bash
bash installers/pi/install.sh --headless
bash installers/pi/install.sh --native-kiosk
bash installers/pi/install.sh --kiosk
```

- `--headless`: local server only. Recommended for SSH installs, mobile companion, Matrix, and browser access from another device.
- `--native-kiosk`: local server plus a fullscreen native Qt display on the attached HDMI screen.
- `--kiosk`: local server plus a fullscreen Chromium display using the LAN browser UI on the attached HDMI screen.

The Pi server is reachable at:

```text
http://localflight.local:8000
```

If mDNS is not available on your network, use the Pi's LAN IP address, for example:

```text
http://192.168.1.42:8000
```

### Pi Management

After installation, use:

```bash
lf start
lf stop
lf logs
lf logs gui
lf update
```

`lf logs gui` is only useful when native Qt kiosk mode is installed.

---

## Mobile Companion

The mobile companion is an iOS-first developer preview. It is not on the App Store or TestFlight yet.

Use it when you want FIDS, radar, history, settings, docs, Matrix/Admin status, and feedback tools from an iPhone, iPad, or simulator.

```bash
cd mobile
npm install
npx expo install --fix
npm run verify
npm run ios
```

For a physical iPhone or iPad:

```bash
cd mobile
npm run ios:device
```

On first launch, the companion blocks normal app access until setup is complete. Enter your Local Flight server's LAN URL, for example:

```text
http://localflight.local:8000
http://192.168.1.42:8000
```

Do not use `localhost` on a phone. On a phone, `localhost` means the phone itself, not your Mac, Windows PC, or Raspberry Pi.

---

## First-Run Setup

Setup asks for:

1. Airport
2. Data access path
3. Optional provider keys
4. Diagnostics/reporting choice
5. Finish confirmation

### Data Access Choices

- **Community Relay**: recommended first path. Uses shared hosted schedule snapshots so you do not need a paid schedule key on day one.
- **Bring your own keys**: use your own AviationStack key, plus optional RapidAPI ADS-B Exchange and OpenSky credentials.
- **VATSIM**: no real-world schedule key. Uses virtual network data.

Community Relay protects shared provider usage, so a local 15 or 30 minute refresh setting may still reuse a cached shared airport snapshot for about one hour.

---

## Where Local Data Lives

Local Flight stores runtime data outside the source tree:

```text
~/.localflight/config.json
~/.localflight/storage/data/<IATA>/snapshots
~/.localflight/history.db
~/.localflight/logs
~/.localflight/api_usage.json
```

Provider keys live in your local `.env` when you choose the BYOK path.

---

## Quick Troubleshooting

- If mobile cannot connect, confirm the phone and server are on the same WiFi and use `http://localflight.local:8000` or the server LAN IP.
- If `localflight.local` does not resolve, use the LAN IP address.
- If a Pi display stays blank, confirm whether you installed `--native-kiosk`, `--kiosk`, or `--headless`.
- If a real-data board looks sparse, try a busier airport or wait for the next fetch. Provider coverage varies by airport and lane.
- If a Matrix board looks cramped, pick the closest panel preset first. Compact boards prioritize airport/lane, UTC/LT, weather, rows, and real-world gate/status information in that order.
- If diagnostics are off, manual reports still work from the Report page.

For display-choice help, see [Display Modes](display-modes.md).
