# Local Flight Companion

React Native / Expo companion app for Local Flight.

The mobile companion is **work in progress**. It is version-synced with the desktop app for the current release line, but it is still a developer preview rather than a public App Store, TestFlight, Play Store, or APK release.

The Python/FastAPI app remains the server of record. This mobile app is a LAN client that reads Local Flight APIs, listens for WebSocket updates, and starts with a native version of the airport-board mockup.

## Requirements

- macOS with Xcode installed
- Node.js 20 LTS or newer for Expo SDK 55
- iPhone/iPad connected for device builds, or an iOS simulator
- Local Flight running on the same network

Expo SDK 55 targets React Native 0.83 and React 19.2. Run `npx expo install --fix` after install on the Mac to align patch versions.

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

## Phase 1 Scope

- Store the Local Flight server URL on-device with SecureStore
- Connection test against `/api/health`
- Dashboard data from `/api/admin/system`, `/api/config`, `/api/health`, `/api/admin/budget`, `/api/admin/connections`, `/api/admin/updates`, and `/api/metar`
- Native FIDS list from `/api/fids`
- Companion-specific ID and platform reporting so mobile-originated actions are traceable separately from the desktop/server app
- Mockup-inspired shell: Flight Island, airport/live header, METAR strip, FIDS tabs, pinned flight, compact board rows, and four-item bottom nav
- Settings tools for airport/source/update interval, Matrix preview, Admin, scheduler restart, feedback, and Buy Me a Coffee
- Feedback and crash reporting, with automatic diagnostics following the server's chosen privacy mode
- WebSocket listener for `/ws` `snapshot_updated`, `config_updated`, and `scheduler_restarted` events
- Responsive iPhone/iPad layout foundation

## Not Yet

- Public iOS release
- Public Android release
- QR pairing and per-device tokens
- Production-ready admin permission model

## Next

- QR pairing and per-device tokens before broader mutating admin controls
- Android test pass after the iOS companion stabilizes
- Real navigation stack once more screens exist
- iPad display mode with keep-awake
- Native radar using `react-native-svg`
