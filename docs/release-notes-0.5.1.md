# Local Flight 0.5.1 Release Overview

`0.5.1` is the active Local Flight release line for desktop and Raspberry Pi.
The platform packages are being rebuilt and validated together before the
GitHub release is published. Mobile TestFlight and Google Play testing uses the
same version so Companion, Standalone, relay compatibility, and privacy choices
remain aligned with the local server.

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
- Kept conservative secret redaction across logs, reports, and diagnostics.
- Stabilized native setup/window transitions and kept the LAN browser, native
  shell, Pi displays, Matrix tools, and mobile clients on the same API contract.
- Moved packaged desktop provider-key storage into the user's Local Flight data
  folder so first-run setup never modifies a signed application bundle.

## Packaging Targets

- Windows: `LocalFlight-0.5.1-Setup.exe` plus checksum. The published release
  must state its actual publisher-signing status.
- macOS: Developer ID signed, notarized, stapled `LocalFlight-0.5.1-macos.pkg`
  plus checksum.
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
- Payments, tips, purchase UI, and in-app purchase processing are not included.

## Validation Gate

Before tagging or publishing `v0.5.1`, maintainers run:

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
Physical Matrix/i75W, Pi service/kiosk, signed installer, and notarized macOS
package smoke remain release-artifact gates.
