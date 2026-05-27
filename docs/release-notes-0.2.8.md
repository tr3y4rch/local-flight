# Local Flight 0.2.8 Preliminary Notes

`0.2.8` is the next polish line after the `0.2.7` release candidate. These
notes are preliminary: packaged Windows, macOS, Raspberry Pi, iOS, and Android
artifacts still remain on the current `0.2.7` release-candidate line until the
version is deliberately bumped.

The theme for this pass is release readiness: the native shell, LAN browser,
mobile Companion, mobile Standalone, relay, and public docs should describe the
same product, with clearer privacy posture and fewer surprising network hops.

---

## LAN And Native Shell Parity

- The LAN browser Settings page now follows the calmer Qt Settings structure,
  with high-signal cards first and secondary controls tucked into organized
  sections.
- Browser Settings now includes Pair Mobile controls with QR/manual pairing,
  preferred LAN URL, server fingerprint, paired-device refresh, copy actions,
  and reset paired devices.
- Outputs/Radar and Profiles are available from normal client Settings instead
  of being hidden behind operator Network Admin.
- FIDS, Display, and Radar are being brought onto the same current shell/nav
  language so browser views no longer look like separate generations of the app.
- Setup reset is being hardened so rerunning setup from Settings launches the
  wizard directly instead of requiring users to relaunch the full app.

## Mobile Companion And Standalone Polish

- The mobile airport hero has been simplified into one shared top rail. Board
  keeps the full airport hero; Radar, History, Control, and Settings use the
  compact companion rail.
- UTC/LT display has been hardened around airport-local time, not device-local
  time.
- The mobile weather presentation now separates compact header weather from the
  richer Board weather card, while preserving user-selected weather style
  behavior on the expanded Board.
- LAN Companion Control and Standalone Settings now share the same interaction
  model: rows either open a sheet directly or expand inline, but do not mix both
  behaviors in one visual affordance.
- Help/reporting, appearance, widgets, diagnostics, and support/tip surfaces are
  streamlined so both mobile modes feel like the same app with different feature
  depth.
- The mobile splash/setup flow has moved toward the new Beacon-style launch
  language: ready-gated entry, compact setup rail after the welcome step,
  keyboard-safe setup pages, gentler page transitions, and a lower bottom nav.

## Store And Platform Readiness

- Mobile store identity is being locked to Beacon-owned IDs before first
  upload: iOS bundle ID and Android package are both
  `cc.beacontools.localflight`, with first store build counters starting at
  `1`.
- Android local development, emulator/device launch, package-uninstall, Gradle,
  and EAS/Play release pathing are documented for the current Expo app.
- Mobile store copy and review notes now point at the Beacon Tools support,
  privacy, mobile trust, network, and privacy-choice pages, with TestFlight and
  Google Play internal testing as the first target.
- Support remains stub-only in the app. Real IAP, StoreKit, Google Play Billing,
  Apple Developer ID signing, and Play Console credentials remain future work.

## Widgets And Glances Prep

- Added a design-only iOS widgets and Dynamic Island plan: small widget as a
  pinned-flight tracker, medium widget as a horizontal-FIDS-style board, and
  Live Activity/Dynamic Island as pinned-flight-only.
- Added in-app `Widgets & Glances` settings/preview paths to both mobile modes
  without enabling native OS widgets yet.
- Added a preliminary widget snapshot contract and storage scaffold so the app
  can prepare bounded, stale-aware, network-free widget data before WidgetKit or
  ActivityKit wiring exists.
- Added pre-entitlement native widget skeleton guidance for the future Apple
  Developer/App Group pass. No App Group, APNs, WidgetKit target, or ActivityKit
  entitlement is wired in this slice.

## Provider Keys And Privacy Hardening

- AeroDataBox is being promoted into the first-run/settings API key flow
  alongside AviationStack, ADS-B Exchange/RapidAPI, and OpenSky.
- BYOK installs are treated as direct/private provider paths: AeroDataBox is the
  preferred schedule source when present, AviationStack can fill/fallback, and
  stale relay schedule credentials are cleared when switching modes.
- Provider status now has a clearer non-secret shape, including active path and
  privacy posture, so UI surfaces can explain whether the app is using direct
  keys, relay, or virtual data.
- Secret leakage tests are being added for settings HTML, provider status,
  admin/mobile config, diagnostics, reports, logs, and report forwarding.
- Radar surface behavior is being split into explicit modes so non-relay and
  relay-cache behavior are easier to reason about.

## Relay, Reporting, And Diagnostics

- Relay/mobile compatibility notes now cover the current standalone summary,
  FIDS, radar, METAR, activation, check-in, and report routes.
- Mobile report metadata is being hardened so bug reports carry OS family and
  app mode (`lan_companion` or `standalone`) without exposing provider secrets.
- Heartbeat and relay presence behavior remains coarse, optional, and
  eligibility-gated. BYOK and virtual/private paths should not create surprise
  relay traffic.
- Public website support/contact/reporting stays separate from operator-only
  Network Admin routes and secrets.

## Documentation, Preview Assets, And Packaging

- Preliminary `0.2.8` release notes now track post-RC changes without changing
  the active package target from `0.2.7`.
- Preview assets are documented under `assets/previews/mobile/iOS/`,
  `assets/previews/mobile/Android/`, and `assets/previews/shell/`.
- Preview priority for public docs/site galleries remains: FIDS first, then
  Radar, History, Setup, Display, and Splash.
- The macOS public release path is planned around a signed/notarized `.pkg`,
  while the current unsigned app/zip remains a local-dev packaging path.
- The Beacon Tools public site still requires a real Cloudflare Worker + Assets
  deploy from the repository; dashboard `.dev` previews do not publish the
  custom domain.

## Still Expected Before 0.2.8 Final

- Decide whether `0.2.8` becomes a full app version bump with rebuilt artifacts
  or remains a provisional docs/client-polish line.
- Re-run the normal release validation sweep after the final scope is frozen:
  backend tests, compile checks, mobile `verify`/`a11y`, iOS/Android local build
  smoke, and release-manifest review.
- Refresh public screenshots from the latest native, LAN browser, Matrix, and
  mobile screens before publishing final notes.
- Use the new Apple Developer/App Store Connect and Google Play Console access
  for private beta uploads first; keep WidgetKit/ActivityKit wiring behind the
  separate App Group/signing pass.
