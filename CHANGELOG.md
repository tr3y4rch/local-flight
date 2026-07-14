# Local Flight changelog

This is the public, user-facing changelog. Implementation-level history lives
in `docs/engineering-changelog.md`; the current release overview is
`docs/release-notes-0.5.1.md`.

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
- Packaged desktop provider keys live in the user's Local Flight data directory
  rather than inside the application bundle.
- FIDS uses airport-local time, passenger-friendly weather, clearer
  city/country titles, operating-flight identity, codeshare grouping, and
  distinct Classic, PAX, VATSIM, and Nerd layouts.
- VATSIM views use callsign, flight-plan, aircraft, and track information while
  suppressing passenger-only fields and person-identifying network data.
- Radar, History, Matrix, Settings, setup, and detail views are aligned across
  native Qt and the LAN browser UI.
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
- The current macOS direct-download archive is ad-hoc signed for Apple silicon
  and may require Finder's explicit Open confirmation once. It is not Developer
  ID notarized; disabling Gatekeeper globally is never required.
- Mobile `0.5.1` remains in TestFlight and Google Play testing until the public
  store review gates are complete.

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
