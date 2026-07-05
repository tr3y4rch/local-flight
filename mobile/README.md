# Local Flight Mobile

React Native / Expo mobile app for Local Flight.

<<<<<<< HEAD
The mobile app is a store-bound beta candidate for TestFlight and Google Play, with iOS and Android validation paths. Public store downloads are not live yet. It supports two first-run paths:

- **Companion:** pair with the Local Flight desktop or Raspberry Pi server on your Wi-Fi/LAN. Companion uses LAN first and can use encrypted Remote Companion fallback after a relay-linked host grants this phone access.
- **Standalone:** use the hosted Local Flight relay directly for a simplified phone board. This is intentionally rate-limited to protect shared relay/API tokens.

For most home setups, start with Companion. Use Standalone when you want a light mobile FIDS/Radar/History app without running your own Local Flight server.
=======
Local Flight Mobile is in internal beta for **iOS TestFlight** and **Google Play testing**. Public store downloads are not live yet. The app has two first-run modes:

- **Standalone:** use the Beacon Tools relay directly for a simple phone board. No desktop or Raspberry Pi server is required.
- **LAN Companion:** pair with your own Local Flight desktop or Raspberry Pi server on the same Wi-Fi/LAN.

For most testers, choose **Standalone** first. It is the quickest way to see the Board, Radar, History, and Settings without extra hardware. Choose **LAN Companion** when you already run Local Flight at home and want the phone to act as a remote board, radar, and control surface.
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae

Local Flight is a personal display aid. Flight, weather, radar, and airport-surface data can be delayed, incomplete, or unavailable. Do not use it for navigation, dispatch, operational control, or safety decisions.

<<<<<<< HEAD
The public front door for Mobile users is [beacontools.cc/local-flight/mobile](https://beacontools.cc/local-flight/mobile). Use that page for install guidance, release notes, support links, source links, and store metadata. The public privacy policy is [beacontools.cc/privacy](https://beacontools.cc/privacy). Remote Companion and Standalone use the Beacon Tools relay at `https://relay.beacontools.cc` for different jobs: encrypted fallback for a paired host vs phone-only board data.
=======
Public links:
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae

- Mobile page: [beacontools.cc/local-flight/mobile](https://beacontools.cc/local-flight/mobile)
- Privacy policy: [beacontools.cc/privacy](https://beacontools.cc/privacy)
- Support: [beacontools.cc/support](https://beacontools.cc/support)
- Relay used by Standalone: `https://relay.beacontools.cc`

---

## Internal Beta Install Path

<<<<<<< HEAD
- macOS with an Xcode version compatible with Expo SDK 55
- Android Studio with the Android SDK command-line tools for Android builds
- Node.js 24 LTS recommended. Node.js 26 Current is also supported for local development. The repo includes a root `.nvmrc`; run `nvm use` from the project root if you use nvm and want the LTS default.
- iPhone/iPad connected for device builds, or an iOS simulator
- Android phone with USB debugging enabled, or an Android Studio emulator
- For Companion: Local Flight already running on the same Wi-Fi/LAN. Remote Companion also requires a relay-linked host, an explicit remote QR grant, and the host online.
- For Standalone: internet access to the hosted relay
=======
### iOS
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae

Use the current TestFlight build. The iOS beta includes the native WidgetKit extension. Widgets read only the app-written pinned-flight/board snapshot through the App Group and never fetch LAN, relay, or provider data directly.

Dynamic Island and Live Activities are not enabled yet. They remain a future ActivityKit pass after the widget path is stable.

### Android

Use Google Play Internal or Closed testing. The Android beta uses package:

```text
cc.beacontools.localflight
```

Android does not include an OS widget target yet. The in-app **Widgets & Glances** page still lets testers preview and configure the same future glance behavior.

### Store Review Notes

Keep these files aligned with the exact submitted build:

- [APP_STORE_REVIEW_NOTES.md](APP_STORE_REVIEW_NOTES.md)
- [PLAY_STORE_REVIEW_NOTES.md](PLAY_STORE_REVIEW_NOTES.md)

Current store identity:

- iOS bundle ID: `cc.beacontools.localflight`
- iOS widget extension ID: `cc.beacontools.localflight.widget`
- iOS App Group: `group.cc.beacontools.localflight`
- Android package ID: `cc.beacontools.localflight`
- Version: `0.2.8`
- iOS build number: `1`
- Android versionCode: `1`

Do not upload a build with old `com.localflight.*` identifiers. App Store bundle IDs and Google Play package names are effectively permanent after the first upload.

<<<<<<< HEAD
Signed beta artifacts are produced through EAS:
=======
---
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae

## First Launch

On first launch, Local Flight asks how this phone should connect.

### Standalone

<<<<<<< HEAD
The release build must keep Companion able to reach `http://localflight.local:8000` and private LAN IP addresses, while Remote Companion and Standalone relay traffic stay HTTPS-only at `https://relay.beacontools.cc`. The release manifest should include camera, internet, and vibration only where needed; microphone, storage, and overlay permissions should not ship.
=======
Standalone is the easiest review and tester path.
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae

It asks for:

1. Airport
2. Mobile diagnostics choice
3. Relay activation

Standalone gives you:

- Board with departures/arrivals
- Radar
- Local on-device History
- Settings
- Manual reports and diagnostics consent

Standalone limits are intentional:

- FIDS refreshes no faster than every 3 hours.
- Radar refreshes no faster than every 5 minutes.
- Radar ranges are `1`, `3`, `5`, and `10` NM.
- Matrix, scheduler, server restart, LAN check-in, and host-control tools are hidden.
- History stays on the phone through Expo SQLite and is retained for 30 days or 1,000 deduped movements.

### Companion

LAN Companion is for users who already run Local Flight on Windows, macOS, or Raspberry Pi.

Pair from Local Flight Settings on the desktop/Pi:

- Scan the QR code, or
- Enter the LAN URL manually.

Manual URL examples:

```text
http://192.168.1.42:8000
http://localflight.local:8000
```

Do not use `localhost` on a phone. On a phone, `localhost` means the phone itself, not your Mac, Windows PC, or Raspberry Pi. Keep the `:8000` port in manual URLs.

The pairing QR is fingerprint-bound to the server that created it. If a QR resolves to another Local Flight host on a multi-server network, the mobile app refuses the pairing instead of silently saving the wrong server.

<<<<<<< HEAD
Remote Companion is added from the same Pair Mobile area. Enable **Allow Remote Companion fallback**, save Settings, create a short-lived remote QR, and scan it while the phone is still on the LAN. After pairing, the phone shows a `LAN`, `REMOTE`, or `OFFLINE` state. LAN is always preferred. Remote is used only when LAN is unreachable, the host is online, and the remote grant is still active.

### Standalone

Choose **Standalone** when this phone should use the hosted relay directly.

Standalone setup asks for:

1. Airport
2. Mobile diagnostics choice
3. Relay activation

Standalone mode is deliberately simpler than the full Companion path:

- FIDS auto-refreshes no faster than every 3 hours.
- Radar refreshes no faster than every 5 minutes.
- Radar range choices are `1`, `3`, `5`, and `10` NM only.
- No WebSocket connection is opened.
- Matrix, Admin, scheduler restart, server URL tools, and other server-control features are hidden.
- History is stored locally on the phone with Expo SQLite and retained for 30 days or 1,000 deduped movements, whichever is smaller. Repeated refreshes and known codeshare aliases do not count as extra flights.

Deep geometry QA is optional and intentionally slow:

```bash
cd mobile
npm run layout:ios -- --runtime latest --only iphone-standard
```

The screenshot script builds a self-contained simulator app and captures portrait/landscape PNGs under `mobile/.layout-smoke/`. Use it only before a release or when debugging a specific layout regression. Add `--skip-build` to reuse the previous bundled simulator app, `--fresh-devices` to force clean temporary simulators, or `--runtime all` for the full installed iOS runtime matrix. iPad simulators are listed under iOS runtimes in `simctl`, which is how Apple exposes iPadOS geometry for this workflow.
=======
LAN Companion gives you:

- Board, Radar, and History from the paired server
- Control for pairing, host status, airport/source/refresh settings, Matrix, widgets, diagnostics, help, and reports
- WebSocket updates from the local server
- Matrix live-remote controls when the host has Matrix configured
- Automatic diagnostics only when both the phone and host allow it
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae

---

## Current Mobile Features

<<<<<<< HEAD
- First-run setup choice for Companion or Standalone
- Local Android development build path through Expo/Android Studio
- Companion daily surfaces: Board, Radar, History, and Control. Help & Reports lives inside Control instead of taking a bottom-nav slot.
- Remote Companion fallback for paired relay-linked hosts, including stored grant refs, LAN-first fallback, friendly offline/revoked messages, and a visible `LAN` / `REMOTE` / `OFFLINE` connection state.
- Standalone daily surfaces: Board, Radar, History, and Settings
- SecureStore persistence for setup mode, server URL, mobile install ID, standalone relay install ID, standalone activation token, standalone airport, mobile diagnostics mode, pinned flight, profiles, mobile appearance choices, and future widget preferences
- Companion connection checks against `/api/health`
- Companion dashboard data from `/api/mobile/summary` plus the existing local APIs, with encrypted relay request/response envelopes used only after LAN fetch failure when a remote grant exists
- QR pairing from native Settings prefers the server's LAN IP and carries the server fingerprint, so the app can reject a scan that resolves to another Local Flight host on a multi-server LAN
- Standalone summary, FIDS, Radar, and METAR data from relay `/v1/mobile/*` endpoints
- Native FIDS list from local `/api/fids` in Companion mode and relay `/v1/mobile/fids` in Standalone mode
- Flight details from `/api/fids/detail`, including the server's shared current-source detail model for real vs VATSIM schedule, motion, aircraft, weather, source confidence, and history fields when available. VATSIM details use the same pilot/ATC contract as desktop: callsign, filed plan, pilot track, XPDR, and recent sessions, without passenger codeshare/gate/registration fields.
- Airport, source, and refresh interval editing. The server offers 15, 30, 45, and 60 minute choices plus longer 2, 4, 8, 12, and 24 hour choices where the active schedule mode allows them. Local Flight Relay shows hourly-or-slower choices because shared airport snapshots protect upstream schedule access.
- Pinned flight island with pin/unpin and tap-for-detail behavior
- WebSocket listener for `/ws` `snapshot_updated`, `config_updated`, and `scheduler_restarted` events in Companion mode on LAN. Remote Companion can fall back to polling when relay event forwarding is unavailable.
- Independent mobile appearance with dark/light theme plus `standard`, `technical`, `neon`, `cyan`, and `crt` skins
- Branded launch overlay with a continuous radar sweep, status text fade, breathing status dot, blinking board LED, and shared Local Flight wordmark text
- Native-feeling interaction polish on key taps, chips, pinned-flight actions, and weather icon changes through haptics, press-scale feedback, and small transitions
- iOS widget and Dynamic Island design spec, a quiet Mobile settings path for future pinned-flight and airport-board glance preferences, and a hardened `localflight-widget-snapshot.json` app snapshot used by the future native extension skeleton
- Widget snapshot contract checks run through `npm run widget:contract` and are included in `npm run verify`
- Companion Matrix live-remote controls from Control using the host Matrix runtime config APIs, focused on runtime settings such as timing, palette, weather badge visibility, gate display, brightness, row count, animation, and refresh cadence.
- Fullscreen landscape FIDS from any screen, with normal portrait state restored when rotating back
- Mobile-owned radar radius controls. Companion uses the paired server for runway and airport-surface drawing; Standalone uses the relay mobile radar response for this pass.
- Local standalone movement history database with Expo SQLite
- Feedback and crash reporting through the connected Local Flight server in Companion mode, or directly through the Beacon Tools relay in Standalone mode

Standalone deliberately hides Matrix, Admin, scheduler restart, server-control panels, and Companion check-in. The goal is a useful mobile board, not a mini desktop clone.
=======
- Shared first-run setup for Standalone and LAN Companion
- Branded launch overlay and keyboard-safe setup flow
- Board with pinned flight, airport-local time, weather, status chips, and flight detail sheets
- Radar with mobile-owned range controls and a desktop-like sweep/blip fade
- Local History for Standalone, host-backed History for LAN Companion
- Appearance controls shared across both modes
- Help & Reports folded into Settings/Control instead of a duplicate nav path
- iOS WidgetKit small and medium widgets through the App Group snapshot
- In-app Widgets & Glances preview/settings for both modes
- No payments, tips, ads, or locked features in this beta build

Payment/tip UI is intentionally not included in this build. StoreKit / Google Play Billing work stays out of the visible app until the Apple/Google release path is resumed intentionally.

---

## Local Development

Use native development builds. Do not use Expo Go for this app; Local Flight uses native modules, SecureStore, SQLite, camera, widgets, and generated native projects.

Requirements:

- Node.js `>=24 <27`
- Xcode compatible with Expo SDK 55 for iOS builds
- Android Studio plus Android SDK Platform-Tools, Command-line Tools, and Emulator for Android builds
- For LAN Companion testing: a Local Flight server on the same Wi-Fi/LAN
- For Standalone testing: internet access to the Beacon Tools relay

Install and verify:

```bash
cd /Applications/local-flight/mobile
npm install
npm run verify
npm run a11y
```

iOS simulator:

```bash
cd /Applications/local-flight/mobile
npm run ios
```

iOS device:

```bash
cd /Applications/local-flight/mobile
npm run ios:device
```

Android environment:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
```

Android emulator or connected phone:

```bash
cd /Applications/local-flight/mobile
adb devices
npm run android
```

Physical Android device:

```bash
cd /Applications/local-flight/mobile
adb devices
npm run android:device
```

If Android install fails with signature mismatch after switching between local and store builds, uninstall the package from the device first:

```bash
adb uninstall cc.beacontools.localflight
```

The first Android build may install NDK `27.1.12297006` and can temporarily need `15-20 GB` of free disk space.

---

## Signed Beta Builds

Use EAS for signed internal-beta artifacts:

```bash
cd /Applications/local-flight/mobile
npm run verify
npm run a11y
npx eas build -p ios --profile beta
npx eas build -p android --profile beta
```

Submit only after the corresponding store console metadata is ready:

```bash
npx eas submit -p ios --profile beta
npx eas submit -p android --profile beta
```

For Google Play, the first AAB upload may need to be manual in Play Console before EAS Submit can be used with a service account.

Production profiles exist, but public production release should wait until internal TestFlight and Play testing pass on real devices:

```bash
npx eas build -p ios --profile production
npx eas build -p android --profile production
```
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae

---

## Privacy Model

<<<<<<< HEAD
### Companion

- It talks to your Local Flight server over your LAN first.
- Prefer the LAN IP shown in Local Flight Settings when pairing. `localflight.local` remains useful for simple one-server networks, but it can resolve to the wrong host if a Pi and a dev machine are both running Local Flight.
- Remote Companion can use the hosted relay only as an encrypted fallback for a paired relay-linked host. The relay sees grant/install refs, request ids, status, latency, and byte sizes, not decrypted board data, commands, provider keys, LAN URLs, or host logs.
- Remote Companion requires the host to stay online. There is no account system, no router port forwarding, no public tunnel, and no offline command queue.
- The host can revoke a remote grant from Local Flight Settings. The phone can forget its stored remote grant and pair again later.
- Automatic mobile reports require both the mobile-local diagnostics choice and the connected server diagnostics mode to allow automatic reporting.
- Manual reports remain available from the app.
- Expo JS/React errors are covered by the current crash reporter. Native iOS crashes before JavaScript starts are not covered without a native crash-reporting service or Apple crash logs.

=======
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae
### Standalone

- Talks to `https://relay.beacontools.cc`.
- Stores the selected airport, activation token, install-scoped relay ID, widget preferences, pinned flight, and local movement history on the device.
- Sends reports only when the user submits one or when automatic diagnostics are enabled by the phone-local diagnostics choice.
- Does not store phone-local history on the relay.

### LAN Companion

- Talks to the paired Local Flight server on the user's LAN.
- Does not call schedule, radar, VATSIM, or provider APIs directly.
- Uses the local server for Board, Radar, History, Matrix, settings, and report forwarding.
- Automatic diagnostics require both the mobile-local diagnostics choice and the connected server diagnostics mode.

Install-scoped IDs exist so pairing, quotas, reports, and troubleshooting can work without creating user accounts.

---

## Source Structure

- `App.tsx` is the provider entrypoint.
- `src/app/AppShell.tsx` coordinates setup mode, data refresh, shell chrome, standalone relay flow, and LAN Companion state.
- `src/api/` contains LAN and standalone relay API clients.
- `src/domain/` contains pure helpers for flights, formatting, radar, widgets, and Matrix.
- `src/screens/AppScreens.tsx` contains screens and sheets.
- `src/storage/` contains SecureStore settings, standalone SQLite history, and widget snapshot writing.
- `src/theme/` contains mobile visual tokens and style generation.
- `native/ios-widget/` contains the tracked WidgetKit source copied into the generated iOS project.

---

## Not Yet

- Public App Store release
- Public Google Play production release
<<<<<<< HEAD
- Wired native iOS WidgetKit / ActivityKit extension targets, App Groups, APNs, and production Live Activity updates
- Remote Companion production proof on real Android and iOS devices before public store rollout.
- Per-device authorization/revoke tokens for broader mutating LAN controls. Current Companion identifies each device with an install-scoped companion ID/check-in plus optional Remote Companion grant, while Standalone uses its relay activation token.
- Production-ready admin permission model
=======
- Dynamic Island / Live Activities
- Android OS widgets
- In-app purchases, payments, or support tips
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae
- Native crash capture before JavaScript starts
- Broader LAN admin authorization/revoke controls

---

## Release Checklist

<<<<<<< HEAD
- Remote Companion release-gate proof: pair on LAN, confirm LAN-first, block LAN, load Board/Radar/History/Control through relay, restart scheduler, revoke grant, and confirm remote access stops.
- TestFlight proof pass on a fresh real iPhone and iPad: Companion LAN/Remote pairing, Standalone setup, denied camera/local-network paths, support stub, and accessibility settings
- App Store Connect privacy/review metadata using `APP_STORE_REVIEW_NOTES.md`
- Google Play internal-test proof pass on a fresh Android phone: Companion LAN/Remote pairing, Standalone setup, denied camera path, support stub, permissions, and accessibility settings
- Play Console privacy/Data Safety/review metadata using `PLAY_STORE_REVIEW_NOTES.md`
- Full standalone flight-detail endpoint parity if Standalone should expose the same detail sheet depth as Companion
- Real in-app purchase support tips after App Store Connect / Google Play Billing products, native purchase testing, and relay verification are ready
- Broader Android device matrix pass after the first local Android smoke test
- Optional React Navigation stack only if future deep links need true back-stack behavior
=======
- TestFlight internal beta on a real iPhone and iPad
- Google Play internal or closed test on a real Android phone
- Fresh Standalone setup
- LAN QR and manual pairing
- Denied camera and local-network paths
- Offline relay retry state
- Widget add/update/stale states on iOS
- Support sheet shows store setup and cannot charge
- Accessibility pass with larger text, reduced motion, and screen-reader labels
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae
