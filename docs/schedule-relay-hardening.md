# Shared schedule fetching

Managed Local Flight installations obtain flight information from Beacon Relay.
The relay owns provider credentials, upstream timing, shared airport snapshots,
and provider budgets. Explicit BYOK remains a separate user-selected route.
Missing or invalid managed access never selects BYOK automatically.

## Fetching contract

The opt-in schedule service uses one airport/policy refresh state in SQLite.
Display direction, shorter display windows, client count, and page navigation do
not create independent provider refreshes. A normal airport refresh is admitted
at most once per 900 seconds, on demand. Existing stricter mobile and community
consumer intervals still apply. There is no inactive-airport warming.

Fresh covered snapshots return immediately. Usable stale snapshots also return
immediately while one eligible refresh starts. A cold request waits at most 30
seconds; otherwise it receives a safe 503 with Retry-After. Wider demand is
recorded for the next permitted refresh and explicitly reports partial coverage
until fulfilled. Two primary workers and one separate enrichment worker are
bounded per service process. SQLite leases, renewal, and generation fencing
coordinate primary refreshes across processes sharing the same database.

AeroDataBox requests cover the lookback, display horizon, refresh margin, and
rounding margin. Requests exceeding the configured provider window are split
into overlapping slices. All planned units are reserved before the first call;
failed slices cannot publish a partial response as a complete board. With a
720-minute provider limit, the default 12-hour future horizon plus lookback
requires two calls (four units at the default cost), not one.

Provider request pacing and pauses are persisted per credential fingerprint.
Authentication rejection pauses that credential; changing the AeroDataBox key
or subscription gateway changes the fingerprint. Upstream Retry-After is honored.
Transient failures allow at most two extra attempts in a provider fetch sequence,
with additional accounting before retries. Reservations are conservative: a
failed sequence does not refund units for slices that could not be completed.

## Enrichment and validation

AeroDataBox is primary in auto mode. AviationStack whole-board fallback requires
an allowed, configured provider and primary failure. An explicit AeroDataBox-only
selection does not enable AviationStack.

Optional AviationStack enrichment is published independently of the primary
board. It runs at most hourly per airport, uses at most 20% of configured
AviationStack daily/monthly allowances, and also consumes the overall allowance.
Cached enrichment is matched using identity, route, direction and scheduled time.
Ambiguous/unrelated movements are not appended. Only missing fields are filled;
primary times/statuses are never replaced. Gates/terminals expire after 15 minutes
and other enrichment after one hour. Consumers retain source evidence so local
cache reads can remove expired enrichment without a provider request.

Missing movement sections, malformed rows and invalid timestamps are failures,
not empty airports. Sparse-refresh comparisons use only overlapping coverage.
Quiet/empty cold boards are valid. A previously busy overlapping interval needs
a second independent valid empty fetch before it can be replaced by an empty board.
AeroDataBox revised time remains estimated unless completion evidence supports
an actual time; approximate quality and uncertain statuses remain explicit.
The mapping follows the status and movement contracts in the
[official AeroDataBox OpenAPI specification](https://doc.aerodatabox.com/docs/openapi-rapidapi-v1.json).

## Compatibility and retention

Existing schedule and mobile board endpoints keep their shapes. Optional fields
include snapshot_id, source_fetched_at, provider_fetched_at, coverage_from,
coverage_to, coverage_complete, next_refresh_at, refresh_after_s, expires_at and
safe notices. The local row-list endpoint remains a list; `/api/fids/status`
provides its additive metadata. Health includes schedule freshness and notices.

Local receipt time is separate from source fetch time. Cached responses cannot
renew the source age. Unknown legacy source age stays unknown. Desktop and mobile
history deduplicate repeated source observations. Older mobile responses cannot
regress a newer saved movement.

Provider-derived managed data defaults to seven-day retention, or a shorter
existing storage limit. Extended retention requires an explicit verified policy.
Stored expiry is not extended by reads, enrichment, or merging. Expired rows are
unavailable to readers before housekeeping; running services clean them daily,
and local applications also clean on reads/writes. Closed applications enforce
expiry on their next access. Stale board serving has a separate 24-hour ceiling
and requires still-relevant coverage.

Access-recovery backups exclude provider schedule and mobile cache tables,
including freed SQLite pages. Backup maintenance also rewrites decryptable legacy
archives to remove those datasets while preserving access recovery data and the
archive's original creation time. Unreadable backups remain an explicit recovery
issue; they are not silently deleted.

## Rollout configuration

The coordinator is disabled by default. Both an enable flag and an airport
allowlist are required. Configuration is evaluated at runtime.

| Setting | Default | Meaning |
| --- | --- | --- |
| RELAY_SCHEDULE_V2_ENABLED | disabled | Enable the new coordinator |
| RELAY_SCHEDULE_V2_AIRPORTS | empty | Comma-separated airport codes; `*` enables all |
| RELAY_AERODATABOX_MAX_FIDS_MINUTES | 720 | Verified subscription request-window limit |
| LOCALFLIGHT_AERODATABOX_MAX_FIDS_MINUTES | 720 | Equivalent explicit BYOK capability |
| RELAY_AERODATABOX_REQUESTS_PER_SECOND | 1 | Global pacing per AeroDataBox credential/gateway |
| RELAY_AVIATIONSTACK_REQUESTS_PER_SECOND | 1 | Global pacing per AviationStack credential |
| RELAY_SCHEDULE_RETENTION_DAYS | 7 | Relay provider-data retention |
| RELAY_SCHEDULE_EXTENDED_RETENTION_VERIFIED | disabled | Permit a verified retention setting above seven days |

Existing provider enablement, access policy, provider selection and budget limits
continue to apply. The shared request planner/response validation also harden the
legacy coordinator and BYOK; disabling V2 does not restore silent truncation.

Before production activation, verify the subscription's permitted Local Flight
use, request window, request rate, unit cost, quotas and retention. This software
configuration does not establish provider permission by itself. Do not increase
budgets automatically to accommodate wider coverage.

Deploy compatible relay code first, initially allowlisting a small selection of
busy, quiet and limited-coverage airports. Deploy updated clients next. Observe
at least 24 hours of source age, coverage gaps, refreshes, rejections, cache hits,
enrichment yield, provider units and fallback behavior before expanding.
The authenticated overview includes `schedule_v2` aggregate metrics, including
successfully fetched enrichment, fields filled and safe fallback reasons.

Rollback disables the coordinator flag while retaining additive database schema
and managed routing. Allow in-flight work to finish before completing a rollback;
never make direct client calls a recovery path. Rebuild affected platform packages
and complete the existing release-process gates before distribution.

## Validation

`tests/test_schedule_hardening.py` exercises complete request planning,
100 consumers across two processes, generation fencing, stale/cold behavior,
route isolation, atomic budgets, bounded retries, credential pauses, enrichment
expiry, source-age/history preservation, and backup exclusions.

Mobile `npm run schedule:test` executes board projection and the actual mobile
history upsert against SQLite, including repeated and out-of-order snapshots.
It is included in `npm run verify`. The normal backend, native, packaging, mobile
verification and accessibility checks remain required.
