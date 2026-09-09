# Native Founder Proof Bridge

`localflight-paid-app` obtains transient native evidence for Relay Access founder restoration and verified Android handoffs. It does not decide entitlement state, persist proof, or implement the new annual subscription.

- iOS calls `AppTransaction.refresh()` only after an explicit founder restore, protection, or move action. It returns the signed AppTransaction JWS and transient StoreKit device-verification ID for server-side verification. Do not call it from app launch, foreground refresh, background tasks, or cached status screens because StoreKit may show authentication UI.
- Android queries the legacy one-time product `cc.beacontools.localflight.relay_access` with Google Play Billing `INAPP` semantics. It never purchases that retired product for a new user. The annual subscription `cc.beacontools.localflight.relay_access.annual` is handled separately through `expo-iap` with subscription semantics.
- An Android activation grant is authenticated with a Play Integrity Standard token. Its request hash is base64url-without-padding SHA-256 of `localflight-relay-grant-v1:{nonce}:{install_id}:{activation_grant}`. Beacon Relay verifies the expected package/app/device/licensing verdicts and nonce/grant replay protection.
- The Android build uses `com.android.vending.BILLING`; obsolete Play Licensing AIDL and `com.android.vending.CHECK_LICENSE` must not ship.

The config plugin writes the legacy founder product ID and Play Integrity Cloud project number into Android application metadata. Set `LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER` in each EAS environment. A missing value makes Integrity operations return `unsupported_build`, and the release-manifest contract rejects the build.

Stable local error codes are:

- `store_cancelled`
- `store_unavailable`
- `ownership_unverified`
- `device_verification_missing`
- `store_timeout`
- `unsupported_build`
- `purchase_pending`

Callers map these to user-facing setup states. Companion and VATSIM remain usable when founder verification is cancelled or unavailable. Real-flight Standalone remains on review until an annual, founder, legacy, or transferred entitlement is verified and its device credential is safely stored.

Run `npm run native-paid-app:contract` after bridge, manifest, or product-boundary changes. Real provider proof still requires TestFlight and Play internal-track testing against the isolated staging relay.
