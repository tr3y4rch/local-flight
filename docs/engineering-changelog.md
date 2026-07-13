# Local Flight engineering changelog

This tracked document records public-safe implementation history for
contributors. It is intentionally not bundled or linked as end-user help.
Private deployment records, service credentials, admin topology, artifact
hashes, and personal build identifiers belong outside Git.

## 0.5.1 engineering line

### Repository, privacy, and notices

- Kept `AGENTS.md` as sanitized cross-platform AI/contributor context and moved
  private operations into an ignored operator runbook.
- Split the public changelog from engineering history and excluded engineering
  notes from packaged help.
- Added fail-closed credential path classification to source packaging and
  expanded ignore coverage for signing, service-account, and token-bearing
  files.
- Hardened POSIX permissions for Local Flight identity, activation, provider,
  and Remote Companion secret storage.
- Replaced raw client-visible install UUIDs and expanded storage paths with a
  public Support ID and logical storage path.
- Added a shared sanitized notice schema, bounded in-memory diagnostics registry,
  API mappers, and Qt/browser/mobile renderers.

### Desktop and Raspberry Pi

- Native remains the primary desktop shell; LAN browser UI remains a permanent
  supported surface and Pi/headless access path.
- Setup and re-setup now treat the Local Flight-owned `.env` as authoritative
  for provider and relay keys and clear mode-specific state when switching
  between relay, BYOK, and VATSIM.
- Native setup transitions no longer terminate the backend while moving from the
  setup window into the main shell.
- Browser clock rendering follows the configured airport timezone.
- Windows/macOS packaged launchers stay quiet while explicit development
  launchers retain console output.

### FIDS, radar, History, and Matrix

- Schedule fusion prefers AeroDataBox, uses AviationStack for sparse fill or
  fallback, preserves provider evidence, and can keep a safe stale merged board.
- FIDS deduplication prioritizes operating flights and folds linked marketed
  flights into codeshare detail.
- Classic, PAX, VATSIM, and Nerd native FIDS styles vary layout, density,
  typography, chrome, status vocabulary, and responsive columns.
- VATSIM payloads suppress passenger-only and person-identifying fields across
  FIDS, radar, Matrix, mobile, and details.
- Radar uses shared normalization/classification, range-aware surface/airborne
  filtering, optional surface/map/terrain context, and conservative derived
  motion labels.
- History stores raw observations but reports deduplicated movements and shared
  analytics across native, browser, and mobile.
- Matrix V4 aligns local time, display labels, weather icons, wide-board layout,
  real-only gate data, animation modes, connected-board mirror state, and stale
  renderer warnings.

### Mobile, widgets, and purchases

- Mobile supports LAN-first Companion with encrypted Remote Companion fallback
  and a separate rate-limited Standalone path.
- Companion uses Board/Radar/History/Control; Standalone uses
  Board/Radar/History/Settings and omits host-control/Matrix/Admin features.
- Standalone history uses Expo SQLite with movement deduplication and bounded
  retention.
- iOS WidgetKit and Android AppWidget templates consume the same bounded,
  stale-aware, network-free snapshot.
- Optional consumable support products use store-localized prices, finish only
  after relay verification, and create no entitlement.
- Mobile metadata uses the permanent Beacon-owned application identifiers and
  keeps store privacy/review notes beside the Expo project.

### Relay and public site

- Shared schedule admission is cache-first with per-install and aggregate safety
  limits, upstream provider caps, coalescing, and stale-if-error behavior.
- Remote Companion uses explicit grants, AES-GCM envelopes, host-side route
  allowlisting, replay/rate/pending controls, and no offline command queue.
- Heartbeats remain low-frequency, eligibility-gated, silent-failure, and
  limited to coarse compatibility/capacity metadata.
- Admin APIs use fingerprints and opaque action references rather than raw
  install IDs or credentials.
- Public support/contact forms are sanitized, capped, rate-limited, and routed
  separately from private operator tooling.
- The Cloudflare Worker exposes a sanitized GitHub release manifest; download
  cards require version-matched artifacts and checksum companions.

## Historical engineering milestones

- `0.2.8`: LAN/native parity planning, store identity, widget scaffold,
  provider-key controls, privacy hardening, and release preparation later folded
  into `0.5.1`.
- `0.2.7`: native visual refresh, FIDS styles, Beacon Tools public home, mobile
  Companion/Standalone split, movement History, Matrix V4, and LAN responsive
  layouts.
- `0.2.6`: native/browser feature parity for History, Matrix, Settings, setup,
  radar, and flight details.
- `0.2.5`: multi-client beta baseline, hosted relay, diagnostics consent, Matrix
  tooling, source installers, and initial mobile companion.
- `0.1.0–0.2.4`: initial FastAPI FIDS, sources/enrichment, platform launchers,
  history, packaging, scheduler control, and relay foundations.
