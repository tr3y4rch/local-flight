# Service status monitoring

Beacon Tools publishes availability at
[beacontools.cc/status/](https://beacontools.cc/status/). This document covers the
parts that live outside the repository.

The split is deliberate:

- **Probing and alerting happen off our infrastructure.** UptimeRobot checks the
  public endpoints from outside Fly.io and Cloudflare, so the result stays honest
  when the failure is ours. It is also what actually pages a human.
- **The page lives on our infrastructure.** `/status/` renders the Beacon Tools
  design and reads `/api/status`, a Worker route that queries the relay and the
  monitoring API server-side. No third-party script reaches a visitor's browser,
  which keeps the boundary set in `workers/beacontools.js` intact, and no visitor
  data reaches the monitoring service.

The obvious consequence is that `/status/` cannot report its own host being down.
That is what `statusFallbackUrl` in `site/src/data/site.ts` is for: it points at
the externally hosted monitor page, and `/status/` links to it once it is set.

## Monitors

Free tier, five-minute HTTP(S) **keyword** checks. Keywords matter — several of
these endpoints return HTTP 200 while being functionally broken.

| Friendly name | URL | Keyword must exist |
|---|---|---|
| `website` | `https://beacontools.cc/` | `Beacon Tools` |
| `relay-api` | `https://relay.beacontools.cc/health` | `"catalog_ready":true` |
| `licensing` | `https://relay.beacontools.cc/v1/access/catalog` | `beacon_relay_annual_v1` |
| `downloads` | `https://beacontools.cc/api/releases/latest` | `"ok":true` |
| `mobile-gateway` | `https://relay.beacontools.cc/v1/mobile/iap/status?platform=ios` | `"ok":true` |

The friendly names are the join key. `STATUS_SERVICES` in
`workers/beacontools.js` matches on them, so renaming a monitor silently drops
its history from the page; `scripts/site_status_contract.mjs` covers the mapping.

All five must be **Keyword** monitors, not HTTP(s) ones. HTTP(s) monitors send
HEAD, and every relay route answers `405 Allow: GET` to HEAD — that is stock
FastAPI behaviour, since `APIRoute` does not add HEAD to GET routes the way a
plain Starlette route does, and not a misconfiguration to fix in `relay/main.py`.
Keyword monitors issue GET because they need the body, which sidesteps it. The
monitor type cannot be changed after a monitor is created, so a monitor made as
HTTP(s) has to be deleted and recreated; selecting the HTTP method directly is a
paid feature and is not a route around this on the free plan.

Set each one to alert when the keyword is **not** found. The two Cloudflare-served
monitors would pass as HTTP(s) checks, because Cloudflare does answer HEAD, but
they belong on keywords too: `/api/releases/latest` returns HTTP 200 with
`"ok":false` when the GitHub proxy fails, so a HEAD check would miss precisely
the failure it exists to catch.

`relay-api` asserts `catalog_ready` rather than a 200 because
`docs/release-process.md` already treats a bare `/health` response as
insufficient evidence that the relay is serving.

`mobile-gateway` uses the IAP status route because it is the only mobile endpoint
that needs no `install_id`; the board, radar, and weather routes all require a real
install identifier, so probing them would mean inventing installs. Its keyword is
`"ok":true` and deliberately **not** `verification_ready` or `purchases_enabled`,
both of which are legitimately `false` while Apple and Google sales are disabled.

A monitor with no entry in `STATUS_SERVICES` is not published, so operator-only
checks can be added upstream without changing the public page.

Do not monitor `/v1/access/stripe/webhook`, `/v1/access/apple/notifications`, or
`/v1/access/google/rtdn` — they are POST-only and would alarm on 405 — or
anything under `/admin/api/`, which is behind Basic auth.

Also enable SSL-expiry alerts for `beacontools.cc` and `relay.beacontools.cc`.
Certificates renew automatically at Cloudflare and Fly.io, so an expiry warning
means that automation has stopped working.

## Credential

`/api/status` reads the monitoring API with a **read-only** key, never the
account's read-write key:

```bash
npx wrangler secret put UPTIMEROBOT_API_KEY
```

The key never appears in `wrangler.jsonc`, in the site source, or in the
`/api/status` response body; the contract test asserts the last of these.

Two caches sit behind the route, with different jobs. The status response itself
is held 30 seconds and carries no `stale-while-revalidate`, because serving a
stale all-clear during an incident is the one failure this page exists to avoid.
The monitor history is cached separately for five minutes, matching the check
interval, and is retained well past that as a fallback: if the monitoring API is
slow or refuses a request, the last known history is served instead of the column
disappearing. That also keeps usage far inside the free tier's 10 requests per
minute no matter how much traffic the page gets.

If the key is absent, unset, or rejected, the page still renders live component
health from the relay and simply omits the uptime history. `wrangler dev`
therefore works with no secrets configured.

## What the page reports

Service rows come from the monitors, except where a signal can be derived from
the request itself — serving the response proves the website is reachable, and
the live `/health` probe is fresher than a five-minute poll, so it wins for the
relay and licensing rows.

Component rows come from `access.*` in the relay's `/health`. Two mappings are
deliberate and should not be "simplified":

- **Purchases tracks `providers.stripe`, not `sales_ready`.** The relay folds the
  `RELAY_ACCESS_SALES_ENABLED` toggle into `sales_ready`, so publishing that field
  would report a deliberate sales pause as a fault. A deliberate pause is shown
  as an informational notice instead.
- **`access.mode` is never mapped.** It is a rollout state, not a health state.
  Production sits in `migration` for an extended period by design.

## Replacing the vendor

`/api/status` defines its own response shape and the vendor appears nowhere in
the site source, so switching monitors means rewriting `normalizeUptimeMonitors`
and `uptimeMonitors` in `workers/beacontools.js` and re-pointing the secret. The
page, its styles, and its tests are unaffected.

## Verifying

```bash
node scripts/site_status_contract.mjs
npx wrangler dev   # then: curl -s http://localhost:8787/api/status
```

Point `RELAY_ORIGIN` at an unroutable host to confirm the outage path renders
instead of hanging; the probe times out after five seconds.
