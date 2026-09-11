# Mobile Purchase Architecture

Local Flight `0.7.1` has two deliberately separate native purchase paths.

## Relay Access

Both apps are free downloads. Real-flight Standalone uses the annual auto-renewing subscription `cc.beacontools.localflight.relay_access.annual`. The shared `expo-iap` service restores an existing annual purchase before offering a new purchase, displays only store-owned localized prices, and sends transient StoreKit 2 or Google Play evidence to Beacon Relay. The relay is authoritative for product, app, environment, period, grace, renewal, refund, and revocation state. The app finishes/acknowledges a transaction only after successful verification.

One annual entitlement can operate one main device: one phone in real-flight Standalone or one Local Flight desktop/Pi host. Companion phones use their host and consume no additional place. VATSIM requires no Relay Access. Shared real-aircraft radar is included on a licensed monthly allowance; BYOK and VATSIM radar also remain available.

The custom [`../../modules/localflight-paid-app/`](../../modules/localflight-paid-app/) bridge is retained only for founder migration and verified handoffs:

- iOS obtains signed `AppTransaction` ownership proof for eligible owners of the earlier paid app.
- Android queries the legacy non-consumable `cc.beacontools.localflight.relay_access` as an `INAPP` product.
- Android Play Integrity binds a transfer grant to the official receiving app.

Do not point that legacy bridge at the annual subscription. The annual product is a subscription owned by `expo-iap`; the legacy product remains one-time and is queried only to restore permanent earlier access.

Mobile never accepts or displays an `LFRA-...` key during setup. Store verification runs only after an explicit user action. Beta/TestFlight/Play-internal proof goes only to the isolated staging relay; production accepts production evidence only.

## Optional Support

These three consumable products remain unrelated to Relay Access:

- `cc.beacontools.localflight.support.small`
- `cc.beacontools.localflight.support.medium`
- `cc.beacontools.localflight.support.large`

They unlock nothing and never create, extend, renew, or restore Relay Access. Store-owned localized prices are shown before purchase. The relay verifies each transaction and stores only a keyed reference and safe status metadata; raw store evidence and payment-card details are not retained.

## Release Gates

1. Create the annual subscription in one App Store subscription group and as one Google Play annual base plan. Keep Family Sharing off initially.
2. Configure tax, agreements, banking, localized store copy, and review screenshots outside the repository.
3. Configure App Store Server API/Notifications V2 and Google Play Developer API/RTDN credentials only in the isolated relay environment.
4. Keep Apple, Google, and support-purchase sales switches closed until their separate sandbox matrices pass.
5. Test annual purchase, pending, restore, renewal, cancellation, grace/hold, expiry, refund/revocation, reinstall, and main-device movement on physical TestFlight and Play internal-track devices.
6. Test legacy paid-iOS and Android non-consumable founder restoration without opening a new subscription sheet.

Run `npm run native-paid-app:contract`, the Relay Access contract, full mobile verification, and platform manifest inspection after changing this boundary.
