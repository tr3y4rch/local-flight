# Local Flight Companion

Phase 1 iOS-first React Native companion app for Local Flight. Companion build: `0.2.2b1`.

The Python/FastAPI app remains the server of record. This mobile app is a LAN client that reads Local Flight APIs, listens for WebSocket updates, and starts with a native version of the airport-board iOS mockup.

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
- Dashboard data from `/api/admin/system`, `/api/config`, `/api/health`, `/api/admin/budget`, and `/api/metar`
- Native FIDS list from `/api/fids`
- Mockup-inspired shell: pseudo status bar/dynamic island, airport badge, live pill, METAR strip, FIDS tabs, pinned flight card, compact board rows, and bottom nav
- WebSocket listener for `/ws` `snapshot_updated` events
- Responsive iPhone/iPad layout foundation

## Next

- QR pairing and per-device tokens before mutating admin controls
- Real navigation stack once more screens exist
- iPad display mode with keep-awake
- Native radar using `react-native-svg`
