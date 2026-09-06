# Purchases: Native Store Support

iOS paid-app ownership and Android’s one-time Relay Access purchase are separate from the optional support products. Native proof is implemented by [`../../modules/localflight-paid-app/`](../../modules/localflight-paid-app/) and creates or finds one portable `beacon_relay_lifetime_v1` license. It can power one main device: a Local Flight desktop using Beacon Relay or a phone in Standalone mode. Companion consumes no place, although Remote Companion still requires Relay Access on its desktop host.

Mobile never accepts or displays an LFRA key. Store ownership is checked only after an explicit action; iOS must not retry `AppTransaction.refresh()` automatically. Moving access requires a named confirmation. Beta/TestFlight/Play-internal proof goes only to the staging relay and database (`sandbox,test`); production accepts `production` evidence only.

The Android app is free; Companion and VATSIM require no purchase, while real-flight Standalone uses the one-time, non-consumable Google Play managed product `cc.beacontools.localflight.relay_access`. Google Play Billing supplies a transient purchase token for server-side Developer API verification; Play Integrity authenticates grant-based transfers of an existing universal license without another Google purchase. A pending purchase never grants access. The backend durably acknowledges a verified non-consumable and reconciles trusted RTDN, cancellation, refund, and voided-purchase signals. Set the environment-specific `LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER` before a store build. Play Console product creation and pricing plus an explicit migration/grant policy for existing paid-download customers are release gates; Billing cannot infer historical ownership of the paid APK.

The paid iOS app uses the signed `AppTransaction`. Separate verified Family Sharing identities create separate licenses. A signed revocation date revokes the related license, while an authoritative refund and repurchase for the same stable app-transaction identity restores that license rather than creating a second one.

Local Flight `0.5.2` implements three optional consumable support products through
StoreKit 2 / Google Play Billing via `expo-iap`. Support unlocks nothing, creates
no durable entitlement, and uses store-owned localized prices.

Product identifiers must match on both stores:

- `cc.beacontools.localflight.support.small`
- `cc.beacontools.localflight.support.medium`
- `cc.beacontools.localflight.support.large`

The app sends Apple transaction IDs or Google purchase tokens directly to the
Beacon Tools relay for official store verification. It finishes/consumes a
transaction only after verification succeeds. The relay stores only a keyed
transaction hash, short reference, product ID, coarse environment/status, and
timestamps. Raw store evidence and payment-card data are never stored there.

Release remains gated on App Store Connect and Play Console product creation,
store agreements/tax setup, relay verification credentials, TestFlight sandbox
testing, and Play license-tester testing. Consumables have no restore button or
durable entitlement; unfinished transactions are recovered automatically.

## Store Setup Gate

1. Accept the current store agreements and complete required tax/banking or
   merchant-profile setup in each store.
2. On Google Play, create `cc.beacontools.localflight.relay_access` as an active
   non-consumable one-time product for real-flight Standalone. Keep the Android
   app itself free; Companion and VATSIM must remain usable before purchase.
3. Create all three support IDs as consumable/one-time products. Use the app labels
   Runway Snack, Gate Coffee, and Long-Haul Fuel, with wording that says each is
   optional support and unlocks nothing. Do not describe them as charitable or
   tax-deductible donations.
4. Pick prices in App Store Connect and Play Console. Do not add prices to this
   repository; the app displays each store's localized `displayPrice`.
5. Add the products and a screenshot of the Support Local Flight sheet to the
   submitted store version/review material.
6. Create an App Store Server API key and a Google Play service account with the
   minimum purchase-verification access, then install those credentials only as
   private relay deployment secrets. Never put their values or private service
   runbooks in `AGENTS.md`, tracked docs, mobile builds, or release packages.
7. Redeploy the relay before testing. Verify cancellation, pending approval,
   offline relay, duplicate delivery, app restart, successful consumption, and
   repeat purchase with TestFlight sandbox and Play license-tester accounts.
