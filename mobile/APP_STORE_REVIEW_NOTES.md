# App Store Review Notes

This is the working checklist for the Local Flight `0.7.1` TestFlight/review candidate. It must stay aligned with the exact submitted archive and App Store Connect configuration.

## Build

- Bundle ID: `cc.beacontools.localflight`
- Version: `0.7.1`
- Build: `15`
- Minimum iOS/iPadOS: 16
- Distribution: free download
- Relay Access product: auto-renewable annual subscription `cc.beacontools.localflight.relay_access.annual`
- Optional support products: three separate consumables that unlock nothing

## What Reviewers Can Use For Free

- **Companion** connects to a Local Flight desktop, Linux server, or Raspberry Pi host. LAN is preferred. Explicitly paired Remote Companion uses end-to-end encrypted relay routing while that host remains online.
- **VATSIM Standalone** uses sanitized virtual-flight data without a Relay Access subscription.
- Companion and VATSIM do not start a subscription check or purchase.
- Shared real-aircraft radar is included in Relay Access, on a licensed monthly allowance. Companion can follow its host's appropriately licensed BYOK radar; Standalone VATSIM Radar remains available without Relay Access.

## Annual Relay Access

- Real-flight Standalone schedules require active annual Relay Access, an existing portable license moved to the phone, or preserved founder/legacy access.
- The app first restores an existing annual or eligible founder entitlement. It opens StoreKit purchase only after the user explicitly chooses to get Relay Access.
- The relay verifies StoreKit 2 signed transactions server-side against the expected app, product, environment, original transaction identity, period, grace, renewal, and revocation state.
- App Store Server Notifications V2 and server reconciliation update renewal, cancellation, billing retry/grace, expiry, refund, and revocation.
- A pending, cancelled-before-purchase, unverified, expired, refunded, or revoked transaction does not create active access.
- Cancellation keeps access through Apple's confirmed paid period. Authoritative grace is honored only until Apple's reported boundary.
- The phone stores only its revocable device credential and safe license summary. It does not expose a raw `LFRA-...` key in the app.
- One entitlement operates one main device: either real-flight Standalone on one phone or one desktop/Pi host. Companion phones do not consume another place. A move names the active device, prepares the new credential, stores it in SecureStore, and revokes the old credential only after commit.
- Earlier verified paid-iOS ownership can restore permanent founder access after signed AppTransaction verification. It is not converted into a subscription.
- Email is optional until a mobile holder chooses portable-key export, recovery, or transfer. Email protection uses a confirmation link and no Beacon account/password.
- The app contains no Stripe checkout, external payment link, or hardcoded App Store subscription price. StoreKit owns localized price display and purchase confirmation.

## Optional Support

- `cc.beacontools.localflight.support.small`, `.medium`, and `.large` are consumable tips.
- They unlock no feature and never create, extend, or restore Relay Access.
- Purchase buttons remain unavailable until all products and server verification are ready. Store-approved but unfinished transactions are recovered on launch and finished only after verification.

## Privacy And Permissions

- Camera access is optional and used only for QR pairing. Manual LAN entry remains available.
- Local-network access is used only for Companion connections to a user-owned Local Flight host.
- No advertising identifier, advertising SDK, cross-app tracking, contacts, microphone, photo library, or payment-card details are used.
- Standalone movement history remains on-device. Widgets and Live Activity read only the bounded snapshot written by the app and make no network requests themselves.
- Raw signed store evidence is processed transiently. The relay retains keyed references and encrypted reconciliation material only where required; it does not log raw transactions, card data, Apple Account identity, or plaintext email.

## Review Walkthrough

1. Complete Companion or VATSIM setup and confirm no purchase sheet appears.
2. Choose real-flight Standalone, use **Get or restore Relay Access**, and verify the annual StoreKit product and localized price appear.
3. Test purchase, restore after reinstall, cancellation through period end, grace/billing retry, expiry, refund/revocation, and repeated verification.
4. Restore an eligible paid-app founder owner and confirm no annual subscription is created.
5. Confirm real-flight Standalone shows schedule boards and shared real-aircraft Radar; VATSIM Radar remains usable without Relay Access.
6. Move the main device and confirm the former credential stays active until the new credential is securely stored and committed.
7. Test an email outage: verified access must remain durable while delivery reports `pending` or `needs_attention` and offers resend/recovery.
8. Test all three support consumables independently and confirm they change no entitlement or feature.
9. Test iPhone and iPad layouts, VoiceOver, larger text, reduced motion, widgets, and the pinned-flight Live Activity.

Local Flight is an informational display aid. It is not for navigation, dispatch, operational control, flight planning, professional aviation work, or safety decisions.
