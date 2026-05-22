# Local Flight Mobile

React Native / Expo mobile app for Local Flight.

The mobile app is an iOS-first developer preview with a working local Android development path. It is not on the App Store, TestFlight, Play Store, or available as a release APK yet, but it now supports two first-run paths:

- **LAN Companion:** pair with the Local Flight desktop or Raspberry Pi server on your Wi-Fi/LAN.
- **Standalone:** use the hosted Local Flight relay directly for a simplified phone board. This is intentionally rate-limited to protect shared relay/API tokens.

For most home setups, start with LAN Companion. Use Standalone when you want a light mobile FIDS/Radar/History app without running your own Local Flight server.

Local Flight Mobile is a personal display aid. Flight, weather, radar, and airport-surface data can be delayed, incomplete, or unavailable, so it must not be used for navigation, dispatch, operational control, or safety decisions.

The public front door for Mobile users is [beacontools.cc/local-flight](https://beacontools.cc/local-flight). Use that page for install guidance, release notes, support links, source links, and store metadata. The public privacy policy is [beacontools.cc/privacy](https://beacontools.cc/privacy). Standalone uses the Beacon Tools relay at `https://relay.beacontools.cc`.

> **Quick alternative:** if
> you only need to glance at the board from a phone, you don't have
> to build this app. Open the LAN browser UI
> (`http://localflight.local:8000` or your server's LAN address) in
> mobile Safari / Chrome — it now auto-switches to a thumb-reachable
> mobile shell with the FIDS table reflowed into per-flight cards.
> This companion app is still the right choice for push-style updates,
> pinned flights, mobile-owned radar ring controls, and the
> mobile-side diagnostics consent flow.

---

## Requirements

- macOS with an Xcode version compatible with Expo SDK 55
- Android Studio with the Android SDK command-line tools for Android builds
- Node.js 24 LTS recommended. Node.js 26 Current is also supported for local development. The repo includes a root `.nvmrc`; run `nvm use` from the project root if you use nvm and want the LTS default.
- iPhone/iPad connected for device builds, or an iOS simulator
- Android phone with USB debugging enabled, or an Android Studio emulator
- For LAN Companion: Local Flight already running on the same Wi-Fi/LAN
- For Standalone: internet access to the hosted relay

Expo SDK 55 targets React Native 0.83 and React 19.2. Run `npm run doctor` after install on the Mac to confirm the active Xcode, CocoaPods, and package versions are compatible.

For App Store/TestFlight preparation, keep [APP_STORE_REVIEW_NOTES.md](APP_STORE_REVIEW_NOTES.md) aligned with the exact build being submitted. For Google Play preparation, keep [PLAY_STORE_REVIEW_NOTES.md](PLAY_STORE_REVIEW_NOTES.md) aligned with the exact Android App Bundle being submitted. Store-facing website/support links should point to `https://beacontools.cc/local-flight`; privacy links should point to `https://beacontools.cc/privacy`.

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
xcrun simctl uninstall booted com.localflight.companion || true
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

### Android Release / Play Store Path

Android release identity is intentionally separate from the existing iOS bundle ID:

- iOS bundle ID: `com.localflight.companion`
- Android package ID: `com.localflight.mobile`
- Android `versionCode`: `7`

Do not upload an Android build with the old `com.localflight.companion` package name. Google Play package names are effectively permanent after the first upload.

Signed Android release artifacts are produced through EAS:

```bash
cd mobile
npm run verify
npm run a11y
npx eas build -p android --profile preview
```

Use the preview AAB for Play Internal Testing first. When the internal install works on a real Android device, create the production AAB:

```bash
cd mobile
npx eas build -p android --profile production
```

The release build must keep LAN Mobile able to reach `http://localflight.local:8000` and private LAN IP addresses, while Standalone relay traffic stays HTTPS-only at `https://relay.beacontools.cc`. The release manifest should include camera, internet, and vibration only where needed; microphone, storage, and overlay permissions should not ship.

Before leaving Internal Testing, complete the Play Console setup:

- Privacy Policy URL: `https://beacontools.cc/privacy`
- Website/support URL: `https://beacontools.cc/local-flight`
- Data Safety answers from [PLAY_STORE_REVIEW_NOTES.md](PLAY_STORE_REVIEW_NOTES.md)
- Content rating and target audience
- Safety disclaimer in the store description: Local Flight is not for navigation, dispatch, operational control, or safety decisions

On first launch, choose how this device should work.

### LAN Companion

Choose **Companion** in the app when you already run Local Flight on Windows, macOS, or Raspberry Pi.

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

Standalone mode is deliberately simpler than the full LAN Companion path:

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

- First-run setup choice for LAN Companion or Standalone
- Local Android development build path through Expo/Android Studio
- LAN Companion daily surfaces: Board, Radar, History, Control, and Help
- Standalone daily surfaces: Board, Radar, History, and Settings
- SecureStore persistence for setup mode, server URL, mobile install ID, standalone relay install ID, standalone activation token, standalone airport, mobile diagnostics mode, pinned flight, profiles, and mobile appearance choices
- LAN Companion connection checks against `/api/health`
- LAN Companion dashboard data from `/api/mobile/summary` plus the existing local APIs
- QR pairing from native Settings prefers the server's LAN IP and carries the server fingerprint, so the app can reject a scan that resolves to another Local Flight host on a multi-server LAN
- Standalone summary, FIDS, Radar, and METAR data from relay `/v1/mobile/*` endpoints
- Native FIDS list from local `/api/fids` in LAN Companion mode and relay `/v1/mobile/fids` in Standalone mode
- Flight details from `/api/fids/detail`, including the server's shared current-source detail model for real vs VATSIM schedule, motion, aircraft, weather, source confidence, and history fields when available. VATSIM details use the same pilot/ATC contract as desktop: callsign, filed plan, pilot track, XPDR, and recent sessions, without passenger codeshare/gate/registration fields.
- Airport, source, and refresh interval editing. The server offers 15, 30, 45, and 60 minute choices plus longer 2, 4, 8, 12, and 24 hour choices where the active schedule mode allows them. Local Flight Relay shows hourly-or-slower choices because shared airport snapshots protect upstream schedule access.
- Pinned flight island with pin/unpin and tap-for-detail behavior
- WebSocket listener for `/ws` `snapshot_updated`, `config_updated`, and `scheduler_restarted` events in LAN Companion mode only
- Independent mobile appearance with dark/light theme plus `standard`, `technical`, `neon`, `cyan`, and `crt` skins
- Branded launch overlay with a continuous radar sweep, status text fade, breathing status dot, blinking board LED, and shared Local Flight wordmark text
- Native-feeling interaction polish on key taps, chips, pinned-flight actions, and weather icon changes through haptics, press-scale feedback, and small transitions
- Companion Matrix live-remote controls from Control using `/api/matrix/config`, focused on runtime settings such as timing, palette, weather badge visibility, brightness, and refresh cadence.
- Fullscreen landscape FIDS from any screen, with normal portrait state restored when rotating back
- Mobile-owned radar radius controls. LAN Companion uses the paired server for runway and airport-surface drawing; Standalone uses the relay mobile radar response for this pass.
- Local standalone movement history database with Expo SQLite
- Feedback and crash reporting through the connected Local Flight server in LAN Companion mode, or directly through the Beacon Tools relay in Standalone mode

Standalone deliberately hides Matrix, Admin, scheduler restart, server-control panels, and LAN Companion check-in. The goal is a useful mobile board, not a mini desktop clone.

---

## Privacy Model

### LAN Companion

- It talks to your Local Flight server over your LAN.
- Prefer the LAN IP shown in Local Flight Settings when pairing. `localflight.local` remains useful for simple one-server networks, but it can resolve to the wrong host if a Pi and a dev machine are both running Local Flight.
- It does not call AviationStack, ADS-B Exchange, RapidAPI, OpenSky, VATSIM, or the hosted relay directly.
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
- `src/iap/` contains the optional support-tip skeleton. It keeps stable product IDs and the purchase-verification seam in place, but the active provider remains a non-charging placeholder until App Store Connect products / Google Play Billing products and native purchase libraries are added to development builds.

### Support Tip Skeleton

The intended iOS support-tip flow is:

1. Create App Store Connect in-app purchase products for `com.localflight.companion.tip.2`, `.tip.5`, `.tip.10`, and `.tip.20`.
2. Add an Expo-compatible native IAP library such as `expo-iap` to a development/TestFlight build.
3. Replace the placeholder export in `src/iap/supportProvider.ts` with `createAppleSupportPurchaseProvider(...)`.
4. Send StoreKit signed transaction info to the relay's scaffolded `POST /v1/mobile/iap/apple/verify` endpoint.
5. Configure the relay with App Store Server API credentials and verify Apple-signed transaction data before finishing transactions.

The intended Android support-tip flow is separate and later:

1. Create matching Google Play Billing in-app products.
2. Add an Expo-compatible native billing adapter to a development build.
3. Switch `src/iap/supportProvider.ts` to a platform-aware provider.
4. Verify purchases on the relay before acknowledging/finishing them.

---

## Not Yet

- Public iOS release
- Public Android / Play Store release
- Per-device authorization/revoke tokens for broader mutating LAN controls. Current LAN Companion identifies each device with an install-scoped companion ID and check-in, while Standalone uses its relay activation token.
- Production-ready admin permission model
- Native crash capture before JavaScript starts
- Full standalone flight-detail endpoint parity; Standalone currently focuses on Board, Radar, History, Settings, and reports
- Real in-app purchase support tips; the current support sheet has a non-charging purchase/relay skeleton

---

## Next

- Per-device authorization/revoke tokens before broader mutating LAN admin controls
- App Store/TestFlight proof pass on a fresh real iPhone and iPad once Apple Developer/App Store Connect credentials are available: Standalone setup, LAN QR/manual pairing, denied camera/local-network paths, support stub, and accessibility settings
- App Store Connect privacy/review metadata using `APP_STORE_REVIEW_NOTES.md`
- Google Play internal-test proof pass on a fresh Android phone once Play Console/client credentials are available: Standalone setup, LAN QR/manual pairing, denied camera path, support stub, permissions, and accessibility settings
- Play Console privacy/Data Safety/review metadata using `PLAY_STORE_REVIEW_NOTES.md`
- Full standalone flight-detail endpoint parity if Standalone should expose the same detail sheet depth as LAN Companion
- Real in-app purchase support tips after App Store Connect / Google Play Billing products, native purchase testing, and relay verification are ready
- Broader Android device matrix pass after the first local Android smoke test
- Optional React Navigation stack only if future deep links need true back-stack behavior
