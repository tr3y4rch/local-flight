# Local Flight Mobile Google Play Review Notes

This file is the working checklist for the current Android internal / Play release candidate. It is not legal advice; keep the final Play Console answers aligned with the exact submitted AAB.

## Reviewer Test Path

- App name: **Local Flight**
- Android package: `cc.beacontools.localflight`
- Version name: `0.2.8`
- Version code: `1`
- Project / support URL: `https://beacontools.cc/local-flight/mobile`
- Privacy Policy URL: `https://beacontools.cc/privacy`
- Recommended review path: choose **Standalone** on first launch so the app can be tested without a desktop or Raspberry Pi server.
- Standalone setup needs an airport, a mobile diagnostics choice, and relay activation through `https://relay.beacontools.cc`. It does not open LAN WebSockets, Matrix controls, scheduler controls, or server-control panels.
- Standalone daily surfaces are **Board**, **Radar**, **History**, and **Settings**.
- LAN Mobile is also included. It pairs with a Local Flight desktop/Pi server on the same local network by QR code or manual URL.
- LAN Mobile daily surfaces are **Board**, **Radar**, **History**, and **Control**. Help, reports, pairing, widgets, and support live inside Control.

## Google Play Store Listing Copy

### Short Description

Personal airport board with radar, history, and companion mode.

### Full Description

Local Flight turns your Android phone into a calm personal airport board.

Choose Standalone mode to follow departures, arrivals, radar, weather, and recent movement history for a selected airport through the Beacon Tools relay. No desktop or Raspberry Pi server is required.

Already run Local Flight at home? Choose LAN Mobile and pair with your desktop or Raspberry Pi server on the same Wi-Fi network. The phone becomes a companion board with radar, history, Control, reports, and safe Matrix board settings when your host supports them.

What you can do:

- View a passenger-style FIDS board for departures and arrivals.
- Pin one flight for quick status checks.
- See nearby radar traffic with mobile-friendly range controls.
- Review recent airport movement history.
- Pair by QR code or manual LAN URL when using your own server.
- Send manual reports only when you choose to.

Local Flight is built around privacy-aware operation. Standalone mode uses the Beacon Tools relay for app functionality. LAN Mobile talks to your own Local Flight server on your local network. There are no ads and no cross-app tracking.

Important: Local Flight is an informational display aid only. Flight, radar, weather, and airport data can be delayed, incomplete, cached, wrong, or unavailable. Do not use Local Flight for navigation, dispatch, operational control, flight planning, professional aviation work, or safety decisions.

### Internal Test Release Notes

Initial Android internal test build for Local Flight Mobile. Includes Standalone mode, LAN Mobile pairing, Board, Radar, History, Settings/Control, manual reports, diagnostics choices, and a non-charging support sheet.

## Permission And Network Rationale

- Camera: used only to scan Local Flight pairing QR codes. Manual URL entry remains available if camera access is denied.
- Internet: used for Standalone relay requests and LAN Mobile requests to the user's own Local Flight server.
- Local cleartext HTTP: LAN Mobile must support `http://localflight.local:8000` and private LAN IP addresses because self-hosted desktop/Pi installs do not ship public TLS certificates. Standalone relay traffic uses HTTPS.
- Vibration: used only for small touch/haptic feedback where supported.
- The release build should not request microphone, storage, or overlay permissions.

## Play Data Safety Summary

Play Console Data Safety answers should be conservative:

- Privacy Policy URL: `https://beacontools.cc/privacy`.
- Data collected: yes.
- Data shared: yes where app-functionality requests/reports are sent to the Beacon Tools relay or, in LAN Mobile mode, to the user's own Local Flight server.
- Data encrypted in transit: yes for Standalone relay HTTPS; LAN Mobile may use local HTTP on the user's private network by design.
- Identifiers: install-scoped mobile ID, LAN companion ID, and standalone relay install ID for pairing, rate limits, reports, and troubleshooting.
- Diagnostics: crash reports and diagnostic context only when the user chooses automatic diagnostics or submits a manual report.
- App activity / usage: coarse relay quota/policy metadata, selected airport, app version, source mode, and refresh status used for app functionality and support.
- User content: manual report title/description if the user sends a report.
- Not collected for this build: precise location, contacts, photos/videos, financial information, payment information, advertising ID, or purchase history.

## Support / Payments

- The app includes an optional **Support Local Flight** tip sheet. The sheet is informational in this submitted Android build and keeps Local Flight fully usable without payment.
- The visible support tiers mirror the stable store product IDs used by the shared mobile code: `cc.beacontools.localflight.tip.2`, `cc.beacontools.localflight.tip.5`, `cc.beacontools.localflight.tip.10`, and `cc.beacontools.localflight.tip.20`.
- This submitted Android build does **not** include a native Google Play Billing adapter and cannot charge. Unavailable tiers show Google Play setup wording and return a no-charge message.
- No features are locked behind support.
- No external Buy Me a Coffee or other external purchase call-to-action should appear in Play builds.
- Before enabling real Android tips, create/approve the Play in-app products, wire the native Google Play Billing adapter, configure relay purchase verification, run Play internal/sandbox purchase tests, and update these notes plus Play Console metadata.

## Safety Copy

Local Flight flight, weather, radar, and surface data are informational display aids only. They are not for navigation, dispatch, operational control, or safety decisions. Keep this message visible in onboarding/help and Play Store metadata.

## Manual Review Checklist

- Fresh install: Standalone setup completes without LAN server hardware.
- Fresh install: LAN Mobile setup still works by manual URL if camera access is denied.
- Bad QR/fingerprint mismatch: app rejects the wrong LAN server.
- Offline relay: Standalone shows a useful retry/error state.
- Support sheet: shows Google Play setup status for each tier and cannot charge in this build.
- Bottom navigation: Standalone shows Board/Radar/History/Settings; LAN Mobile shows Board/Radar/History/Control.
- Accessibility: only claim Play listing accessibility support after real Android common-task testing with TalkBack, font scaling, contrast, and reduced animation.
