# Local Flight Mobile App Store / TestFlight Review Notes

This file is the working checklist for the `0.5.1` TestFlight/review build. It is not legal advice; keep the final App Store Connect answers aligned with the exact submitted build.

## Reviewer Test Path

- App name: **Local Flight**
- Bundle identifier: `cc.beacontools.localflight`
- Version: `0.5.1`
- Build number: `5`
- Project / support URL: `https://beacontools.cc/local-flight/mobile`
- Privacy Policy URL: `https://beacontools.cc/privacy`
- Recommended review path: choose **Standalone** on first launch so the app can be tested without a desktop or Raspberry Pi server.
- Standalone setup needs an airport, a mobile diagnostics choice, and relay activation through `https://relay.beacontools.cc`. It does not open LAN WebSockets, Matrix controls, scheduler controls, or server-control panels.
- Standalone daily surfaces are **Board**, **Radar**, **History**, and **Settings**.
- Companion is also included. It pairs with a Local Flight desktop/Pi server over the same local network by QR code or manual URL.
- Remote Companion is part of Companion mode. After explicit host-side grant pairing, Companion uses LAN first and can fall back to encrypted relay routing when the phone is away from Wi-Fi and the host is online.
- Companion daily surfaces are **Board**, **Radar**, **History**, and **Control**. Help & Reports is inside Control.

## Permission Rationale

- Camera: used only to scan Local Flight pairing QR codes. Manual URL entry remains available if camera access is denied.
- Local Network: used only by Companion to connect to the user's own Local Flight server on Wi-Fi/LAN and to complete trusted pairing before optional Remote Companion.
- App Transport Security: the app enables cleartext transport because a user-owned Local Flight host can be reached by a private IPv4 address or mDNS name that cannot be enumerated in an ATS domain list. This is used for user-entered/self-scanned LAN Companion URLs. Remote Companion, Standalone, support, and Beacon Tools relay traffic use HTTPS.

## Privacy Summary

App Store Connect privacy answers should be conservative:

- Privacy Policy URL: `https://beacontools.cc/privacy`.
- Marketing/support URL: `https://beacontools.cc/local-flight/mobile`.
- Data collected: yes.
- Data linked to the user: yes, conservatively, because install-scoped IDs are sent with app-functionality requests.
- Tracking: no advertising, no data brokers, and no cross-app/site tracking.
- Identifiers: install-scoped mobile ID, companion ID, Remote Companion grant/install refs when enabled, and standalone relay install ID for pairing, rate limits, reports, and troubleshooting.
- Remote Companion privacy: encrypted request/response envelopes are routed through `https://relay.beacontools.cc` only after explicit pairing. The relay cannot read board data or commands and does not receive the AES grant secret.
- Diagnostics: crash reports and diagnostic context only when the user chooses automatic diagnostics or submits a manual report.
- Usage data: coarse relay quota/policy metadata, selected airport, app version, source mode, and refresh status used for app functionality and support.
- User content: manual report title/description if the user sends a report.
- Purchases: optional product ID and minimal transaction-verification metadata, linked conservatively to an install-scoped identifier, used only for app functionality, duplicate prevention, and store/security compliance; not used for tracking.
- Not collected by Local Flight: device location, contacts, photos/videos, payment-card information, advertising ID, or financial account details. Apple processes payment details. Local Flight receives only the transaction/product evidence needed to verify an optional support purchase.

The bundled iOS privacy manifest declares required-reason APIs and conservative app-functionality data categories. Keep it aligned with the submitted App Store Connect privacy answers.

## Optional In-App Support

- Settings/Control includes three optional consumable support products: `cc.beacontools.localflight.support.small`, `.medium`, and `.large`.
- Every product unlocks nothing and creates no entitlement. The sheet states this before purchase and displays only App Store-owned localized prices.
- Local Flight sends the transaction ID to the Beacon Tools relay, which verifies it through Apple's App Store Server API. The app finishes the consumable only after verification.
- The relay stores a keyed transaction hash, short reference, product ID, store environment, status, and timestamps. It does not retain the signed transaction, payment-card data, or Apple account identity.
- No external Buy Me a Coffee or other external purchase call-to-action appears in App Store builds.
- External project website, source, and release-note links are informational/support links only, not purchase links. The app should route users to `https://beacontools.cc/local-flight/mobile` first; GitHub remains available from that public project page for source/issues.

## Home-Screen Widget

- Build `5` includes small and medium iOS home-screen widgets through bundle ID `cc.beacontools.localflight.widget` and App Group `group.cc.beacontools.localflight`.
- The app writes a bounded local board snapshot into the shared App Group. The widget does not make LAN, relay, provider, analytics, or advertising requests.
- The small widget shows the pinned flight or a clear open-app prompt. The medium widget shows a bounded airport-board glance with stale labeling.
- Dynamic Island and Live Activities are not enabled in this build.

## Safety Copy

Local Flight flight, weather, radar, and surface data are informational display aids only. They are not for navigation, dispatch, operational control, or safety decisions. Keep this message visible in onboarding/help and App Store metadata.

## Manual Review Checklist

- Fresh install: Standalone setup completes without LAN server hardware.
- Fresh install: Companion setup still works by manual URL if camera access is denied.
- Remote Companion: pair on LAN, block LAN, confirm `REMOTE` state loads Board/Radar/History/Control, then revoke and confirm remote access stops.
- Denied local network: app explains LAN pairing cannot reach the server and Standalone remains usable.
- Bad QR/fingerprint mismatch: app rejects the wrong LAN server.
- Offline relay: Standalone shows a useful retry/error state.
- Purchase surface: open Standalone **Settings** or Companion **Control**, choose **Support Local Flight**, confirm all three localized products load, complete one sandbox purchase, and confirm the thank-you state. Interrupt relay access after store approval to verify the unfinished transaction is retained and safely retried before consumption.
- Widget: add small and medium Local Flight widgets, confirm empty/stale states, pin a flight in the app, and confirm the widget updates without requesting new permissions.
- Bottom navigation: Standalone shows Board/Radar/History/Settings; Companion shows Board/Radar/History/Control.
- Accessibility labels: only claim App Store Accessibility Nutrition Labels after real common-task testing.
