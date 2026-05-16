# Local Flight 0.2.7 Client Notes

`0.2.7` is the next client-polish release candidate after the `0.2.6`
baseline. The focus is the public Local Flight experience: the native Qt shell
is calmer, FIDS reads more like a passenger board, setup/settings/history/matrix
are friendlier, the LAN browser UI remains a supported access surface, and the
mobile app now has a clear LAN Companion vs Standalone shape.

This release does not change the basic setup choices. You can still use
Community Relay, bring your own provider keys, or run VATSIM-only virtual
traffic.

---

## Highlights

- **Native Qt shell polish.** The main window now has clearer navigation:
  Display/FIDS/Radar as core viewing pages, UTC/LT as the centered divider,
  Matrix/Settings/Admin/History/Logs/Report as tools, and a small sync dot near
  Power instead of a large "live" banner.
- **Cleaner FIDS header.** FIDS now shows a city/country display name such as
  `Zurich, Switzerland` or `Miami, United States`. It no longer uses long
  formal airport names or IATA/ICAO descriptors in the title.
- **Passenger-friendly weather.** The main FIDS weather card now favors plain
  wording, temperature, and visibility hints instead of raw METAR fragments.
- **Long-name protection.** Very long airport labels are clamped safely and keep
  the full value as a tooltip in the native GUI.
- **Footer support icons.** The footer now keeps the version/privacy phrase
  compact and uses icon-only GitHub / coffee support buttons with tooltips.
- **Shared app typography and assets.** Native, LAN browser, and mobile surfaces
  use bundled local fonts and local support assets instead of online font/CDN
  dependencies.
- **Mobile Standalone preview.** The same Expo app can now be set up as either
  a LAN Companion for your desktop/Pi server or as a simplified Standalone phone
  board through the hosted relay.

---

## FIDS And Flight Details

- FIDS title display is now deliberately passenger-facing: city plus country,
  with no airport-name wall of text and no technical code suffix.
- Operating-flight identity remains the main board identity, with marketed or
  sold-as flights shown as secondary/codeshare detail.
- Aircraft type display stays compact on the board, while richer aircraft,
  source, timing, live-motion, and history context stays in the detail drawer.
- Native and LAN/browser detail views continue to use the shared
  current-source intelligence model. Opening a detail panel reuses data already
  fetched or cached by Local Flight; it should not cause surprise per-row paid
  provider calls.

---

## Matrix

- Matrix setup/config is now presented as a guided "choose panel, tune preview,
  apply live config, generate main.py" workflow.
- Panel presets, startup lane, row count, weather, gate/stand, brightness,
  palette, animation, and live preview behavior are aligned across native Qt,
  LAN browser, and generated MicroPython.
- Compact Matrix FIDS headers keep weather inside the existing header space so
  small boards such as `128x128` do not lose a flight row.
- Real-world Matrix boards can show gate/stand data when available. VATSIM
  presets hide gate placeholders because that source does not provide reliable
  gate data.

---

## Mobile

- First-run mobile setup now asks whether the device should be a **LAN
  Companion** or **Standalone** install.
- LAN Companion keeps the current paired-server behavior: WebSocket updates,
  server settings/control surfaces where allowed, server-mediated reporting, and
  the full Local Flight desktop/Pi relationship.
- Standalone registers its own mobile relay install, stores its relay activation
  token and airport locally, and talks to relay `/v1/mobile/*` endpoints without
  needing a desktop or Pi on the LAN.
- Standalone is intentionally simpler: FIDS refreshes no faster than every 3
  hours, radar refreshes no faster than every 5 minutes, radar ranges are `1`,
  `3`, `5`, and `10` NM, and Matrix/Admin/server-control tools are hidden.
- Standalone History is local on the device through Expo SQLite and retains 30
  days or 1,000 rows, whichever is smaller.
- Standalone manual/crash reports go directly to the relay reporting gateway.
  Automatic reports require the mobile diagnostics choice to allow them.

---

## History, Settings, Setup

- History is a dashboard-first view: filters, KPIs, delay buckets, airline
  delay quotas, route/aircraft stats, recent flights, and clean detail panels.
- Settings is organized around normal user tasks first: airport/source,
  appearance, outputs/radar, and profiles, with diagnostics/docs/advanced
  controls tucked away.
- First-run setup is a six-step wizard with Local Flight branding, airport
  search, source choice, optional keys, diagnostics choice, and launch review.
  The LAN browser setup is supported wording-wise, not described as a lesser
  path.

---

## Data And Relay Notes

- AeroDataBox remains the staged primary real-schedule path, with AviationStack
  available as compatible sparse fill/fallback where configured.
- Community Relay remains cache-first and may keep serving the last safe shared
  airport snapshot if a live provider is slow, capped, or suspiciously sparse.
- Mobile Standalone uses the same relay provider policy as Community Relay, but
  adds stricter mobile-specific cadence and radar-range limits.
- Public client docs continue to avoid operator-only relay/admin details.

---

## Operator-Only Network Admin

The separate Network Admin console also received polish in this line:

- coarse "seen within 24h" fleet wording instead of live-online wording
- clearer disconnect/quit behavior
- idle auto-logoff
- calmer operator UI styling
- extracted relay admin SPA assets

This operator console is not part of the normal public client navigation.

---

## Release Packaging

Windows and Raspberry Pi artifacts should be built from the current `0.2.7`
tree. Older `0.2.6` artifacts and any pre-Standalone `0.2.7` artifacts should
be treated as stale after the client-polish changes.

macOS still needs its own packaging and smoke-test pass on a Mac before a full
cross-platform GitHub release.
