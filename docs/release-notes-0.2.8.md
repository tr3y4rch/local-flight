# Local Flight 0.2.8 Client Notes

`0.2.8` is the current beta/client-polish line after the `0.2.7` release
candidate. It keeps the project in beta, but it makes the native shell, LAN
browser, mobile Companion, mobile Standalone, relay behavior, preview assets,
and public docs describe the same product.

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
  of being tucked away in maintenance-oriented tooling.
- FIDS, Display, and Radar have been brought closer to the same current
  shell/nav language so browser views no longer feel like separate generations
  of the app.
- Setup reset is hardened so rerunning setup from Settings can launch the
  wizard directly instead of leaving users to guess whether they need to relaunch
  the full app.

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

- Mobile store identity is locked to Beacon-owned IDs before first
  upload: iOS bundle ID and Android package are both
  `cc.beacontools.localflight`, with first store build counters starting at
  `1`.
- Android local development, emulator/device launch, package-uninstall, Gradle,
  and EAS/Play release pathing are documented for the current Expo app.
- Mobile store copy and review notes now point at the Beacon Tools support,
  privacy, mobile trust, network, and privacy-choice pages, with TestFlight and
  Google Play internal testing as the first target.
- Support tips are visible in the app but remain non-charging. Real IAP,
  StoreKit, Google Play Billing, and relay purchase verification remain future
  work before any support tier can charge.

## Widgets And Glances Prep

- Added an iOS widget path: small widget as a pinned-flight tracker and medium
  widget as a horizontal-FIDS-style board, both reading the app-written snapshot
  through the App Group in TestFlight builds.
- Added in-app `Widgets & Glances` settings/preview paths to both mobile modes.
  Android still treats this as a future OS-widget preview.
- Hardened the widget snapshot contract so widgets receive bounded,
  stale-aware, network-free data. ActivityKit / Dynamic Island remain deferred.
- Added native widget source guidance for the tracked WidgetKit template and
  App Group path. APNs and ActivityKit entitlements are not wired in this slice.

## Provider Keys And Privacy Hardening

- AeroDataBox is promoted into the first-run/settings API key flow
  alongside AviationStack, ADS-B Exchange/RapidAPI, and OpenSky.
- BYOK installs are treated as direct/private provider paths: AeroDataBox is the
  preferred schedule source when present, AviationStack can fill/fallback, and
  stale relay schedule credentials are cleared when switching modes.
- Provider status now has a clearer non-secret shape, including active path and
  privacy posture, so UI surfaces can explain whether the app is using direct
  keys, relay, or virtual data.
- Secret leakage checks cover settings HTML, provider status,
  admin/mobile config, diagnostics, reports, logs, and report forwarding.
- Radar surface behavior is split into explicit modes so non-relay and
  relay-cache behavior are easier to reason about.

## Relay, Reporting, And Diagnostics

- Relay/mobile compatibility notes now cover the current standalone summary,
  FIDS, radar, METAR, activation, check-in, and report routes.
- Mobile report metadata is hardened so bug reports carry OS family and
  app mode (`lan_companion` or `standalone`) without exposing provider secrets.
- Heartbeat and relay presence behavior remains coarse, optional, and
  eligibility-gated. BYOK and virtual/private paths should not create surprise
  relay traffic.
- Public website support/contact/reporting stays separate from private admin
  tooling and secrets.

## Documentation, Preview Assets, And Packaging

- `0.2.8` release notes now describe the active app/package line.
- Preview assets are documented under `assets/previews/mobile/iOS/`,
  `assets/previews/mobile/Android/`, and `assets/previews/shell/`.
- Preview priority for public docs/site galleries remains: FIDS first, then
  Radar, History, Setup, Display, and Splash.
- The macOS public release path is planned around a signed/notarized `.pkg`,
  while the current unsigned app/zip remains a local-dev packaging path.
- The Beacon Tools public site still requires a real Cloudflare Worker + Assets
  deploy from the repository; dashboard `.dev` previews do not publish the
  custom domain.

## Release Validation Focus

- Rebuild release artifacts from the current 0.2.8 tree on the appropriate
  machines: Windows installer on Windows, macOS package on macOS after
  Developer ID signing is available, and Pi source bundle from the release
  checkout.
- Keep internal beta uploads first for TestFlight and Google Play Internal
  Testing. Real StoreKit/Google Play Billing, ActivityKit/Dynamic Island, and
  public store rollout remain separate follow-up work.
- Refresh public screenshots from the latest native, LAN browser, Matrix, and
  mobile screens whenever the website gallery is updated.
