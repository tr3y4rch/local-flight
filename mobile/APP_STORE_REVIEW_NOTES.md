# Local Flight Mobile App Store / TestFlight Review Notes

This file is the working checklist for the first iOS proof-of-concept review. It is not legal advice; keep the final App Store Connect answers aligned with the exact submitted build.

## Reviewer Test Path

- App name: **Local Flight**
- Bundle identifier: `com.localflight.companion`
- Version: `0.2.7`
- Recommended review path: choose **Standalone** on first launch so the app can be tested without a desktop or Raspberry Pi server.
- Standalone setup needs an airport, a mobile diagnostics choice, and relay activation. It does not open LAN WebSockets, Matrix controls, scheduler controls, or server-control panels.
- Standalone daily surfaces are **Board**, **Radar**, **History**, and **Settings**.
- LAN Mobile is also included. It pairs with a Local Flight desktop/Pi server over the same local network by QR code or manual URL.
- LAN Mobile daily surfaces are **Board**, **Radar**, **History**, and **Control**. Help, troubleshooting, reports, and support are folded into Control so there is no separate Help tab in the current build.

## Permission Rationale

- Camera: used only to scan Local Flight pairing QR codes. Manual URL entry remains available if camera access is denied.
- Local Network: used only by LAN Mobile to connect to the user's own Local Flight server on Wi-Fi/LAN.
- App Transport Security: local HTTP is allowed for LAN pairing with self-hosted desktop/Pi servers. Standalone relay traffic should use HTTPS.

## Privacy Summary

App Store Connect privacy answers should be conservative:

- Privacy Policy URL: `https://github.com/tr3y4rch/local-flight/blob/main/PRIVACY.md` until a dedicated project website is available.
- Data collected: yes.
- Data linked to the user: yes, conservatively, because install-scoped IDs are sent with app-functionality requests.
- Tracking: no advertising, no data brokers, and no cross-app/site tracking.
- Identifiers: install-scoped mobile ID, LAN companion ID, and standalone relay install ID for pairing, rate limits, reports, and troubleshooting.
- Diagnostics: crash reports and diagnostic context only when the user chooses automatic diagnostics or submits a manual report.
- Usage data: coarse relay quota/policy metadata, selected airport, app version, source mode, and refresh status used for app functionality and support.
- User content: manual report title/description if the user sends a report.
- Not collected for this proof-of-concept build: device location, contacts, photos/videos, financial information, payment information, advertising ID, or purchase history.

The bundled iOS privacy manifest declares required-reason APIs and conservative app-functionality data categories. Keep it aligned with the submitted App Store Connect privacy answers.

## Support / Payments

- This proof-of-concept build keeps support tips as a stub-only in-app sheet.
- No features are locked behind support.
- No external Buy Me a Coffee or other external purchase call-to-action should appear in App Store builds.
- External GitHub/release links are informational/support links only, not purchase links.
- Real tips later require Apple in-app purchase products matching the stable product IDs, a native StoreKit adapter, relay App Store Server API verification, and TestFlight/sandbox verification.

## Safety Copy

Local Flight flight, weather, radar, and surface data are informational display aids only. They are not for navigation, dispatch, operational control, or safety decisions. Keep this message visible in onboarding/help and App Store metadata.

## Manual Review Checklist

- Fresh install: Standalone setup completes without LAN server hardware.
- Fresh install: LAN Mobile setup still works by manual URL if camera access is denied.
- Denied local network: app explains LAN pairing cannot reach the server and Standalone remains usable.
- Bad QR/fingerprint mismatch: app rejects the wrong LAN server.
- Offline relay: Standalone shows a useful retry/error state.
- Support sheet: shows coming soon / not active and cannot charge.
- Bottom navigation: Standalone shows Board/Radar/History/Settings; LAN Mobile shows Board/Radar/History/Control.
- Accessibility labels: only claim App Store Accessibility Nutrition Labels after real common-task testing.
