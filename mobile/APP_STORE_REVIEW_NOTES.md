# Local Flight Mobile App Store / TestFlight Review Notes

This file is the working checklist for the current iOS TestFlight / App Store candidate. It is not legal advice; keep the final App Store Connect answers aligned with the exact submitted build.

## Reviewer Test Path

- App name: **Local Flight**
- Bundle identifier: `cc.beacontools.localflight`
- Widget extension identifier: `cc.beacontools.localflight.widget`
- App Group: `group.cc.beacontools.localflight`
- Version: `0.2.8`
- Build number: `1`
- Project / support URL: `https://beacontools.cc/local-flight/mobile`
- Privacy Policy URL: `https://beacontools.cc/privacy`
- Recommended review path: choose **Standalone** on first launch so the app can be tested without a desktop or Raspberry Pi server.
- Standalone setup needs an airport, a mobile diagnostics choice, and relay activation through `https://relay.beacontools.cc`. It does not open LAN WebSockets, Matrix controls, scheduler controls, or server-control panels.
- Standalone daily surfaces are **Board**, **Radar**, **History**, and **Settings**.
- LAN Companion is also included. It pairs with a Local Flight desktop/Pi server over the same local network by QR code or manual URL.
- LAN Companion daily surfaces are **Board**, **Radar**, **History**, and **Control**. Help, reports, pairing, widgets, and support live inside Control.
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

## Permission Rationale

- Camera: used only to scan Local Flight pairing QR codes. Manual URL entry remains available if camera access is denied.
- Local Network: used only by LAN Companion to connect to the user's own Local Flight server on Wi-Fi/LAN.
- App Transport Security: local HTTP is allowed for LAN pairing with self-hosted desktop/Pi servers. Standalone relay traffic should use HTTPS.
- App Groups: used only to share the bounded widget snapshot between the app and the Local Flight widget extension.

## Privacy Summary

App Store Connect privacy answers should be conservative:

- Privacy Policy URL: `https://beacontools.cc/privacy`.
- Marketing/support URL: `https://beacontools.cc/local-flight/mobile`.
- Data collected: yes.
- Data linked to the user: yes, conservatively, because install-scoped IDs are sent with app-functionality requests.
- Tracking: no advertising, no data brokers, and no cross-app/site tracking.
- Identifiers: install-scoped mobile ID, LAN companion ID, and standalone relay install ID for pairing, rate limits, reports, and troubleshooting.
- Diagnostics: crash reports and diagnostic context only when the user chooses automatic diagnostics or submits a manual report.
- Usage data: coarse relay quota/policy metadata, selected airport, app version, source mode, and refresh status used for app functionality and support.
- User content: manual report title/description if the user sends a report.
- Not collected for this build: device location, contacts, photos/videos, financial information, payment information, advertising ID, or purchase history.

The bundled iOS privacy manifest declares required-reason APIs and conservative app-functionality data categories. Keep it aligned with the submitted App Store Connect privacy answers.

## Support / Payments

- The app includes an optional **Support Local Flight** tip sheet. The sheet is informational in this submitted build and keeps Local Flight fully usable without payment.
- The support tiers use stable App Store product IDs in code: `cc.beacontools.localflight.tip.2`, `cc.beacontools.localflight.tip.5`, `cc.beacontools.localflight.tip.10`, and `cc.beacontools.localflight.tip.20`.
- This submitted build does **not** enable a native StoreKit purchase adapter and does **not** complete App Store Server API verification on the relay, so it cannot charge. Unavailable tiers show App Store setup wording and return a no-charge message.
- No features are locked behind support.
- No external Buy Me a Coffee or other external purchase call-to-action should appear in App Store builds.
- External project website, source, and release-note links are informational/support links only, not purchase links. The app should route users to `https://beacontools.cc/local-flight/mobile` first; GitHub remains available from that public project page for source/issues.
- Before enabling real tips, create/approve the App Store in-app purchase products, wire the native StoreKit adapter, configure relay App Store Server API verification, run sandbox/TestFlight purchase tests, and update these notes plus App Store Connect metadata.

## Safety Copy

Local Flight flight, weather, radar, and surface data are informational display aids only. They are not for navigation, dispatch, operational control, or safety decisions. Keep this message visible in onboarding/help and App Store metadata.

## Manual Review Checklist

- Fresh install: Standalone setup completes without LAN server hardware.
- Fresh install: LAN Companion setup still works by manual URL if camera access is denied.
- Denied local network: app explains LAN pairing cannot reach the server and Standalone remains usable.
- Bad QR/fingerprint mismatch: app rejects the wrong LAN server.
- Offline relay: Standalone shows a useful retry/error state.
- Support sheet: shows App Store setup status for each tier and cannot charge in this build.
- Widgets: small widget is pinned-flight-only; medium widget shows pinned plus bounded board rows; stale/no-data states do not silently switch to unrelated flights.
- Bottom navigation: Standalone shows Board/Radar/History/Settings; LAN Companion shows Board/Radar/History/Control.
- Accessibility labels: only claim App Store Accessibility Nutrition Labels after real common-task testing.
