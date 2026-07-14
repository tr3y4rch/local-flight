# Local Flight Install Guide

Local Flight can run as a desktop app, a Raspberry Pi server, a kiosk display, a LAN browser board, the mobile app, and an LED matrix feed. Pick the path that matches where you want the board to live.

If you are unsure, use the packaged Windows or macOS app on a desktop first. It gives you the native GUI, the local server, browser access, mobile access, and Matrix support from one install.

Public project docs live at [beacontools.cc/local-flight](https://beacontools.cc/local-flight), support starts at [beacontools.cc/support](https://beacontools.cc/support), and the public privacy policy lives at [beacontools.cc/privacy](https://beacontools.cc/privacy). Privacy and diagnostics requests can use [beacontools.cc/privacy/choices](https://beacontools.cc/privacy/choices).

The website [Downloads section](https://beacontools.cc/local-flight#downloads) reads the official GitHub Releases list and links directly to the newest complete Windows, macOS, and Raspberry Pi packages. A direct package is shown only when the matching SHA256 file is present; GitHub remains the file host and source of record.

---

## Before You Start

- Local Flight is meant for your own trusted LAN, not the open internet.
- First launch opens a six-step guided setup wizard before the normal app.
- You can choose **Local Flight Relay**, **Use your own keys**, or **VATSIM**.
- The official hosted relay is `https://relay.beacontools.cc`.
- Diagnostics are optional. Manual reports stay available even if automatic diagnostics are off.
- The current release is `0.5.1` across desktop, Raspberry Pi, relay compatibility, and mobile store-testing builds.

---

## Windows

Use this path for the easiest Windows desktop setup.

1. After the `0.5.1` packages are published, choose Windows in the website Downloads section, or download `LocalFlight-0.5.1-Setup.exe` from the linked GitHub release. Until then, use the source-checkout path below rather than an older package.
2. Double-click the installer and follow the Local Flight wizard.
3. Launch Local Flight from the final installer page, Start Menu, or desktop shortcut.
4. Complete the setup wizard: Welcome, Airport, Flight Data, Optional Keys, Diagnostics, and Review & Open.

Only run an installer downloaded from the official GitHub release and verify its published SHA256 checksum. If Windows cannot verify a publisher signature, treat the package as untrusted until its checksum and release source are confirmed.

The installer is self-contained. You do not need Python, Node, or the source installer for normal use. A `LocalFlight-windows.zip` artifact may also be attached for portable/manual installs: unzip it to any folder, then double-click `LocalFlight.exe`.
The packaged `LocalFlight.exe` is a windowed desktop app, so it should open the branded Local Flight UI without a Python or cmd console in front.
While Local Flight is running, its notification-area menu can reopen the app, jump to Display, FIDS, Radar, History, or Settings, open the LAN browser, restart flight updates, or quit cleanly.

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

Use this path for the current macOS desktop setup.

1. On an Apple silicon Mac, choose macOS in the website Downloads section, or download `LocalFlight-0.5.1-macos.pkg` and its checksum from the linked GitHub release. The current package is ARM64-only; Intel Mac users should use the source checkout until a separate universal build is published.
2. Open the package, complete the macOS installer flow, then launch `Local Flight.app` from Applications.
3. Complete the setup wizard: Welcome, Airport, Flight Data, Optional Keys, Diagnostics, and Review & Open.

The app launches the native Qt desktop shell. The LAN browser UI remains available from the local server while the app is running.
The Dock and menu-bar status menu can reopen Local Flight, jump to its main views, open the LAN browser, restart flight updates, or quit cleanly.
Finder opens the app directly, so normal use shows the branded app/splash rather than Terminal. The current package is Developer ID signed and notarized by Apple. Never disable Gatekeeper globally or lower system-wide security settings. Local Flight settings, history, logs, install identity, and activation token remain in your user folder and survive replacing the app.

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

You can clone the repo on the Pi or choose Raspberry Pi in the website Downloads section to fetch the versioned source bundle from the latest complete GitHub release, for example:

```text
LocalFlight-pi-source-<version>.zip
```

The `0.5.1` package name is `LocalFlight-pi-source-0.5.1.zip` with a matching `.sha256` file.

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

- `--headless`: local server only. Recommended for SSH installs, mobile Companion, Matrix, and browser access from another device.
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

The mobile app is aligned to `0.5.1` for TestFlight and Google Play testing. Public store listings are not live yet; availability is published at [beacontools.cc/local-flight/mobile](https://beacontools.cc/local-flight/mobile). The commands below are for source development.

Use it when you want a lightweight airport-board view, radar, history, control, and support tools from an iPhone, iPad, or Android device.

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

### Companion

Choose **Companion** if you already run Local Flight on a desktop or Raspberry Pi.

Enter your Local Flight server's LAN URL, for example:

```text
http://192.168.1.42:8000
http://localflight.local:8000
```

Do not use `localhost` on a phone. On a phone, `localhost` means the phone itself, not your Mac, Windows PC, or Raspberry Pi. Keep the `:8000` port in manual URLs. Prefer the LAN IP shown in Local Flight Settings when more than one Local Flight server is on the same network; `localflight.local` is convenient but can point at a different Pi/desktop if you run multiple servers.

The QR pairing code in native Settings and LAN browser Settings is fingerprint-bound to the server that created it. If your phone scans a QR that resolves to another Local Flight host, the mobile app refuses to save that pairing instead of silently connecting to the wrong server.

Companion keeps the richer paired experience: server WebSocket updates when on LAN, host status, airport/source/refresh controls, History, support/reporting, safe Matrix live-remote controls, and mobile/server double-consent for automatic diagnostics.

Remote Companion is part of the same Companion mode. In **Pair Mobile**, choose the QR that matches what you want: the QR shown by default is **LAN only**; **Create LAN + Remote QR** makes one short-lived QR that connects LAN and adds encrypted away-from-home backup in one scan. Scan it while the phone is still on the LAN. The phone verifies the encrypted round trip before saving it, then uses LAN first and Remote only when the local host cannot be reached. The host must stay online. A fresh QR for the same phone replaces its previous remote grant.

After pairing, the mobile connection panel shows whether Remote backup is verified. **Test Remote Backup** can repeat the safe smoke test later. It sends a tiny encrypted probe through the relay, retries only once for short-lived network/host failures, and then explains the likely cause instead of showing raw HTTP text.

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
~/.localflight/api_usage.sqlite3
~/.localflight/api_usage.json  (legacy compatibility only)
```

Provider keys live in the source checkout `.env` for source installs. Packaged desktop apps store them in `~/.localflight/.env`, outside the signed application bundle.

On macOS, Linux, or Raspberry Pi, contributors can run the security preflight
after upgrading an older checkout. It reports credential-like local files whose
permissions are too broad without reading or printing their contents:

```bash
python scripts/security_preflight.py
```

To apply the one-time owner-only permission repair explicitly:

```bash
python scripts/security_preflight.py --fix-permissions
```

This uses POSIX owner-only modes (`0600` for credential files); Windows keeps
its normal account ACL behavior. Local Flight also repairs app-written identity,
activation, provider-key, and Remote Companion files on best-effort load/write.

---

## Quick Troubleshooting

- If Companion cannot connect on LAN, confirm the phone and server are on the same WiFi and use the server LAN IP shown in Settings. Use `http://localflight.local:8000` only when you have one Local Flight server on that LAN.
- If Remote Companion shows offline away from LAN, run **Test Remote** from the mobile connection panel. If it reports host offline, open Local Flight on the desktop/Pi. If it reports grant revoked or key mismatch, pair the phone again from that host. If it reports rate limited, wait before trying again.
- If Standalone mobile cannot load, check internet access first. It does not need your desktop or Pi to be online.
- If Standalone FIDS looks stale, remember that it is deliberately limited to a 3-hour auto-refresh cadence. Pull to refresh only when you intentionally need a fresh check.
- If Standalone Radar refuses a range, use `1`, `3`, `5`, or `10` NM.
- If `localflight.local` resolves to the wrong server, use the LAN IP address or re-scan the fingerprint-bound QR from the server you want.
- If a Pi display stays blank, confirm whether you installed `--native-kiosk`, `--kiosk`, or `--headless`.
- If a real-data board looks sparse, try a busier airport or wait for the next fetch. Provider coverage varies by airport and lane, and cached relay snapshots may intentionally remain in place when a live provider returns suspiciously thin data.
- If a Matrix board looks cramped, pick the closest panel preset first. Compact boards prioritize airport/lane, UTC/LT, weather, rows, and real-world gate/status information in that order.
- If diagnostics are off, manual reports still work from the Report page.

For display-choice help, see [Display Modes](display-modes.md).
