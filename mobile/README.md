# Local Flight Mobile

React Native / Expo mobile app for Local Flight.

The mobile app is aligned to Local Flight `0.5.1` for TestFlight and Google Play testing. Public store listings are not live yet. It supports two first-run paths:

- **Companion:** pair with the Local Flight desktop or Raspberry Pi server on your Wi-Fi/LAN. Companion uses LAN first and can use encrypted Remote Companion fallback after a relay-linked host grants this phone access.
- **Standalone:** use the hosted Local Flight relay directly for a simplified phone board. Careful refresh limits keep the shared service reliable and fairly available.

For most home setups, start with Companion. Use Standalone when you want a light mobile FIDS/Radar/History app without running your own Local Flight server.

Local Flight Mobile is a personal display aid. Flight, weather, radar, and airport-surface data can be delayed, incomplete, or unavailable, so it must not be used for navigation, dispatch, operational control, or safety decisions.

The public front door for Mobile users is [beacontools.cc/local-flight/mobile](https://beacontools.cc/local-flight/mobile). Use that page for availability, install guidance, release notes, support links, source links, and store metadata. The public privacy policy is [beacontools.cc/privacy](https://beacontools.cc/privacy). Remote Companion and Standalone use the Beacon Tools relay at `https://relay.beacontools.cc` for different jobs: encrypted fallback for a paired host versus direct Standalone board data.

> **Quick alternative:** if
> you only need to glance at the board from a phone, you don't have
> to build this app. Open the LAN browser UI
> (`http://localflight.local:8000` or your server's LAN address) in
> mobile Safari / Chrome — it now auto-switches to a thumb-reachable
> mobile shell with the FIDS table reflowed into per-flight cards.
> The companion app is the right choice for push-style updates,
> pinned flights, mobile-owned radar ring controls, and the
> mobile-side diagnostics consent flow.

---

## Requirements

- macOS with an Xcode version compatible with Expo SDK 55
- Android Studio with the Android SDK command-line tools for Android builds
- Node.js 24 LTS recommended. Node.js 26 Current is also supported for local development. The repo includes a root `.nvmrc`; run `nvm use` from the project root if you use nvm and want the LTS default.
- iPhone/iPad connected for device builds, or an iOS simulator
- Android phone with USB debugging enabled, or an Android Studio emulator
- For Companion: Local Flight already running on the same Wi-Fi/LAN. Remote Companion also requires a relay-linked host, an explicit remote QR grant, and the host online.
- For Standalone: internet access to the hosted relay

Expo SDK 55 targets React Native 0.83 and React 19.2. Run `npm run doctor` after install on the Mac to confirm the active Xcode, CocoaPods, and package versions are compatible.

For App Store/TestFlight preparation, keep [APP_STORE_REVIEW_NOTES.md](APP_STORE_REVIEW_NOTES.md) aligned with the exact build being submitted. For Google Play preparation, keep [PLAY_STORE_REVIEW_NOTES.md](PLAY_STORE_REVIEW_NOTES.md) aligned with the exact Android App Bundle being submitted. Store-facing website/support links should point to `https://beacontools.cc/local-flight/mobile`; privacy links should point to `https://beacontools.cc/privacy`.

The design and data-contract handoff for future iOS widgets and Dynamic Island / Live Activity surfaces lives in [`../docs/mobile-ios-widgets-dynamic-island.md`](../docs/mobile-ios-widgets-dynamic-island.md). The app writes a hardened widget snapshot now and the tracked native template lives in [`native/ios-widget/`](native/ios-widget/), but the current store-testing build does not enable the WidgetKit config plugin or ship a widget target.

If Xcode was freshly installed or upgraded, accept the Apple SDK license first:

```bash
sudo xcodebuild -license accept
sudo xcode-select --reset
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

If `expo run:ios` exits with a destination/runtime error, open Xcode -> Settings -> Components and install the matching iOS simulator runtime.

For Android, expose Android Studio's SDK tools to the current terminal before running Expo:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
```

If `adb` or `emulator` is still missing, open Android Studio -> Settings -> Android SDK and install Android SDK Platform-Tools, Android SDK Command-line Tools, and Android Emulator.

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

For Android emulator/device development:

```bash
cd mobile
npm run verify
npm run android
```

`npm run android` creates or updates the generated `android/` project with Expo prebuild, builds a debug APK, installs it on the running emulator or connected phone, and opens Local Flight.

`npm run verify` runs TypeScript plus Expo Doctor. Use the running simulator or device for visual checks instead of the screenshot matrix during regular feature work.

To retest the forced first-launch setup and diagnostics consent on a simulator:

```bash
cd mobile
xcrun simctl uninstall booted cc.beacontools.localflight || true
npm run ios
```

This removes the simulator app data so the setup gate appears again. On a physical iPhone or iPad, delete the app from the device before reinstalling.

For a physical iPhone or iPad:

```bash
cd mobile
npm run ios:device
```

For a physical Android phone:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

cd mobile
adb devices
npm run android:device
```

Enable Developer Options and USB debugging on the phone first. Accept the phone's USB debugging prompt before running the build.

The first Android build may install NDK `27.1.12297006` and can temporarily need `15-20 GB` of free disk space. If it fails with `No space left on device`, stop Gradle and clear the partial SDK download before retrying:

```bash
cd mobile
./android/gradlew --stop 2>/dev/null || true
rm -rf "$ANDROID_HOME/.temp"
rm -rf "$ANDROID_HOME/ndk/27.1.12297006"
sdkmanager "ndk;27.1.12297006"
npm run android
```

### Store Testing / Release Path

Store identity and the current `0.5.1` testing counters are:

- iOS bundle ID: `cc.beacontools.localflight`
- iOS `buildNumber`: `4`
- Android package ID: `cc.beacontools.localflight`
- Android `versionCode`: `8`

Do not upload a store build with any old `com.localflight.*` identifier. App Store bundle IDs and Google Play package names are effectively permanent after first upload.

The current signed artifacts are already built as iOS `0.5.1 (4)` and Android `0.5.1 (8)`. Do not rebuild those counters for the same testing upload. For a later version, increment both store counters first, then use EAS:

```bash
cd mobile
npm run verify
npm run a11y
npx eas build -p ios --profile beta
npx eas submit -p ios --profile beta
npx eas build -p android --profile beta
npx eas submit -p android --profile beta
```

Use TestFlight internal testing and Google Play internal testing first. When the internal install works on real devices, create production-track artifacts only when the public release decision is made:

```bash
cd mobile
npx eas build -p ios --profile production
npx eas build -p android --profile production
```

The release build must keep Companion able to reach `http://localflight.local:8000` and private LAN IP addresses, while Remote Companion and Standalone relay traffic stay HTTPS-only at `https://relay.beacontools.cc`. The release manifest should include camera, internet, and vibration only where needed; microphone, storage, and overlay permissions should not ship.

Before leaving Internal Testing, complete the Play Console setup:

- Privacy Policy URL: `https://beacontools.cc/privacy`
- Website/support URL: `https://beacontools.cc/local-flight/mobile`
- Data Safety answers from [PLAY_STORE_REVIEW_NOTES.md](PLAY_STORE_REVIEW_NOTES.md)
- Content rating and target audience
- Safety disclaimer in the store description: Local Flight is not for navigation, dispatch, operational control, or safety decisions

On first launch, choose how this device should work.

### Companion

Choose **Companion** in the app when you already run Local Flight on Windows, macOS, or Raspberry Pi.

Enter the Local Flight server URL from your LAN, for example:

```text
http://192.168.1.42:8000
http://localflight.local:8000
```

Do not use `localhost` on a physical iPhone or Android phone. `localhost` means the phone itself, not your Mac, Windows PC, or Raspberry Pi. Keep the `:8000` port in manual URLs.

For the easiest setup, open **Pair Mobile** from the native Qt Settings page or the LAN browser Settings page and scan the QR code. The QR is fingerprint-bound to the server that created it, and the same card shows manual LAN URL fallbacks when scanning is not convenient.

Remote Companion is added from the same Pair Mobile area. Enable **Allow Remote Companion fallback**, save Settings, create a short-lived remote QR, and scan it while the phone is still on the LAN. After pairing, the phone shows a `LAN`, `REMOTE`, or `OFFLINE` state. LAN is always preferred. Remote is used only when LAN is unreachable, the host is online, and the remote grant is still active.

The Companion connection panel also has **Test Remote** after a remote grant is paired. It sends one tiny encrypted probe through the relay and retries once only for short-lived network/host failures. If it fails, the message should say what to check next: host offline, grant revoked, key mismatch/re-pair needed, relay rate limit, or relay unreachable.

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

---

## What Works Now

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
- iOS widget and Dynamic Island design spec, a quiet Mobile settings path for future pinned-flight and airport-board glance preferences, and a hardened `localflight-widget-snapshot.json` contract. The current store build does not ship the widget extension.
- Widget snapshot contract checks run through `npm run widget:contract` and are included in `npm run verify`
- Companion Matrix live-remote controls from Control using the host Matrix runtime config APIs, focused on runtime settings such as timing, palette, weather badge visibility, gate display, brightness, row count, animation, and refresh cadence.
- Fullscreen landscape FIDS from any screen, with normal portrait state restored when rotating back
- Mobile-owned radar radius controls. Companion uses the paired server for runway and airport-surface drawing; Standalone uses the relay mobile radar response for this pass.
- Local standalone movement history database with Expo SQLite
- Feedback and crash reporting through the connected Local Flight server in Companion mode, or directly through the Beacon Tools relay in Standalone mode

Standalone deliberately hides Matrix, Admin, scheduler restart, server-control panels, and Companion check-in. The goal is a useful mobile board, not a mini desktop clone.

---

## Privacy Model

### Companion

- It talks to your Local Flight server over your LAN first.
- Prefer the LAN IP shown in Local Flight Settings when pairing. `localflight.local` remains useful for simple one-server networks, but it can resolve to the wrong host if a Pi and a dev machine are both running Local Flight.
- Remote Companion can use the hosted relay only as an encrypted fallback for a paired relay-linked host. The relay sees grant/install refs, request ids, status, latency, and byte sizes, not decrypted board data, commands, provider keys, LAN URLs, or host logs.
- Remote Companion requires the host to stay online. There is no account system, no router port forwarding, no public tunnel, and no offline command queue.
- **Test Remote** is safe to use for troubleshooting because the test payload is encrypted between phone and host. The relay routes the envelope but does not receive the Remote Companion key or readable board/control data.
- The host can revoke a remote grant from Local Flight Settings. The phone can forget its stored remote grant and pair again later.
- Automatic mobile reports require both the mobile-local diagnostics choice and the connected server diagnostics mode to allow automatic reporting.
- Manual reports remain available from the app.
- Expo JS/React errors are covered by the current crash reporter. Native iOS crashes before JavaScript starts are not covered without a native crash-reporting service or Apple crash logs.

### Standalone

- It talks directly to the hosted Local Flight relay.
- The default relay URL is `https://relay.beacontools.cc`.
- It registers a separate relay install UUID and activation token for this mobile install.
- It stores the selected airport and local deduped movement history on the device.
- Manual reports go directly to relay `/v1/reports`.
- Automatic reports only send when the mobile diagnostics choice is `auto` or `auto_logs`.
- It does not store phone-local history on the relay.

The mobile install ID and standalone relay install ID are install-scoped. They are there so reports, quotas, and troubleshooting can say "this came from this app install" without needing an account.

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
- This build contains no payment UI, purchase products, billing adapter, or purchase-verification endpoint. Monetization is outside the `0.5.1` release baseline.

---

## Current Boundaries

- Public App Store release
- Public Google Play production release
- Wired native iOS WidgetKit / ActivityKit extension targets, App Groups, APNs, and production Live Activity updates
- Remote Companion physical-device validation on Android and iOS before public store rollout.
- Per-device authorization/revoke tokens for broader mutating LAN controls. Current Companion identifies each device with an install-scoped companion ID/check-in plus optional Remote Companion grant, while Standalone uses its relay activation token.
- Broader mobile admin control is intentionally out of scope; Companion exposes only the current allowlisted control surfaces.
- Native crash capture before JavaScript starts
- Full standalone flight-detail endpoint parity; Standalone currently focuses on Board, Radar, History, Settings, and reports
- Payments, tips, and in-app purchases

---

## Release Validation

- Remote Companion release-gate proof: pair on LAN, run **Test Remote**, confirm LAN-first, block LAN, load Board/Radar/History/Control through relay, restart scheduler, revoke grant, and confirm remote access stops.
- TestFlight proof pass on a fresh real iPhone and iPad: Companion LAN/Remote pairing, Standalone setup, denied camera/local-network paths, and accessibility settings
- App Store Connect privacy/review metadata using `APP_STORE_REVIEW_NOTES.md`
- Google Play internal-test proof pass on a fresh Android phone: Companion LAN/Remote pairing, Standalone setup, denied camera path, permissions, and accessibility settings
- Play Console privacy/Data Safety/review metadata using `PLAY_STORE_REVIEW_NOTES.md`
- Full standalone flight-detail endpoint parity if Standalone should expose the same detail sheet depth as Companion
- Broader Android device matrix pass after the first local Android smoke test
- Optional React Navigation stack only if future deep links need true back-stack behavior
