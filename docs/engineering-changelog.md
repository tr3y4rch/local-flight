# Local Flight engineering changelog

This tracked document records public-safe implementation history for
contributors. It is intentionally not bundled or linked as end-user help.
Private deployment records, service credentials, admin topology, artifact
hashes, and personal build identifiers belong outside Git.

## 0.6.0 engineering line

### Universal Relay Access

- Added a canonical fulfillment orchestrator that maps verified Stripe,
  AppTransaction, and Google Play one-time-product purchases onto the same
  `beacon_relay_lifetime_v1` license while rejecting unrelated support
  consumables and replaying purchases idempotently.
- Added additive, ordered Relay Access migrations for holders, licenses,
  purchases, provider events, activations, challenges, pending commits,
  delivery/notification work, provider reconciliation, and key-version
  metadata without invalidating the initial licensing schema.
- Replaced one-step receiver movement with an expiring prepare/store/commit
  activation protocol. The prior main device remains active until the receiving
  client has stored its credential and commits against the exact observed
  activation.
- Added purpose-separated versioned HMAC, license-derivation, encryption, and
  backup keyrings; raw keys, credentials, emails, store proofs, and provider
  identifiers remain outside plain database fields, logs, and operator output.
- Added source-neutral browser delivery, passwordless email protection,
  one-time key reveal, activation grants, deactivation, recovery rotation, and
  notification retries without introducing accounts or passwords.
- Added structured access and credential states, fail-closed provider
  capability policy, purchase suspension/refund/revocation transitions, Apple
  reconciliation hooks, Google Play Billing verification/acknowledgement/RTDN
  handling, and durable reconciliation diagnostics.
- Extended the operator surface with cursor pagination, masked search and
  history, CSRF-protected actions, notification and reconciliation retry,
  unresolved-event handling, activation movement, and key rotation.

### Desktop and mobile clients

- Made desktop `data_route` authoritative across runtime, profiles, provider
  configuration, setup, and Remote Companion. Beacon Relay, Bring Your Own
  Keys, and VATSIM are the only desktop choices; the two free routes make no
  licensing calls.
- Added journaled route transitions, idempotent/pending release recovery,
  loopback-only LFRA key entry, LAN activation-code entry, hydrated reruns, and
  asynchronous native Relay checks.
- Added the prepare/store/commit flow to both desktop setup surfaces and mobile
  Standalone, including occupied-device confirmation, stale-move protection,
  terminal-state handling, and secure-write recovery.
- Made mobile setup transactional so canceled pairing, store verification, or
  activation cannot destroy a working configuration. VATSIM bypasses Relay
  Access and pending release does not block LAN Companion or VATSIM.
- Retained signed AppTransaction proof for the paid iOS app. Replaced Android
  paid-app licensing with a free-download model using Google Play Billing for
  the Relay non-consumable and request-bound Play Integrity for license moves.
- Removed Android Play Licensing/LVL behavior and its legacy permission while
  keeping optional support purchases separate.

### Release, reliability, and public surfaces

- Reframed the Beacon Tools website around the Local Flight ecosystem and one
  portable one-main-device Relay license, with live catalog-driven web/store
  availability and source-neutral passwordless management.
- Added encrypted, WAL-consistent Relay Access backup/restore tooling with
  retention planning and referenced-key validation.
- Upgraded the audited Python cryptography baseline to 50.0.1 where upstream
  wheels exist. Intel macOS retains the audited 48.0.1 wheel because 50.x is not
  published for that target and Local Flight does not use the affected PKCS#7
  decryption API.
- Promoted desktop, server, Pi, site, Worker, and native mobile metadata to
  0.6.0, with iOS build 13 and Android versionCode 16.

## 0.5.2 engineering line

### Release and platform packaging

- Promoted `pyproject.toml` to `0.5.2` across runtime metadata, HTTP identity,
  installers, Worker contracts, mobile build metadata, and bundled help, with a
  consistency test preventing current-version drift.
- Added architecture-native release jobs for Windows x64, macOS arm64/x86_64,
  Linux x86_64/aarch64, and the Raspberry Pi source bundle. Final assembly
  requires the exact artifact/checksum inventory before creating a draft
  release.
- Split macOS output into Developer ID signed, notarized, stapled packages with
  Mach-O architecture and macOS 12 deployment-target validation.
- Added portable AppImage and integrated Debian desktop packaging, including
  desktop metadata, icons, AppStream data, architecture checks, and user-home
  state retention.
- Added a Qt-free `localflight-server` freeze and Debian service package with a
  locked service account, protected environment, systemd hardening, setup-gated
  scheduling, upgrade-safe state, and no Pi-specific hostname/kiosk behavior.
- Added exact release dependency inputs and package-stage rejection for secret,
  operator, agent-context, internal-note, cache, and workstation-path material.
- Kept cryptography 49 on supported wheel targets while selecting the audited
  48.0.1 universal Intel Mac wheel after upstream removed x86-64 builds, and
  made macOS releases reject source-built dependencies before packaging.

### Runtime and compatibility

- Generic Linux native mode now opens a normal resizable window; Pi and explicit
  kiosk modes retain fullscreen behavior.
- Headless startup exposes setup and health immediately while deferring the
  scheduler until setup completion.
- A shared runtime version/User-Agent helper replaces scattered current-version
  fallbacks while retaining an explicit source-bundle fallback verified against
  `pyproject.toml`.
- Mobile moved to version 0.5.2, iOS build 9, and Android versionCode 12 without
  changing permanent application or widget identifiers.

### Security, relay, and publication

- Raised vulnerable web/request/form/image/environment dependency floors and
  pinned the relay's production set; removed an unused relay dependency.
- Added an ASGI boundary that rejects oversized or ambiguous public bug-report
  requests before multipart parsing, preserving existing upload, sanitization,
  deduplication, CORS, and network-rate protections.
- Added Fly health monitoring and gated relay deployment behind full Python,
  mobile, audit, site-contract, and container-smoke jobs.
- Expanded the public release manifest with independent architecture keys while
  preserving the legacy `macos` alias during rollout.
- Reworked public network/privacy/download wording so user choices come first
  while precise technical and legal behavior remains in contributor/policy
  detail.

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
- Relay ground context now uses authenticated, radius-aware surface/map/terrain
  snapshots, 5/10/20 NM coverage buckets, bounded major-road geometry, hybrid
  airport selection, and a disabled-by-default 30-day prewarm scheduler.
- A versioned radar-presentation contract now keeps Qt, LAN JavaScript, and
  mobile on north-zero clockwise geometry, a monotonic 15-second revolution,
  one leading line, a 72-degree fading trail, post-crossing blip visibility,
  semantic phase colors/shapes, and deterministic label priority. Selection
  is explicitly dismissible and stale asynchronous detail responses cannot
  reopen a cleared native card.
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
- The native footer gives GitHub and Beacon Tools separate, correctly routed
  actions rather than sharing one destination.

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
