# Relay Access release validation

This is the public-safe certification checklist for Beacon Relay Access. It
contains no credentials or private service topology. Complete it against an
isolated staging relay before enabling any production purchase or licensed-data
flag.

## Non-negotiable contract

- Stripe, verified paid-iOS ownership, and the Android non-consumable each
  create one separate `beacon_relay_lifetime_v1` license.
- Replaying payment, ownership, notification, or retry evidence resolves to the
  same license. It never creates another one.
- The three mobile support purchases are consumable tips. They create no
  license, entitlement, receiver, subscription, or feature.
- Stripe, Apple, and Google issue the financial receipt. Local Flight sends a
  separate access-delivery or recovery email and never receives card details.
- Email is optional while a verified mobile purchase remains on its current
  device. A verified email is required before its portable key is delivered or
  the license is handed to another main device.
- Mail failure never rolls back verified ownership, license generation, or a
  completed receiver move.

## Automated gate

Run the complete Python, mobile, site, accessibility, dependency, and security
checks from a clean checkout. The relay dependency set is required; a missing
Stripe or store-verification package is a broken test environment, not an
accepted failure.

Build and start the exact candidate relay image, then run:

```bash
python scripts/check_relay_access_deployment.py https://relay.example.test \
  --expected-revision <candidate-commit>
```

The check must verify the deployed version and commit, Relay Access schema,
catalog readiness, and canonical product. A generic healthy response is not a
licensing deployment proof.

## Email certification

First use a local SMTP capture service to inspect plaintext and HTML delivery,
sender and reply addresses, key formatting, fragment-based recovery links,
duplicate suppression, retry timing, and log redaction. Then certify one
transactional SMTP provider with all of the following:

- TLS transport, SPF, DKIM, and DMARC alignment.
- A monitored sender and working reply address.
- Queue-age and terminal-failure monitoring using aggregate state only.
- Delivery checks to Gmail, iCloud Mail, and Outlook, including spam placement
  and mobile/desktop link handling.
- Friendly public states limited to `pending`, `sent`, and `needs_attention`.
  SMTP responses and retry internals stay operator-only.

## Provider sandbox matrix

Stripe test mode must cover successful and delayed checkout, failed and expired
sessions, duplicate signed webhooks, a lost browser result secret, resend,
recovery, refund, dispute, and process restart.

TestFlight must cover first ownership verification, reinstall, restore, email
protection, portable-key delivery, desktop handoff, occupied-receiver movement,
repeat verification, refund/revocation, and restoration after a valid
repurchase.

Google Play internal testing must cover purchase, pending, cancellation,
already-owned, acknowledgement, reinstall restore, RTDN replay, voided purchase,
refund, email protection, portable-key delivery, and a verified handoff while
another receiver is active.

Every failure screen must offer one safe next action: wait, retry the same
verification, resend delivery, request a recovery link, restore store ownership,
or contact support with a masked reference.

## Recovery and security matrix

- Expired and replayed links fail safely; recovery requests remain
  enumeration-safe and rate-limited.
- Initial verified delivery reveals the existing key once. Lost-key recovery
  rotates it and revokes the old key and active receiver.
- Resending the current key is cooldown-protected, idempotent, and never returns
  the raw key from the action API.
- Concurrent receiver moves preserve exactly one active receiver.
- Searches of APIs, SQLite data, logs, reports, diagnostics, and operator lists
  find no raw key, plaintext email, purchase token, signed store evidence, or
  provider exception.
- A WAL-consistent encrypted backup restores into an empty staging relay with
  every referenced historical key version available. Fulfillment, recovery,
  and reconciliation must still work after restore.

## Enablement order

1. Deploy the candidate relay with sales, mobile ownership, licensed data, and
   Remote Companion licensing flags closed.
2. Confirm health identity and catalog contract through the public route.
3. Configure separate versioned derivation, hashing, email-encryption, and
   backup keyrings; verify all persisted key references.
4. Pass SMTP, Stripe, TestFlight, Play, recovery, security, and backup drills in
   staging.
5. Enable mobile ownership for TestFlight and Play internal testing only.
6. Enable Stripe checkout only after fulfillment, delivery, refund, and
   recovery pass together.
7. Enable licensed receiver enforcement only after rollback and migration are
   proven.

An authoritatively verified purchase can be guaranteed to fulfill
idempotently, survive a temporary email outage, and retain a documented browser,
store-restore, or verified-email recovery path. Instant email, inbox placement,
provider uptime, and perpetual hosted-service availability cannot be guaranteed.
