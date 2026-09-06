# Local Flight Mobile App Store / TestFlight Review Notes

This file is the working checklist for the `0.6.0` TestFlight/review build. It is not legal advice; keep the final App Store Connect answers aligned with the exact submitted build.

Customer-facing English (U.S.) listing copy is maintained in
[`store/ios/en-US/`](store/ios/en-US/). The checked metadata pack contains the
name, subtitle, promotional text, keywords, full description, and public URLs.
Run `npm run appstore:contract` before copying it into App Store Connect.

## Reviewer Test Path

- App name: **Local Flight**
- Bundle identifier: `cc.beacontools.localflight`
- Version: `0.6.0`
- Build number: `13`
- Minimum iOS version: `16.0` (`AppTransaction` ownership proof is required for the included Relay license)
- Marketing URL: `https://beacontools.cc/local-flight/mobile`
- Support URL: `https://beacontools.cc/support`
- Privacy Policy URL: `https://beacontools.cc/privacy`
- Recommended review path: choose **Use without a Local Flight host** on first launch so the app can be tested without a desktop, Linux server, or Raspberry Pi host. The app explains that this is Standalone mode after the choice.
- The app is a paid download and includes Beacon Relay Access with no subscription or extra purchase. First run keeps the existing four stages: Welcome, connection choice, pair or choose airport, then privacy and review. For real airline data, the final Standalone action is **Verify App Store purchase & open Board**; only that explicit action calls `AppTransaction.refresh()` and prepares activation on this phone. VATSIM works without Relay activation and does not refresh AppTransaction.
- Standalone daily surfaces are **Board**, **Radar**, **History**, and **More**.
- Companion is also included. It pairs with a Local Flight desktop, Linux server, or Pi host over the same local network by QR code or manual URL.
- Remote Companion is part of Companion mode. After explicit host-side grant pairing, Companion uses the nearby host first and can fall back to encrypted relay routing when this device is away from the same Wi-Fi and the host is online.
- Companion’s final explicit action pairs the host first and then makes one paid-app verification attempt. A successful check creates or finds the included license and leaves it available for another main device. Cancellation or a store/relay outage never blocks LAN or Remote Companion; More shows an explicit retry. Remote Companion still requires Relay Access on its desktop host. The iOS app never accepts or displays an LFRA key, and moving access always requires fresh AppTransaction verification plus a named confirmation.
- This TestFlight build uses `https://relay-staging.beacontools.cc`; its iOS verifier requires `sandbox` evidence. The staging deployment accepts only the cross-platform `sandbox,test` set. The production profile uses `https://relay.beacontools.cc` and accepts only `production` evidence; the two deployments must not share a database.
- Companion daily surfaces are **Board**, **Radar**, **History**, and **More**. Host/display controls and diagnostics are progressively disclosed inside More.

## Permission Rationale

- Camera: used only to scan Local Flight pairing QR codes. Manual URL entry remains available if camera access is denied.
- Local Network: used only by Companion to connect to the user's own Local Flight host on the same Wi-Fi and to complete trusted pairing before optional Remote Companion.
- App Transport Security: the app enables cleartext transport because a user-owned Local Flight host can be reached by a private IPv4 address or mDNS name that cannot be enumerated in an ATS domain list. This is used for user-entered/self-scanned LAN Companion URLs. Remote Companion, Standalone, support, and Beacon Tools relay traffic use HTTPS.

## Privacy Summary

App Store Connect privacy answers should be conservative:

- Privacy Policy URL: `https://beacontools.cc/privacy`.
- Marketing/support URL: `https://beacontools.cc/local-flight/mobile`.
- Data collected: yes.
- Data linked to the user: yes, conservatively, because install-scoped IDs are sent with app-functionality requests.
- Tracking: no advertising, no data brokers, and no cross-app/site tracking.
- Identifiers: install-scoped mobile ID, companion ID, Remote Companion grant/install refs when enabled, and standalone relay install ID for pairing, rate limits, reports, and troubleshooting.
- Remote Companion privacy: encrypted request/response envelopes are routed through the build-profile relay only after explicit pairing (`https://relay-staging.beacontools.cc` for this TestFlight build). The relay cannot read board data or commands and does not receive the AES grant secret.
- Diagnostics: crash reports and diagnostic context only when the user chooses automatic diagnostics or submits a manual report.
- Usage data: coarse relay quota/policy metadata, selected airport, app version, source mode, and refresh status used for app functionality and support.
- User content: manual report title/description if the user sends a report.
- Purchase history: a freshly refreshed, signed AppTransaction proof and StoreKit device-verification value for paid-app ownership, plus optional support product evidence. The device-verification ID is checked transiently and not retained. Beacon Relay retains one-way purchase/evidence references and license state, linked conservatively to an install-scoped identifier, for app functionality, duplicate prevention, recovery, refunds, and store/security compliance; not for tracking. This matches the bundled `NSPrivacyCollectedDataTypePurchaseHistory` declaration.
- Not collected by Local Flight: device location, contacts, photos/videos, payment-card information, advertising ID, or financial account details. Apple processes payment details. Local Flight receives only signed paid-app ownership evidence and the transaction/product evidence needed to verify an optional support purchase.

The bundled iOS privacy manifest declares required-reason APIs and conservative app-functionality data categories. Keep it aligned with the submitted App Store Connect privacy answers.

## Paid App And Relay Access

- The submitted app is paid. In response to an explicit setup, restore, protection, or transfer action, StoreKit refreshes `AppTransaction`; its signed proof and transient device-verification ID are sent to Beacon Relay. The relay checks signature, app identity, environment, signing freshness, and StoreKit's device-verification hash.
- One unique paid-app entitlement maps idempotently to one portable `beacon_relay_lifetime_v1` license for one main device: a Local Flight desktop using Beacon Relay or a phone using real-flight Standalone. A distinct verified Family Sharing identity receives its own license. An authoritative refund and later repurchase for the same Apple Account restores the existing license because Apple keeps its app-transaction identity stable; a signed `revocationDate` maps to revoked access rather than being guessed to mean a refund.
- Real-flight Standalone activates the phone only after the final explicit verification action. If access is already active elsewhere, the app names that main device and waits for **Move Relay Access here**. The relay prepares a short-lived credential while the old main device stays active; the app stores it in SecureStore and commits the move only after storage succeeds.
- Email is not collected during ordinary mobile use. It is requested only in post-setup protection, key delivery, recovery, or transfer. After the address is confirmed, Beacon Tools displays and emails the portable desktop-compatible key once. There is no password, Beacon profile, or general-purpose account.
- Switching from Standalone to Companion pairs the host first and then releases the phone. If the relay is temporarily unreachable, the encrypted device credential is retained only to retry that release; LAN Companion can continue and shows `release_pending` without allowing direct Relay runtime use.
- The app contains no Stripe checkout, price, web-purchase prompt, or direct link to the Relay Access sales page.
- The existing three consumable support products remain unrelated to Relay Access and unlock nothing.

## Optional In-App Support

- More includes three optional consumable support products: `cc.beacontools.localflight.support.small`, `.medium`, and `.large`.
- Every product unlocks nothing and creates no entitlement. The sheet states this before purchase and displays only App Store-owned localized prices.
- Local Flight sends the transaction ID to the Beacon Tools relay, which verifies it through Apple's App Store Server API. The app finishes the consumable only after verification.
- The relay stores a keyed transaction hash, short reference, product ID, store environment, status, and timestamps. It does not retain the signed transaction, payment-card data, or Apple account identity.
- No external Buy Me a Coffee or other external purchase call-to-action appears in App Store builds.
- External project website, source, and release-note links are informational/support links only, not purchase links. The app should route users to `https://beacontools.cc/local-flight/mobile` first; GitHub remains available from that public project page for source/issues.

## Widgets And Live Activity

- Build `13` includes small and medium iOS home-screen widgets and a capability-gated pinned-flight Live Activity through bundle ID `cc.beacontools.localflight.widget` and App Group `group.cc.beacontools.localflight`.
- The app writes a bounded local board snapshot into the shared App Group. The widget does not make LAN, relay, provider, analytics, or advertising requests.
- The small widget shows the pinned flight or a clear open-app prompt. The medium widget shows a bounded airport-board glance with stale labeling.
- On supported iPhones, **Pin & show on Lock Screen** explicitly starts a best-effort local Live Activity for the selected flight. It reads the same snapshot, adds no push notification infrastructure, keeps missing data stale instead of switching flights, and ends on unpin, dismissal, or two hours after a terminal state. Unsupported devices retain ordinary pinning and widgets.

## Safety Copy

Local Flight flight, weather, radar, and surface data are informational display aids only. They are not for navigation, dispatch, operational control, or safety decisions. Keep this message visible in onboarding/help and App Store metadata.

## Manual Review Checklist

- Fresh install: Standalone setup completes without LAN server hardware.
- Fresh install: Companion setup still works by manual URL if camera access is denied.
- Remote Companion: pair on the same Wi-Fi, block the nearby route, confirm **Connected remotely** loads Board/Radar/History/More, then revoke and confirm remote access stops.
- Denied local network: app explains LAN pairing cannot reach the server and Standalone remains usable.
- Bad QR/fingerprint mismatch: app rejects the wrong LAN server.
- Offline relay: Standalone shows a useful retry/error state.
- Relay Access: finish Standalone once, open **More → Relay Access**, and confirm cached purchase source, masked key reference, protection state, and this phone as the current main device are shown without refreshing StoreKit or revealing a raw key.
- License delivery: from Companion, request optional email protection, confirm the link, and verify the same `LFRA-…` key is delivered for desktop activation while the iOS app never displays or accepts it.
- Main-device move: start from a holder-issued `localflight://relay-access#grant=…` link, confirm paid-app ownership is rechecked, and verify the old credential stays active until the new credential is securely stored and committed after **Move Relay Access here**.
- Store outcomes: cancel the system prompt, test offline StoreKit, provide an unverified JWS, exercise a distinct Family Sharing identity and signed `revocationDate`, then reconcile a refund and repurchase for the same app-transaction identity. Real-flight Standalone must remain on Review with an inline retry for non-terminal failures, while Companion must finish pairing and record `verification_needed`.
- VATSIM: open Standalone with VATSIM selected and confirm no AppTransaction refresh, Relay credential, or access API call is required.
- Mode switch: change Standalone to Companion online and offline; verify the online release is immediate and the offline release remains visibly pending while LAN Companion stays usable.
- Environment isolation: on physical devices, confirm TestFlight sends sandbox proof only to the staging relay and that the production relay/database rejects it.
- Archive inspection: confirm `PrivacyInfo.xcprivacy` belongs to the actual Local Flight application target, appears in Copy Bundle Resources, and is present inside the archived IPA alongside the StoreKit proof module.
- Purchase surface: open **More → Advanced diagnostics**, choose **Support Local Flight**, confirm all three localized products load, complete one sandbox purchase, and confirm the thank-you state. Interrupt relay access after store approval to verify the unfinished transaction is retained and safely retried before consumption.
- Widget: add small and medium Local Flight widgets, confirm empty/stale states, pin a flight in the app, and confirm the widget updates without requesting new permissions.
- Live Activity: on a supported iPhone, choose **Pin & show on Lock Screen**, confirm the selected flight appears and becomes stale rather than switching; verify ordinary pinning on an unsupported device.
- Navigation: both modes show Board/Radar/History/More. Compact widths use bottom tabs; iPad and compatible Apple-silicon Mac windows use the adaptive rail. Display is entered explicitly and always has an exit control.
- Accessibility labels: only claim App Store Accessibility Nutrition Labels after real common-task testing.
