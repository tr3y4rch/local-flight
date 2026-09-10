# Relay Access 0.7.1 validation

This document is the public-safe release gate for Relay Access. It contains no
credentials, private hostnames, customer records, or operator commands.

## Product boundary

New Relay Access is one accountless, portable annual entitlement:

- Launch price: CHF 8 per year, automatically renewing.
- One independent main device: desktop/Pi or real-flight Standalone phone.
- Companion phones connected through a licensed host occupy no extra place.
- Included hosted capabilities: shared real-flight schedules and encrypted
  Remote Companion while the host is online.
- Shared real-aircraft radar is excluded. BYOK and VATSIM radar remain free.
- The software, LAN Companion, BYOK, and VATSIM remain free.

The website uses Stripe subscriptions. iOS and Android are free downloads and
use their native annual subscriptions for real-flight Standalone. Optional
support consumables remain separate and unlock nothing.

## Preserved authorities

The relay must continue to recognize these permanent authorities:

- Verified earlier Stripe lifetime purchases.
- Verified ownership of the earlier paid iOS app.
- Verified Android Relay Access non-consumable purchases.
- Existing valid complimentary grants.
- Founder entitlements created from the immutable migration snapshot.

Annual subscriptions use `beacon_relay_annual_v1`. Permanent purchases and
founders retain `beacon_relay_lifetime_v1`; no migration rewrites or expires
those records.

## Required deployment state

Before any sales channel opens, health and deployment smoke tests must confirm:

- Exact application version and source revision.
- Expected access schema and catalog contract v2.
- Required hash, license-derivation, encryption, and backup key versions.
- Encrypted backup creation and restoration into an empty staging database.
- SMTP transport readiness and monitored durable outbox.
- Provider-specific verification and reconciliation readiness.
- Isolated staging data, credentials, domains, and provider environments.
- Shared schedule and Remote Companion policy enabled only where permitted.
- Shared real radar policy disabled.

Generic `/health` success is insufficient. The catalog must identify
`beacon_relay_annual_v1`, one receiver, annual billing, provider-owned localized
pricing, independent sales states, and the legacy products that remain
restorable.

## Common entitlement checks

Every provider must pass the same behavior:

- A verified purchase creates exactly one license for the stable provider
  lineage; replay returns the same license.
- `active`, valid `grace`, and `cancelled_active` authorize hosted service.
- Cancellation retains access through the confirmed current period end.
- `past_due`, `expired`, `refunded`, `revoked`, and `suspended` do not authorize.
- Older provider events cannot overwrite a newer authoritative state.
- Provider unavailability retains the last authoritative state only until its
  known paid/grace boundary.
- Moving the main device uses prepare, secure local storage, and commit. The old
  receiver is not revoked before the new credential is stored.
- Raw provider customer IDs, purchase tokens, signed payloads, license keys,
  plaintext email, and payment details do not appear in databases, logs,
  diagnostics, reports, admin JSON, or backups.

## Stripe gate

Use test mode and test clocks to verify:

- Subscription Checkout uses the configured recurring Price, automatic tax,
  metadata, and stable idempotency.
- Checkout success with a valid email fulfills once, queues delivery, and gives
  one browser reveal.
- A lost, expired, or consumed browser secret directs the buyer to email
  recovery and never creates a second license.
- Renewal invoice, failed payment, dunning, grace policy, cancellation at period
  end, immediate cancellation, refund, dispute open/won/lost, and duplicate or
  out-of-order webhooks materialize the correct state.
- The authenticated billing portal opens only for the active Stripe receiver
  and never exposes the stored provider customer reference.
- Stripe Tax, refund wording, tax registrations/remittance responsibility, and
  applicable consumer-law obligations are reviewed before worldwide sales.

## Apple gate

Use TestFlight sandbox and App Store Server Notifications V2:

- New annual purchase, restore, reinstall, renewal, cancellation, billing retry,
  grace, expiry, refund, and revocation.
- Server-side signed-transaction validation checks bundle, app, product,
  environment, lineage, and transaction timing.
- The earlier paid app restores permanent founder access after signed
  `AppTransaction` verification and never opens an unnecessary subscription
  sheet first.
- The first annual subscription is submitted with the 0.7.1 app version and
  all store metadata, review instructions, and localized pricing are present.
- Family Sharing remains disabled unless a later entitlement design explicitly
  supports it.

## Google gate

Use the Play internal track, subscriptions v2, and RTDN:

- New annual purchase, pending purchase, acknowledgement, restore, reinstall,
  renewal, cancellation, account hold, grace, pause, expiry, refund, and revoke.
- Only a provider-verified purchased subscription is acknowledged.
- Stable purchase lineage remains idempotent across replacement tokens.
- The earlier non-consumable restores permanent legacy access.
- Play Integrity remains request-bound for movement of an existing portable
  entitlement and does not become a substitute purchase proof.

## Founder migration gate

- Set one immutable UTC cutoff.
- Dry-run eligibility from successful authenticated activity in the preceding
  90 days and review aggregate counts independently.
- Back up production, then execute the snapshot idempotently.
- New anonymous `lfm_` issuance stops at cutoff.
- Eligible credentials continue through the 12-month bridge and can claim one
  permanent `lfr_` founder credential.
- Ineligible, revoked, mismatched-install, replayed, and post-cutoff credentials
  fail safely.
- A failed client store or commit restores the old credential and leaves the
  bridge usable.
- After the bridge, old credentials can claim preserved ownership but cannot
  fetch hosted data until upgraded.

## Email and recovery gate

Use a local SMTP capture service, then one production transactional provider:

- Validate sender, reply address, subject, plaintext/HTML content, key format,
  fragment-based recovery links, duplicate suppression, and bounded retries.
- SPF, DKIM, DMARC alignment and TLS are required before public sales.
- Test Gmail, iCloud Mail, and Outlook delivery. Inbox placement and instant
  delivery are not guaranteed.
- Email outage never rolls back a verified entitlement.
- Resend is cooldown-protected, idempotent, and never returns the raw key.
- Recovery links are enumeration-safe, short-lived, single-use, and replay-safe.
- Lost-key recovery rotates the key and revokes the old key and receiver;
  ordinary resend does not rotate anything.

## Rollout

1. Validate email, keyrings, backups, and empty-database restoration.
2. Deploy staging with all sales flags closed.
3. Pass Stripe, Apple, and Google sandbox gates independently.
4. Dry-run and execute the founder snapshot after reviewed backup.
5. Deploy production in `migration` mode with schedule and Remote Companion on,
   shared real radar off, and all new sales still closed.
6. Publish tested 0.7.1 clients and verify founder upgrades.
7. Open Stripe, Apple, and Google separately only after each channel passes.
8. After 12 months, stop runtime `lfm_` access while retaining founder claims.

Production acceptance requires the complete Python suite, mobile verification
and accessibility contracts, site checks, secret scans, payment idempotency,
email capture, backup restoration, migration rollback, and fresh-install and
upgrade smokes. Store processing and physical-device tests remain explicit
pending gates until actually completed.
