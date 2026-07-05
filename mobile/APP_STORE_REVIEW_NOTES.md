# Local Flight Mobile App Store / TestFlight Review Notes

This file is the working checklist for the current iOS TestFlight / App Store candidate. It is not legal advice; keep the final App Store Connect answers aligned with the exact submitted build.

## Reviewer Test Path

- App name: **Local Flight**
- Bundle identifier: `cc.beacontools.localflight`
<<<<<<< HEAD
- Version: `0.5.1`
=======
- Widget extension identifier: `cc.beacontools.localflight.widget`
- App Group: `group.cc.beacontools.localflight`
- Version: `0.2.8`
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae
- Build number: `1`
- Project / support URL: `https://beacontools.cc/local-flight/mobile`
- Privacy Policy URL: `https://beacontools.cc/privacy`
- Recommended review path: choose **Standalone** on first launch so the app can be tested without a desktop or Raspberry Pi server.
- Standalone setup needs an airport, a mobile diagnostics choice, and relay activation through `https://relay.beacontools.cc`. It does not open LAN WebSockets, Matrix controls, scheduler controls, or server-control panels.
- Standalone daily surfaces are **Board**, **Radar**, **History**, and **Settings**.
<<<<<<< HEAD
- Companion is also included. It pairs with a Local Flight desktop/Pi server over the same local network by QR code or manual URL.
- Remote Companion is part of Companion mode. After explicit host-side grant pairing, Companion uses LAN first and can fall back to encrypted relay routing when the phone is away from Wi-Fi and the host is online.
- Companion daily surfaces are **Board**, **Radar**, **History**, **Control**, and **Help**.
=======
- LAN Companion is also included. It pairs with a Local Flight desktop/Pi server over the same local network by QR code or manual URL.
- LAN Companion daily surfaces are **Board**, **Radar**, **History**, and **Control**. Help, reports, pairing, and widgets live inside Control.
- The first TestFlight build includes a WidgetKit extension. Widgets read only the app-written pinned-flight/board snapshot through the App Group and do not fetch LAN, relay, or third-party data directly.

## App Store Listing Copy

### Subtitle

Airport board for your phone

### Promotional Text

Track your selected airport board, radar, and recent movement history in Standalone mode or pair with your own Local Flight server at home.

### Description

Local Flight turns your phone into a calm personal airport board.

Choose Standalone mode to follow departures, arrivals, radar, weather, and recent movement history for a selected airport through the Beacon Tools relay. No desktop or Raspberry Pi server is required.

Already run Local Flight at home? Choose LAN Companion and pair with your desktop or Raspberry Pi server on the same Wi-Fi network. The phone becomes a companion board with radar, history, Control, reports, widgets, and safe Matrix board settings when your host supports them.

What you can do:

- View a passenger-style FIDS board for departures and arrivals.
- Pin one flight for quick status checks.
- See nearby radar traffic with mobile-friendly range controls.
- Review recent airport movement history.
- Use iOS widgets for your pinned flight and a compact airport board glance.
- Pair by QR code or manual LAN URL when using your own server.
- Send manual reports only when you choose to.

Local Flight is built around privacy-aware operation. Standalone mode uses the Beacon Tools relay for app functionality. LAN Companion talks to your own Local Flight server on your local network. There are no ads and no cross-app tracking.

Important: Local Flight is an informational display aid only. Flight, radar, weather, and airport data can be delayed, incomplete, cached, wrong, or unavailable. Do not use Local Flight for navigation, dispatch, operational control, flight planning, professional aviation work, or safety decisions.

### Keywords Seed

airport, flight board, departures, arrivals, radar, FIDS, aviation, flight tracker, local flight
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae

## Permission Rationale

- Camera: used only to scan Local Flight pairing QR codes. Manual URL entry remains available if camera access is denied.
<<<<<<< HEAD
- Local Network: used only by Companion to connect to the user's own Local Flight server on Wi-Fi/LAN and to complete trusted pairing before optional Remote Companion.
- App Transport Security: local HTTP is allowed for LAN pairing with self-hosted desktop/Pi servers. Remote Companion and Standalone relay traffic use HTTPS.
=======
- Local Network: used only by LAN Companion to connect to the user's own Local Flight server on Wi-Fi/LAN.
- App Transport Security: local HTTP is allowed for LAN pairing with self-hosted desktop/Pi servers. Standalone relay traffic should use HTTPS.
- App Groups: used only to share the bounded widget snapshot between the app and the Local Flight widget extension.
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae

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
- Not collected for this build: device location, contacts, photos/videos, financial information, payment information, advertising ID, or purchase history.

The bundled iOS privacy manifest declares required-reason APIs and conservative app-functionality data categories. Keep it aligned with the submitted App Store Connect privacy answers.

## Payments

- This submitted build does **not** include tips, purchases, subscriptions, ads, paywalls, or locked features.
- No native StoreKit purchase adapter is enabled in the mobile app for this build.
- No external Buy Me a Coffee or other external purchase call-to-action should appear in App Store builds.
- External project website, source, and release-note links are informational/support links only, not purchase links. The app should route users to `https://beacontools.cc/local-flight/mobile` first; GitHub remains available from that public project page for source/issues.
- If optional tips are intentionally resumed later, create/approve App Store in-app purchase products, wire the native StoreKit adapter, configure relay App Store Server API verification, run sandbox/TestFlight purchase tests, and update these notes plus App Store Connect metadata before submission.

## Safety Copy

Local Flight flight, weather, radar, and surface data are informational display aids only. They are not for navigation, dispatch, operational control, or safety decisions. Keep this message visible in onboarding/help and App Store metadata.

## Manual Review Checklist

- Fresh install: Standalone setup completes without LAN server hardware.
- Fresh install: Companion setup still works by manual URL if camera access is denied.
- Remote Companion: pair on LAN, block LAN, confirm `REMOTE` state loads Board/Radar/History/Control, then revoke and confirm remote access stops.
- Denied local network: app explains LAN pairing cannot reach the server and Standalone remains usable.
- Bad QR/fingerprint mismatch: app rejects the wrong LAN server.
- Offline relay: Standalone shows a useful retry/error state.
<<<<<<< HEAD
- Support sheet: shows coming soon / not active and cannot charge.
- Bottom navigation: Standalone shows Board/Radar/History/Settings; Companion shows Board/Radar/History/Control/Help.
=======
- Support sheet: shows App Store setup status for each tier and cannot charge in this build.
- Widgets: small widget is pinned-flight-only; medium widget shows pinned plus bounded board rows; stale/no-data states do not silently switch to unrelated flights.
- Bottom navigation: Standalone shows Board/Radar/History/Settings; LAN Companion shows Board/Radar/History/Control.
>>>>>>> c3fc673e424e1621c0008f2365d2414c4f23e3ae
- Accessibility labels: only claim App Store Accessibility Nutrition Labels after real common-task testing.
