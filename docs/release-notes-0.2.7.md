# Local Flight 0.2.7 Client Notes

`0.2.7` is a polish pass on top of the `0.2.6` baseline. The user-facing client
behavior is unchanged — this release reshapes the operator/admin surface and
clarifies the privacy contract for the periodic relay heartbeat.

If you only run the native desktop app, the LAN browser UI, the Pi kiosk, the
mobile companion, or the Matrix board, you can upgrade or skip this release
without losing or gaining any feature. Update only if you also run the operator
Network Admin console, or if you want the explicit heartbeat-metadata
disclosure in `PRIVACY.md`.

---

## What Changed

### Privacy disclosure (everyone)

`PRIVACY.md` now lists the periodic-heartbeat install profile explicitly:

- app version
- OS family / version / architecture
- GUI mode (native / browser)
- source mode (real / VATSIM / BYOK)
- diagnostics mode
- companion device count
- matrix device count

The heartbeat already existed in `0.2.6`. The doc change makes the fields
visible so operator-side fleet shape (which versions and OSes are out there) is
transparent. Heartbeats remain ~30 min cadence with jitter, real-source installs
only, BYOK and incomplete-setup installs do not heartbeat.

### Network Admin (operator-only)

If you do not run the operator Network Admin console, the rest of this page does
not affect you.

- **Coarse-presence framing.** "Active installs" / "Active 24h" relabeled as
  "Seen ≤24h" with "Heartbeat or relay activity" sublabel on both the HTML
  admin SPA and the native Qt console. The `Last seen` column is now labeled
  consistently. Filter values (`status="active"`) and JSON contract are
  unchanged — display only.
- **Sign-out flow.** New `POST /admin/api/logout` endpoint returns 401 with a
  rotated `WWW-Authenticate` realm to invalidate the cached basic-auth
  credential in Chrome / Firefox / Edge. Safari sometimes clings; the new open
  `GET /admin/signed-out` page tells you to close the tab if so.
- **Idle auto-logoff.** Both surfaces auto-sign-out after 15 minutes of
  inactivity by default. Configurable via
  `LOCALFLIGHT_NETWORK_ADMIN_IDLE_S` (seconds, minimum 60). HTML shows a 60s
  warning toast before signing out.
- **Qt console buttons.** Native Network Admin now has explicit Disconnect
  (clears credentials, returns to the login state) and Quit (closes the
  window) buttons in the topbar.
- **Calmer styling.** Stripped the CRT scanlines, glow underlines, shimmer
  overlays, and multi-stop gradients from both surfaces. Same color identity,
  much less visual noise.

### Relay internals

- The admin SPA is now served from `relay/admin/admin.{html,css,js}` instead
  of being inlined in `relay/main.py`. No behavioral difference; future
  redesign iterations are easier to review.
- AeroDataBox schedule fetching now supports API.Market keys by default, with
  RapidAPI still available through the explicit marketplace setting. This keeps
  the fused schedule path compatible with the key source selected during setup.

---

## Upgrade Notes

- No client setup changes. Existing installs upgrade transparently.
- Operator installs that bind the `LOCALFLIGHT_NETWORK_ADMIN_IDLE_S` env var
  in their launcher / env file get the configurable idle threshold; everyone
  else gets the 15-minute default.
- The relay container needs to be redeployed for the new admin SPA and the
  logout endpoint to be live. The native Qt console works against any reachable
  relay regardless.

---

## Next

The next pass will likely revisit the admin SPA layout itself (path-routed
views, calmer hero, accessibility audit) now that the assets are extracted and
reviewable on their own.
