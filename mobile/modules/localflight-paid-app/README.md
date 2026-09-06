# Native Relay Access proof bridge

`localflight-paid-app` obtains transient native store evidence for Relay Access. It does not decide license state, persist proof, or activate Relay Access by itself.

- iOS calls `AppTransaction.refresh()` only after an explicit setup, verify, restore, protection, or move action. It returns the signed AppTransaction JWS and transient StoreKit device-verification ID for server-side verification. Do not call it from app launch, foreground refresh, background tasks, or cached status screens because StoreKit may show authentication UI.
- Android is a free app. Google Play Billing 9.1 queries or explicitly purchases the one-time, non-consumable managed product `cc.beacontools.localflight.relay_access` when the user chooses Standalone. Companion does not query or purchase it. The bridge returns only the product ID, purchase state, acknowledgement state, and purchase token needed for immediate backend verification. Purchase tokens must never be persisted by the app, logged, or treated as an unlock flag.
- An Android activation grant without a managed-product purchase is authenticated with a Play Integrity Standard token. The native request hash is base64url-without-padding SHA-256 of the UTF-8 string `localflight-relay-grant-v1:{nonce}:{install_id}:{activation_grant}`. Beacon Relay must decrypt the token through Google, require the expected package/app/device/licensing verdicts, reproduce the request hash, and enforce nonce/grant replay protection before accepting the grant.
- The Android build uses `com.android.vending.BILLING`; the obsolete Play Licensing AIDL service and `com.android.vending.CHECK_LICENSE` permission must not ship.

The app-level config plugin writes the managed-product ID and Play Integrity Cloud project number into application metadata. Set `LOCALFLIGHT_PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER` in each EAS environment before producing an Android store build. The value is a public project number, not a credential, but staging and production must use the Cloud projects linked to their intended Play/relay environments. A missing value makes Integrity operations return `unsupported_build`, and the merged-release-manifest contract rejects the build.

The JavaScript boundary exposes these stable local error codes:

- `store_cancelled`
- `store_unavailable`
- `ownership_unverified`
- `device_verification_missing`
- `store_timeout`
- `unsupported_build`
- `purchase_pending`

Callers map them to inline setup cards. Companion remains usable when verification is cancelled or unavailable; Standalone remains on Review until verification succeeds and the resulting device credential is safely written to SecureStore. A pending Play purchase never grants Relay Access.

Beacon Relay must verify managed-product purchase tokens with the Google Play Developer API and acknowledge a verified non-consumable purchase server-side within Google Play's acknowledgement window. The app never embeds a Play public key and never acknowledges before backend verification.

Run `npm run native-paid-app:contract` after native or manifest changes. Store proof must also be tested on physical TestFlight and Play internal-track devices against the staging relay before production is enabled.
