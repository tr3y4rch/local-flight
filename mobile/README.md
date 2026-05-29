# Local Flight Mobile

React Native / Expo mobile app for Local Flight.

Local Flight Mobile is in internal beta for **iOS TestFlight** and **Google Play testing**. Public store downloads are not live yet. The app has two first-run modes:

- **Standalone:** use the Beacon Tools relay directly for a simple phone board. No desktop or Raspberry Pi server is required.
- **LAN Companion:** pair with your own Local Flight desktop or Raspberry Pi server on the same Wi-Fi/LAN.

For most testers, choose **Standalone** first. It is the quickest way to see the Board, Radar, History, and Settings without extra hardware. Choose **LAN Companion** when you already run Local Flight at home and want the phone to act as a remote board, radar, and control surface.

Local Flight is a personal display aid. Flight, weather, radar, and airport-surface data can be delayed, incomplete, or unavailable. Do not use it for navigation, dispatch, operational control, or safety decisions.

Public links:

- Mobile page: [beacontools.cc/local-flight/mobile](https://beacontools.cc/local-flight/mobile)
- Privacy policy: [beacontools.cc/privacy](https://beacontools.cc/privacy)
- Support: [beacontools.cc/support](https://beacontools.cc/support)
- Relay used by Standalone: `https://relay.beacontools.cc`

---

## Internal Beta Install Path

### iOS

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

---

## First Launch

On first launch, Local Flight asks how this phone should connect.

### Standalone

Standalone is the easiest review and tester path.

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

### LAN Companion

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

LAN Companion gives you:

- Board, Radar, and History from the paired server
- Control for pairing, host status, airport/source/refresh settings, Matrix, widgets, diagnostics, help, and reports
- WebSocket updates from the local server
- Matrix live-remote controls when the host has Matrix configured
- Automatic diagnostics only when both the phone and host allow it

---

## Current Mobile Features

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

---

## Privacy Model

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
- Dynamic Island / Live Activities
- Android OS widgets
- In-app purchases, payments, or support tips
- Native crash capture before JavaScript starts
- Broader LAN admin authorization/revoke controls

---

## Release Checklist

- TestFlight internal beta on a real iPhone and iPad
- Google Play internal or closed test on a real Android phone
- Fresh Standalone setup
- LAN QR and manual pairing
- Denied camera and local-network paths
- Offline relay retry state
- Widget add/update/stale states on iOS
- Support sheet shows store setup and cannot charge
- Accessibility pass with larger text, reduced motion, and screen-reader labels
