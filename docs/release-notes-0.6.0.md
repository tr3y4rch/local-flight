# Local Flight 0.6.0 — One Ecosystem, Clear Access Choices

Local Flight 0.6.0 brings the desktop apps, Linux server, Raspberry Pi, LAN
browser, Beacon Relay, mobile apps, widgets, and Beacon Tools website onto one
coherent release line. The main change is a portable Beacon Relay Access model
that keeps Local Flight free and local-first while making hosted real-flight
data an explicit, optional service.

Local Flight is an informational display. Flight, weather, map, and status data
can be delayed, incomplete, cached, wrong, or unavailable. Never use it for
navigation, dispatch, operational control, flight planning, or safety decisions.

## The Short Version

- The desktop app remains free and open source.
- Desktop setup has exactly three choices: **Beacon Relay**, **Bring Your Own
  Keys**, and **VATSIM**.
- Beacon Relay Access is a one-time purchase with no recurring fee. It has no
  scheduled expiry, but remains subject to refunds, abuse controls, upstream
  provider permission, and service availability.
- One purchase creates one separate portable license for one active main
  device: a desktop using Beacon Relay or a phone using real-flight Standalone.
- Companion follows its Local Flight host and uses no additional license.
- The paid iOS app includes one Relay Access license after App Store ownership
  is verified.
- Android is free to download. Companion and VATSIM are free; real-flight
  Standalone uses an optional one-time, non-consumable Google Play purchase.
- A Stripe web purchase, verified iOS entitlement, or Android Relay purchase
  produces the same backend license type. Buying twice creates two licenses.
- A web or Android purchase does not include the paid App Store download.
- No Local Flight account, password, profile, or subscription is introduced.

## Choose Your Desktop Data Route

### Beacon Relay

Beacon Relay supplies hosted, shared real-flight data from Beacon Tools. Enter
the `LFRA-…` key shown after a website purchase or sent by email. Local Flight
exchanges it for a revocable credential stored on this desktop, then removes
the master key from the setup field and local configuration.

If that license is already active on another main device, setup names the
current device and asks before moving access. The previous device remains
active until the new credential has been stored safely and the move is
committed. Leaving the Relay route frees access for another main device; a
temporary network failure is shown as a pending release rather than silently
discarding the credential.

New Relay purchases can be paused independently of existing-license
activation. The setup card therefore remains visible when sales are
temporarily unavailable.

### Bring Your Own Keys

Use supported aviation-provider credentials directly on your own Local Flight
installation. Your provider’s terms, limits, pricing, and permitted use apply.
This route does not call Relay Access licensing endpoints.

### VATSIM

Use sanitized virtual-flight data without Relay Access or real-flight provider
keys. VATSIM stays callsign- and flight-plan-focused and excludes pilot names,
controller names, network IDs, and passenger-only fields. This route does not
call Relay Access licensing endpoints.

## Portable Relay Access

Every supported purchase is fulfilled through the same backend license model:

```text
Stripe website / paid iOS entitlement / Android Relay purchase
                              ↓
                 Beacon Relay Access license
                              ↓
             one active desktop or phone Standalone
```

Licenses remain separate even when several are protected by the same email.
Email is required for Stripe key delivery and optional on mobile for protection,
recovery, or transfer. It does not create an account. Passwordless email links
can list protected licenses, show their current main device, create a one-time
activation code, release a device, or rotate a lost key.

Mobile never accepts or displays a raw `LFRA-…` key. Moving a protected license
to an official mobile app uses a short-lived transfer plus fresh App Store or
Play Integrity proof. A mobile-created license can optionally send its existing
desktop-compatible key after the user confirms an email address.

Refunded, revoked, or suspended purchases stop authorizing real Relay data.
Existing active credentials do not contact Stripe, Apple, Google, or email
services on every data request; purchase systems are used for fulfillment,
restoration, and reconciliation instead.

## Mobile 0.6.0

The mobile release line is iOS build **13** and Android versionCode **16**.

### Companion

- Connect to Local Flight on Windows, macOS, Linux, or Raspberry Pi over the
  local network.
- Pair by QR code or manual address with host fingerprint verification.
- Prefer the nearby connection and use encrypted Remote Companion only after an
  explicit host-side grant, while that host remains online.
- Read Board, Radar, History, and allowed controls through the host.
- Use no additional Relay license. Remote Companion requires active Relay
  Access on the desktop host; a phone’s available license cannot substitute for
  an unlicensed host.
- On iOS, the final setup action may verify the included app ownership once so
  the unused license can be found later. Cancellation or an outage never blocks
  LAN Companion. Android Companion requires no Relay purchase.

### Standalone

- Run a simpler Board, Radar, History, and Settings experience without a Local
  Flight host.
- Choose VATSIM for a free route that does not verify or occupy Relay Access.
- Choose real-flight data to activate one portable license on the phone.
- On iOS, an explicit action verifies the paid App Store download and uses its
  included access.
- On Android, an explicit action buys or restores the one-time Google Play
  Relay product. An existing universal license can instead move to the official
  app through a verified transfer without another Google purchase.
- Keep the previous working setup until pairing or activation succeeds. Store
  cancellation, an unavailable service, or secure-storage failure returns to a
  clear retry state instead of destroying the old setup.

When moving from real-flight Standalone to Companion or VATSIM, the app releases
the phone only after the replacement route is ready. If the service is offline,
the release remains visibly pending while LAN Companion or VATSIM can continue.

### Widgets And Support

iOS and Android home-screen widgets still read only the bounded snapshot saved
by the app. They do not contact a LAN host, Beacon Relay, or an aviation
provider themselves.

The three optional support purchases remain separate consumables. They unlock
nothing, create no Relay license, and create no subscription.

## Desktop, Server, And Display Improvements

- The native Qt and LAN setup wizards share the same three-route rules while
  retaining their platform-specific visual styles.
- Desktop route selection is explicit and persisted. Provider-key edits,
  profile changes, and Remote Companion setup cannot silently switch routes.
- Relay activation is a two-step prepare, store, and commit flow so a failed
  local credential write cannot displace a working device.
- Browser and native settings show plain route and access summaries and reopen
  a hydrated setup flow for changes.
- Windows, macOS, Linux desktop, Linux headless server, and Raspberry Pi retain
  the local FIDS, radar, weather, history, Matrix, kiosk, LAN, and display
  capabilities introduced in earlier releases.
- Remote Companion remains end-to-end encrypted between the phone and host. The
  relay routes opaque envelopes and never receives the shared encryption key.

## Beacon Relay And Operations

- Stripe, App Store, and Google Play proofs feed one provider-neutral
  fulfillment service and map to `beacon_relay_lifetime_v1`.
- Replay-safe purchase records prevent duplicate webhooks, receipts, store
  proofs, or notification events from creating duplicate licenses.
- Device credentials are opaque and revocable. Raw keys, email addresses,
  purchase tokens, and store proofs are not stored as plain database fields or
  exposed in operator responses.
- One active main device is enforced atomically, including concurrent moves.
- Structured access states distinguish active, suspended, refunded, revoked,
  replaced, deactivated, pending, and unknown credentials.
- Durable notification delivery records failures and safe retry timing for key,
  recovery, protection, and device-move email.
- The operator surface can search and page through licenses, inspect masked
  purchase/activation/delivery history, retry safe work, and perform protected
  suspend, reactivate, revoke, move, and key-rotation actions.
- Commercial provider capabilities remain fail-closed. A valid payment never
  overrides an aviation provider agreement.
- Mobile navigation and native-project tooling now resolve to the patched URL
  decoding and UUID dependency lines. Clean installs, dependency audit, and
  both iOS and Android production bundles are part of the release checks.
- Production sales and licensed-mode data routes remain disabled until payment,
  store, reconciliation, secret, backup, and provider-permission gates pass.

## Privacy And Recovery

- Local boards, settings, snapshots, logs, and history remain local to the
  device or Local Flight host unless the user explicitly sends a report.
- Relay Access requires no general-purpose Beacon account or persistent profile.
- Stripe checkout uses an email for delivery. Mobile asks for email only when
  the user chooses protection, recovery, or transfer.
- The licensing database uses keyed lookups and encrypted notification
  destinations rather than plain email fields.
- Passwordless links are short-lived and single-use. Their secret is carried in
  the URL fragment so normal hosting and CDN request logs do not receive it.
- Mobile stores a Relay device credential only in platform secure storage and
  keeps only masked, non-secret license state in ordinary app storage.

See [Privacy & Diagnostics](../PRIVACY.md) for the complete data inventory,
retention, provider, and privacy-choice explanation.

## Packages And Supported Systems

The 0.6.0 release targets ten packages, each with a matching SHA-256 file:

- Windows x64 installer.
- Separate Developer ID signed, notarized, and stapled macOS packages for Apple
  silicon and Intel Macs on macOS 12 or newer.
- x86-64 and ARM64 Linux AppImages.
- x86-64 and ARM64 Ubuntu/Debian desktop packages.
- x86-64 and ARM64 Ubuntu/Debian headless server packages.
- Raspberry Pi source bundle for headless, native HDMI kiosk, browser kiosk,
  and Matrix use.

The Windows 0.6.0 installer remains intentionally unsigned and may appear as an
unknown publisher. Its SHA-256 verifies that the downloaded file matches the
published release; it is not a publisher signature.

Download buttons become available only after both a package and its matching
checksum exist on the complete GitHub release. Until then, the website shows
that the 0.6.0 package is not yet available instead of linking to an older or
partial artifact.

## Before Public Store And Licensed-Service Launch

The source and local automated checks do not replace these release gates:

- Rebuild, sign where applicable, and inspect every native OS package.
- Inspect the archived iOS app for the app-target privacy manifest, StoreKit
  bridge, widget, application identity, and build number.
- Inspect the signed Android App Bundle for Billing, Play Integrity, widget,
  permissions, package identity, and version code.
- Complete physical TestFlight and Play internal-track purchase, cancellation,
  pending, refund, revocation, reinstall, restore, and cross-device-move tests
  against a separate staging relay and database.
- Complete native Windows, macOS, Linux, Raspberry Pi, LAN, Matrix, Companion,
  Remote Companion, and upgrade smoke tests.
- Confirm Stripe, email, Apple, Google, production secret, reconciliation,
  encrypted backup, restore-drill, and operator workflows.
- Confirm the upstream aviation-provider permissions for every paid Relay
  capability before enabling sales or licensed production data.

Production moves directly from legacy access to licensed access only after
these gates pass. There is no user-visible shadow period, grandfathered
Community access, or grace period.

## Upgrade Notes

Installing 0.6.0 over an earlier desktop release preserves the normal Local
Flight data directory. Existing settings are mapped to Relay, BYOK, or VATSIM;
the hydrated wizard opens when a route-dependent choice needs confirmation.
Legacy Relay credentials are retained only for migration/audit and do not
authorize licensed real-data routes after cutover.

Use only the official [Local Flight downloads page](https://beacontools.cc/local-flight#downloads)
and [GitHub Releases](https://github.com/tr3y4rch/local-flight/releases). Keep
the package and matching checksum together when verifying a download.
