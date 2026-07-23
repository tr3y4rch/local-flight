# Local Flight Mobile

React Native / Expo mobile app for Local Flight.

The mobile app is aligned to Local Flight `0.5.2` for TestFlight and Google Play internal testing. It supports two first-run paths:

- **Connect to a Local Flight host:** pair with Local Flight on Windows, macOS, Linux, or Raspberry Pi over the same Wi-Fi. This is called Companion mode after setup; it uses the nearby host first and can use encrypted Remote Companion fallback after a relay-linked host grants this device access.
- **Use without a Local Flight host:** choose an airport and use the hosted Local Flight relay directly. This is called Standalone mode after setup, with careful refresh limits that keep the shared service reliable and fairly available.

For most home setups, start with Companion. Use Standalone when you want a light mobile FIDS/Radar/History app without running your own Local Flight server.

Local Flight Mobile is a personal display aid. Flight, weather, radar, and airport-surface data can be delayed, incomplete, or unavailable, so it must not be used for navigation, dispatch, operational control, or safety decisions.

The public front door for Mobile users is [beacontools.cc/local-flight/mobile](https://beacontools.cc/local-flight/mobile). Use that page for availability, install guidance, release notes, support links, source links, and store metadata. The public privacy policy is [beacontools.cc/privacy](https://beacontools.cc/privacy). Remote Companion and Standalone use the Beacon Tools relay at `https://relay.beacontools.cc` for different jobs: encrypted fallback for a paired host versus direct Standalone board data.

> **Quick alternative:** if
> you only need to glance at the board from a phone, you don't have
> to build this app. Open the LAN browser UI
> (`http://localflight.local:8000` or your server's LAN address) in
> mobile Safari / Chrome — it now auto-switches to a thumb-reachable
> mobile shell with the FIDS table reflowed into per-flight cards.
> The companion app is the right choice for live board updates,
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

For App Store/TestFlight preparation, keep [APP_STORE_REVIEW_NOTES.md](APP_STORE_REVIEW_NOTES.md) aligned with the exact build being submitted. Copy the checked English (U.S.) customer listing from [`store/ios/en-US/`](store/ios/en-US/) and run `npm run appstore:contract` before submission. For Google Play preparation, keep [PLAY_STORE_REVIEW_NOTES.md](PLAY_STORE_REVIEW_NOTES.md) aligned with the exact Android App Bundle being submitted. Store marketing links should point to `https://beacontools.cc/local-flight/mobile`, support links to `https://beacontools.cc/support`, and privacy links to `https://beacontools.cc/privacy`.

The home-screen widget contract and Dynamic Island / Live Activity boundary live in [`../docs/mobile-ios-widgets-dynamic-island.md`](../docs/mobile-ios-widgets-dynamic-island.md). The current source enables a WidgetKit extension for iOS, a local `AppWidgetProvider` for Android, and a capability-gated local pinned-flight Live Activity. All three read the same bounded app-written snapshot and never fetch LAN, relay, or provider data themselves. Starting a Live Activity requires the explicit **Pin & show on Lock Screen** action; no APNs or notification service is involved.

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

Mobile launcher, splash, and Play feature artwork have their own deterministic source pipeline;
it does not reuse or rewrite the desktop/package icon master. From the
repository root, regenerate the iOS light/dark/tinted icons, Android adaptive and
monochrome layers, transparent in-app marks and splash lockups, and Play feature
graphic with:

```bash
.venv/bin/python scripts/mobile_brand_assets.py
```

The full `scripts/sync_brand_v2.py` brand synchronization calls the same mobile
generator and records the outputs in `assets/brand-manifest.json`.

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

Enable Developer Options and USB debugging on the Android device first. Accept its USB debugging prompt before running the build.

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

Store identity and the current `0.5.2` testing counters are:

- iOS bundle ID: `cc.beacontools.localflight`
- iOS `buildNumber`: `12`
- Android package ID: `cc.beacontools.localflight`
- Android `versionCode`: `12`

Do not upload a store build with any old `com.localflight.*` identifier. App Store bundle IDs and Google Play package names are effectively permanent after first upload.

The current widget-enabled source targets iOS `0.5.2 (9)` and Android `0.5.2 (12)`; these counters identify the refreshed V2 TestFlight and Google Play internal builds because native widget and launcher changes cannot be delivered through an over-the-air JavaScript update alone.

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

For one validated store-binary build that automatically uploads iOS to
TestFlight and Android to the Google Play internal-testing track, use:

```bash
cd mobile
npx eas build --platform all --profile production --auto-submit --non-interactive
```

The `production` build profile means store-signed binaries; it does not publish
the app publicly. The checked submit profile pins Android to `internal`, while
Apple receives the build in TestFlight for review/testing.

The release build must keep Companion able to reach `http://localflight.local:8000` and private LAN IP addresses, while Remote Companion and Standalone relay traffic stay HTTPS-only at `https://relay.beacontools.cc`. The release manifest should include camera, internet, and vibration only where needed; microphone, storage, and overlay permissions should not ship.

Before leaving Internal Testing, complete the Play Console setup:

- Privacy Policy URL: `https://beacontools.cc/privacy`
- Website/support URL: `https://beacontools.cc/local-flight/mobile`
- Data Safety answers from [PLAY_STORE_REVIEW_NOTES.md](PLAY_STORE_REVIEW_NOTES.md)
- Content rating and target audience
- Safety disclaimer in the store description: Local Flight is not for navigation, dispatch, operational control, or safety decisions

On first launch, choose how this device should work.

### Companion

Choose **Connect to a Local Flight host** when you already run Local Flight on Windows, macOS, Linux, or Raspberry Pi. The app calls this Companion mode after setup.

Enter the Local Flight server URL from your LAN, for example:

```text
http://192.168.1.42:8000
http://localflight.local:8000
```

Do not use `localhost` on a physical iPhone, iPad, or Android device. `localhost` means this device, not your Mac, Windows PC, or Raspberry Pi host. Keep the `:8000` port in manual URLs.

For the easiest setup, open **Pair Mobile** from the native Qt Settings page or the LAN browser Settings page. Use the QR already shown for LAN-only access, or choose **Create LAN + Remote QR** for one scan that adds LAN plus encrypted away-from-home backup. Both are fingerprint-bound to the server that created them, and the same card shows manual LAN URL fallbacks when scanning is not convenient.

Remote Companion is added from the same Pair Mobile area. Enable **Allow Remote Companion fallback**, save Settings, create the short-lived **LAN + Remote QR**, and scan it once while this device is still on the same Wi-Fi. The app tests the encrypted round trip before it says Remote is ready. After pairing, the app shows **Connected nearby**, **Connected remotely**, or **Offline** separately from board freshness. The nearby connection is always preferred. Remote is used only when the host cannot be reached nearby, the host is online, and the remote grant is still active. Re-pairing the same device replaces its previous remote grant.

The Companion connection panel also has **Test Remote Backup** after a remote grant is paired. It sends one tiny encrypted probe through the relay and retries once only for short-lived network/host failures. If it fails, the message says what to check next: host offline, grant removed, pairing verification, relay rate limit, or relay unreachable.

### Standalone

Choose **Use without a Local Flight host** when this device should use the hosted relay directly. The app calls this Standalone mode after setup.

The shared first-run path is **Welcome → connection choice → pair or choose airport → privacy and review**. Standalone activation and the airport choice happen inside the third step; Companion QR scanning and manual pairing share that same step.

Standalone mode is deliberately simpler than the full Companion path:

- Airline schedules usually refresh about once an hour.
- Nearby traffic can refresh about every 3 minutes while Radar is open.
- Board shows up to 50 current departures and 50 arrivals when supplied; shared information may still be cached or delayed.
- Radar range choices are `1`, `3`, `5`, and `10` NM only.
- No WebSocket connection is opened.
- Matrix, Admin, scheduler restart, server URL tools, and other server-control features are hidden.
- History is stored locally on this device with Expo SQLite and retained for 30 days or 1,000 deduped movements, whichever is smaller. Repeated refreshes and known codeshare aliases do not count as extra flights.

Deep geometry QA is optional and intentionally slow:

```bash
cd mobile
npm run layout:ios -- --runtime latest --only iphone-standard
```

The screenshot script builds a self-contained simulator app and captures portrait/landscape PNGs under `mobile/.layout-smoke/`. Use it only before a release or when debugging a specific layout regression. Add `--skip-build` to reuse the previous bundled simulator app, `--fresh-devices` to force clean temporary simulators, or `--runtime all` for the full installed iOS runtime matrix. iPad simulators are listed under iOS runtimes in `simctl`, which is how Apple exposes iPadOS geometry for this workflow.

---

## What Works Now

- Four-stage first run: Welcome, connection choice, pair or choose airport, then privacy and review
- Local Android development build path through Expo/Android Studio
- Consistent **Board / Radar / History / More** navigation in Companion and Standalone, with bottom tabs below 600dp and an adaptive left rail on wider windows
- Remote Companion fallback for paired relay-linked hosts, including stored grant refs, LAN-first fallback, friendly offline/revoked messages, and a visible `LAN` / `REMOTE` / `OFFLINE` connection state.
- Width-driven phone, tablet, foldable, and Apple-silicon Mac layouts without device-name detection
- SecureStore persistence for setup mode, server URL, mobile install ID, standalone relay install ID, standalone activation token, standalone airport, mobile diagnostics mode, pinned flight, profiles, mobile appearance choices, and widget preferences
- Companion connection checks against `/api/health`
- Companion dashboard data from `/api/mobile/summary` plus the existing local APIs, with encrypted relay request/response envelopes used only after LAN fetch failure when a remote grant exists
- QR pairing from native Settings prefers the server's LAN IP and carries the server fingerprint, so the app can reject a scan that resolves to another Local Flight host on a multi-server LAN
- Standalone summary, FIDS, Radar, and METAR data from relay `/v1/mobile/*` endpoints
- Native FIDS list from local `/api/fids` in Companion mode and relay `/v1/mobile/fids` in Standalone mode
- Flight details from `/api/fids/detail`, including the server's shared current-source detail model for real vs VATSIM schedule, motion, aircraft, weather, source confidence, and history fields when available. VATSIM details use the same pilot/ATC contract as desktop: callsign, filed plan, pilot track, XPDR, and recent sessions, without passenger codeshare/gate/registration fields.
- Airport, source, and refresh interval editing. The server offers 15, 30, 45, and 60 minute choices plus longer 2, 4, 8, 12, and 24 hour choices where the active schedule mode allows them. Local Flight Relay shows 30-minute-or-slower choices because shared airport snapshots protect upstream schedule access.
- Pinned flight island with pin/unpin and tap-for-detail behavior
- WebSocket listener for `/ws` `snapshot_updated`, `config_updated`, and `scheduler_restarted` events in Companion mode on LAN. Remote Companion can fall back to polling when relay event forwarding is unavailable.
- System, warm light, and midnight dark appearance choices, with a separate high-contrast preference and migration from every legacy skin
- Six-second code-native radar-intercept launch sequence with an orbiting aircraft, acquired blips, the canonical aircraft-and-sweep mark, quiet readiness captions, and a Reduce Motion fallback
- Native-feeling interaction polish through haptics, press and pointer feedback, keyboard focus, native sheets, and short purposeful transitions
- iOS small/medium WidgetKit and Android resizable home-screen widgets backed by the hardened `localflight-widget-snapshot.json` contract. The widgets are read-only, stale-aware, size-bounded, and network-free.
- Best-effort local pinned-flight Live Activity on supported iPhones, started only by the explicit Board action and updated from the same app-written snapshot
- Widget snapshot and native-platform contract checks run through `npm run widget:contract` and `npm run native-widget:contract`; both are included in `npm run verify`.
- Companion Matrix and connected-display controls under **More → Host & Displays**, using the existing host Matrix runtime config APIs
- Explicit **Display** route for the horizontal fullscreen FIDS, with a permanent exit, pause/play, page indicator, pinned-row accent, freshness, and eight-second unattended paging
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
- The host can revoke a remote grant from Local Flight Settings. This device can forget its stored remote grant and pair again later.
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
- It does not store this device's local history on the relay.

The mobile install ID and standalone relay install ID are install-scoped. They are there so reports, quotas, and troubleshooting can say "this came from this app install" without needing an account.

---

## Structure

- `App.tsx` is only the provider entrypoint.
- `src/app/AppShell.tsx` coordinates setup mode and compatibility sheets while `src/session/MobileSessionProvider.tsx` exposes shared transport, refresh, cached-state, pinning, and widget behavior to V2 features.
- `src/navigation/MobileNavigatorV2.tsx` owns adaptive Board/Radar/History/More navigation, native stacks, deep links, and the explicit Display route.
- `src/v2/` contains the Board, Radar, History, More, Display, and shared Board row-model implementations.
- `src/content/` contains the typed English copy catalog and terminology contract.
- `src/api/standalone.ts` is the relay-backed mobile data/report client for Standalone mode.
- `src/api/iap.ts` and `src/iap/` own the native-store product catalog, purchase lifecycle, unfinished-transaction recovery, and relay verification client.
- `src/domain/` contains pure helpers and constants for flights, formatting, radar, matrix, and feedback context.
- `src/hooks/` contains stateful behavior such as launch/bootstrap, dashboard refresh, flight detail loading, and Matrix draft/save/reset.
- `src/screens/AppScreens.tsx` contains retained setup, detail, configuration, host-display, and diagnostics compatibility surfaces while the remaining extraction proceeds.
- `src/storage/standaloneHistory.ts` stores successful standalone FIDS rows locally with Expo SQLite.
- `src/theme/` contains warm semantic tokens, runtime appearance storage, icon mapping, and the compatibility style bridge used only by retained legacy sheets.
- Optional one-time support uses three store-owned consumable products. It unlocks nothing, shows only App Store/Play localized prices, and is consumed only after secure relay verification.

---

## Current Boundaries

- Public App Store release
- Public Google Play production release
- APNs, notification infrastructure, and server-pushed Live Activity updates; this release intentionally uses local best-effort updates only
- Remote Companion physical-device validation on Android and iOS before public store rollout.
- Per-device authorization/revoke tokens for broader mutating LAN controls. Current Companion identifies each device with an install-scoped companion ID/check-in plus optional Remote Companion grant, while Standalone uses its relay activation token.
- Broader mobile admin control is intentionally out of scope; Companion exposes only the current allowlisted control surfaces.
- Native crash capture before JavaScript starts
- Full standalone flight-detail endpoint parity; Standalone currently focuses on Board, Radar, History, More, and reports
- Subscriptions, paywalls, durable paid entitlements, and external payment links

---

## Release Validation

- Remote Companion release-gate proof: pair on the same Wi-Fi, run **Test Remote**, confirm nearby-first behavior, block the nearby route, load Board/Radar/History/More through the relay, exercise an allowed host action, revoke the grant, and confirm remote access stops.
- TestFlight proof pass on a fresh real iPhone and iPad: Companion LAN/Remote pairing, Standalone setup, denied camera/local-network paths, and accessibility settings
- App Store Connect privacy/review metadata using `APP_STORE_REVIEW_NOTES.md`
- Google Play internal-test proof pass on a fresh Android phone: Companion LAN/Remote pairing, Standalone setup, denied camera path, permissions, and accessibility settings
- Play Console privacy/Data Safety/review metadata using `PLAY_STORE_REVIEW_NOTES.md`
- App Store sandbox and Play license-tester proof: all three localized consumables load, cancellation and pending states stay friendly, relay interruption leaves the purchase unfinished, reconnect verifies once, and verified purchases can be bought again after consumption.
- Full standalone flight-detail endpoint parity if Standalone should expose the same detail sheet depth as Companion
- Broader Android device matrix pass after the first local Android smoke test
- Optional React Navigation stack only if future deep links need true back-stack behavior
