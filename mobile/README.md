# Local Flight Companion

React Native / Expo companion app for Local Flight.

The companion is an iOS-first developer preview. It is not on the App Store, TestFlight, Play Store, or available as an APK yet, but it is now a real LAN companion instead of a bare prototype.

The Python/FastAPI desktop or Pi app remains the server of record. The mobile app reads that server's APIs, listens for WebSocket updates, and keeps its own mobile-only appearance and diagnostics choices.

---

## Requirements

- macOS with an Xcode version compatible with Expo SDK 55
- Node.js 20 LTS or newer
- iPhone/iPad connected for device builds, or an iOS simulator
- Local Flight already running on the same WiFi/LAN

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

In the app, enter the Local Flight server URL from your LAN, for example:

```text
http://192.168.1.42:8000
```

Do not use `localhost` on a physical iPhone. `localhost` means the phone itself, not your Mac, Windows PC, or Raspberry Pi.

Deep geometry QA is optional and intentionally slow:

```bash
cd mobile
npm run layout:ios -- --runtime latest --only iphone-standard
```

The screenshot script builds a self-contained simulator app and captures portrait/landscape PNGs under `mobile/.layout-smoke/`. Use it only before a release or when debugging a specific layout regression. Add `--skip-build` to reuse the previous bundled simulator app, `--fresh-devices` to force clean temporary simulators, or `--runtime all` for the full installed iOS runtime matrix. iPad simulators are listed under iOS runtimes in `simctl`, which is how Apple exposes iPadOS geometry for this workflow.

---

## What Works Now

- FIDS and Radar as the main daily-use companion screens
- Settings as the main tool hub for server connection, appearance, matrix, admin summary, docs, feedback, and local profiles
- History, Matrix, Admin, and Docs launched from Settings instead of crowding the bottom nav
- SecureStore persistence for server URL, companion ID, mobile diagnostics mode, and mobile appearance choices
- Connection checks against `/api/health`
- Dashboard data from `/api/admin/system`, `/api/config`, `/api/health`, `/api/admin/budget`, `/api/admin/connections`, `/api/admin/updates`, and `/api/metar`
- Native FIDS list from `/api/fids`
- Flight details from `/api/fids/detail`, including real vs VATSIM detail modes when the server has that data
- Airport, source, and refresh interval editing. The server offers 15, 30, 45, and 60 minute choices plus longer 2, 4, 8, 12, and 24 hour choices. Community Relay may still reuse already-cached airport snapshots for about one hour to protect shared upstream schedule access.
- Pinned flight island with pin/unpin and tap-for-detail behavior
- WebSocket listener for `/ws` `snapshot_updated`, `config_updated`, and `scheduler_restarted` events
- Independent mobile appearance with dark/light theme plus `standard`, `technical`, `neon`, `cyan`, and `crt` skins
- Server-backed Matrix runtime editor using `/api/matrix/config`, with local-only panel preview presets
- Fullscreen landscape FIDS from any screen, with normal portrait state restored when rotating back
- Mobile-owned radar radius controls with server-mediated runway and airport-surface drawing
- In-app Markdown reader for README, Privacy, and Changelog
- Feedback and crash reporting through the connected Local Flight server

---

## Privacy Model

The companion is server-mediated:

- It talks to your Local Flight server over your LAN.
- It does not call AviationStack, ADS-B Exchange, RapidAPI, OpenSky, VATSIM, or the hosted relay directly.
- Automatic mobile reports require both the mobile-local diagnostics choice and the connected server diagnostics mode to allow automatic reporting.
- Manual reports remain available from the app.
- Expo JS/React errors are covered by the current crash reporter. Native iOS crashes before JavaScript starts are not covered without a native crash-reporting service or Apple crash logs.

The companion ID is install-scoped. It is there so reports and connection logs can say "this came from the phone" without needing an account.

---

## Structure

- `App.tsx` is only the provider entrypoint.
- `src/app/AppShell.tsx` coordinates connection state, refresh flow, WebSocket handling, and shared app chrome.
- `src/domain/` contains pure helpers and constants for flights, formatting, radar, matrix, and feedback context.
- `src/hooks/` contains stateful behavior such as launch/bootstrap, dashboard refresh, flight detail loading, and Matrix draft/save/reset.
- `src/screens/AppScreens.tsx` contains the main screens and sheets.
- `src/theme/` contains mobile appearance tokens, runtime appearance storage, and the style bridge used by extracted screens.

---

## Not Yet

- Public iOS release
- Public Android release
- QR pairing and per-device tokens
- Production-ready admin permission model
- Native crash capture before JavaScript starts

---

## Next

- QR pairing and per-device tokens before broader mutating admin controls
- Android test pass after the iOS companion stabilizes
- Real navigation stack once screen history/deep links justify it
- iPad keep-awake/display-mode polish
- Native radar rendering polish around labels, density, and tablet geometry
