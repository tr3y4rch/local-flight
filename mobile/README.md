# Local Flight Companion

React Native / Expo mobile app for Local Flight.

The mobile app is an iOS-first developer preview. It is not on the App Store, TestFlight, Play Store, or available as an APK yet, but it now supports two first-run paths:

- **LAN Companion:** pair with the Local Flight desktop or Raspberry Pi server on your Wi-Fi/LAN. This keeps the full companion behavior.
- **Standalone:** use the hosted Local Flight relay directly for a simplified phone board. This is intentionally rate-limited to protect shared relay/API tokens.

For most home setups, start with LAN Companion. Use Standalone when you want a light mobile FIDS/Radar/History app without running your own Local Flight server.

---

## Requirements

- macOS with an Xcode version compatible with Expo SDK 55
- Node.js 20 LTS or newer
- iPhone/iPad connected for device builds, or an iOS simulator
- For LAN Companion: Local Flight already running on the same Wi-Fi/LAN
- For Standalone: internet access to the hosted relay

Expo SDK 55 targets React Native 0.83 and React 19.2. Run `npm run doctor` after install on the Mac to confirm the active Xcode, CocoaPods, and package versions are compatible.

If Xcode was freshly installed or upgraded, accept the Apple SDK license first:

```bash
sudo xcodebuild -license accept
sudo xcode-select --reset
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

If `expo run:ios` exits with a destination/runtime error, open Xcode -> Settings -> Components and install the matching iOS simulator runtime.

---

## First Run

```bash
cd mobile
npm install
npx expo install --fix
npm run verify
npm run ios
```

For the normal development loop, keep it fast:

```bash
cd mobile
npm run verify
npm run ios
```

`npm run verify` runs TypeScript plus Expo Doctor. Use the running simulator or device for visual checks instead of the screenshot matrix during regular feature work.

To retest the forced first-launch setup and diagnostics consent on a simulator:

```bash
cd mobile
xcrun simctl uninstall booted com.localflight.companion || true
npm run ios
```

This removes the simulator app data so the setup gate appears again. On a physical iPhone or iPad, delete the app from the device before reinstalling.

For a physical iPhone or iPad:

```bash
cd mobile
npm run ios:device
```

On first launch, choose how this device should work.

### LAN Companion

Choose **LAN Companion** when you already run Local Flight on Windows, macOS, or Raspberry Pi.

Enter the Local Flight server URL from your LAN, for example:

```text
http://192.168.1.42:8000
```

Do not use `localhost` on a physical iPhone. `localhost` means the phone itself, not your Mac, Windows PC, or Raspberry Pi.

### Standalone

Choose **Standalone** when this phone should use the hosted relay directly.

Standalone setup asks for:

1. Airport
2. Mobile diagnostics choice
3. Relay activation

Standalone mode is deliberately simpler than the full companion:

- FIDS auto-refreshes no faster than every 3 hours.
- Radar refreshes no faster than every 5 minutes.
- Radar range choices are `1`, `3`, `5`, and `10` NM only.
- No WebSocket connection is opened.
- Matrix, Admin, scheduler restart, server URL tools, and other server-control features are hidden.
- History is stored locally on the phone with Expo SQLite and retained for 30 days or 1,000 rows, whichever is smaller.

Deep geometry QA is optional and intentionally slow:

```bash
cd mobile
npm run layout:ios -- --runtime latest --only iphone-standard
```

The screenshot script builds a self-contained simulator app and captures portrait/landscape PNGs under `mobile/.layout-smoke/`. Use it only before a release or when debugging a specific layout regression. Add `--skip-build` to reuse the previous bundled simulator app, `--fresh-devices` to force clean temporary simulators, or `--runtime all` for the full installed iOS runtime matrix. iPad simulators are listed under iOS runtimes in `simctl`, which is how Apple exposes iPadOS geometry for this workflow.

---

## What Works Now

- First-run setup choice for LAN Companion or Standalone
- FIDS/Board, Radar, History, and Settings as the daily-use mobile surfaces
- SecureStore persistence for setup mode, server URL, companion ID, standalone relay install ID, standalone activation token, standalone airport, mobile diagnostics mode, pinned flight, profiles, and mobile appearance choices
- LAN Companion connection checks against `/api/health`
- LAN Companion dashboard data from `/api/mobile/summary` plus the existing local APIs
- Standalone summary, FIDS, Radar, and METAR data from relay `/v1/mobile/*` endpoints
- Native FIDS list from local `/api/fids` in LAN Companion mode and relay `/v1/mobile/fids` in Standalone mode
- Flight details from `/api/fids/detail`, including the server's shared current-source detail model for real vs VATSIM schedule, motion, aircraft, weather, source confidence, and history fields when available
- Airport, source, and refresh interval editing. The server offers 15, 30, 45, and 60 minute choices plus longer 2, 4, 8, 12, and 24 hour choices where the active schedule mode allows them. Community Relay shows hourly-or-slower choices because shared airport snapshots protect upstream schedule access.
- Pinned flight island with pin/unpin and tap-for-detail behavior
- WebSocket listener for `/ws` `snapshot_updated`, `config_updated`, and `scheduler_restarted` events in LAN Companion mode only
- Independent mobile appearance with dark/light theme plus `standard`, `technical`, `neon`, `cyan`, and `crt` skins
- Branded launch overlay with a continuous radar sweep, status text fade, breathing status dot, blinking board LED, and shared Local Flight wordmark text
- Native-feeling interaction polish on key taps, chips, pinned-flight actions, and weather icon changes through haptics, press-scale feedback, and small transitions
- Server-backed Matrix runtime editor using `/api/matrix/config`, with local-only panel preview presets. Real-world Matrix feeds can expose gate/stand labels when available; VATSIM Matrix presets intentionally hide gate placeholders.
- Fullscreen landscape FIDS from any screen, with normal portrait state restored when rotating back
- Mobile-owned radar radius controls. LAN Companion uses the paired server for runway and airport-surface drawing; Standalone uses the relay mobile radar response for this pass.
- Local standalone history database with Expo SQLite
- Feedback and crash reporting through the connected Local Flight server in LAN Companion mode, or directly through the hosted relay in Standalone mode

Standalone deliberately hides Matrix, Admin, scheduler restart, server-control panels, and LAN companion check-in. The goal is a useful mobile board, not a mini desktop clone.

---

## Privacy Model

### LAN Companion

- It talks to your Local Flight server over your LAN.
- It does not call AviationStack, ADS-B Exchange, RapidAPI, OpenSky, VATSIM, or the hosted relay directly.
- Automatic mobile reports require both the mobile-local diagnostics choice and the connected server diagnostics mode to allow automatic reporting.
- Manual reports remain available from the app.
- Expo JS/React errors are covered by the current crash reporter. Native iOS crashes before JavaScript starts are not covered without a native crash-reporting service or Apple crash logs.

### Standalone

- It talks directly to the hosted Local Flight relay.
- It registers a separate relay install UUID and activation token for this mobile install.
- It stores the selected airport and local flight history on the device.
- Manual reports go directly to relay `/v1/reports`.
- Automatic reports only send when the mobile diagnostics choice is `auto` or `auto_logs`.
- It does not store phone-local history on the relay.

The companion ID and standalone relay install ID are install-scoped. They are there so reports, quotas, and troubleshooting can say "this came from this app install" without needing an account.

---

## Structure

- `App.tsx` is only the provider entrypoint.
- `src/app/AppShell.tsx` coordinates setup mode, connection state, refresh flow, WebSocket handling, standalone relay flow, and shared app chrome.
- `src/api/standalone.ts` is the relay-backed mobile data/report client for Standalone mode.
- `src/domain/` contains pure helpers and constants for flights, formatting, radar, matrix, and feedback context.
- `src/hooks/` contains stateful behavior such as launch/bootstrap, dashboard refresh, flight detail loading, and Matrix draft/save/reset.
- `src/screens/AppScreens.tsx` contains the main screens and sheets.
- `src/storage/standaloneHistory.ts` stores successful standalone FIDS rows locally with Expo SQLite.
- `src/theme/` contains mobile appearance tokens, runtime appearance storage, and the style bridge used by extracted screens.

---

## Not Yet

- Public iOS release
- Public Android release
- QR pairing and per-device tokens
- Production-ready admin permission model
- Native crash capture before JavaScript starts
- Full standalone flight-detail endpoint parity; Standalone currently focuses on Board, Radar, History, Settings, and reports

---

## Next

- QR pairing and per-device tokens before broader mutating admin controls
- Android test pass after the iOS companion stabilizes
- Real navigation stack once screen history/deep links justify it
- iPad and landscape display-mode polish
- Standalone on-device UX pass on a real iPhone after relay deployment
- Native radar rendering polish around labels, density, and tablet geometry
