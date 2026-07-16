# Local Flight Mobile Google Play Review Notes

This file is the working checklist for the `0.5.1` Play internal-testing build. It is not legal advice; keep the final Play Console answers aligned with the exact submitted AAB.

## Reviewer Test Path

- App name: **Local Flight**
- Android package: `cc.beacontools.localflight`
- Version name: `0.5.1`
- Version code: `10`
- Project / support URL: `https://beacontools.cc/local-flight/mobile`
- Privacy Policy URL: `https://beacontools.cc/privacy`
- Recommended review path: choose **Standalone** on first launch so the app can be tested without a desktop or Raspberry Pi server.
- Standalone setup needs an airport, a mobile diagnostics choice, and relay activation through `https://relay.beacontools.cc`. It does not open LAN WebSockets, Matrix controls, scheduler controls, or server-control panels.
- Companion is also included. It pairs with a Local Flight desktop/Pi server on the same local network by QR code or manual URL.
- Remote Companion is part of Companion mode. After explicit host-side grant pairing, Companion uses LAN first and can fall back to encrypted relay routing when the phone is away from Wi-Fi and the host is online.

## Permission And Network Rationale

- Camera: used only to scan Local Flight pairing QR codes. Manual URL entry remains available if camera access is denied.
- Internet: used for Standalone relay requests, Remote Companion fallback, and Companion requests to the user's own Local Flight server.
- Local cleartext HTTP: the Android manifest permits cleartext transport because Companion must support user-owned hosts at `http://localflight.local:8000` and arbitrary private LAN IP addresses that cannot be enumerated in a domain allowlist. Remote Companion, Standalone, support, and Beacon Tools relay traffic use HTTPS.
- Vibration: used only for small touch/haptic feedback where supported.
- The release build should not request microphone, storage, or overlay permissions.

## Play Data Safety Summary

Play Console Data Safety answers should be conservative:

- Privacy Policy URL: `https://beacontools.cc/privacy`.
- Data collected: yes.
- Data sharing: complete the Play Console answer per data category and Google's current definition. App-functionality requests go to the user's own Local Flight server or the Beacon Tools relay; diagnostic/report data only leaves the app under the consent rules below. Do not use one blanket answer without matching the submitted console questionnaire.
- Data encrypted in transit: yes for Remote Companion and Standalone relay HTTPS; Companion LAN may use local HTTP on the user's private network by design.
- Identifiers: install-scoped mobile ID, companion ID, Remote Companion grant/install refs when enabled, and standalone relay install ID for pairing, rate limits, reports, and troubleshooting.
- Remote Companion privacy: encrypted request/response envelopes are routed through `https://relay.beacontools.cc` only after explicit pairing. The relay cannot read board data or commands and does not receive the AES grant secret.
- Diagnostics: crash reports and diagnostic context only when the user chooses automatic diagnostics or submits a manual report.
- App activity / usage: coarse relay quota/policy metadata, selected airport, app version, source mode, and refresh status used for app functionality and support.
- User content: manual report title/description if the user sends a report.
- Purchase history: optional product ID and minimal transaction-verification metadata, linked conservatively to an install-scoped identifier, used only for app functionality, duplicate prevention, and store/security compliance; not used for advertising or tracking.
- Not collected by Local Flight: precise location, contacts, photos/videos, payment-card information, advertising ID, or financial account details. Google Play processes payment details. Local Flight receives only the purchase token/product evidence needed to verify an optional support purchase.

## Optional In-App Support

- Settings/Control includes three optional consumable support products: `cc.beacontools.localflight.support.small`, `.medium`, and `.large`.
- Every product unlocks nothing and creates no entitlement. The sheet states this before purchase and displays only Google Play-owned localized prices.
- Local Flight sends the purchase token to the Beacon Tools relay, which verifies it through the Google Play Developer API. The app consumes the product only after verification.
- The relay stores a keyed transaction hash, short reference, product ID, store environment, status, and timestamps. It does not retain the purchase token, payment-card data, or Google account identity.
- No external Buy Me a Coffee or other external purchase call-to-action appears in Play builds.

## Home-Screen Widget

- Version code `10` includes a resizable Android home-screen widget.
- The app writes a bounded snapshot to its private files directory. The widget reads that local file only; it does not make LAN, relay, provider, analytics, or advertising requests.
- The widget refresh action rereads local app data and does not trigger an external data fetch. Android's periodic widget update remains at 30 minutes.

## Safety Copy

Local Flight flight, weather, radar, and surface data are informational display aids only. They are not for navigation, dispatch, operational control, or safety decisions. Keep this message visible in onboarding/help and Play Store metadata.

## Manual Review Checklist

- Fresh install: Standalone setup completes without LAN server hardware.
- Fresh install: Companion setup still works by manual URL if camera access is denied.
- Remote Companion: pair on LAN, block LAN, confirm `REMOTE` state loads Board/Radar/History/Control, then revoke and confirm remote access stops.
- Bad QR/fingerprint mismatch: app rejects the wrong LAN server.
- Offline relay: Standalone shows a useful retry/error state.
- Purchase surface: open Standalone **Settings** or Companion **Control**, choose **Support Local Flight**, confirm all three localized products load, complete one license-tester purchase, and confirm the thank-you state. Interrupt relay access after store approval to verify the unfinished transaction is retained and safely retried before consumption.
- Widget: add and resize the Local Flight widget, confirm compact/medium layouts, empty/stale states, app tap-through, and local refresh behavior.
- Bottom navigation: Standalone shows Board/Radar/History/Settings; Companion shows Board/Radar/History/Control.
- Accessibility: only claim Play listing accessibility support after real Android common-task testing with TalkBack, font scaling, contrast, and reduced animation.
