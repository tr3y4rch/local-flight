# Local Flight Companion

React Native / Expo companion app for Local Flight.

The mobile companion is **work in progress**. It is version-synced with the desktop app for the current release line, but it is still a developer preview rather than a public App Store, TestFlight, Play Store, or APK release.

The Python/FastAPI app remains the server of record. This mobile app is a LAN client that reads Local Flight APIs, listens for WebSocket updates, and starts with a native version of the airport-board mockup.

## Requirements

- macOS with an Xcode version compatible with Expo SDK 55
- Node.js 20 LTS or newer for Expo SDK 55
- iPhone/iPad connected for device builds, or an iOS simulator
- Local Flight running on the same network

Expo SDK 55 targets React Native 0.83 and React 19.2. Run `npm run doctor` after install on the Mac to confirm the active Xcode and package versions are compatible.

## First Run

```bash
cd mobile
npm install
npx expo install --fix
npm run doctor
npm run ios
```

For a physical iPhone or iPad:

```bash
cd mobile
npm run ios:device
```

In the app, enter the Local Flight server URL from your LAN, for example:

```text
http://192.168.1.42:8000
```

Do not use `localhost` on a physical iPhone. `localhost` means the phone itself, not your Mac or Windows machine.

## Current Dev Scope

- Store the Local Flight server URL on-device with SecureStore
- Connection test against `/api/health`
- Dashboard data from `/api/admin/system`, `/api/config`, `/api/health`, `/api/admin/budget`, `/api/admin/connections`, `/api/admin/updates`, and `/api/metar`
- Native FIDS list from `/api/fids`
- Companion-specific ID and platform reporting so mobile-originated actions are traceable separately from the desktop/server app
- Mockup-inspired shell: Flight Island, airport/live header, METAR strip, FIDS tabs, pinned flight, compact board rows, and four-item bottom nav
- Settings tools for airport/source/update interval, Matrix preview, Admin, scheduler restart, feedback, and Buy Me a Coffee
- Feedback and crash reporting, with automatic diagnostics requiring both the mobile-local choice and the connected server's privacy mode
- WebSocket listener for `/ws` `snapshot_updated`, `config_updated`, and `scheduler_restarted` events
- Responsive iPhone/iPad layout foundation
- Independent mobile appearance with dark/light theme plus standard, technical, neon, cyan, and CRT skins
- Server-backed Matrix runtime editor using `/api/matrix/config`, with local-only panel preview presets
- Landscape split display for FIDS/Radar and responsive radar pinch zoom across the existing 20/40/80 NM ranges

## Structure

- `App.tsx` is only the provider entrypoint.
- `src/app/AppShell.tsx` coordinates connection state, refresh flow, WebSocket handling, and shared app chrome.
- `src/domain/` contains pure helpers and constants for flights, formatting, radar, matrix, and feedback context.
- `src/hooks/` contains stateful behavior such as launch/bootstrap, flight detail loading, and Matrix draft/save/reset.
- `src/screens/AppScreens.tsx` contains the main screens and sheets.
- `src/theme/` contains mobile appearance tokens, runtime appearance storage, and the style bridge used by extracted screens.

## Not Yet

- Public iOS release
- Public Android release
- QR pairing and per-device tokens
- Production-ready admin permission model

## Next

- QR pairing and per-device tokens before broader mutating admin controls
- Android test pass after the iOS companion stabilizes
- Real navigation stack once screen history/deep links justify it
- iPad keep-awake/display-mode polish
- Native radar using `react-native-svg`
