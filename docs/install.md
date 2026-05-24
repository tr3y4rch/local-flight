# Local Flight Install Guide

Local Flight can run as a desktop app, a Raspberry Pi server, a kiosk display, a LAN browser board, the mobile app, and an LED matrix feed. Pick the path that matches where you want the board to live.

If you are unsure, use the packaged Windows or macOS app on a desktop first. It gives you the native GUI, the local server, browser access, mobile access, and Matrix support from one install.

Public project docs live at [beacontools.cc/local-flight](https://beacontools.cc/local-flight), support starts at [beacontools.cc/support](https://beacontools.cc/support), and the public privacy policy lives at [beacontools.cc/privacy](https://beacontools.cc/privacy). Privacy and diagnostics requests can use [beacontools.cc/privacy/choices](https://beacontools.cc/privacy/choices).

---

## Before You Start

- Local Flight is meant for your own trusted LAN, not the open internet.
- First launch opens a six-step guided setup wizard before the normal app.
- You can choose **Local Flight Relay**, **Use your own keys**, or **VATSIM**.
- The official hosted relay is `https://relay.beacontools.cc`; older Fly.io relay roots remain compatibility-only for existing installs.
- Diagnostics are optional. Manual reports stay available even if automatic diagnostics are off.
- The current client target is `0.2.7`. It is still beta software, but the client paths are now intended to work across the supported display types. Preliminary `0.2.8` notes exist for the next docs/LAN Settings/mobile pairing polish, but release artifacts are still `0.2.7` until the version is deliberately bumped.

---

## Windows

Use this path for the easiest Windows desktop setup.

1. Download `LocalFlight-0.2.7-Setup.exe` from the latest GitHub release.
2. Double-click the installer and follow the Local Flight wizard.
3. Launch Local Flight from the final installer page, Start Menu, or desktop shortcut.
4. Complete the setup wizard: Welcome, Airport, Flight Data, Optional Keys, Diagnostics, and Review & Open.

Windows may show a SmartScreen warning because the app is not signed yet. Click **More info**, then **Run anyway** if you trust the download source.

The installer is self-contained. You do not need Python, Node, or the source installer for normal use. A `LocalFlight-windows.zip` artifact may also be attached for portable/manual installs: unzip it to any folder, then double-click `LocalFlight.exe`.
The packaged `LocalFlight.exe` is a windowed desktop app, so it should open the branded Local Flight UI without a Python or cmd console in front.

### Windows Source Checkout

Use the source installer only if you are developing Local Flight or testing from a checkout:

```powershell
powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1
powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -DisplayMode Native
powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -DisplayMode Browser
powershell -ExecutionPolicy Bypass -File installers\windows\install.ps1 -DisplayMode Headless
```

`Native` opens the Qt desktop shell. `Browser` opens the local browser UI. `Headless` runs only the local server for LAN/mobile/Matrix clients.

The source installer creates a **Local Flight** desktop shortcut that launches through `pythonw.exe`, so normal source-checkout use is also quiet. Use `start.bat` from the repo root when you intentionally want a visible developer console with startup logs.

---

## macOS

Use this path for the easiest macOS desktop setup.

1. Download `LocalFlight-0.2.7-macos.pkg` from the latest GitHub release.
2. Double-click the package and follow the standard macOS Installer steps.
3. Launch **Local Flight** from Applications.
4. Complete the setup wizard: Welcome, Airport, Flight Data, Optional Keys, Diagnostics, and Review & Open.

The app launches the native Qt desktop shell. The LAN browser UI remains available from the local server while the app is running.
Finder opens the installed app directly, so normal release use should show the branded app/splash rather than Terminal. The installer only places the app in Applications; your Local Flight settings, history, logs, install ID, and activation token remain in your user folder.

### macOS Source Checkout

Use the source installer only if you are developing Local Flight or testing from a checkout:

```bash
bash installers/macos/install.sh --display native
bash installers/macos/install.sh --display browser
bash installers/macos/install.sh --display headless
```

Use `native` for the normal desktop shell, `browser` when you specifically want the browser UI to open, or `headless` when this Mac should only serve other clients.

The source installer also builds `~/Applications/LocalFlight.app`; use that app bundle for quiet Finder launches while developing. Use `./start.command` from the project root or `bash installers/macos/start.sh` when you intentionally want Terminal output for development/debugging.

If a quiet app launch fails early, bootstrap output is written locally under `~/.localflight/logs/` so troubleshooting does not require keeping Terminal open.

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

- `--headless`: local server only. Recommended for SSH installs, mobile LAN Companion, Matrix, and browser access from another device.
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

## Mobile App

The mobile app is a developer preview. iOS is the primary validation path; Android local development builds are also supported. It is not on the App Store, TestFlight, Play Store, or available as a release APK yet.

Use it when you want a lightweight airport-board view, radar, history, control, and support tools from an iPhone, iPad, or simulator.

```bash
cd mobile
npm install
npx expo install --fix
npm run verify
npm run ios
```

For Android emulator/device development:

```bash
cd mobile
npm run verify
npm run android
```

For a physical iPhone or iPad:

```bash
cd mobile
npm run ios:device
```

On first launch, the app blocks normal access until setup is complete and asks how this device should be used.

### LAN Companion

Choose **LAN Companion** if you already run Local Flight on a desktop or Raspberry Pi.

Enter your Local Flight server's LAN URL, for example:

```text
http://192.168.1.42:8000
http://localflight.local:8000
```

Do not use `localhost` on a phone. On a phone, `localhost` means the phone itself, not your Mac, Windows PC, or Raspberry Pi. Keep the `:8000` port in manual URLs. Prefer the LAN IP shown in Local Flight Settings when more than one Local Flight server is on the same network; `localflight.local` is convenient but can point at a different Pi/desktop if you run multiple servers.

The QR pairing code in native Settings and LAN browser Settings is fingerprint-bound to the server that created it. If your phone scans a QR that resolves to another Local Flight host, the mobile app refuses to save that pairing instead of silently connecting to the wrong server.

LAN Companion keeps the richer paired experience: server WebSocket updates, host status, airport/source/refresh controls, History, support/reporting, safe Matrix live-remote controls, and mobile/server double-consent for automatic diagnostics.

### Standalone

Choose **Standalone** if the phone should use the hosted Beacon Tools relay directly without a desktop or Pi server.

Standalone is intentionally simpler and rate-limited:

- FIDS auto-refreshes no faster than every 3 hours.
- Radar refreshes no faster than every 5 minutes.
- Radar range choices are `1`, `3`, `5`, and `10` NM.
- No Matrix, Admin, scheduler restart, LAN server controls, or WebSocket connection.
- History is stored locally on the phone for 30 days or 1,000 deduped movements.

The app creates a mobile relay install ID, receives an activation token, stores both locally with Expo SecureStore, and keeps the selected airport on the device.

---

## First-Run Setup

Setup asks for:

1. Welcome
2. Airport
3. Data access path
4. Optional provider keys
5. Diagnostics/reporting choice
6. Review and open

### Data Access Choices

- **Local Flight Relay**: recommended first path. Uses `https://relay.beacontools.cc` and shared hosted schedule snapshots so you do not need a paid schedule key on day one. The relay is cache-first and may combine compatible real schedule providers behind the scenes, currently AeroDataBox primary schedule data plus AviationStack sparse fill/fallback where configured, to keep boards populated.
- **Use your own keys**: use your own AeroDataBox schedule key (API.Market by default, RapidAPI if selected by env), AviationStack schedule key, plus optional RapidAPI ADS-B Exchange and OpenSky credentials.
- **VATSIM**: no real-world schedule key. Uses virtual network data.

Local Flight Relay protects shared provider usage, so real schedule refresh choices are hourly-or-slower when the app is using the hosted shared relay. If a live provider is unavailable or the relay asks clients to back off, Local Flight can keep serving the latest safe cached board instead of replacing it with a bad empty refresh.

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

- If mobile cannot connect, confirm the phone and server are on the same WiFi and use the server LAN IP shown in Settings. Use `http://localflight.local:8000` only when you have one Local Flight server on that LAN.
- If Standalone mobile cannot load, check internet access first. It does not need your desktop or Pi to be online.
- If Standalone FIDS looks stale, remember that it is deliberately limited to a 3-hour auto-refresh cadence. Pull to refresh only when you intentionally need a fresh check.
- If Standalone Radar refuses a range, use `1`, `3`, `5`, or `10` NM.
- If `localflight.local` resolves to the wrong server, use the LAN IP address or re-scan the fingerprint-bound QR from the server you want.
- If a Pi display stays blank, confirm whether you installed `--native-kiosk`, `--kiosk`, or `--headless`.
- If a real-data board looks sparse, try a busier airport or wait for the next fetch. Provider coverage varies by airport and lane, and cached relay snapshots may intentionally remain in place when a live provider returns suspiciously thin data.
- If a Matrix board looks cramped, pick the closest panel preset first. Compact boards prioritize airport/lane, UTC/LT, weather, rows, and real-world gate/status information in that order.
- If diagnostics are off, manual reports still work from the Report page.

For display-choice help, see [Display Modes](display-modes.md).
