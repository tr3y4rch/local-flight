# Local Flight Mobile Google Play Review Notes

This file is the working checklist for the `0.6.0` Play internal-testing build. It is not legal advice; keep the final Play Console answers aligned with the exact submitted AAB.

## Reviewer Test Path

- App name: **Local Flight**
- Android package: `cc.beacontools.localflight`
- Version name: `0.6.0`
- Version code: `16`
- Project / support URL: `https://beacontools.cc/local-flight/mobile`
- Privacy Policy URL: `https://beacontools.cc/privacy`
- Recommended review path: choose **Use without a Local Flight host** on first launch so the app can be tested without a desktop, Linux server, or Raspberry Pi host. The app explains that this is Standalone mode after the choice.
- The Android app is free to download. Companion and VATSIM require no Relay Access purchase. Real-flight Standalone uses the one-time, non-consumable Beacon Relay Access product and has no subscription. First run keeps the existing four stages: Welcome, connection choice, pair or choose airport, then privacy and review. The final real-flight Standalone action is **Get or restore Relay Access & open Board**; only that explicit action queries or opens Google Play Billing and prepares this phone as the main device after server verification.
- Companion pairs with a Local Flight desktop, Linux server, or Pi host on the same local network by QR code or manual URL.
- Both modes use **Board**, **Radar**, **History**, and **More**. Host/display controls appear only for Companion.
- Remote Companion is part of Companion mode. After explicit host-side grant pairing, Companion uses the nearby host first and can fall back to encrypted relay routing when this device is away from the same Wi-Fi and the host is online.
- Companion’s final explicit action pairs the host without querying or purchasing the Relay Access product. VATSIM likewise uses no purchase or licensing endpoint. A store or relay outage never blocks LAN Companion or VATSIM. Remote Companion still requires Relay Access on its desktop host. Mobile never accepts or displays an LFRA key, and moving access always requires an explicit, integrity-protected transfer plus a named confirmation.
- Google Play Billing queries the non-consumable managed product `cc.beacontools.localflight.relay_access`. Only a `PURCHASED` purchase token can create or restore Relay Access; `PENDING` never grants access. Grant-based transfers use a request-bound Play Integrity Standard token. Purchase-token verification, acknowledgement, Integrity-token decryption, and refund/revocation reconciliation remain server-side.
- This internal-track build uses `https://relay-staging.beacontools.cc`; its Android verifier requires `test` evidence. The staging deployment accepts only the cross-platform `sandbox,test` set. The production profile uses `https://relay.beacontools.cc` and accepts only `production` evidence; the two deployments must not share a database.

## Permission And Network Rationale

- Camera: used only to scan Local Flight pairing QR codes. Manual URL entry remains available if camera access is denied.
- Internet: used for Standalone relay requests, Remote Companion fallback, and Companion requests to the user's own Local Flight host.
- Local cleartext HTTP: the Android manifest permits cleartext transport because Companion must support user-owned hosts at `http://localflight.local:8000` and arbitrary private LAN IP addresses that cannot be enumerated in a domain allowlist. Remote Companion, Standalone, support, and Beacon Tools relay traffic use HTTPS.
- Vibration: used only for small touch/haptic feedback where supported.
- `com.android.vending.BILLING` is used for the Relay Access non-consumable and the separate optional support products. The obsolete `com.android.vending.CHECK_LICENSE` permission is removed. The release build should not request microphone, storage, or overlay permissions.

## Play Data Safety Summary

Play Console Data Safety answers should be conservative:

- Privacy Policy URL: `https://beacontools.cc/privacy`.
- Data collected: yes.
- Data sharing: complete the Play Console answer per data category and Google's current definition. App-functionality requests go to the user's own Local Flight host or the Beacon Tools relay; diagnostic/report data only leaves the app under the consent rules below. Do not use one blanket answer without matching the submitted console questionnaire.
- Data encrypted in transit: yes for Remote Companion and Standalone relay HTTPS; Companion LAN may use local HTTP on the user's private network by design.
- Identifiers: install-scoped mobile ID, companion ID, Remote Companion grant/install refs when enabled, and standalone relay install ID for pairing, rate limits, reports, and troubleshooting.
- Remote Companion privacy: encrypted request/response envelopes are routed through the build-profile relay only after explicit pairing (`https://relay-staging.beacontools.cc` for this internal-track build). The relay cannot read board data or commands and does not receive the AES grant secret.
- Diagnostics: crash reports and diagnostic context only when the user chooses automatic diagnostics or submits a manual report.
- App activity / usage: coarse relay quota/policy metadata, selected airport, app version, source mode, and refresh status used for app functionality and support.
- User content: manual report title/description if the user sends a report.
- Purchase history: the Relay Access managed-product token plus optional support product metadata, linked conservatively to an install-scoped identifier. Beacon Relay retains one-way purchase/evidence references and license state for app functionality, duplicate prevention, recovery, refunds, and store/security compliance; not for advertising or tracking.
- Not collected by Local Flight: precise location, contacts, photos/videos, payment-card information, advertising ID, or financial account details. Google Play processes payment details. Local Flight receives only purchase-token/product evidence and encrypted Play Integrity tokens needed for verification.

## Google Play Billing And Relay Access

- The Android app requests a relay nonce and queries the Relay Access non-consumable through Google Play Billing. It sends the transient purchase token to Beacon Relay for verification with the Google Play Developer API. A website-transfer grant instead obtains a Play Integrity token whose request hash binds the relay nonce, install ID, and activation grant.
- One verified Relay managed-product purchase maps idempotently to one portable `beacon_relay_lifetime_v1` license for one main device: a Local Flight desktop using Beacon Relay or a phone in Standalone mode.
- Real-flight Standalone activates the phone only after the final explicit verification action. If access is already active elsewhere, the app names that main device and waits for **Move Relay Access here**. The backend prepares a short-lived credential while the old main device remains active; the app stores it securely and commits the move only after that write succeeds.
- Email is not collected during ordinary mobile use. It is requested only in post-setup protection, key delivery, recovery, or transfer. After the address is confirmed, Beacon Tools displays and emails the portable desktop-compatible key once. There is no password, Beacon profile, or general-purpose account.
- Switching from real-flight Standalone to Companion pairs the host first and then releases the phone. Switching to VATSIM also releases real-flight access. If the relay is temporarily unreachable, the encrypted device credential is retained only to retry that release; LAN Companion and VATSIM can continue and show `release_pending` without allowing direct Relay runtime use.
- The app contains no Stripe checkout, price, web-purchase prompt, or direct link to the Relay Access sales page.
- The existing three consumable support products remain unrelated to Relay Access and unlock nothing.
- Before submission, change the Play listing to a free app, create and activate the Relay managed product, configure its one-time price, link the correct staging/production Cloud projects to Play Integrity, and install the Cloud project number in each EAS environment. Existing paid-download customers need an explicit migration/grant policy because Google Play Billing cannot infer historical ownership of the paid APK.

## Optional In-App Support

- More includes three optional consumable support products: `cc.beacontools.localflight.support.small`, `.medium`, and `.large`.
- Every product unlocks nothing and creates no entitlement. The sheet states this before purchase and displays only Google Play-owned localized prices.
- Local Flight sends the purchase token to the Beacon Tools relay, which verifies it through the Google Play Developer API. The app consumes the product only after verification.
- The relay stores a keyed transaction hash, short reference, product ID, store environment, status, and timestamps. It does not retain the purchase token, payment-card data, or Google account identity.
- No external Buy Me a Coffee or other external purchase call-to-action appears in Play builds.

## Home-Screen Widget

- Version code `16` includes a resizable Android home-screen widget with compact one-row and wide up-to-three-row layouts.
- The app writes a bounded snapshot to its private files directory. The widget reads that local file only; it does not make LAN, relay, provider, analytics, or advertising requests.
- The widget refresh action rereads local app data and does not trigger an external data fetch. Android's periodic widget update remains at 30 minutes.

## Safety Copy

Local Flight flight, weather, radar, and surface data are informational display aids only. They are not for navigation, dispatch, operational control, or safety decisions. Keep this message visible in onboarding/help and Play Store metadata.

## Manual Review Checklist

- Fresh install: Companion and VATSIM complete without buying Relay Access; real-flight Standalone completes without LAN server hardware after a license-tester purchase or restore of the Relay Access managed product.
- Fresh install: Companion setup still works by manual URL if camera access is denied.
- Remote Companion: pair on the same Wi-Fi, block the nearby route, confirm **Connected remotely** loads Board/Radar/History/More, then revoke and confirm remote access stops.
- Bad QR/fingerprint mismatch: app rejects the wrong LAN server.
- Offline relay: Standalone shows a useful retry/error state.
- Relay Access: finish Standalone once, open **More → Relay Access**, and confirm cached purchase source, masked key reference, protection state, and this phone as the current main device are shown without contacting Google Play or revealing a raw key.
- License delivery: from Companion, request optional email protection, confirm the link, and verify the same `LFRA-…` key is delivered for desktop activation while Mobile never displays or accepts it.
- Main-device move: start from a holder-issued `localflight://relay-access#grant=…` link, confirm Play Integrity authenticates the request-bound transfer without another Google purchase, and verify the old credential remains active until the new credential is securely stored and committed after **Move Relay Access here**.
- Store outcomes: exercise owned, not-owned, pending, cancelled, refunded/revoked, unavailable product, timeout, missing/outdated Play client, reinstall, second-device restore, durable acknowledgement retry, RTDN replay, cancellation/refund reconciliation, and a voided purchase. Exercise valid, malformed, mismatched-request-hash, unlicensed-app, and failed-device Play Integrity verdicts for grant transfers. Real-flight Standalone must remain on Review for failures; Companion and VATSIM remain usable without purchase.
- Mode switch: change Standalone to Companion online and offline; verify the online release is immediate and the offline release remains visibly pending while LAN Companion stays usable.
- Environment isolation: on physical devices, confirm an authorized internal-track tester sends test proof only to the staging relay and that the production relay/database rejects it.
- Release manifest: build the final AAB with `LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER` set and run `npm run android-manifest:contract`; the merged release manifest must contain `com.android.vending.BILLING`, the product/project metadata, no `CHECK_LICENSE`, and no microphone, legacy external-storage, or overlay permission.
- Purchase surface: open **More → Advanced diagnostics**, choose **Support Local Flight**, confirm all three localized products load, complete one license-tester purchase, and confirm the thank-you state. Interrupt relay access after store approval to verify the unfinished transaction is retained and safely retried before consumption.
- Widget: add and resize the Local Flight widget, confirm compact/medium layouts, empty/stale states, app tap-through, and local refresh behavior.
- Navigation: both modes show Board/Radar/History/More. Compact widths use bottom tabs; tablets and foldables use an adaptive rail. Display is entered explicitly and always has an exit control.
- Accessibility: only claim Play listing accessibility support after real Android common-task testing with TalkBack, font scaling, contrast, and reduced animation.
