# Local Flight changelog

This is the public, user-facing changelog. Implementation-level history lives
in `docs/engineering-changelog.md`; the current release overview is
`docs/release-notes-0.6.0.md`.

## 0.6.0 — universal Relay Access and explicit data routes

### Added

- One portable Beacon Relay Access license shared by verified Stripe,
  paid-iOS, and Android one-time-product purchases. Each purchase creates a
  separate license for one active main device: a desktop using Beacon Relay or
  a phone using real-flight Standalone.
- VST-style `LFRA-…` website license delivery, one-time browser reveal,
  passwordless email protection/recovery, activation codes, and source-neutral
  license management without a Local Flight account or password.
- Provider-neutral fulfillment, replay-safe purchase records, durable
  notification delivery, purchase reconciliation hooks, and masked operator
  controls for license, activation, delivery, and event history.
- Explicit mobile access states for verification, availability, active-here,
  active-elsewhere, suspension, refund, revocation, temporary unavailability,
  and pending release.

### Improved

- Desktop setup now presents exactly Beacon Relay, Bring Your Own Keys, and
  VATSIM, with `data_route` as the authoritative runtime boundary. BYOK and
  VATSIM bypass licensing completely.
- Relay activation now prepares a short-lived credential, lets the client store
  it safely, and commits the move only afterward. A local storage failure cannot
  silently remove access from the previous main device.
- Mobile setup keeps the current working configuration until a new pairing or
  activation succeeds. Moves name the affected main device and always require
  confirmation.
- The paid iOS app verifies its included Relay Access explicitly. Android is a
  free download with free Companion and VATSIM; real-flight Standalone uses an
  optional one-time, non-consumable Google Play purchase.
- Mobile-to-desktop and desktop-to-mobile movement uses the same backend license
  while preserving store-specific app-download ownership. Mobile never accepts
  or displays a raw license key.
- LAN and encrypted Remote Companion continue through the desktop host without
  another license. Remote Companion now requires the host itself to have active
  Relay Access.
- The Beacon Tools product, mobile, Relay Access, network, privacy, terms,
  checkout-result, and passwordless-management pages now describe one coherent
  Local Flight ecosystem and use live catalog availability.

### Privacy, security, and reliability

- Licensed mode rejects legacy Community credentials for real schedules,
  radar, and Remote Companion; Managed credentials are limited to operator
  diagnostics.
- Purchase and access failures return stable, structured states instead of
  requiring clients to interpret prose.
- Raw license keys, device credentials, plain email fields, store proofs, and
  provider identifiers stay out of database columns, logs, and operator JSON.
- Purpose-separated key versions, atomic one-main-device enforcement, expiring
  pending activations, idempotent deactivation, encrypted notification
  destinations, and fail-closed provider capabilities harden the access path.
- The operator surface adds protected state changes, searchable masked
  references, cursor pagination, delivery retries, reconciliation diagnostics,
  and activation history.
- Existing three-tier mobile support purchases remain optional consumables and
  create no Relay Access, durable entitlement, or subscription.

### Distribution notes

- Version 0.6.0 uses iOS build 13 and Android versionCode 16 for store testing.
- Windows, separate Apple silicon/Intel macOS packages, Linux AppImages,
  Ubuntu/Debian desktop and server packages, and the Raspberry Pi bundle retain
  the complete architecture-specific package and checksum matrix.
- Beacon Relay Access has no scheduled expiry or recurring fee, subject to
  refunds, abuse controls, upstream provider permission, and service
  availability. It is not an unconditional lifetime-service guarantee.
- Sales and licensed production data remain disabled until store/payment
  verification, reconciliation, backups, production secrets, physical-device
  tests, and upstream provider permissions are confirmed.

## 0.5.2 — full desktop and Linux coverage

### Added

- Separate Developer ID signed and notarized macOS packages for Apple silicon
  and Intel Macs.
- Portable AppImages for x86-64 and ARM64 Linux desktops.
- Integrated Ubuntu/Debian desktop packages and separate headless server
  packages for x86-64 and ARM64.
- A reproducible native release matrix with architecture checks, package safety
  scans, exact checksums, and a draft-release inventory gate.
- A complete, user-oriented 0.5.2 feature guide for desktop, LAN, server,
  Raspberry Pi, Matrix, and mobile testing.

### Improved

- Ordinary Linux desktop sessions now open in a normal resizable window, while
  fullscreen stays limited to Raspberry Pi and explicit kiosk use.
- HUB75 `main.py` generation now works in every packaged desktop/server build,
  and the native Matrix page saves a freshly generated configuration instead
  of reusing an older preview.
- Fresh headless installs serve setup immediately but defer scheduled provider
  work until setup is complete.
- The public download page explains every operating-system and CPU choice and
  enables each file only when its matching SHA-256 checksum is available.
- Network, privacy, support, install, and mobile wording now leads with plain
  answers and user choices before technical detail.

### Privacy, security, and reliability

- Updated the desktop and relay web, request, form-upload, image, and
  environment dependency baseline.
- Bounded public bug-report request bodies before multipart parsing while
  retaining file, deduplication, and network-rate limits.
- Added relay health monitoring and gated production deployment behind full
  Python, mobile, dependency-audit, package-safety, and container smoke checks.
- Binary packaging now fails closed when a required runtime template, web
  asset, airport index, bundled help file, or app identity asset is missing.
- Preserved the local-first storage model, public Support ID boundary, optional
  diagnostics, encrypted Remote Companion envelopes, and minimal purchase
  verification records.

### Distribution notes

- macOS supports Apple silicon and Intel on macOS 12 or newer through separate
  packages; no Universal 2 package is published in this release.
- x86-64 Linux desktop testing covers Ubuntu 22.04/24.04 and Debian 12/13.
  ARM64 desktop packages require Ubuntu 24.04 or Debian 13; ARM64 headless and
  Raspberry Pi paths retain the older tested operating-system line.
- The Windows installer remains intentionally unsigned for 0.5.2 and is
  published with an explicit unknown-publisher notice and checksum. A checksum
  verifies release-file integrity but is not a publisher signature.
- Mobile 0.5.2 remains a TestFlight and Google Play internal-testing line until
  the public store gates are completed.

## 0.5.1 — release hardening

### Added

- Native Qt desktop app, supported LAN browser UI, Raspberry Pi display modes,
  mobile Companion/Standalone paths, and Matrix tooling on one compatibility
  baseline.
- Encrypted Remote Companion fallback for explicitly paired phones while the
  Local Flight host remains online.
- iOS and Android home-screen widgets that read only the app's bounded local
  snapshot and never fetch network data themselves.
- Optional one-time mobile support purchases through the platform stores. They
  unlock nothing and create no subscription or durable entitlement.
- Beacon Tools download, mobile, support, network, privacy, and privacy-choice
  pages.
- Shared user notices with plain-language state and next-step guidance across
  native, LAN browser, Companion, and Standalone clients.

### Improved

- First-run and re-setup transitions between Local Flight Relay, personal
  provider keys, and VATSIM now clear stale mode-specific state safely.
- Community Relay setup now verifies the install link before opening the app,
  self-repairs older unlinked installs without activation spam, and offers
  clear retry, VATSIM, or own-key choices when linking is unavailable.
- Community schedule snapshots now allow a 30-minute minimum cadence. Failed
  first updates use bounded retries, while loaded boards retain safe cached
  data during temporary relay or provider failures.
- Packaged desktop provider keys live in the user's Local Flight data directory
  rather than inside the application bundle.
- FIDS uses airport-local time, passenger-friendly weather, clearer
  city/country titles, operating-flight identity, codeshare grouping, and
  distinct Classic, PAX, VATSIM, and Nerd layouts.
- VATSIM views use callsign, flight-plan, aircraft, and track information while
  suppressing passenger-only fields and person-identifying network data.
- Radar, History, Matrix, Settings, setup, and detail views are aligned across
  native Qt and the LAN browser UI.
- Radar now separates provider board status from live movement phase, uses
  strong flight identity matches, and applies elevation-aware ground, taxi,
  departure, en-route, descent, approach, and final rules with hysteresis.
- Qt, LAN browser, and mobile radar views now share the same clockwise
  15-second sweep contract: one leading line, a fading trail, and blips that
  appear only after the sweep reaches them. Selected targets stay readable and
  can be dismissed without choosing another aircraft.
- Terrain now combines radius-aware AWS elevation mosaics and real contour
  geometry with separately cached OpenStreetMap water, vegetation, coastline,
  and limited road context.
- Native Qt now provides complete dark and light appearances across pages,
  dialogs, menus, control icons, and FIDS styles, with contrast-checked text
  and semantic colors for every skin.
- Windows and macOS native sessions expose a branded status menu with shortcuts
  to core pages, the LAN browser, flight-update restart, and clean shutdown;
  macOS also attaches the menu to the Dock icon.
- History counts deduplicated movements instead of repeated snapshot rows.
- Matrix preview and generated board clients share the current display contract,
  weather/gate rules, animations, and renderer-version warnings.
- Mobile setup, navigation, launch polish, local history, widgets, reporting,
  and LAN/remote connection feedback are aligned across iOS and Android.
- Remote Companion pairing now uses correctly encoded cross-platform encrypted
  envelopes, verifies the remote backup before saving it, and replaces stale
  grants for the same phone instead of accumulating retries.
- Public release downloads activate only when a matching package and SHA256
  checksum are present on the official GitHub release.

### Privacy and security

- Client-facing install identity is represented by a public Support ID rather
  than a raw install UUID.
- Ordinary UI notices no longer expose internal routes, provider mechanics,
  local filesystem paths, or raw exception text.
- Credential-like files are excluded from Git and rejected independently by
  source-release packaging.
- App-written credentials and identity files use owner-only POSIX permissions
  where supported.
- Remote Companion, diagnostics, provider-key, relay-admin, mobile-purchase,
  and public-support paths have dedicated redaction and abuse-safety coverage.

### Distribution notes

- Windows and Raspberry Pi packages are built from the same `0.5.1` source
  line.
- The current macOS direct-download `.pkg` is Developer ID signed, notarized,
  stapled, and built for Apple silicon. Disabling Gatekeeper globally is never
  required.
- Mobile `0.5.1` remains in TestFlight and Google Play testing until the public
  store review gates are complete.
- `0.5.1` is the shared Windows, macOS, Raspberry Pi, LAN, relay, and mobile
  testing line. Platform installers are built on their native toolchains and
  published with matching checksums.

## 0.2.8 — preliminary hardening work

- Prepared the LAN/native parity, mobile store identity, widget snapshot,
  provider-key privacy, relay/reporting, preview asset, and packaging work later
  folded into `0.5.1`.
- This was an intermediate development line and has no separate public package.

## 0.2.7 — client polish

- Introduced the polished native shell, four FIDS styles, movement-based History,
  Matrix display-contract improvements, Companion/Standalone mobile split,
  LAN phone/7-inch layouts, Beacon Tools public home, and stronger VATSIM
  display/privacy rules.

## 0.2.6 — client parity

- Aligned native and browser History, Matrix, Settings, setup, FIDS details, and
  radar behavior around the same local APIs and user model.

## 0.2.5 — multi-client beta baseline

- Established native desktop, LAN browser, Raspberry Pi, mobile Companion, and
  Matrix as supported clients of one local server.

## 0.2.1–0.2.4 — platform and relay foundations

- Added cross-platform startup, setup gating, scheduler control, WebSocket live
  updates, history, packaging, local diagnostics, initial mobile support, and
  the hosted shared-relay path.

## 0.1.0 — initial release

- Initial FastAPI FIDS board, schedule/radar/weather sources, WebSocket updates,
  Matrix preview/client, setup wizard, and SQLite history.
