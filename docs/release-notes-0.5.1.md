# Local Flight 0.5.1 Public Release Notes

`0.5.1` is the public-release hardening line for Local Flight desktop and
Raspberry Pi installs. The mobile app is now store-bound after the Remote
Companion connectivity/privacy proof pass, with App Store Connect and Google
Play Console metadata kept aligned to the same privacy model.

Local Flight is still informational beta software. Flight, radar, weather,
surface, Matrix, relay, and mobile data can be delayed, incomplete, cached,
wrong, or unavailable. Do not use Local Flight for navigation, dispatch,
operational control, flight planning, professional aviation work, or safety
decisions.

## What This Release Focuses On

- Desktop and Raspberry Pi are the public release path for this milestone.
- Native Qt, LAN browser, Pi display modes, Matrix/i75W, public support forms,
  Beacon Tools docs, and relay-facing client behavior are treated as one release
  ecosystem.
- Mobile keeps the permanent Beacon package IDs and first store counters, and
  treats Remote Companion as a fixed Companion feature once the release-gate
  proof passes.

## Hardening Since 0.2.7

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
- Repaired the public preview gallery contract: five desktop cards plus four
  mobile cards, with Matrix retained and stale deploy-site preview duplicates
  removed.
- Repaired Beacon Tools homepage brand placement and Local Flight public preview
  references so the site uses the current stable PNG aliases.
- Hardened the macOS preinstall-script test for Windows development machines
  while keeping the executable-bit assertion meaningful on POSIX/macOS.
- Matched the local AviationStack fair-fetch metadata contract to the relay path
  by always exposing fallback-use state and adaptive page metadata.
- Hardened setup/re-setup provider-mode transitions so BYOK, managed relay,
  community relay, and virtual paths clear stale provider keys and process env
  state consistently.
- Made setup-written `.env` provider/relay values authoritative across startup,
  scheduler restarts, settings/status, and setup completion while keeping log
  redaction paranoid about stale process secrets.
- Locked the native Qt setup transition against accidental backend shutdown by
  keeping Qt from quitting just because the setup window closes internally.
- Updated Expo SDK 55 patch dependencies to satisfy Expo Doctor without a
  breaking SDK upgrade.

## Packaging Targets

- Windows: signed `LocalFlight-0.5.1-Setup.exe` plus portable zip/checksum.
- macOS: Developer ID signed, notarized, stapled `LocalFlight-0.5.1-macos.pkg`
  plus checksum.
- Raspberry Pi: `LocalFlight-pi-source-0.5.1.zip` plus checksum.

## Mobile Beta Notes

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

Before tagging or publishing `v0.5.1`, run:

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
