# Changelog

All notable changes to Local Flight are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.5.1] - Public release hardening

> Public desktop/Raspberry Pi release target. Mobile is store-bound after the
> Remote Companion connectivity/privacy proof pass, with Companion remote
> fallback treated as a fixed feature rather than a separate app mode.
>
> For the public-facing summary, see
> [docs/release-notes-0.5.1.md](docs/release-notes-0.5.1.md).

### Release hardening
- Bumped durable app, native, relay, installer, and mobile metadata to `0.5.1`.
- Cleared the known regression slice around browser airport-local clocks, mobile
  setup copy, preview gallery/card count, Beacon Tools brand placement, macOS
  installer portability tests, and AviationStack fair-fetch metadata.
- Hardened first-run/re-setup provider-mode transitions so BYOK, managed relay,
  community relay, and virtual modes clear stale Local Flight-owned provider
  env state consistently.
- Made `.env` authoritative for provider/relay keys across startup, setup
  completion, scheduler restarts, and provider status while keeping log
  redaction conservative about stale process secrets.
- Added a native Qt lifecycle guard so internal setup-window transitions cannot
  accidentally shut down the backend host process.
- Updated Expo SDK 55 patch dependencies to the versions expected by Expo Doctor
  without forcing a breaking SDK upgrade.
- Hardened Remote Companion as the store-ready mobile fallback: LAN-first
  transport, encrypted relay envelopes, explicit grants/revocation, relay
  envelope/rate/pending limits, host dispatcher allowlist coverage, and
  privacy-proof tests that keep decrypted payloads and AES secrets out of relay
  storage/logs.

### Public docs and site
- Promoted the preliminary `0.2.8` notes into the `0.5.1` public hardening line
  for desktop/Pi release readiness.
- Updated README, install guidance, display-mode copy, Beacon Tools homepage,
  Local Flight product page, and support form placeholders to use `0.5.1`.
- Kept the versioned `0.2.7` preview PNG filenames as historical screenshot
  asset names while using the stable public-site preview aliases for Beacon
  Tools pages.

### Mobile store readiness
- Kept the permanent Beacon-owned mobile IDs:
  `cc.beacontools.localflight` for both iOS and Android.
- Kept first store build counters at iOS build `1` and Android versionCode `1`
  unless a store upload has already consumed those counters.
- Preserved the Standalone reviewer path and Companion path while making Remote
  Companion a normal paired-host fallback. Support tips/IAP remain disabled for
  this pass.

---

## [0.2.8] - Preliminary

> Historical preliminary notes after the `0.2.7` release candidate. This work
> has now been promoted into the `0.5.1` public hardening line; this section is
> kept so the intermediate development trail remains readable.
>
> For the public-facing summary, see
> [docs/release-notes-0.2.8.md](docs/release-notes-0.2.8.md).

### LAN client and native shell parity
- Brought the LAN browser Settings page back into parity with the native Qt shell.
- Moved Outputs/Radar and Profiles into collapsed folder cards by default, matching the calmer Qt Settings dashboard rhythm.
- Added the same folder order used by the native shell: Outputs & Radar, Profiles, Pair Mobile, Advanced board timing, Maintenance, Relay details, and Diagnostics & Docs.
- Added browser-side Pair Mobile pairing controls with reusable QR, preferred LAN URL, manual URL fallbacks, server fingerprint, paired-device refresh, copy-link/copy-URL actions, and reset paired devices.
- Updated the LAN Settings status strip to follow the Qt client-state shape more closely: Airport, Data, Refresh, Relay, and Surface.
- Started unifying the LAN FIDS, Display, and Radar chrome with the newer Settings/native shell language so stale top bars and mismatched utility controls do not drift from the release UI.
- Hardened the setup-reset path so rerunning setup from Settings can close the running shell and launch the wizard directly instead of requiring a manual app relaunch.
- Tightened the desktop/Qt setup wizard window so first-run pages keep their primary guidance and buttons visible, with shorter transient feedback instead of sticky bottom messages.

### Mobile IA, setup, and visual polish
- Reworked the mobile airport hero into one shared top rail: Board keeps the full airport hero underneath, while Radar, History, Control, and Settings use the compact companion rail.
- Aligned the app title and UTC/LT clock, centered compact and expanded weather blocks, added board-only fuller weather, and made compact pinned-flight summaries include at-a-glance flight/status data.
- Made the airport hero behavior consistent across LAN Companion and Standalone modes, including airport-local LT clock handling and compact header behavior.
- Rebuilt LAN Companion Control and Standalone Settings around the same low-noise IA: top-level rows either open a sheet directly or expand inline, but no longer mix sheet launchers inside accordion bodies.
- Folded LAN Help into Control, kept standalone help/settings separate where appropriate, preserved the support/tip footer, and removed duplicated settings/help paths.
- Polished Matrix controls, appearance controls, and pull-up sheets so titles, chip grids, palettes, and live-board controls no longer crowd or visually scrape each other.
- Added a shared `Widgets & Glances` settings path to both mobile modes as a design/preview surface for future widgets and Live Activities.
- Updated the mobile launch overlay and setup flow with the newer beacon/splash language, a ready-gated enter state, compact setup rail after the welcome step, keyboard-safe setup pages, reduced-motion-aware transitions, and a lower main bottom nav.

### Mobile store readiness and Android scaffold
- Locked the mobile store identity to Beacon-owned IDs before first upload: iOS bundle ID and Android package are both `cc.beacontools.localflight`, with first store build counters starting at `1`.
- Added Android local-dev pathing and commands for Android Studio, `adb`, emulator/device runs, debug install conflicts, and Expo/Gradle build expectations.
- Added EAS beta release scaffold notes for TestFlight and Play Internal Testing, package-ID permanence, release-manifest review, cleartext LAN HTTP expectations, and Play Data Safety preparation.
- Updated mobile store/readiness docs around App Store review notes, Play Store review notes, privacy/support URLs, LAN/camera permission explanations, and support-stub copy.
- Kept real IAP, StoreKit, Google Play Billing, Apple Developer ID credentials, and Play Console credentials explicitly out of this preliminary slice.

### iOS widgets, Live Activities, and snapshot contract prep
- Added a design-only iOS widget and Dynamic Island spec covering small pinned-flight widgets, medium FIDS-style board widgets, compact/expanded Live Activities, empty/stale states, and the future data contract.
- Added widget preview documentation and refreshed the static SVG preview to follow the horizontal mobile FIDS visual language, with small widget as a pinned-flight tracker and medium widget as a clean board preview.
- Added pre-entitlement widget skeleton files and README guidance for the future Apple Developer/App Group/WidgetKit/ActivityKit wiring pass.
- Added mobile widget snapshot helpers and storage scaffolding so the Expo app can prepare bounded, stale-aware, network-free widget data before native extension wiring exists.
- Kept the widget extension path intentionally read-only and network-free by design; no App Groups, native targets, APNs, or ActivityKit entitlements are wired yet.

### Backend provider keys and private-network hardening
- Promoted AeroDataBox into the real first-run/settings API key flow alongside AviationStack, ADS-B Exchange/RapidAPI, and OpenSky instead of leaving it as an implicit env-only backend option.
- Hardened BYOK behavior so direct schedule keys mean a private/direct provider path: AeroDataBox is preferred when present, AviationStack remains fallback/fill, and stale relay credentials are cleared when switching modes.
- Added provider-key status, save/clear, and test plumbing with redacted status output, explicit `active_path`/`privacy_posture` fields, and OpenSky test parity.
- Added secrecy regressions so provider keys do not leak through status JSON, admin/mobile config, rendered settings HTML, reports, log-tail responses, or diagnostics payloads.
- Split radar surface behavior into explicit non-relay/relay choices so `off`, `estimated`, and relay-cache behavior can be reasoned about without surprise network hops.
- Reinforced BYOK radar privacy: schedule BYOK without RapidAPI uses snapshot/OpenSky fallback and must not silently call the ADS-B relay.

### Relay, reporting, and diagnostics hardening
- Refreshed relay/client compatibility notes around standalone mobile endpoints, mobile summaries, FIDS/radar/metar paths, activation/check-in behavior, and report forwarding.
- Hardened report payload metadata so Linear/mobile reports carry OS family and app mode (`lan_companion` vs `standalone`) without exposing provider secrets or raw local paths.
- Clarified heartbeat/privacy behavior for BYOK, relay, virtual, and standalone paths so relay presence remains coarse, non-blocking, and eligibility-gated.
- Continued separating public support/contact/report routes from operator-only Network Admin routes and secrets.

### Documentation and preview planning
- Added preliminary `0.2.8` release notes before this work was promoted into the `0.5.1` hardening line.
- Documented `assets/previews/mobile/iOS/`, `assets/previews/mobile/Android/`, and `assets/previews/shell/` as the source hierarchy for public screenshots and website imagery.
- Captured the preview priority order for public docs/site imagery: FIDS, Radar, History, Setup, Display, Splash.
- Updated mobile documentation to point store/review/support/privacy flows at the Beacon Tools public website, including mobile trust, support, network, privacy, and privacy-choice pages.
- Clarified the Beacon Tools production deploy path: the public site is served by the Cloudflare Worker + Assets deploy, while dashboard `.dev` previews do not automatically update the custom domain.

### macOS installer path
- Added a signed/notarized macOS `.pkg` release path for DAU-facing installs.
- The package installs only `Local Flight.app` into Applications and preserves local settings, history, logs, install identity, and activation tokens.
- Kept source checkout launchers and source-built `~/Applications/LocalFlight.app` documented as developer/testing paths, not public release paths.

---

## [0.2.7]

> Client-polish release-candidate pass on top of the `0.2.6` baseline.
> This release folds in the native GUI visual-refresh work: unified setup and
> shell styling, animated stepper, rotating spinner, page-fade transitions,
> status pills, toasts, info bubbles, color emoji nav glyphs, and four FIDS
> board styles (Classic / PAX / VATSIM / Nerd), plus the new mobile LAN
> Companion / Standalone split.
>
> Late in the cycle the release also picked up a visual-language
> pass that finishes earlier work: the four FIDS preset skins now actually
> render distinct designs and scale with the viewport, the Settings page
> replaces its bland checkbox-titled sections with proper disclosure cards,
> the LAN browser UI gets a mirror-image of the Qt top nav, a real mobile
> view for phones, and a dedicated 7-inch Pi screen layout.
>
> For the user-facing summary, see [docs/release-notes-0.2.7.md](docs/release-notes-0.2.7.md).

### Beacon Tools public home
- Beacon Tools is now the public home for Local Flight at `https://beacontools.cc/local-flight`, with the public privacy policy at `https://beacontools.cc/privacy`.
- Added a no-build Cloudflare Worker + Assets site under `site/` for the Beacon Tools home, Local Flight product page, privacy page, and `/local-flight/privacy` redirect.
- Added `relay.beacontools.cc` as the official relay hostname, moved the relay's public/admin host defaults to `relay.beacontools.cc` and `network.beacontools.cc`, and flipped client relay defaults to `https://relay.beacontools.cc` after DNS and Fly TLS were verified. The Fly.io root remains accepted for existing installs.
- Public copy now routes general/support contact through the Beacon Tools support page while keeping the privacy contact discoverable on the privacy/choices pages.
- Added public Beacon Tools support forms: a relay-backed contact form that delivers to the support mailbox and a sanitized manual bug-report form that files into Linear without exposing Linear credentials.
- Refreshed the public README, install/display guides, mobile docs, App Store/TestFlight notes, release notes, preview gallery captions, and Cloudflare public-site copy so they describe the current native, LAN browser, mobile Standalone/Companion, Matrix, History, relay, and privacy behavior.
- Replaced stale desktop preview illustrations with current Qt screenshot cards for FIDS, Radar, History, Settings, and Matrix across the README gallery and Beacon Tools site assets.
- Added the Beacon Tools website logo system, including the public-site nav mark, favicon/touch icons, and homepage lockup while keeping Local Flight app marks on product-specific panels.
- Reworded the public Network page as an end-user relay explainer and removed explicit operator/admin route copy from public navigation copy.
- Disclosed Linear as the developer triage inbox for consent-based manual reports and automatic diagnostics in the privacy documentation.
- Refreshed developer-facing handoff docs so future release/package work starts from the Beacon Tools relay defaults, current validation status, current Windows/Pi package status, macOS/mobile/Android QA notes, and Cloudflare Worker + Assets workflow.

### History movement hardening
- Added a canonical `history_movements` layer beside the raw `flights` observation table. User-facing History now counts deduped movements instead of repeated board snapshot rows.
- History windows now filter by movement `event_time` (actual time first, scheduled time second), not by when a snapshot was fetched. Future scheduled board rows no longer inflate "last 24h" history until the movement time is current.
- Repeated snapshots and linked codeshare aliases collapse into one movement with `observation_count`, while unrelated flights on the same route/time stay separate.
- `/api/history`, `/api/history/summary`, `/api/history/flight`, FIDS detail history, LAN browser History, native Qt History, Admin history stats, and mobile History copy now use movement semantics and expose raw observation counts only as diagnostics.
- Existing local `history.db` files are backfilled idempotently into `history_movements` without deleting raw observations.
- Mobile Standalone history now upserts movement rows in Expo SQLite and keeps the 30-day / 1,000-entry retention by movement instead of by repeated snapshot row.

### VATSIM display contract
- VATSIM / `source=virtual` is now treated as a pilot/ATC-style mode instead of a passenger/codeshare board. Rows are callsign-first and can expose aircraft type, flight rules, filed route/cruise, altitude, ground speed, XPDR, track state, and VATSIM freshness.
- `/api/fids` and `/api/fids/detail` now sanitize virtual rows/details before clients render them: codeshares, sold-as, marketing carrier fields, airline labels, gate/terminal/stand fields, delay chips, registrations, and ICAO24 are empty in virtual mode.
- LAN browser, native Qt, and mobile detail views now use virtual sections: VATSIM Summary, Filed Plan, Pilot Track, VATSIM Data, and Recent Sessions. Real-source flight details are unchanged.
- Matrix payloads keep the existing VATSIM gate/codeshare suppression even when fed richer virtual FIDS rows.
- Added regression coverage for VATSIM row/detail payloads, browser template guards, native Qt detail HTML, and mobile type coverage.

### Mobile QR pairing hardening
- Native Settings pairing now prefers the actual LAN IP over `localflight.local`, keeping the mDNS shortcut as a fallback for one-server LANs.
- New pairing QR links include the redacted server fingerprint. The mobile app compares that fingerprint with `/api/mobile/summary.system.install_id` before saving a scanned pairing, so a QR that resolves to another Pi/desktop is rejected instead of silently connecting to the wrong host.
- Added `DELETE /api/admin/companion` and a Qt Settings **Reset paired devices** action to clear this server's remembered mobile companion check-ins.
- Updated pairing copy in native Settings, mobile setup, and docs to recommend LAN IP / fingerprint-bound QR pairing for multi-server test networks.

### Relay identity and activation reliability
- Desktop/Pi installs now keep a versioned local identity bundle and a reset-safe local mirror so normal setup resets and dev wipes can recover the same install ID without creating duplicate relay clients.
- Setup activation is verify-first: an existing local relay token is checked before `/v1/activate` is called, preventing harmless setup refreshes from rotating tokens or adding activation noise.
- Relay errors now return stable local statuses such as `token_invalid`, `token_bound_elsewhere`, `manual_review`, `rate_limited`, and `relay_unreachable` so setup UI can show friendly repair copy instead of raw HTTP/JSON details.
- Known-install relay reissues no longer consume anonymous new-install network burst capacity; unknown new installs still go through the existing manual-review safety net.
- Managed relay auth failures now set a local cooldown before retrying, avoiding repeated scheduler noise when a stored token is stale or revoked.

### FIDS preset skins finally render their respective designs
- Classic / PAX / VATSIM / Nerd were only labels on the same board until now. The active style is now driven by a richer `FidsStyle` dataclass (`row_height`+min/max, `row_gap`, `header_height`, `padding`, `font_scale`, primary/mono font families, palette overlay, `header_kind`, `row_chrome`, `status_chip`, `Column` spec with `(key, label, weight, min_w, hide_threshold)`).
- **Classic** keeps the original rounded blue/cyan card layout with status rail and pill chips — fully unchanged for existing users.
- **PAX** uses oversized rounded cards (`card-big` chrome, 104 px base row), a "tape"-style header band, warm sky-blue + amber accent palette, friendly status verbs ("Boarding now", "Significantly late"), bigger gate badge.
- **VATSIM** uses an ATC scope chrome: flat rows on a faint green grid backdrop with a range-ring marker in the corner, monospace everywhere, callsign-first columns, square phase chip (TAXI / DESCENT / DELAY / PLAN), tighter 58 px base rows.
- **Nerd** uses a grid chrome with column separators on every row, 13 columns visible (callsign + flight + registration + altitude + ground-speed + squawk + delay + source...), 3-letter status codes (BRD / DLY / SCH), low-intensity palette.
- Geometric scaling: `FidsBoardView._viewport_scale()` returns a 1.0-centered scale factor based on viewport width (clamped 0.78–1.35), feeding both `_scaled_row_height` (per-skin clamp between `row_height_min` and `row_height_max`) and `_font_pt` (`base × font_scale × viewport_scale`). The board recomputes on every paint so the skin stays proportional when the window is resized.
- `_column_rects` now consumes `style.columns`: hides any column whose `hide_threshold` exceeds the viewport, then distributes leftover space proportionally to weight (above `min_w`). Verified across 540–2400 px viewports: Nerd drops a column at 540 px and shows all 13 by 1400 px without ever overflowing.
- `_draw_row` dispatches on `row_chrome` (`card` / `card-big` / `scope` / `grid`); `_draw_header` on `header_kind` (`pill` / `tape` / `scope` / `mono`); `_draw_status` on `status_chip` (`pill` / `pill-big` / `square` / `code`). A generic `_draw_text_cell` + `_cell_text` resolver covers the extra columns introduced by VATSIM and Nerd so adding a column to a future skin no longer needs a new draw method.
- `FidsScreen.set_fids_style()` now also calls `self.board.set_style(style)` and re-renders; `FlightBoardModel` accepts the simpler `style.model_columns` two-tuple shape.

### Settings page — disclosure cards instead of tiny checkboxes
- The bland `QGroupBox(setCheckable=True)` pattern (Relay details / Diagnostics & Docs / Maintenance / Advanced Board Timing) was replaced with a new `DisclosureCard` widget in `localflight/native/widgets.py`. The whole header bar is the toggle, with an emoji slot, bold title, muted one-line subtitle that stays visible when collapsed, and a chevron that flips ▸ / ▾.
- Each section now carries an emoji + subtitle so it self-describes without expanding: 🔗 Relay details, 📚 Diagnostics & Docs, 🔧 Maintenance, ⚙️ Advanced Board Timing.
- New QSS rules in `design.py` style `QFrame#DisclosureCard`, `QFrame#DisclosureHeader`, and the four label slots. When expanded the header takes an accent-tinted background with a divider line; the chevron turns accent.
- `SettingsScreen._collapsible_section()` keeps its `(group, body, body_layout)` return shape so existing call-sites kept working; `Advanced Board Timing` migrated from a raw `QGroupBox` to the same card so the page reads as a single consistent stack.

### LAN browser UI — new shell that mirrors the Qt desktop
- New `static/lf-shell.css` becomes the source of truth for the browser shell. Tokens are aligned 1-for-1 with `localflight/native/design.py` (bg `#080c12`, panel `#0d1520`, line `#1e3a5a`, text `#e8f0fe`, accent `#4a9eda`, cyan `#7ce7ff`); skin overrides from `skins.css` flow into the same `--lf-accent` / `--lf-accent-2` tokens so picking a skin in Settings now retints the LAN browser chrome too.
- `_nav.html` was rewritten to mirror the Qt `TopNav`: brand mark + Audiowide brand name + monospace version chip → UTC + LT clock chips → centred segmented tab group with emoji glyphs (Display 🖥, FIDS 🛫, Radar 🛰, Matrix 🟩) → operator icon-chip bar (⚙ 🛠 📅 📜 💬) with a pulsing green heartbeat → Power button with a stroke icon.
- New components for every page: `.lf-panel`, `.lf-card`, `.lf-kicker`, `.lf-section`, `.lf-disclosure` (HTML `<details>` styled to match the Qt `DisclosureCard`), `.lf-pill` + good/warn/bad variants, `.lf-btn` + primary/quiet/danger/mono. Inputs pick up the Qt focus ring (`accent` border + 3 px accent halo).
- `app.css` token palette (`--bg / --panel / --card / --input / --btn`) now uses the Qt design.py values so even legacy pages that don't use the new classes pick up the right colours.
- Stripped ~330 lines of legacy `.lf-nav` rules from inline `base.html` styles (now redundant with `lf-shell.css`). Quit modal switched to `.lf-btn-quiet` / `.lf-btn-danger`.

### LAN browser UI — mobile view for phones
- New `static/mobile.css` activates whenever `<html>` carries `lf-is-mobile`. The class is toggled by base.html JS based on either viewport width ≤ 720 px (auto) or a `?mobile=1` query (manual override, remembered in `sessionStorage` so navigation keeps it; `?mobile=0` clears).
- Top nav pins to the bottom edge as a thumb-reachable bar with `env(safe-area-inset-bottom)` for notched/home-indicator phones. The brand block + clock chips drop out (duplicated on each page header), centre tabs become a flat icon-and-caption row, and the icon bar keeps Settings + Admin (History/Logs/Report still reachable from the desktop view + Settings). Power collapses to icon-only.
- FIDS table reflows to a per-flight card stack: time column on the left, flight + airline + route stacked, status pill top-right, gate badge on a meta row. Status colour rides a left accent rail on each card. Narrower-phone tightening at ≤520 px and ≤380 px.
- Settings / Admin / Setup multi-column grids stack to a single column. Inputs become 16 px + 44 px minimum height (prevents iOS Safari focus-zoom). `<pre>` / `.logbox` wrap instead of horizontal-scrolling.
- Radar / Matrix / Display panes stack their sidebars and resize their canvases to viewport width.
- Updated viewport meta to `viewport-fit=cover` and added PWA meta tags (`apple-mobile-web-app-capable`, `theme-color` for dark/light). A small `window.lfMobileSet(true/false)` helper is exposed for future toggles.

### LAN browser UI — 7-inch Pi screen compact layout
- Added a "compact landscape" tier keyed on viewport **height** (not width), since the official Pi 7" screen is 800×480 and common 7" IPS panels are 1024×600 — short, not narrow.
- `@media (max-height: 600px)` tightens shell-wide chrome: nav padding 48 px (was 60), brand mark 22 px, LT clock chip hidden, smaller tabs / icon buttons / power, page padding 12 px (was 22), panel padding 12 px, disclosure header padding tightened.
- `@media (max-width: 1024px) and (max-height: 600px)` drops the brand text (logo mark stays as the home link) and hides History/Logs/Report from the icon bar so the centre tabs + Settings/Admin chips fit unscrolled.
- `@media (max-width: 880px) and (max-height: 520px)` (the official Pi 7"): strips the UTC chip and shrinks tab padding.
- `fids.html` got matching page-level compact rules: row height 40 px (was 52), `fids-hhmm` 1.02 rem (was 1.18), tighter METAR bar, narrower time/flight/gate/status columns. At Pi 7" the A/C column is hidden (least actionable for a kiosk display). Net effect: 8 flights visible at 800×480 (was 5), 11 at 1024×600.
- `settings.html` got matching compact rules: 1.1 rem title (down from 1.45–2.1 rem `clamp`), 12 px-radius cards, 5-card status strip collapses to 3 columns at Pi 7".

### Files added
- `docs/previews/mobile-fids-preview.svg`, `mobile-radar-preview.svg`, `mobile-history-preview.svg`, `mobile-settings-preview.svg` — refreshed mobile showcase illustrations for README/gallery use.
- `src/localflight/native/widgets.py` — new `DisclosureCard` factory.
- `src/localflight/ui/static/lf-shell.css` — Qt-aligned browser shell.
- `src/localflight/ui/static/mobile.css` — mobile / compact view.

### Files updated
- `src/localflight/native/pages/fids_styles.py` — richer `FidsStyle` dataclass, four reworked presets with distinct visual identity + layout primitives.
- `src/localflight/native/pages/fids.py` — `FidsBoardView` now skin-aware (geometric scaling, dispatch per chrome/header/chip, generic cell painter).
- `src/localflight/native/pages/settings.py` — `_collapsible_section` builds a `DisclosureCard`; Advanced Board Timing converted off raw `QGroupBox`.
- `src/localflight/native/design.py` — QSS for `QFrame#DisclosureCard` family; aligned LAN-browser color tokens stay in sync.
- `src/localflight/ui/templates/_nav.html` — Qt-shell-aligned top nav.
- `src/localflight/ui/templates/base.html` — loads `lf-shell.css` + `mobile.css`; ~330 lines of legacy nav CSS removed; PWA meta tags + `?mobile=1` JS toggle added.
- `src/localflight/ui/templates/fids.html` — compact rules at `(max-height: 600px)` + Pi 7" rules at `(max-width: 880px) and (max-height: 520px)`.
- `src/localflight/ui/templates/settings.html` — compact rules at the same break-points.
- `src/localflight/ui/static/app.css` — token palette aligned with Qt `THEME_TOKENS`.
- Removed stale versioned mobile preview SVGs that were superseded by the refreshed Board/Radar/History/Settings gallery set.

### Verification
- Qt FIDS renders verified per-skin (Classic / PAX / VATSIM / Nerd) via `QPainter` headless renders; column-rect math verified across 540 px / 900 px / 1400 px / 2400 px (no overflow; lowest-priority columns drop first); row-height interpolation verified at 640 / 1024 / 1600 / 2400 px (stays within each skin's `min`/`max`).
- LAN browser responsive layouts were verified at desktop (1400×820), 7" Pi landscape (1024×600 and 800×480), tablet (768×1024), and phone (390×844). The desktop view picks up the new Qt-shell chrome; the phone view shows the bottom-bar mobile layout; the Pi viewports show 8–11 flight rows + compact chrome without horizontal scroll. No regression on the desktop FIDS table or detail drawer.

### Native first-run setup wizard
- Replaced the row of numbered step buttons with an animated horizontal stepper: numbered circles connected by a fill line that glides as you advance, current step has a pulsing accent halo, done steps show ✓, hovering a node shows a soft ring.
- Welcome page now shows an animated hero: floating logo with concentric "radar rings" pulsing behind it and a tagline that fades in.
- Page transitions fade in for ~200 ms instead of swapping instantly.
- The thin marquee progress bar was replaced with a rotating-glyph spinner (◐◓◑◒) plus a live caption synced to the busy status.
- Every form field now has an inline `ⓘ` info bubble with extra context (display name, IATA/ICAO, timezone, AviationStack, RapidAPI, OpenSky).
- All four masked secret fields (AviationStack, RapidAPI, OpenSky secret, activation token) have a 👁/🙈 eye toggle.
- Nav and action buttons carry emoji prefixes for clarity: 🚀 Start setup · ▶ Next · ◀ Back · ✅ Finish · 🌐 Open LAN browser setup · 📨 Request activation · 🔄 Check relay status · 🧪 Test token / Test AviationStack / Test RapidAPI · 🔗 every provider link.
- "Start setup" / "Next" / "Finish" carry a new `SetupPrimary` object name so they pop visually over the muted/Quiet buttons.
- Source option cards (Local Flight Relay / BYOK / VATSIM) now hover-lift with an accent border glow.
- Hitting Finish plays a 260 ms ✅ celebration overlay before handing off to the main app.
- Setup-guidance descriptors got real emoji icons (📺 / 📡 / 🔐 for welcome; 📡 / 🔑 / 🛩 for source; ✋ / 💥 / 📜 for diagnostics).

### Native main shell — unified design language
- Page switching now fades the old page out and the new page in (`fade_swap` in `shell_widgets.py`).
- The `_loading_indicator` factory used by every utility page now returns the same rotating-glyph spinner the setup wizard uses.
- New `shell_widgets.py` module: `make_pill`, `set_pill`, `make_spinner`, `make_info_button`, `make_page_hero`, `show_toast`, `fade_swap` — reusable across every page.
- Admin / History / Logs / Feedback / Requests pages now use a unified `PageHero` band: emoji + title + subtitle + inline `ⓘ` info bubble + "Last refreshed HH:MM:SS" pill + status pill + action buttons on the right.
- Toast notifications slide in from the bottom-right on Admin / History / Logs / Feedback / Requests refresh and on Feedback submit, then auto-fade.
- Status chips/pills consolidated into a single `Pill[tone="good|warn|bad|info|muted"]` QSS look across pages.
- Top nav: power button keeps `⏻`, sync dot keeps `●`, but the compact "More" menu now uses `⋯` instead of `☰` to avoid colliding with the FIDS nav glyph.
- The brand-mark fallback (when the logo SVG is missing) is now `🛫` instead of `*`.

### FIDS board — four switchable styles
- New `fids_styles.py` module with descriptors for four board layouts: **Classic** (default — the original Local Flight board, unchanged behavior for upgrades), **PAX** (passenger-friendly: bigger rows, friendly status verbs like "Boarding now" / "Running late", high-contrast colors), **VATSIM** (sim-network: callsign-first, flight rules, phase TAXI/CLIMB/CRUISE/DESCENT, alt/GS compact field), **Nerd** (dense operator view: every available column, monospace, code-style status tokens like BRD/DEP/LND/CXL).
- 4-segment selector in the FIDS header (🛬 Classic · 🧳 PAX · 🛩 VATSIM · 🤓 Nerd) with hover and checked states.
- Active style persists per-install via `QSettings("LocalFlight", "Native").value("fids/style", ...)`. Fresh installs default to Classic so existing users see no change.
- `FlightBoardModel` is now style-aware: takes `columns` and `status_vocabulary` per instance, gained `set_columns()` and `set_status_vocabulary()`; status text routes through `translate_status` to produce friendly / phase / code variants when not in Classic.
- `_display_value` handles the new column keys used by PAX/VATSIM/Nerd: `callsign`, `flight_display`, `registration`, `altitude_ft`, `ground_speed_kt`, `alt_speed` (formatted `FL120 / 412kt`), `squawk`, `flight_rules`, `phase`, `delay_label`, `source`.
- The native FIDS painter now uses the active style for row height, row gap, responsive column weights, hide thresholds, font families, header chrome, row chrome, status chip shape, and palette overlays.
- Classic/PAX/VATSIM/Nerd now look meaningfully different instead of being only column presets: rounded Local Flight cards, passenger-size cards, ATC-scope green grid, and dense operator rows respectively.

### Icons, glyphs, and official brand assets
- Centralised three emoji dicts in `design.py`: `NAV_GLYPHS` (page nav), `WEATHER_EMOJI` (weather strip — single source of truth replacing three duplicates), `SECTION_EMOJI` (31 entries for section headers, status cards, FIDS row icons, setup option cards). Plus a `paint_emoji` helper that renders emoji into a `QPainter` rect using Segoe UI Emoji.
- Replaced the obscure-Unicode `NAV_GLYPHS` (`◴` / `≡` / `▣` / `≋` / `⇁`) with color emoji per page: 📺 Display · 🛫 FIDS · 🛰 Radar · 🟩 Matrix · ⚙️ Settings · 🛠 Admin · 📅 History · 📜 Logs · 💬 Feedback · 🔧 Setup.
- Weather strip glyphs now use color emoji (☀️ ⛅ ☁️ 🌧 ❄️ 🌫 ⛈ 🌬 🧊 ❓) from a single dict — previously duplicated in `fids.py`, `radar.py`, and `_legacy_app.py`.
- FIDS row icons (aircraft / gate / route / clock / codeshare / arrival / departure) now render color emoji via `paint_emoji` instead of monochrome QPainter shapes.
- Settings page status-card icons (airport / source / clock / relay / radar / palette / profile / docs) now render color emoji in the existing rounded accent badges.
- Section headers across Admin / History / Logs / Feedback / Requests / Settings carry emoji prefixes for instant scanability.
- **Official brand assets** bundled in `src/localflight/ui/static/`:
  - `support-repository.svg` — official GitHub Invertocat (white) for the dark theme footer button.
  - `support-repository-dark.svg` — official GitHub Invertocat (black) for the light theme footer button. Auto-selected by `_apply_design_from_config` on theme change.
  - `support-coffee.svg` — official Buy Me a Coffee cup logo.
  - `support-coffee-button.svg` — official BMC button SVG (available for any larger CTA placement).

### QSS additions in `design.py`
- `QFrame#Pill` plus `[tone="good|warn|bad|info"]` — single rounded chip used everywhere.
- `QFrame#PageHero`, `QLabel#PageHeroEmoji`, `QLabel#PageHeroTitle`, `QLabel#PageHeroSubtitle` — unified page header band.
- `QFrame#ShellSpinner`, `QFrame#SetupSpinner` — accent-tinted card around the rotating glyph.
- `QToolButton#ShellInfoButton`, `QToolButton#SetupInfoButton` — small accent-tinted ⓘ helpers with hover state.
- `QToolButton#SetupEyeButton` — squared eye toggle for password fields.
- `QFrame#ShellToast` plus `[tone="*"]` — bottom-right transient notification with soft tinted border.
- `QPushButton#PrimaryCTA`, `QPushButton#SetupPrimary` — solid-accent call-to-action with contrast-correct text, hover lift, and disabled state.
- `QPushButton#FidsStyleButton` — segmented selector for the FIDS style choice.
- `QFrame#SetupOptionCard:hover` — accent tint + glowing border on hover; deeper state when `selected="true"`.
- `QLabel#SetupStepCaption`, `QLabel#SetupFieldLabel` — uppercase BOARD-font step caption and bolder form field labels.

### Files added
- `src/localflight/native/shell_widgets.py` — shared visual primitives for the main shell.
- `src/localflight/native/pages/setup_widgets.py` — setup-wizard widgets (stepper, hero, spinner, info button, celebration overlay, page-fade helper).
- `src/localflight/native/pages/fids_styles.py` — `FidsStyle` dataclass + `CLASSIC` / `PAX` / `VATSIM` / `NERD` descriptors + `translate_status` helper.
- `mobile/src/components/Brand.tsx` — shared mobile wordmark/kicker components so launch and setup surfaces use the bundled brand font consistently.
- `start.command` — double-clickable macOS source-checkout launcher that mirrors `start.bat` for local native/browser/headless development.
- `src/localflight/ui/static/support-repository.svg`, `support-repository-dark.svg`, `support-coffee.svg`, `support-coffee-button.svg` — official GitHub + Buy Me a Coffee brand assets.

### Native client layout and data polish
- Reworked the native top bar into three clear groups: brand and primary pages, centered UTC/LT clock divider, then utility pages, sync indicator, and Power.
- Replaced the large live-status banner with a tooltip-only sync dot and restored the footer to `v0.2.7 - Local-first - private by design` plus icon-only support links.
- Rebuilt the FIDS header around a city/country airport hero, passenger-friendly weather, and readable ARR/DEP/Refresh actions.
- FIDS display titles now intentionally show city and country only; long formal airport names and IATA/ICAO descriptors stay out of the main passenger board.
- Weather on the main board now favors friendly condition, temperature, and visibility wording instead of raw METAR fragments.

### Mobile LAN Companion and Standalone mode
- The Expo mobile app now has a first-run mode choice: **LAN Companion** for a trimmed remote and glance view of an existing desktop/Pi host, or **Standalone** for a simplified relay-backed phone board.
- Standalone setup creates a separate mobile relay install UUID, requests an activation token with `requested_mode=mobile_standalone`, stores the token/airport locally with SecureStore, and does not require a LAN server URL.
- Added relay endpoints for standalone mobile airport search/resolve, summary, FIDS, radar, and METAR data. These endpoints require `install_id`, `activation_token`, `app_version`, and `client_kind=mobile_standalone`.
- Standalone product limits are enforced on both sides: 3-hour minimum FIDS freshness, 5-minute radar refresh cache, and radar ranges limited to `1`, `3`, `5`, and `10` NM.
- Standalone hides WebSocket, Matrix, Admin, scheduler restart, LAN server controls, and companion check-in surfaces. The mobile bottom nav becomes Board, Radar, History, and Settings.
- Standalone History now uses Expo SQLite on-device storage and prunes to 30 days or 1,000 deduped movements. No relay-side per-install flight history was added.
- Standalone manual/crash reports post directly to relay `/v1/reports`; automatic standalone reports require the mobile diagnostics choice to be `auto` or `auto_logs`.
- LAN Companion behavior remains paired to the local desktop/Pi server, including WebSocket refresh, local host status/control, Help & Reports inside Control, safe Matrix live-remote controls, and mobile/server double-consent for automatic diagnostics.
- The mobile launch overlay now uses shared brand text components, an independent continuous radar sweep, status text cross-fade, breathing status dot, and blinking amber board LED.
- Mobile screen interactions gained small native-feeling polish: haptics on key taps, press-scale chips/buttons, animated weather icon swaps, and a soft live glow around the pinned-flight island.

### FIDS, Details, Matrix, Settings
- Operating-first flight identity is now the board rule, so the main FIDS row favors the operating carrier while marketed/codeshare identities remain visible as sold-as detail.
- AeroDataBox `codeshareStatus` evidence is now preserved before dedupe. `IsOperator` rows win the primary board identity, linked `IsCodeshared` rows collapse into sold-as/codeshare detail, and same-route/time rows without provider linkage stay separate.
- Aircraft types stay compact on the FIDS board while fuller aircraft/source detail is kept in the click-through detail surfaces.
- Matrix configuration now uses a guided i75W/HUB75 workflow with panel presets, connected-board mirror preview, v4 renderer/geometry warnings, live settings parity, compact weather headers, local-time clock fixes, full-width wide-board layout, real-only gate display, split-flap/typewriter/cascade motion, stable Matrix-specific display labels, Matrix-safe weather icons, and generated MicroPython `main.py` parity.
- History, Settings, Setup, and Matrix are aligned around dashboard-card layouts in native Qt and LAN/browser surfaces.
- Native and LAN FIDS/Radar/History/Matrix detail surfaces share the current-source flight intelligence model without adding per-click provider calls.

### Network Admin (operator-only)
- Reframed fleet/overview copy as coarse heartbeat presence, not live online status. "Seen <=24h" replaces "Active installs" wherever the count referred to a 24-hour last-seen window. Applies to both the HTML admin SPA and the native Qt console.
- Added a proper operator sign-out flow for browser-based Network Admin sessions.
- Idle auto-logoff now works on both Network Admin surfaces. The browser console warns before signing out; the Qt console clears the session silently and shows a status message.
- Native Qt console gained explicit Disconnect (clear credentials, return to login state) and Quit (`QApplication.quit()`) buttons. Hero split into a connection row and a controls row; removed the decorative `MONITOR / INVESTIGATE / OPERATE` chip.
- Stripped visual decoration on both surfaces: dropped CRT scanline overlay, glow underlines, shimmer overlays, multi-stop body and panel gradients, tri-color brand mark. Calmer shared palette with accents only on hover / focus / checked states.

### Relay
- Extracted the admin SPA from `relay/main.py` into `relay/admin/{admin.html,admin.css,admin.js}`, loaded once at module import with `__BOOT__` / `__ADMIN_CSS__` / `__ADMIN_JS__` substitution. No new dependency and no extra HTTP requests; render output stays byte-equivalent. The Dockerfile now copies the new asset directory into the Fly image.
- Removed ~330 lines of dead legacy admin renderer (`_render_admin_legacy`) that was no longer wired to any route.
- AeroDataBox transport now supports API.Market keys by default while preserving an explicit RapidAPI gateway mode for existing RapidAPI subscriptions.

### Privacy
- PRIVACY.md now lists the heartbeat install-profile fields explicitly (app version, OS family/version/architecture, GUI mode, source mode, diagnostics mode, companion count, matrix count) so operator-side fleet shape visibility is transparent.
- PRIVACY.md now explains the two mobile modes: LAN Companion stays server-mediated, while Standalone is relay-mediated, simplified, rate-limited, and keeps phone history local.
- VATSIM privacy rules remain strict: virtual traffic details do not expose pilot names, CIDs, controller names, server names, or other person-identifying fields.

### Deferred polish
- Not in 0.2.7: animated KPI counters on Admin/History cards, matrix flap-board boot animation, top-nav sliding underline indicator, per-page empty-state cards, custom-painted VATSIM/Nerd-only FIDS columns, style-specific delegate row sizing, and broader toast coverage for theme/save/network-state changes.

### Verification
- `python -m py_compile` clean across every modified native visual-refresh file.
- Generated stylesheet contains the new shared selectors for pills, page heroes, spinners, info buttons, toasts, primary actions, FIDS style buttons, and setup option cards.
- FIDS style registry returns `['classic', 'pax', 'vatsim', 'nerd']` with `classic` as the default.
- Current Windows/Codex validation after AeroDataBox codeshare hardening, Matrix display-integrity, and Matrix v4 live-settings/local-clock/web-preview hardening: focused Matrix regressions passed; `.venv\Scripts\python.exe -m pytest tests -q` returned `432 passed`; `.venv\Scripts\python.exe -m compileall -q src relay installers scripts tests` passed in the same release-candidate sweep; `cd mobile && npm run typecheck` passed; `git diff --check` passed.

### Mobile companion — tip jar redesign + setup wizard polish

Third targeted redesign pass focusing on the two surfaces that needed more
work after the screen audit: the tip jar (SupportSheet) and the setup wizard.

**Tip jar (SupportSheet)**:
- New `SupportTierRow` component replaces the 2×2 grid. Tiers now render as
  full-width rows with an amount chip + label + tagline + perk line + forward
  chevron. Easier to scan, less cramped on narrow phones.
- The $10 tier is highlighted with a "POPULAR" badge and amber accent ring.
- `SUPPORT_TIP_TIERS` reworked: names are now passenger-friendly
  (`Small tip`, `Nice tip`, `Generous`, `Captain`) with separate `tagline` and
  `perk` fields (e.g. "A coffee for the dev" / "Supporter badge · gold accent").
- Hero redesigned: bigger centered heart icon with soft amber glow halo,
  centered title + body, optional tagline below.
- New `supportContextStrip` shows where tips go (Servers · New features · Maintenance)
  as a horizontal row with mono-uppercase labels and dividers.
- Success card upgraded: bigger halo, divider, perk line ("Your Supporter badge
  will appear next to your airport code"), explicit Continue button so users
  can dismiss the celebration when they're ready instead of it sitting forever.
- Existing supporter banner (shown to returning supporters) now wraps the star
  in a proper badge circle for visual parity with the post-purchase card.
- Message card now flexes a small info icon next to the text and uses a blue
  tint instead of amber so it reads as informational rather than celebratory.
- Fine print compressed to a single dot-separated line.

**Setup wizard polish**:
- Text trim across all five steps: welcome / mode / server / privacy / ready
  body copy reduced by ~50 % each. Walls-of-text replaced with one-line summaries.
- New `SetupInfoBubble` collapsible "ⓘ + label + chevron" component — exposes
  technical detail on demand (What is Local Flight? · Where do I find this? ·
  What gets sent?) without cluttering the main panel copy. Each bubble springs
  open/closed with an animated chevron rotation.
- Mode cards reworded: "RECOMMENDED" / "JUST EXPLORING" badge tone instead of
  "FULL FEATURES" / "NO SERVER NEEDED". Description switched from third-person
  to first-person ("I have a Local Flight server running.").
- New `launching` step + `SetupLaunchCelebration` component: when the user taps
  LAUNCH APP, the wizard transitions to a dedicated celebration screen with
  three concentric expanding rings around a green check icon, a "You're all set"
  headline, and a green progress bar. The celebration holds for ~900 ms before
  `onComplete` fires and the main app opens.
- `hapticSuccess()` fires on the LAUNCH APP press for a richer confirmation.
- Step rail label `launching: "Launch"` added so the dedicated step has a name
  if/when it ever appears in the visible rail (currently kept out of the rail).

### Mobile companion — full UI/UX redesign (style registry + screen pass)

Second redesign pass completing the visual overhaul started in the seven-phase session above.
All changes typecheck clean. No backend changes required.

**Style registry (AppShell.tsx `createStyles`)** — 60+ new style keys wired for all
redesigned components:
- Airport hero: `airportHero`, `airportHeroTopRow/Left/Right/CodeRow`, `airportIataBadge/Text`,
  `airportIcaoText`, `airportCityName/Placeholder`, `airportChangeHint/Text`,
  `heroUtcTime/Suffix`, `heroLocalTime/Suffix`, `heroConnectionPill/Dot/Ring/Label`,
  `heroSourcePill/Text`, `heroCountPill/Text`, `heroStatusStrip`, `heroSnapshotRing`,
  `supporterBadge/BadgeText`
- Radar: `radarRangeBar/BarLabel/Chips/Chip/ChipActive`, `radarRangeChipNum/Unit/NumActive/UnitActive`,
  `radarSettingsButton`, `radarStatusBar/Item/Divider/Value/Label`,
  `radarLegendStrip/Left/Source/Dots/Item/Ground`,
  `radarSettingsRangeGrid/Item/ItemActive/Num/Unit/NumActive/UnitActive`,
  `radarSettingsLegend/Row/Label/Detail`, `radarSettingsNote`
- Support sheet: `supporterBanner/Star/Text/Title/Body`, `supportSuccessCard/Icon/Title/Body`,
  `supportTierCardDimmed`, `supportTierFooter`, `supportTierStatusDim`, `supportMessageCard`
- Settings: `settingsDiagnosticsGroup/Row/RowActive/Check/EmptyCheck/Copy/Label/LabelActive/Desc`
- History: `historyVolumeBarRow/Group/Stack/Seg/DayLabel`, `historyVolumeLegend/Item/Dot/Label`,
  `historyTruncationNote/Text`

**Bug fixes** — two TypeScript errors fixed: added `hapticSuccess` import in AppScreens.tsx;
replaced invalid `groundData?.bbox` access with `surfaceFeatureCount` (property does not exist
on `RadarMapResponse`).

**History screen**:
- `iataToFlag()` helper with ~200-airport `IATA→ISO 2` lookup table; flag emoji prepended to
  origin and destination codes in the Top Routes panel (e.g. `🇺🇸JFK›🇬🇧LHR`).
- `HistoryVolumeChart` component: stacked bar chart from `daily_volume` API data showing
  per-day departure (blue) and arrival (green) counts. Up to 14 days rendered inline
  above the KPI grid.
- Truncation notice banner: shown when `data.count > data.flights.length` (i.e. the server
  holds more records than the 120-row display cap) so users know totals are correct.

**Control/Settings screen**:
- Replaced the three-pill `settingsCompactButton` row (HIDE SERVER / AIRPORT & SOURCE /
  RESTART FETCH) with individual full-width `SettingsToolPill` rows — each shows an icon,
  label, value, and chevron.
- Removed the redundant QUICK ACTIONS `CollapsibleCard`; its entries are now in
  APPEARANCE & DISPLAY and DIAGNOSTICS sections.
- Diagnostics mode picker replaced: was a `filterRow` of small pill buttons; now renders
  as a bordered radio group with individual labelled rows (icon ✓ / empty circle + label
  + description) matching iOS Settings style.
- Sections renamed and reordered: HOST STATUS → CONNECTION → APPEARANCE & DISPLAY →
  DIAGNOSTICS for logical top-to-bottom scan order.

### Mobile companion — icon registry

- Added `mobile/src/theme/icons.tsx` — `LocalFlightIcon` component backed by a semantic icon registry (`statusIcons`, `navIcons`, `flightIcons`, `actionIcons`). All interactive UI is now keyed off semantic names rather than raw glyph strings, making skin changes and future icon swaps centralised in one place.
- Added `mobile/src/theme/weatherIcons.ts` — maps METAR decoded weather conditions to icon names, condition keys, and tone hints. Single source of truth consumed by `CompactWeatherCapsule`, `FlightIsland`, and the Admin weather hero.
- Added `mobile/src/components/Brand.tsx` — `BrandMark` component encapsulating the animated companion logo used in the setup wizard and launch overlay. Supports a `size` prop and an optional breathing-ring animation mode.

### Mobile companion — seven-phase UI/UX redesign

All seven phases are additive visual polish on the existing data contracts. No route, schema, or server-side changes required.

- **Phase 1 — Animated bottom-nav dot and press scale.** `BottomNav` now renders an animated accent dot that slides between tabs on navigation, and a spring press-scale (`usePressScale`) on every tab button. `hapticSelection` fires on tab switch.
- **Phase 2 — Haptic feedback throughout.** `hapticSuccess` fires on successful server connection; `hapticLight` fires on manual refresh; `hapticSelection` fires when opening any flight detail sheet or interactive control. Applied in the `AppShell` coordinator and screen-level action handlers.
- **Phase 3 — Press scale and haptics on every interactive row.** Every tappable row in FIDS, History, Radar, Settings, and Control now uses `usePressScale` for spring-animated press feedback. Covers `FidsRowView`, `HistoryRow`, `RadarBlipRow`, `DirectionButton`, `OptionChip`, `SettingsQuickAction`, `SettingsToolPill`, `ConnectPrompt`, and `CollapsibleCard` headers.
- **Phase 4 — Two-line FIDS time cell, delay tags, and GATE column.** Flight time cells now show the scheduled time on line 1 and an inline delay badge (`EARLY` / `+NNm` / `+NNm` in green/amber/red) on line 2 when `delay_minutes` is populated. A `GATE` column was added between `STATUS` and `ROUTE`, showing `terminal_gate_display` or a muted `—` placeholder. Column widths were rebalanced to accommodate the new column without horizontal scrolling on standard phone widths.
- **Phase 5 — History screen redesign.** The flat history list was replaced with a dashboard: a four-cell KPI grid (total flights, on-time rate, average delay, median delay), a per-airline delay-quota progress stack, and sectioned panels for top airlines, busiest routes, and aircraft-type distribution. Each panel uses `CollapsibleCard`.
- **Phase 6 — Sectioned Control screen and Help tab panels.** The Control screen was restructured into four `CollapsibleCard` sections (Schedule, Radar, Weather, Diagnostics — Diagnostics collapsed by default). The Help screen renders three tab panels (Status / Check / Report). A density toggle (Compact / Comfortable) was added to the FIDS header.
- **Phase 7 — Animated micro-interactions.** `CompactWeatherCapsule` cross-fades weather icons when the METAR condition changes (100 ms fade-out → icon swap → 220 ms fade-in via `prevIconRef`). `FlightIsland` renders an animated border glow that pulses when live data is fresh. `RadarScope` shows a rotating sweep-needle empty state (`Easing.linear`, 3 s period) when the scope contains no blips.
- Public preview artwork now covers all current mobile showcase surfaces: Board, Radar, History, and Settings/Control.

### Mobile companion — setup wizard overhaul

- Replaced the single connection screen with a full welcome-first wizard: **Welcome → Mode → Server URL (companion only) → Privacy → Ready**.
- **Welcome step** shows a breathing logo ring (2 s opacity/scale loop), the Local Flight wordmark, a tagline, and a feature chip row. Entirely new; first thing every new user sees.
- **Mode step** presents two large `SetupModeCard` components — **LAN Companion** (requires a running Local Flight server on the local network; Board/Radar/History/Control with Help & Reports inside Control plus safe Matrix live-remote features) and **Standalone** (no LAN server required; simplified relay-backed Board/Radar/History/Settings with stricter refresh limits). Each card shows a RECOMMENDED / OFFLINE badge, a description, and a feature bullet list. Cards animate via `usePressScale` and show a checkmark when selected.
- **Server URL step** (companion mode only) retains the existing URL input with an inline health-check icon (spinner → green check / red ✗ from `/api/health`) and a LAN pairing tip. Skipped entirely in standalone mode.
- **Privacy step** presents three `SetupOptionCard` options (Manual reports / Automatic crash reports / Automatic + sanitized logs) with radio-button selection and a RECOMMENDED badge on the middle option.
- **Ready step** shows an animated `SetupReadyCheck` circle (spring pop-in, stiffness 260, damping 18) confirming setup is complete, with a summary of chosen mode and diagnostics level.
- All step transitions use direction-aware spring animations — forward slides/fades in from the right, back from the left — via `stepAnim` (opacity + scale) and `stepShift` (translateY). Spring stiffness 300, damping 24.
- `SetupStepRail` renders a segmented progress rail with connector lines, numbered dots, and ✓ marks for completed steps. Step count adapts to wizard mode: 4 steps for standalone, 5 for companion.
- Standalone path saves through `completeStandaloneMobileSetupState()` in `settings.ts` and navigates directly to the FIDS board without requiring a server URL.
- `mobile/src/storage/settings.ts` gained `MobileSetupMode = "lan_companion" | "standalone"`, `completeStandaloneMobileSetupState()`, and updated `normalizeMobileSetupState` / `isMobileSetupComplete` to handle the standalone completion path correctly.

---

## [0.2.6] - 2026-05-10

> Temporary client-polish and docs target after the `0.2.5` beta baseline.
> For the user-facing summary, see [docs/release-notes-0.2.6.md](docs/release-notes-0.2.6.md).

### Client UX
- Native Qt and LAN/browser History now share the same dashboard-style analytics model: filters, KPIs, delay buckets, airline delay quotas, route/aircraft stats, sortable recent flights, and polished detail panels.
- Native Qt and LAN/browser Matrix now expose the same friendly board configurator shape with panel presets, startup lane, live preview, config save/apply feedback, Wi-Fi/server guidance, and generated `main.py` support.
- Native Qt and LAN/browser Settings now use a calmer dashboard-card structure with user-first controls, collapsed advanced/support sections, stronger theme/skin contrast, and cleaner setup/reset/resource flows.
- Native setup copy and layout now follow the same first-run guidance model as the browser setup while keeping the hosted relay root user-facing and hiding internal route details.

### Matrix
- Matrix FIDS weather no longer consumes a dedicated third header line. Compact boards such as `128x128` keep a two-line header and fit weather into the existing top area.
- Real-world Matrix FIDS can show gate/stand information from existing schedule data, including tiny-board status/gate alternation when space is tight.
- VATSIM Matrix presets intentionally hide gate placeholders because the current virtual source does not provide reliable gate data.
- Native preview, LAN browser preview, and generated MicroPython `main.py` now follow the same compact weather and gate-display policies.

### FIDS, Radar, And Details
- FIDS detail, Radar detail, History detail, Matrix compact fields, native Qt, and LAN/browser views now share a current-source flight intelligence layer built from existing schedule, radar, METAR, surface context, and local history data.
- Radar information and drawing behavior from the native client have been carried into the LAN/browser radar path so blip status, layering, surface context, and detail wording stay aligned.
- No new paid provider or surprise per-row detail fetches were added for this intelligence pass.

### Schedule Relay And Real Data
- AeroDataBox is staged as a first-class real schedule provider for hosted relay and bring-your-own-key installs, while `source=real` remains the public app mode.
- AviationStack can act as compatible sparse fill/fallback for real schedule rows, filling empty board fields without overwriting primary provider times or status.
- The schedule pipeline now has hard upstream budget guards, provider source caches, stale merged-cache serving, and canonical provider metadata for cache/fusion visibility.
- Native Qt and LAN/browser FIDS paths now have regression coverage for fused AeroDataBox/AviationStack rows compiling into the same passenger-board row shape.

### Privacy And Docs
- Public docs now describe `0.2.6` as a temporary client-polish target and keep `0.2.5` as the beta baseline it builds on.
- Privacy copy now clarifies that richer detail drawers reuse already-fetched local/server data and that Matrix gate display is real-FIDS-only, with VATSIM gate placeholders suppressed by design.
- Public docs stay focused on normal client functions and avoid exposing maintenance/admin internals.

## [0.2.5] - 2026-05-10

> Still beta, but now treated as the working multi-client release for native desktop, LAN browser UI, Pi/headless/kiosk, mobile companion, and Matrix.
> For a user-facing beta client summary, see [docs/release-notes-0.2.5.md](docs/release-notes-0.2.5.md).

### Native GUI
- Native Qt is now the recommended Windows/macOS desktop shell, backed by the same local FastAPI routes, WebSocket events, docs, config, diagnostics, and reporting controls as the LAN browser UI.
- Native FIDS now uses a composed passenger-board surface with stronger time/flight/route hierarchy, status/gate chips, codeshare rotation, loading motion, and a restyled flight-detail drawer.
- Native Radar now uses explicit drawing layers for runways, airport surface, map context, terrain/relief, grid, blips, trails, hover, and footer details.
- Native Settings now has a quieter control-room layout with explicit apply/save feedback, profile controls, radar surface status, collapsible help/diagnostics sections, and bundled local docs.
- Native first-run setup now guides users through Welcome, Airport, Data Access, Provider Keys, Diagnostics, and Finish before opening the main shell.
- Native History is now a dashboard instead of a debug table, with filter-driven KPIs, delay buckets, status mix, airline delay quotas, route/aircraft stats, sortable recent flights, and a sectioned detail drawer.

### Mobile Companion
- Mobile now has a forced first-launch companion setup gate for LAN pairing and diagnostics consent before normal FIDS/Radar/Settings access.
- Companion setup tests the Local Flight server URL, rejects phone-local `localhost`, explains LAN pairing, saves mobile diagnostics choice, and auto-migrates existing installs when possible.
- Mobile Settings is now a guided hub with connection status first and focused entry points for Mobile Look, Matrix Board, Admin & Reports, History, Docs, Privacy, resources, and setup rerun.
- Landscape rotation opens a display-only fullscreen FIDS board from any companion screen, hides chrome/actions/modals, disables screen sleep while active, and restores the previous portrait screen on rotation back.
- Mobile Radar now consumes server-mediated runway/surface geometry through `/api/radar/map` with `/api/radar/surface` compatibility behavior, while range rings and radius chips remain mobile-owned.
- Mobile docs now load bundled Markdown through the Local Flight server, not raw GitHub content from the phone.
- Mobile FIDS now has an airport-first hero header, compact passenger weather on FIDS, richer METAR/weather display on Radar, persistent weather wording preferences, and tablet-safe row/header alignment.
- Mobile crash-report dedupe now records fingerprints only after both the phone and connected server allow automatic diagnostics.

### Browser/LAN UI And Pi
- The LAN browser UI is documented and treated as a supported access/display surface for headless installs, remote viewing, tablets, browser-mode displays, and recovery.
- Raspberry Pi installs support three clear paths: headless server, native Qt HDMI kiosk, and Chromium HDMI kiosk.
- Source installers explain display-mode choices in user-facing terms instead of treating browser or kiosk paths as leftovers.
- Browser Settings now groups diagnostics, documents, and display-output copy around the current install/display model.
- Browser History now shares the same analytics contract as native History, combining filters, KPIs, CSS-only charts, recent matching movements, and a polished detail panel on one page.

### Matrix
- Matrix V2 exposes three public presets: `real_fids`, `vatsim_pilot`, and `vatsim_atc`.
- Matrix runtime, preview, generated `main.py`, and device check-in are aligned across native Qt and LAN browser UI.
- Matrix rows now preserve display-safe route/codeshare/status fields for small panels, while weather payloads expose decoded condition and temperature fields.
- The generated Interstate 75 W client supports rectangular HUB75 layouts, small-panel rotation, weather toggles, and VATSIM ATC page rotation.
- Matrix setup is now a guided board configurator in native Qt and LAN browser UI, with shared panel-combination presets, startup-lane control, live preview overrides, clearer Wi-Fi/main.py guidance, action feedback, and compact `128x128` header rendering for airport, weather, UTC, and local time.

### Radar And FIDS Contracts
- FIDS detail, Radar blip detail, History detail, native Qt, and LAN/browser views now share a current-source `flight-intel-v1` detail model that merges schedule, live motion, aircraft, operations, source confidence, and local history without adding provider calls or exposing VATSIM personal identifiers.
- `/api/radar/map` now carries runway, simplified surface/map context, optional terrain availability, attribution, and source confidence metadata while preserving `/api/radar` and `/api/radar/surface` compatibility.
- Runway drawing uses local OurAirports data when available, merges OSM/Overpass geometry when available, and uses clearly labeled estimated geometry when no reliable cache exists.
- Radar source normalization preserves useful ADS-B fields for display and classification without exposing raw provider payloads.
- FIDS rows share richer presentation fields for deltas, tones, gates, terminals, route labels, operating-flight priority, codeshares, and safe source hints.
- Schedule rendering can show nearest available real rows when a live board window would otherwise be empty, instead of presenting a dead-empty board.

### Docs And Installers
- README is now the friendly front door, with detailed install and display-mode guidance moved into focused public docs.
- In-app docs are server-mediated and bundled for native, browser, and mobile clients.
- Public copy now frames native Qt, LAN browser UI, Pi headless, native kiosk, Chromium kiosk, mobile companion, and Matrix as supported client/display choices.
- Preview illustrations now reflect the current native GUI, Matrix tooling, and mobile companion surfaces.

### Fixed
- Native Radar map and terrain overlays no longer disappear behind the grid.
- Native Radar handles OSM map points with string coordinates as well as numeric coordinate arrays.
- Runway labels and confidence text are suppressed at wider ranges to avoid clutter.
- Radar map refresh/cache handling keeps last-good context available when optional geometry sources are slow or unavailable.
- Native Settings radar-surface controls save through the same config payload as the rest of the page.
- Generated `main.py` no longer crashes when route/status values arrive as non-string JSON values.
- Matrix preview scaling now treats base HUB75 modules as rectangles, so `128x128` and `256x64` preview correctly.
- VATSIM matrix weather no longer uses real-world weather when VATSIM presets are selected.

## [0.2.5b4] - 2026-05-01

### Changed
- Community setup and source installers now show the hosted relay root URL (`https://localflight-community-relay.fly.dev`) instead of the older compatibility path ending in `/v1/flights`. The app still derives `/v1/schedule`, `/v1/radar`, `/v1/reports`, and activation routes internally.
- Relay auto-activation burst limits can now be tuned for local lab reinstall testing without changing the default production safety rails.
- FIDS rows now sort by the full airport-local timestamp, not just the visible `HH:MM`, and the table labels board times as `Time (LT)`.
- Real-data radar responses now hide aircraft that are clearly on the surface, and the radar status line reports when ground blips were filtered.
- Radar responses now switch into surface mode for 1 / 2 / 3 / 5 NM ranges, showing only aircraft that appear to be on the ground and hiding airborne/overflying blips for both real ADS-B and VATSIM.
- Radar now includes tighter 1 / 2 / 3 / 5 NM ground-radar ranges for airport-surface inspection. Tiny aircraft views now reuse the shortest practical ADS-B provider fetch radius (`5 NM`) and crop locally, while the optional surface overlay itself stays capped to a 1-5 NM ground-scale request instead of following wider aircraft radar ranges.
- Radar surface styling now follows dark/light theme and the active skin palette instead of using one generic overlay color.
- Standalone Radar now fills the available viewport below the real navigation height instead of subtracting a fixed chrome value, and its controls/weather strip compact themselves for 7-10 inch Pi screens and large wall displays.
- METAR weather is now decorated by Local Flight's own semantic decoder instead of adding another weather provider. `/api/metar` still returns the raw/decoded aviation fields, plus additive `weather_*` mood, icon, tone, summary, hazards, and chip fields for richer UI.
- `/api/metar` now tries VATSIM ATIS/METAR first in virtual mode, extracts only the raw METAR line, and falls back to AviationWeather when VATSIM weather is unavailable.
- FIDS weather now shows icon, temperature, and decoded summary only, while Radar keeps icon/category/temperature/summary plus raw METAR.
- FIDS flight rows now decode common airline IATA/ICAO prefixes into readable airline names, format public flight numbers consistently, and preserve deduped codeshare partners in the row/detail metadata.
- VATSIM radar now applies the same exact circular local range crop as real-data radar, so 1 / 2 / 3 NM virtual views do not show square-corner traffic outside the selected ring.
- GUI launch now goes through a shared native-first platform decision layer. Blank or invalid `LOCALFLIGHT_GUI_MODE` values request the PySide6/Qt shell first, then fall back to browser/kiosk only when Qt or display support is unusable; display-less Pi/Linux still runs headless.
- Windows and macOS source launchers now install/verify the native PySide6 extra before native launch; release packaging also fails early if PySide6/Qt is unavailable.
- Bug reports now include requested/effective GUI shell, display availability, Qt availability, fullscreen state, and launch-decision reason so native GUI, browser/LAN UI, and headless service reports are distinguishable inside the same two-team Linear routing model.
- Native Qt now follows the browser UI structure more closely: top navigation, version/clocks, Display/FIDS/Radar/Matrix/Settings/Admin/History/Logs/Report pages, responsive nav labels, and a quit confirmation replace the earlier side-nav prototype.
- Native FIDS, Radar, Display, Settings, Admin, History, Logs, Matrix, Setup, and Feedback now use the same local API contracts as the browser UI instead of debug JSON-only placeholders.
- Native Qt now connects directly to the local `/ws` live-push endpoint and reacts to `snapshot_updated`, `config_updated`, and `scheduler_restarted` events like the browser UI instead of relying only on fallback polling.
- Native Qt now has a browser-parity design-token layer for dark/light theme plus standard/technical/neon/cyan/crt skins. The shell reloads styling from `/api/config`, the top nav scrolls compactly on smaller displays, and FIDS/Radar/Matrix renderers use the active skin palette instead of one hardcoded cyan-dark look.
- Native Qt now reuses short-lived local GET results for high-frequency routes such as config, FIDS, radar, METAR, airport search, admin summaries, logs, and surface geometry. Mutating actions clear the cache immediately, reducing duplicate local API/database work without changing backend contracts.
- Native Qt manual reports now carry richer `native/gui` context, and diagnostics-gated native UI crashes use the same local `/api/feedback/crash` and relay `/v1/reports` path as the browser, server, and mobile reporters.
- Native first-run setup now includes a dedicated Diagnostics step, saves `diagnostics_mode` through `/api/setup/complete`, and keeps manual reports as the privacy-first default instead of leaving reporting consent unset.
- README and Privacy now describe the native Qt shell as the recommended privacy-first desktop UI while keeping the LAN browser UI as a permanent supported access/display path.
- README and Privacy now explain why native Qt is preferred for the default desktop shell: fewer browser-vendor surfaces, no webview dependency for the main window, no browser profile/sync/extensions/cookies, and clearer separation between the local display shell and intentional aviation/network data sources.
- Windows source installer now writes a client-only native `.env`, while the Pi installer writes a client-only `.env` and keeps `LOCALFLIGHT_GUI_MODE=headless` unless `--native-kiosk` is explicitly selected.

### Fixed
- Relay admin no longer crashes when a live client lane exists before a shared schedule snapshot has been created.
- Schedule snapshot counter columns are now migration-safe for older relay databases.
- Arrivals and departures that cross midnight no longer rotate into a confusing order such as tomorrow's `00:08` before today's `17:45`.
- FIDS row times now use the active airport timezone passed into the board renderer instead of falling back to whatever timezone is currently stored in the global config.
- Pi source pre-release bundles now include non-ignored local file additions as well as tracked files, preventing hardware test zips from silently missing newly added modules before a commit exists.
- Radar surface overlay no longer appears broken on a clean first run when the relay surface cache is disabled or empty. If no cached OSM geometry is available yet, the radar now draws a clearly labeled local estimated airport surface instead of silently rendering nothing.
- Native History stats no longer deletes and reuses its own period selector during refreshes, avoiding a Qt lifecycle crash after interacting with the stats tab.
- Native traffic/log/report controls now have declared routes and constructor coverage so user-visible buttons are less likely to drift into no-op placeholders.
- Native first-run completion now opens the Display page and prompts for the same diagnostics/reporting choice when diagnostics mode is still unset, keeping bug reporting consent behavior aligned with the browser shell.
- Native WebSocket shutdown now tolerates Qt deleting the socket during app/test teardown, avoiding an ugly finalizer traceback after otherwise successful native constructor tests.
- Native Radar and Matrix canvases now pause their animation timers while hidden, Radar sweep runs at a lighter cadence, active page polling backs off to 30 seconds, and airport search avoids repeating the same query while typing.
- Native report routing now maps `native/gui` issues to the desktop/user report bucket instead of letting UI exceptions look like server-only crashes.
- Pi `lf update` no longer switches into native dependency installs merely because PySide6 happens to be importable; it now follows the explicit Pi GUI mode in `.env`.

### Added
- Hosted relay maintenance now has a clean setup-trial action that clears transient request logs, activation-review rows, live client lanes, shared schedule snapshots, and report-event clutter while keeping provider keys, managed tokens, blocked installs, and usage counters intact.
- FIDS now shows a neutral schedule-fetching hint while an empty board may still be waiting on the relay/shared schedule warmup.
- Radar now has a staged, opt-in airport surface overlay using relay-cached OpenStreetMap/Overpass geometry through `GET /api/radar/surface` and relay `GET /v1/airport-surface`. The overlay draws runways, taxiways, aprons, terminals, airport boundaries, selected terminal/hangar-style building outlines, and visible OSM attribution without using public raster tile servers. It is disabled by default locally and requires explicit relay operator enablement via `RELAY_AIRPORT_SURFACE_ENABLED=1`.
- FIDS, Radar, and Admin now render the METAR-derived weather mood with compact weather-app-style icons, colored tone treatments, and local summaries while preserving raw METAR visibility.
- Chrome-free native UI is now the default requested shell for desktop/source/release builds; `LOCALFLIGHT_GUI_MODE=browser` remains an explicit supported browser-display/debug override.
- Raspberry Pi installs still run headless without a display, keep the Chromium kiosk display available through `--kiosk`, and add a `--native-kiosk` path that installs Qt runtime packages, verifies PySide6/Qt, and starts Local Flight as a fullscreen native shell on the attached display.
- Native first-run setup now has a real wizard for airport search, community/BYOK/managed/virtual source selection, relay activation checks, API key tests, and setup completion without opening a browser.
- Native Matrix now has a LED-style canvas preview, panel/zoom/brightness/runtime controls, config save, and MicroPython script generation.
- Native Logs now has log-file selection, refresh, live tail, scroll-to-bottom, line counts, and last-update metadata. Native Admin can open the local anonymized traffic log as a user-facing tool.

## [0.2.5b3] - 2026-05-01

### Added
- Shared relay schedule snapshots for community and managed installs via `GET /v1/schedule`, so the relay can fan out one upstream AviationStack refresh to many clients watching the same airport window.
- Relay-side schedule cache metadata and savings stats in admin/settings payloads, including shared access counts, upstream pull counts, cache-hit rate, and estimated savings.
- AviationStack audit script (`scripts/audit_aviationstack.py`) for comparing baseline, paginated, and fair windowed fetch strategies across a global airport sample.
- Configurable board-density controls for real-data fairness and overflow handling: `display_grace_minutes`, `display_horizon_hours`, `web_row_limit`, `web_rotation_seconds`, and matrix page rotation.
- Relay-backed developer report gateway at `POST /v1/reports`, with Linear team routing, relay-side dedupe, rate limits, and secret redaction before Linear issue creation.
- Mobile-local diagnostics consent, stored on-device, so companion auto-reporting requires both the mobile choice and the connected server diagnostics mode to allow it.

### Changed
- AviationStack schedule fetching now uses a shared date-aware planner across BYOK, direct local relay-key use, and hosted relay-backed paths: page size `100`, airport-local date windows, and per-date pagination.
- The AviationStack planner now keeps paging past the initial production slice when a busy airport has not yet reached the visible board window, and relay-backed shared snapshots now rebuild on planner version `fair-v3`.
- Community and managed installs no longer consume raw provider JSON from the relay. They now receive Local Flight canonical records and continue the normal local normalize, enrich, history, and FIDS pipeline.
- Community relay budget wording now reflects the actual model: `LOCALFLIGHT_RELAY_MONTHLY_LIMIT` tracks per-install relay schedule accesses, while upstream AviationStack pulls are shared and counted separately on the relay.
- Web and matrix boards now rotate overflow pages locally instead of forcing a single fixed visible slice.
- When a date-scoped AviationStack board would otherwise come back empty, Local Flight now tries an undated rescue pass before surfacing that sparse result.
- Developer report submission now forwards through the hosted relay instead of shipping a developer Linear credential in the desktop/mobile package.
- Relay community traffic now has network-level and global daily safety caps on top of per-install monthly quotas, reducing abuse risk from rotated install IDs.
- Setup-provided relay URLs are now validated before the local app calls them; official relay hosts work by default, while custom/private relay roots require explicit local opt-in environment flags.
- Local browser mutations now reject cross-origin POST-style requests, blocking drive-by web pages from changing settings or triggering local actions on the LAN.
- README, Privacy, and mobile docs now explain the current relay, diagnostics, LAN trust, and mobile privacy model in plain end-user language.

### Fixed
- FIDS board filtering now uses the snapshot timestamp as its reference clock, so valid saved rows do not disappear just because the wall clock moved on while the snapshot stayed unchanged.
- When a real-data lane still has no rows inside the live display window, the board now falls back to the nearest available real flights instead of showing a completely empty departures/arrivals table.
- Matrix clients now clear stale rows when a refresh fails or returns empty data, avoiding misleading leftovers and tight retry hammering.
- Bug reports now attach truthful schedule-mode context for BYOK, direct local community-key, and shared relay snapshot paths, plus the active display window and web board density settings.
- Automatic crash deduplication is now scoped by crash context as well as message, and the mobile crash boundary copy now reflects best-effort report delivery more honestly.
- Relay production packaging now bundles the `localflight` schedule helpers inside the Fly image, so the shared `/v1/schedule` route works live instead of failing with `ModuleNotFoundError`.
- Relay-backed schedule fetches now allow a longer timeout on cold shared-snapshot rebuilds, reducing false client failures while the relay performs the heavier sparse-board rescue path.
- Mobile crash reports with feature-specific context now keep the standard companion identity, app version, device type, and server URL attached for triage.
- Relay report routing now respects explicit desktop/web/server origins before inferring iOS from generic OS text, keeping platform triage separated.
- Operator login now throttles repeated bad-password attempts per network tag.
- Windows PyInstaller release EXEs now bootstrap writable stdio in windowed mode, preventing uvicorn/logging startup from failing silently before the browser window opens.

---

## [0.2.5b2] - 2026-04-30

### Added
- iOS-first companion polish pass across the Expo shell, including the longer branded launch overlay, stronger crash-reporting context, and cleaner companion identity reporting.
- Mobile companion appearance system with independent on-device `dark` / `light` theme selection and five mobile skins: `standard`, `technical`, `neon`, `cyan`, and `crt`.
- Mobile Settings **Appearance** controls with theme toggle, skin chips, and a live preview strip. Mobile appearance stays local to the device and does not sync with desktop/server skin.
- Mobile support for the existing `/api/matrix/config` runtime contract. The Matrix screen now loads server config, edits a local draft, saves explicitly, and can reset unsaved edits back to the server state.
- Mobile landscape display mode for FIDS and Radar. Rotating while on either screen opens a side-by-side display, with FIDS-primary or Radar-primary focus preserved.
- Responsive mobile radar scope with pinch-to-zoom range changes that snap across the desktop-aligned 10 / 20 / 40 / 80 NM ranges, plus compact fallback range chips.
- In-app mobile document reader for README, Privacy, and Changelog, with formatted Markdown rendering and an external-browser escape hatch.
- Mobile settings/admin support for the refined desktop relay and diagnostics surfaces, keeping the companion aligned with the latest server controls.

### Changed
- Desktop `/api/fids/detail` now exposes richer no-extra-request live-track metadata from stored snapshots, including geometric/barometric altitude fields, ICAO24, squawk, last contact, snapshot age, enrichment source, and confidence.
- Canonical flight snapshots now preserve DAU-relevant aircraft and virtual-flight-plan fields: registration, flight rules, planned route, cruise altitude/TAS, planned departure/arrival, enroute time, alternate, and assigned transponder.
- Desktop FIDS flight detail drawer now presents operations/aircraft, data source coverage, and live-track fields more explicitly, matching the companion's expanded detail contract.
- VATSIM normalization now keeps filed plan details useful to virtual pilots while avoiding noisy personal fields such as pilot names or VATSIM IDs.
- Desktop flight detail UI now branches between real-world and VATSIM modes: real flights prioritize airport operations, registration, and real data-source freshness, while VATSIM flights prioritize filed plan, virtual network, pilot track, route, cruise, alternate, and transponder details.
- Mobile Matrix tooling is now split into **Board Runtime** controls for server-backed settings and **Panel Preview** controls for local Interstate 75 W / HUB75 sizing.
- Matrix board preview keeps the mobile app chrome on the selected mobile appearance while rendering simulated LED colors from the server-returned matrix skin.
- Mobile Expo config now allows automatic system appearance instead of forcing dark mode, while the app drives its own StatusBar styling from the selected mobile theme.
- Mobile app internals were refactored from a single large `App.tsx` into a provider entrypoint, `AppShell`, domain helpers, state hooks, extracted chrome components, and screen/sheet modules.
- Mobile main navigation is now focused on FIDS, Radar, and Settings. History, Matrix, Admin, and Docs remain available from Settings instead of crowding the bottom nav.
- Mobile Settings is now sectioned into Server, Looks, Tools, and Docs areas to reduce page density.
- Pinned-flight chrome is now a compact, theme-aware info island with direct pin/unpin and tap-for-detail behavior instead of the previous expandable dark pill.
- Mobile airport/profile changes now explicitly ask the connected server to restart the scheduler and begin a fresh fetch cycle after config save.
- Mobile flight detail sheets now consume the expanded `/api/fids/detail` contract, including real vs VATSIM detail modes, data-source freshness, aircraft registration, ICAO24/squawk, geometric/barometric altitude, and filed VATSIM plan fields when available.
- Mobile automatic diagnostics now cover critical flight-detail communication failures (`5xx` responses or malformed JSON) through the existing diagnostics-gated crash route, while normal offline, validation, and `4xx` states stay user-visible without auto-report noise.
- The companion now feels closer to the supplied airport-board mockup in daily use, with the updated FIDS shell, launch flow, and diagnostics-aware reporting path.
- Public mobile docs now describe the current beta scope more accurately instead of treating the companion like a bare phase-one scaffold.
- Expo mobile dependency alignment updated for SDK 55: `expo` now targets `~55.0.24`, `expo-secure-store` `~55.0.14`, `expo-splash-screen` `~55.0.21`, plus `expo-crypto` and `expo-sqlite` for standalone relay identity/history support.

### Fixed
- Mobile pinned-flight island and bottom nav no longer keep hardcoded dark backgrounds in light mode.
- Mobile landscape split panes are constrained for safer scrolling/resizing after rotation.
- Companion version reporting now derives from Expo app metadata instead of a duplicated hardcoded string, reducing release drift risk.
- Mobile API typings now include the newer board-window config fields, keeping the companion aligned with the desktop server contract.

---

## [0.2.5b1] - 2026-04-29

### Added
- Pi installer (`installers/pi/install.sh`) fully rewritten: headless by default, optional `--kiosk` flag for Chromium kiosk, clean progress output (`ok`/`step`/`fail` helpers), all apt output suppressed, stale kiosk service removed on headless re-runs.
- `lf` management command installed to `/usr/local/bin/lf` during Pi setup - `lf start`, `lf stop`, `lf restart`, `lf status`, `lf logs`, `lf update` work from any directory.
- `lf.sh` rewritten: `has_kiosk()` guard makes all kiosk operations conditional on whether the kiosk service is installed; kiosk operations never run in headless mode.
- `scripts/package_pi_source.py` builds the versioned Pi source release bundle plus SHA256 so the Pi installer is reproducible from one documented command.
- `GET /api/matrix/config` and `POST /api/matrix/config` - LED matrix config (brightness, max rows, refresh interval, default view) stored server-side at `~/.localflight/matrix_config.json`; board picks up changes without reflashing.
- `POST /api/matrix/script` - generates a complete, ready-to-flash Interstate 75 W `main.py` from the canonical board client template, with LAN-host validation for the board download path.
- Matrix preview **Save Config** button: stores brightness, rows, refresh interval, and default view to the server so the board picks them up automatically.
- First-launch diagnostics choice for each install: `Manual reports only`, `Automatic crash reports`, or `Automatic crash reports + sanitized logs`.
- In-app document viewer routes (`/docs/readme`, `/docs/privacy`, `/docs/changelog`) so README, privacy, and changelog content are readable from Settings inside the desktop app.

### Changed
- MicroPython matrix client (`sources/matrix/client.py`) no longer has hardcoded airport or config values. Airport is read from `/api/config` on boot and every 5 minutes. Brightness, row count, refresh interval, default view, and skin are read from `/api/matrix/config`.
- Matrix board LED colors now track the app's active skin (`standard`, `technical`, `neon`, `cyan`, `crt`) - skin propagated via `/api/matrix/config` response, applied by `apply_skin()` which recreates all PicoGraphics pen objects.
- Matrix preview canvas palette is now skin-aware: initialized from `{{ cfg.skin }}` at page render, updates when skin changes.
- Matrix preview page cleaned up: aligned visual style with the rest of the app, clearer "flash once / tune here" guidance, explicit LAN host / port entry, and safer DAU-oriented hints instead of browser alerts.
- Automatic diagnostics now respect the install's chosen privacy mode across desktop, browser UI, scheduler/runtime, and mobile companion flows.
- Manual reports and automatic crash reports now describe their delivery path, source context, Python/runtime details, and whether a sanitized log excerpt was included.
- Version metadata, mobile companion metadata, runtime fallbacks, and preview badges are now aligned to `0.2.5b1`.
- Community relay defaults are now centralized on the live Fly.io endpoint so app code, setup, installers, and docs stop drifting.
- Settings now separate install/relay status, flight setup, app controls, and diagnostics/resources more clearly, and community mode now truthfully reports when the hosted relay is active.
- README now documents the Pi source release bundle and the local docs viewer routes.

### Fixed
- `.env.example` relay URL corrected from the unregistered `relay.localflight.app` to the live endpoint `https://localflight-community-relay.fly.dev/v1/flights`.
- Matrix board download no longer depends on a stale browser-only copy of the MicroPython client, no longer suggests `localhost`, and no longer ships real local SSID / IP placeholders in the canonical board file.
- Automatic crash submission now returns a clear disabled state when diagnostics are turned off instead of looking like a backend failure.
- Setup, installer, and runtime relay references now resolve to the same hosted community backend contract.
- macOS packaging now bundles `README.md`, `PRIVACY.md`, and `CHANGELOG.md` into the app and uses a more reliable `.icns` generation path before falling back to `iconutil`.

---

## [0.2.4b1] - 2026-04-28

### Changed
- Community relay URL updated to the live Fly.io endpoint (`https://localflight-community-relay.fly.dev/v1/flights`). The older `relay.localflight.app` custom-domain plan was later superseded by the Beacon Tools domain plan.
- Source installers (Windows, macOS, Pi) and `.env` defaults now point to the confirmed-working relay endpoint.
- Version bumped to `0.2.4b1` across `pyproject.toml`, runtime fallbacks, and mobile metadata.
- Removed orphaned `claude2.md` and root `package-lock.json`.

### Fixed
- `relay/main.py` used `uvicorn.run("relay.main:app", ...)` (string module import) which fails in Docker because there is no `relay` package in the container filesystem. Changed to `uvicorn.run(app, ...)`.
- Removed a redundant relay database-path step from deploy docs.

---

## [0.2.3b2] - 2026-04-28

### Added
- Fly.io deployment guidance and defaults for the hosted community backend, including a public relay host and a separate operator host.
- Host-aware relay health and root responses so public clients can hit the hosted backend directly while the operator console stays on its own hostname.
- Regression coverage for public/admin hostname gating, relay privacy writes, hosted relay defaults, and the `0.2.3b2` runtime metadata sweep.

### Changed
- Community mode now defaults to the hosted relay URL `https://relay.localflight.app/v1/flights` across the client, setup flow, and source installers. This historical hostname was later superseded first by the Fly.io root and then by the Beacon Tools hostname plan.
- The relay now runs as one Fly app with one warm machine in `fra`, one SQLite volume, and separate public/admin hostnames on top.
- Setup keeps the user-facing model to exactly three paths: Community, Bring your own keys, or VATSIM.
- Source-install templates, `.env.example`, and handoff docs now describe the hosted relay as the standard community path instead of a local-only relay experiment.
- Mobile companion metadata is version-synced to `0.2.3b2`, while the docs continue to mark mobile as WIP/beta.

### Fixed
- Fly deployment artifacts now agree on port `8080`, and the GitHub workflow explicitly deploys the `relay/` app instead of relying on repo-root defaults.
- The public relay hostname no longer exposes `/admin`, and the operator hostname no longer serves the public `/v1/*` client surface.
- Relay activity and activation records no longer persist airport-identifying fields for new writes; anonymous install fingerprints and network tags remain for abuse protection.
- Community relay setup no longer derives stored relay labels from the selected airport, keeping the privacy story consistent from the client through the hosted backend.

---

## [0.2.2b3] - 2026-04-27

### Added
- Community AviationStack relay mode for real flight schedules when no personal `AVIATIONSTACK_API_KEY` is configured.
- Personal subscription budget defaults for AviationStack and RapidAPI increased to 10,000 calls/month.
- RapidAPI / ADS-B Exchange usage tracking in Admin, including calls used, remaining quota, and monthly limit.
- Radar range controls, including URL-driven range selection for shared/bookmarked radar views.
- Airport timezone auto-detection from the server-side airport database, including region-level timezone handling for multi-timezone countries.
- Companion preview artwork in the README and local preview gallery.

### Changed
- Manual refreshes, scheduler restarts, and config changes now respect snapshot freshness before making another live schedule request.
- Manual restart now returns a rate-limited status when triggered repeatedly within a short window.
- OpenSky live radar fallback is cached briefly per airport so multiple open clients do not all trigger their own fallback fetch.
- Admin budget cards now distinguish community relay mode from personal-key mode and show separate RapidAPI usage.
- Setup now clearly presents the three main ways to use Local Flight: shared relay, your own keys, or VATSIM.
- Settings and setup now use airport-provided timezone data instead of browser-side country guesses.
- API-key test buttons now send keys in request bodies instead of putting keys in browser URLs.
- Developer reports now include a privacy-preserving install fingerprint instead of a raw relay install identifier.
- Mobile metadata, Expo metadata, runtime fallbacks, and docs now target `0.2.2b3`.
- Splash screens now stay on screen longer, show progress/status, and use richer launch animation on desktop and in the mobile companion.
- README mobile companion section now reflects the current beta feature set, setup flow, and preview graphics.
- Network/traffic diagnostics are now kept out of the standard client path and reserved for explicit local development launch.

### Fixed
- Windows taskbar/tray crash on some 64-bit systems.
- Fresh-data checks could fail because of a missing scheduler dependency import.
- Traffic Log no longer stores raw IP addresses or raw user-agent strings.
- Traffic Log rendering now escapes displayed request paths.
- Relay admin views no longer expose raw install identifiers.
- Relay admin rendering now escapes displayed table values.
- Real-mode radar now prefers ADS-B Exchange live data when a RapidAPI key is available, while caching responses so the faster radar refresh does not burn extra subscription calls.
- Radar range buttons now update the display correctly and keep mobile/desktop radar views in sync with the selected range.

---

## [0.2.2b2] - 2026-04-26

### Added
- Scheduler control API and UI controls for checking scheduler status and restarting a sleeping scheduler.
- WebSocket sync events for config changes and scheduler restarts so desktop display windows, Admin, and mobile stay in sync.
- Server crash-report endpoint for mobile/server crash submissions with duplicate suppression.
- Richer feedback context so mobile reports include client environment alongside server environment.
- macOS release zip and `.sha256` checksum generation for GitHub Releases.
- README preview gallery with sample FIDS, Radar, and Settings screenshots.

### Mobile Companion
- Matrix configurator screen with panel presets, row count, brightness, view selection, preview text, and MicroPython config output.
- Mobile airport/config sheet for searching airports, changing source, changing update interval, and managing local airport profiles.
- Animated launch overlay using the companion app icon.
- Flight Island for pinned or active flight focus.
- Long-press flight actions for pinning and details.
- In-app feedback form.
- Mobile crash reporting with client-side deduplication.
- Persistent pinned flights.
- Admin updates and connection status in the mobile API client.
- Safer layout handling for notched iPhones and iPads.

### Changed
- Scheduler-relevant config changes now wake the scheduler immediately instead of waiting for the previous sleep interval.
- Desktop display, FIDS, Radar, Admin, and mobile now refresh or reload on live sync events.
- Release docs now separate packaged release installs from source-checkout installers.
- README now presents desktop release installation before mobile developer-preview instructions.
- Mobile main navigation now contains FIDS, Radar, History, and Settings; Matrix and Admin are launched from Settings.
- Mobile header now shows airport/live status plus UTC and local time.
- Pinned flights persist locally and sort back to the top of the mobile FIDS list.
- Mobile feedback/crash submissions now share a common JSON POST helper.

### Fixed
- Mobile dependency metadata now matches `0.2.2-b2`.
- macOS code signing no longer fails when optional entitlements are absent.

---

## [0.2.2b1] - 2026-04-26

### Added
- macOS source-checkout `.app` bundle installer.
- Pre-rendered macOS app icon asset for systems without SVG conversion tools.
- Initial React Native / Expo mobile companion preview.
- Mobile FIDS shell styled after an airport-board mobile mockup.
- Mobile server URL storage.
- Mobile WebSocket listener for live updates.

### Changed
- Version metadata updated to `0.2.2b1` for Python, runtime fallbacks, PyInstaller fallback, docs, and release guidance.
- Mobile package metadata uses npm prerelease version `0.2.2-b1`.
- Mobile dependency pins updated for the current Expo SDK.

### Notes
- Mobile install/build verification should be run on the Mac/Xcode machine.

---

## [0.2.1b2] - 2026-04-26

### Added
- Versioned launch splash screen before setup/display.
- Regression coverage for key scheduler, storage, route, and runtime-state behavior.
- Windows release zip checksum output.
- Cross-platform startup model for Windows, macOS, Raspberry Pi, and Linux.
- Desktop kiosk browser launcher.
- Cross-platform tray/taskbar support.
- Raspberry Pi installer and management helper.
- Shared navigation bar across app pages.
- FIDS arrivals/departures toggle improvements.
- Flight detail drawer with times, position, operational details, and recent history.
- Settings page improvements.
- Admin hub with scheduler status, API budget, connection count, history stats, METAR, log tail, and update checks.
- SQLite flight history database and history browser.
- Five display skins: standard, technical, neon, cyan, and CRT.
- PyInstaller desktop packaging.
- Version badge in the app UI.
- API-key error banner on the FIDS board.
- Quit confirmation modal.
- User feedback/report page.
- RapidAPI key validation during setup.
- Buy Me a Coffee link in Admin.
- Per-flight detail data for desktop and mobile clients.
- Setup reset option.
- GitHub release update check.

### Changed
- Desktop launchers and Pi kiosk now open through the splash screen.
- Runtime snapshots now live in the user data directory, while older source-tree snapshots remain readable.
- Installer docs now distinguish source-checkout installers from packaged release artifacts.
- README rewritten from an end-user perspective.
- Installer layout reorganized by platform.
- Windows source installer clarified as source-only.
- Shutdown now exits the app more reliably after closing browser processes.

### Fixed
- Snapshot pruning now runs during snapshot jobs.
- Failed fetch cycles preserve the previous successful fetch timestamp.
- Duplicate config route registration removed.
- Local AviationStack file loading now checks current and older snapshot locations consistently.
- Example environment files no longer include private operator Linear variables.
- Windows source installer detects Python more reliably and supports additional install flags.
- Windows launcher UTF-8 comment issue fixed.
- RapidAPI and OpenSky signup links fixed.
- Tray quit no longer logs a false crash.
- VATSIM aircraft type extraction handles heavy-prefix formats.
- Navigation template syntax issue fixed.
- Windows console encoding issue during build fixed.

---

## [0.1.0] - 2025-03-01

### Added
- Initial release.
- FastAPI web server and browser FIDS board.
- WebSocket live push.
- AviationStack schedule data source with monthly budget guard.
- ADS-B Exchange position enrichment.
- OpenSky Network position fallback.
- VATSIM virtual traffic source.
- METAR weather display.
- Radar view with sweep animation.
- Split FIDS/Radar display.
- Matrix preview.
- MicroPython client for Pimoroni Interstate 75 W.
- First-run setup wizard.
- SQLite flight history.
- Raspberry Pi ADS-B receiver support.
