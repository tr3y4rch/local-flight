# Local Flight Mobile App Store / TestFlight Review Notes

This file is the working checklist for the first iOS proof-of-concept review. It is not legal advice; keep the final App Store Connect answers aligned with the exact submitted build.

## Reviewer Test Path

- App name: **Local Flight**
- Bundle identifier: `cc.beacontools.localflight`
- Version: `0.5.1`
- Build number: `1`
- Project / support URL: `https://beacontools.cc/local-flight/mobile`
- Privacy Policy URL: `https://beacontools.cc/privacy`
- Recommended review path: choose **Standalone** on first launch so the app can be tested without a desktop or Raspberry Pi server.
- Standalone setup needs an airport, a mobile diagnostics choice, and relay activation through `https://relay.beacontools.cc`. It does not open LAN WebSockets, Matrix controls, scheduler controls, or server-control panels.
- Standalone daily surfaces are **Board**, **Radar**, **History**, and **Settings**.
- Companion is also included. It pairs with a Local Flight desktop/Pi server over the same local network by QR code or manual URL.
- Remote Companion is part of Companion mode. After explicit host-side grant pairing, Companion uses LAN first and can fall back to encrypted relay routing when the phone is away from Wi-Fi and the host is online.
- Companion daily surfaces are **Board**, **Radar**, **History**, **Control**, and **Help**.

## Permission Rationale

- Camera: used only to scan Local Flight pairing QR codes. Manual URL entry remains available if camera access is denied.
- Local Network: used only by Companion to connect to the user's own Local Flight server on Wi-Fi/LAN and to complete trusted pairing before optional Remote Companion.
- App Transport Security: local HTTP is allowed for LAN pairing with self-hosted desktop/Pi servers. Remote Companion and Standalone relay traffic use HTTPS.

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
- Not collected for this proof-of-concept build: device location, contacts, photos/videos, financial information, payment information, advertising ID, or purchase history.

The bundled iOS privacy manifest declares required-reason APIs and conservative app-functionality data categories. Keep it aligned with the submitted App Store Connect privacy answers.

## Support / Payments

- This proof-of-concept build keeps support tips as a stub-only in-app sheet.
- No features are locked behind support.
- No external Buy Me a Coffee or other external purchase call-to-action should appear in App Store builds.
- External project website, source, and release-note links are informational/support links only, not purchase links. The app should route users to `https://beacontools.cc/local-flight/mobile` first; GitHub remains available from that public project page for source/issues.
- Real tips later require Apple in-app purchase products matching the stable product IDs, a native StoreKit adapter, relay App Store Server API verification, and TestFlight/sandbox verification.

## Safety Copy

Local Flight flight, weather, radar, and surface data are informational display aids only. They are not for navigation, dispatch, operational control, or safety decisions. Keep this message visible in onboarding/help and App Store metadata.

## Manual Review Checklist

- Fresh install: Standalone setup completes without LAN server hardware.
- Fresh install: Companion setup still works by manual URL if camera access is denied.
- Remote Companion: pair on LAN, block LAN, confirm `REMOTE` state loads Board/Radar/History/Control, then revoke and confirm remote access stops.
- Denied local network: app explains LAN pairing cannot reach the server and Standalone remains usable.
- Bad QR/fingerprint mismatch: app rejects the wrong LAN server.
- Offline relay: Standalone shows a useful retry/error state.
- Support sheet: shows coming soon / not active and cannot charge.
- Bottom navigation: Standalone shows Board/Radar/History/Settings; Companion shows Board/Radar/History/Control/Help.
- Accessibility labels: only claim App Store Accessibility Nutrition Labels after real common-task testing.
