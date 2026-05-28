# Local Flight Widget Template

Tracked WidgetKit template for the future iOS widget extension. The generated
`mobile/ios/` directory is ignored, so keep these files as the source of truth
until Apple Developer Program signing and App Groups are available.

The Expo app already writes `localflight-widget-snapshot.json` using the schema
in `mobile/src/domain/widgets.ts`. The future native widget must read that file
only. It must never fetch LAN, relay, or third-party flight data directly.

## Current Pre-Credential State

- `WidgetSnapshot.swift` contains defensive decoding and normalization for the
  app-written snapshot contract.
- `LocalFlightWidget.swift` is the thin WidgetKit provider/host. The V2 visuals
  live in `DesignTokens.swift`, `SmallWidgetViewV2.swift`,
  `MediumWidgetViewV2.swift`, and `LiveActivityViewV2.swift`.
- `Fonts/` contains the same bundled app fonts the Expo app uses:
  Audiowide for the Local Flight wordmark, DM Sans for readable UI text, and
  Space Mono for board/FIDS text.
- `LocalFlightWidget-Info.plist` is copied into the generated widget extension
  and carries the WidgetKit extension point plus bundled font declarations.
- `SampleSnapshots.swift` contains preview/sample states for pinned, no-pinned,
  stale, and empty-board rendering.
- `LocalFlightWidget.entitlements` documents the future App Group ID, but it is
  not wired into the live Expo iOS app target yet.
- The app writer remains passive: it prefers the shared container only if it
  already exists and otherwise writes to the app sandbox fallback.

## Once Apple Credentials Are Available

1. Confirm the iOS bundle ID that will ship:
   `cc.beacontools.localflight`.
2. In Apple Developer/App Store Connect, enable App Groups for the app ID.
3. Create/enable the shared group:
   `group.cc.beacontools.localflight`.
4. Regenerate or refresh signing assets/provisioning profiles so both the app
   and widget extension can use the group.
5. Run Expo prebuild from a clean mobile tree. The tracked
   `with-localflight-ios-widget` config plugin copies this template, creates the
   `LocalFlightWidget` extension target, and adds the App Group entitlement:
   `npx expo prebuild --platform ios --clean`.
6. Verify the generated extension target is named `LocalFlightWidget` and uses
   bundle ID `cc.beacontools.localflight.widget`.
7. Verify the target contains `WidgetSnapshot.swift`, `LocalFlightWidget.swift`,
   `DesignTokens.swift`, `SmallWidgetViewV2.swift`, and
   `MediumWidgetViewV2.swift`. Do not add `LiveActivityViewV2.swift` to target
   membership until ActivityKit is intentionally enabled.
8. Verify everything in `Fonts/` is present in the widget target bundle.
9. Verify the widget target `Info.plist` includes these font names:
   `Audiowide-Regular`, `SpaceMono-Regular`, `SpaceMono-Bold`,
   `DMSans-9ptRegular_Regular`, and `DMSans-9ptRegular_Bold`.
   This keeps the medium widget aligned with the mobile header and Qt shell
   hierarchy instead of falling back to SF/Arial-like system text.
10. Keep `SampleSnapshots.swift` in debug/preview-only membership, or exclude it
   from release builds unless used only inside SwiftUI preview code.
11. Confirm App Groups entitlement exists on both targets:
    app target `LocalFlight` and extension target `LocalFlightWidget`.
12. Confirm `group.cc.beacontools.localflight` is in both target entitlements.
13. Verify the Expo app can still build and that `Paths.appleSharedContainers`
    exposes the group container before expecting widget data sharing to work.
14. Build the app, pin a flight, open Widgets & Glances, and confirm the writer
    reports `Snapshot ready · app group`.
15. Add the widget in the simulator/device widget gallery and verify the small
    widget stays pinned-flight-only while the medium widget shows pinned plus
    bounded board rows.
16. Archive with the final signing team and verify the embedded extension is
    present in the `.ipa`.

## ActivityKit / Dynamic Island Later

- Keep Dynamic Island and Live Activity wiring separate from the WidgetKit
  target pass.
- Add ActivityKit only after the WidgetKit/App Group path is stable.
- Use `LiveActivityViewV2.swift` as the source for ActivityKit visuals. Compact
  and minimal states remain flight/status only; expanded Dynamic Island should
  use the separate leading, trailing, and bottom region views so route and
  destination copy stays below the TrueDepth camera area.
- Keep the richer rounded `LFLockScreenBannerV2` layout for Lock Screen/StandBy
  only, not as the Dynamic Island expanded region layout.
- The Live Activity should read the same pinned-flight snapshot shape and should
  never promote a random row when the pinned flight disappears.
- If remote Live Activity updates are added later, wire APNs and server update
  credentials as a separate release task.

## Validation Commands

Run these before wiring the target and again after the target exists:

```bash
cd /Applications/local-flight/mobile
npm run verify
npm run a11y
```

```bash
cd /Applications/local-flight
xcrun --sdk iphonesimulator swiftc -parse \
  -target arm64-apple-ios15.1-simulator \
  mobile/native/ios-widget/WidgetSnapshot.swift \
  mobile/native/ios-widget/DesignTokens.swift \
  mobile/native/ios-widget/SmallWidgetViewV2.swift \
  mobile/native/ios-widget/MediumWidgetViewV2.swift \
  mobile/native/ios-widget/LiveActivityViewV2.swift \
  mobile/native/ios-widget/LocalFlightWidget.swift \
  mobile/native/ios-widget/SampleSnapshots.swift
plutil -lint mobile/native/ios-widget/LocalFlightWidget-Info.plist
plutil -lint mobile/native/ios-widget/LocalFlightWidget.entitlements
```

After the Xcode target is wired, also validate from `mobile/ios/`:

```bash
xcodebuild \
  -workspace LocalFlight.xcworkspace \
  -scheme LocalFlight \
  -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
  build
```

## Guardrails

- Do not add the App Group entitlement to the live app target until the Apple
  account has the group enabled and provisioning profiles are refreshed.
- Do not point widgets at the LAN server, relay, or provider APIs.
- Do not let stale or malformed snapshots silently switch to another flight.
- Keep `schemaVersion: 1` until a real migration plan exists.
