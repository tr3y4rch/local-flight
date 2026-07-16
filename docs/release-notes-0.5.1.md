# Local Flight 0.5.1 Release Overview

`0.5.1` is the active Local Flight release line across Windows, macOS,
Raspberry Pi, LAN browsers, the shared relay, and mobile testing. Desktop and
Pi packages are built on their appropriate platform and published with matching
checksums. Mobile TestFlight and Google Play testing use the same version so
Companion, Standalone, relay compatibility, and privacy choices remain aligned
with the local server.

Local Flight is an informational display. Flight, radar, weather, surface,
Matrix, relay, and mobile data can be delayed, incomplete, cached, wrong, or
unavailable. Do not use Local Flight for navigation, dispatch,
operational control, flight planning, professional aviation work, or safety
decisions.

## What This Release Brings Together

- Desktop and Raspberry Pi are the public release path for this milestone.
- Native Qt, LAN browser, Pi display modes, Matrix/i75W, public support forms,
  Beacon Tools docs, and relay-facing client behavior are treated as one release
  ecosystem.
- Mobile keeps the permanent Beacon package IDs and treats Remote Companion as
  a fixed Companion feature, not a separate account or cloud-control mode.

## User-Facing Improvements

- Restored browser display-shell airport-local clock parity so the LAN display
  shell follows the configured airport timezone instead of relying on device
  local time.
- Re-aligned mobile setup copy around Companion and Standalone mode so the
  product explanation matches current Companion behavior.
- Added Remote Companion hardening as the store-bound Companion path: LAN-first
  mobile behavior, encrypted relay fallback for paired relay-linked hosts,
  explicit grants/revocation, relay safety limits, and privacy-proof tests.
- Added a **Test Remote** action in the mobile Companion connection panel. It
  sends a tiny encrypted probe through the relay, retries only once for
  short-lived network/host failures, avoids repeat-tap spam, and explains common
  failures in plain language.
- Refreshed Beacon Tools product, mobile, network, support, and privacy pages so
  each setup path is explained consistently and in plain language.
- Hardened setup and re-setup transitions between Local Flight Relay, personal
  provider keys, and VATSIM so old credentials or source choices do not linger.
- Community Relay setup now verifies the install link before opening the first
  board. Older installs can repair the link once without repeated activation
  requests, and first-load failures retry safely instead of waiting for the
  full schedule interval.
- Community schedule refresh choices now start at 30 minutes. Navigation reads
  server-held state and no-op settings saves no longer restart data services.
- Radar movement phases now use live track evidence independently from the
  passenger-board status, including elevation-aware taxi/final rules and short
  hysteresis against noisy positions.
- Radar presentation is aligned across Qt, LAN browser, and mobile: a
  clockwise 15-second leading sweep reveals each target, then leaves a calm
  fading trail. Hovered, focused, or selected targets remain readable, and a
  selection can be closed without selecting another aircraft.
- Terrain uses radius-aware elevation mosaics, relief bands, and true contours,
  with OpenStreetMap water and land context kept as a separate calm layer.
- Kept conservative secret redaction across logs, reports, and diagnostics.
- Stabilized native setup/window transitions and kept the LAN browser, native
  shell, Pi displays, Matrix tools, and mobile clients on the same API contract.
- Completed the Qt light/high-visibility appearance across native palettes,
  custom FIDS styles, dialogs, menus, controls, setup, and splash surfaces,
  with contrast checks across every skin.
- Restored native Windows/macOS status controls with a compact branded icon,
  direct page shortcuts, LAN-browser access, update restart, and clean quit.
- Moved packaged desktop provider-key storage into the user's Local Flight data
  folder so first-run setup never modifies a signed application bundle.

## Packaging Targets

The Beacon Tools Downloads section discovers the newest complete packaged
release from GitHub and links directly to its files. Windows, macOS, or Pi
buttons become direct downloads only when the expected artifact and matching
SHA256 file are both attached to that release.

- Windows: `LocalFlight-0.5.1-Setup.exe` plus checksum, built and validated on
  Windows with its actual publisher-signing status stated on the release.
- macOS: Developer ID signed and notarized Apple silicon installer package
  `LocalFlight-0.5.1-macos.pkg` plus checksum. Users install through the normal
  macOS installer flow; the documentation never asks users to disable
  Gatekeeper.
- Raspberry Pi: `LocalFlight-pi-source-0.5.1.zip` plus checksum.

## Mobile Store-Testing Notes

- App name: `Local Flight`.
- Publisher/site brand: Beacon Tools.
- iOS bundle ID and Android package: `cc.beacontools.localflight`.
- URL scheme remains `localflight`.
- Store review path should choose Standalone first so reviewers do not need a
  desktop or Raspberry Pi host.
- Companion review/smoke should also pair on LAN, confirm LAN-first behavior,
  simulate LAN failure, verify `REMOTE` mode through the relay, revoke the
  phone grant, and confirm remote access stops.
- Widget-enabled source targets iOS build `7` and Android versionCode `10`.
  Both home-screen widgets read only a bounded app-written snapshot; they do
  not poll LAN, relay, or flight-provider services.
- Dynamic Island and Live Activities remain deferred.
- Mobile adds optional one-time App Store/Play support purchases. They unlock nothing, use store-owned localized prices, and are completed only after secure store verification; subscriptions and paywalls are not included.

## Validation Gate

Before replacing or adding any `v0.5.1` artifact, maintainers run:

```powershell
.venv\Scripts\python.exe -m compileall -q src relay installers scripts tests
.venv\Scripts\python.exe -m pytest tests -q
cd mobile
npm run verify
npm run a11y
npx expo config --type public
```

Also smoke fresh install and upgrade paths on Windows, macOS, and Raspberry Pi,
plus Beacon Tools public pages and support forms after the Cloudflare deploy.
Physical Matrix/i75W, Pi service/kiosk, Windows installer, and notarized macOS
package smoke remain release-artifact gates.
