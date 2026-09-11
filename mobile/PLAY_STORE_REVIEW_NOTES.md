# Google Play Review Notes

This is the working checklist for the Local Flight `0.7.1` internal-testing/review candidate. It must stay aligned with the exact submitted AAB and Play Console configuration.

## Build

- Package: `cc.beacontools.localflight`
- Version name: `0.7.1`
- Version code: `18`
- Distribution: free download
- Relay Access product: annual auto-renewing subscription `cc.beacontools.localflight.relay_access.annual`
- Optional support products: three separate consumables that unlock nothing

## What Reviewers Can Use For Free

- **Companion** connects to a Local Flight desktop, Linux server, or Raspberry Pi host. LAN is preferred. Explicitly paired Remote Companion uses end-to-end encrypted relay routing while that host remains online.
- **VATSIM Standalone** uses sanitized virtual-flight data without a Relay Access subscription.
- Companion and VATSIM do not query or purchase Relay Access.
- Shared real-aircraft radar is included in Relay Access, on a licensed monthly allowance. Companion can follow its host's appropriately licensed BYOK radar; Standalone VATSIM Radar remains available without Relay Access.

## Annual Relay Access

- Real-flight Standalone schedules require active annual Relay Access, an existing portable license moved to the phone, or preserved founder/legacy access.
- The app first restores an existing annual or eligible founder entitlement. It opens Google Play Billing only after the user explicitly chooses to get Relay Access.
- The relay verifies the subscription with `purchases.subscriptionsv2.get`, checks the expected package, product, purchase state, subscription lineage, period, grace/hold state, and acknowledgement state, then acknowledges only a verified purchased subscription.
- Authenticated RTDN and provider reconciliation update renewal, cancellation, grace, account hold, expiry, refund, and revocation.
- `PENDING`, cancelled-before-purchase, unverified, expired, refunded, or revoked purchases do not create active access.
- Cancellation keeps access through Google's confirmed paid period. Authoritative grace is honored only until Google's reported boundary.
- The phone stores only its revocable device credential and safe license summary. It does not expose a raw `LFRA-...` key in the app.
- One entitlement operates one main device: either real-flight Standalone on one phone or one desktop/Pi host. Companion phones do not consume another place. A move names the active device, prepares the new credential, stores it securely, and revokes the old credential only after commit.
- Earlier verified ownership of the legacy Android non-consumable can restore permanent legacy access. It is not converted into a subscription.
- Email is optional until a mobile holder chooses portable-key export, recovery, or transfer. Email protection uses a confirmation link and no Beacon account/password.
- The app contains no Stripe checkout, external payment link, or hardcoded Google Play subscription price. Google Play owns localized price display and purchase confirmation.

## Optional Support

- `cc.beacontools.localflight.support.small`, `.medium`, and `.large` are consumable tips.
- They unlock no feature and never create, extend, or restore Relay Access.
- Purchase buttons remain unavailable until all products and server verification are ready. Store-approved but unfinished purchases are retried and consumed only after verification.

## Data Safety And Permissions

- `com.android.vending.BILLING` is used for the annual subscription and optional support consumables. `com.android.vending.CHECK_LICENSE` is not requested.
- Camera access is optional and used only for QR pairing. Manual LAN entry remains available.
- Cleartext LAN HTTP is permitted only because Companion must reach user-owned private-LAN hosts such as `http://localflight.local:8000`; relay and Remote Companion traffic use HTTPS.
- No advertising identifier, advertising SDK, cross-app tracking, contacts, microphone, external storage, overlay, precise location, or payment-card details are used.
- Standalone movement history remains on-device. The widget reads only the bounded app snapshot and makes no network requests itself.
- Raw purchase tokens and Play Integrity payloads are processed transiently. The relay retains keyed references and encrypted reconciliation material only where required; it does not log raw tokens, card data, Google Account identity, or plaintext email.

## Review Walkthrough

1. Complete Companion or VATSIM setup and confirm no purchase sheet appears.
2. Choose real-flight Standalone, use **Get or restore Relay Access**, and verify the annual Play product and localized price appear.
3. Test purchase, pending payment, acknowledgement, restore after reinstall, cancellation through period end, grace, account hold, expiry, refund/revocation, RTDN replay, and repeated verification.
4. Restore an eligible legacy non-consumable owner and confirm no annual subscription is created.
5. Confirm real-flight Standalone shows schedule boards and shared real-aircraft Radar; VATSIM Radar remains usable without Relay Access.
6. Move the main device and confirm the former credential stays active until the new credential is securely stored and committed.
7. Test an email outage: verified access must remain durable while delivery reports `pending` or `needs_attention` and offers resend/recovery.
8. Test all three support consumables independently and confirm they change no entitlement or feature.
9. Test phone, tablet, and foldable layouts, TalkBack, font scaling, reduced motion, and widget resizing.

Local Flight is an informational display aid. It is not for navigation, dispatch, operational control, flight planning, professional aviation work, or safety decisions.
