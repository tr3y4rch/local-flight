# Local Flight 0.7.0 release candidate

Local Flight 0.7.0 prepares a simpler Relay Access model while keeping the
software local-first and the free routes intact. Public desktop, Linux, and
Raspberry Pi downloads remain at 0.6.0 until rebuilt 0.7.0 packages complete
their platform checks.

## Relay Access

- New Relay Access is one portable annual entitlement at a launch price of
  CHF 8 per year. Website checkout and the mobile stores show the final local
  price and applicable tax before purchase.
- One entitlement can be active on one independent main device: either a
  desktop/Raspberry Pi host or a phone using real-flight Standalone. Companion
  phones connected through that host do not use another place.
- Relay Access includes hosted real-flight schedules and encrypted Remote
  Companion while the host is online.
- Shared real-aircraft radar is not included. Radar remains available with a
  user's own compatible provider key or with VATSIM virtual traffic.
- iOS and Android are free downloads. Companion and VATSIM remain free; only
  real-flight Standalone uses the annual mobile subscription.
- Website purchasers receive a portable `LFRA-...` key through a one-time
  browser reveal and delivery email. Passwordless recovery and Stripe billing
  management are prepared as separately validated release gates.

## Existing users

- Verified earlier lifetime purchases and complimentary grants remain
  permanent.
- Verified owners of the earlier paid iOS app and Android non-consumable can
  restore permanent access without buying the annual plan.
- Eligible active legacy Relay installs can claim permanent founder access
  during the migration period. The old credential and preserved install
  identity are required unless access has already been protected by email.
- Moving access to another main device is explicit and revokes the former
  device credential only after the new credential has been stored safely.

## Reliability and privacy

- Renewable access now tracks the provider-confirmed paid period, renewal
  state, cancellation, grace, expiry, refund, and revocation without storing
  raw store proofs or payment credentials.
- Provider outages retain the last authoritative state until its known paid or
  grace boundary. A network outage alone does not invent an expiry.
- Sales can be opened independently for Stripe, Apple, and Google. Closing new
  sales does not revoke existing access.
- Email delivery remains durable and retryable. A verified purchase is not
  undone by a temporary mail outage, although instant delivery and inbox
  placement cannot be guaranteed.
- Optional support purchases remain one-time tips. They unlock nothing and do
  not create, extend, or renew Relay Access.

## Free and local routes

Companion over the LAN, Bring Your Own Keys, VATSIM, local history, Matrix
output, the LAN browser, and the open-source application remain available
without Relay Access. Local settings and history remain on the user's device
when hosted access expires or is cancelled.

## Availability

The 0.7.0 source reserves iOS build 15 and Android versionCode 18 for testing.
Build upload, store processing, tester availability, provider sandbox approval,
tax readiness, and public sales are separate gates. This candidate does not
claim that annual subscriptions or 0.7.0 native downloads are already public.

Local Flight is an informational display. Its flight, weather, radar, map, and
relay data may be delayed, incomplete, cached, unavailable, or wrong. Do not
use it for navigation, dispatch, operational control, or safety decisions.
