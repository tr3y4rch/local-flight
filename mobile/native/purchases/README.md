# Purchases: Native Store Support

Local Flight `0.5.1` implements three optional consumable support products through
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

1. Accept the current paid-app agreements and complete required tax/banking or
   merchant-profile setup in each store.
2. Create all three IDs as consumable/one-time products. Use the app labels
   Runway Snack, Gate Coffee, and Long-Haul Fuel, with wording that says each is
   optional support and unlocks nothing. Do not describe them as charitable or
   tax-deductible donations.
3. Pick prices in App Store Connect and Play Console. Do not add prices to this
   repository; the app displays each store's localized `displayPrice`.
4. Add the products and a screenshot of the Support Local Flight sheet to the
   submitted store version/review material.
5. Create an App Store Server API key and a Google Play service account with the
   minimum purchase-verification access, then install those credentials only as
   private relay deployment secrets. Never put their values or private service
   runbooks in `AGENTS.md`, tracked docs, mobile builds, or release packages.
6. Redeploy the relay before testing. Verify cancellation, pending approval,
   offline relay, duplicate delivery, app restart, successful consumption, and
   repeat purchase with TestFlight sandbox and Play license-tester accounts.
