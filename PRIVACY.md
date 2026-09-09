# Privacy

Local Flight follows one simple rule: **keep your data on your device unless a feature needs an online connection.**

There is no Local Flight account, advertising profile, analytics tracker, or sign-up flow. Optional online features need a small amount of service information to connect the right devices, share provider capacity fairly, and diagnose failures. The exact details remain documented below.

This policy explains what stays on your device, when Local Flight connects online, what limited information the service handles, and what you can reset or delete. Technical identifiers are tied to an installation rather than a person, and automatic diagnostics stay off unless the saved diagnostics choice allows them.

Last updated: September 9, 2026.

The 0.7.0 candidate retains these data boundaries. Described purchase and
recovery paths apply when that service is available; their presence in the app
does not mean sales have opened or email delivery has been certified. New
optional support purchases can be paused without discarding an unfinished
store transaction. Relay Access delivery can be retried without creating
another license; delivery timing and inbox placement cannot be guaranteed.

Beacon Tools is responsible for the hosted Local Flight relay, website forms, and related support processing. General/support questions and public bug reports start at [beacontools.cc/support](https://beacontools.cc/support). Privacy, diagnostics, and data-request questions can go through [beacontools.cc/privacy/choices](https://beacontools.cc/privacy/choices) or [privacy@beacontools.cc](mailto:privacy@beacontools.cc). The public privacy URL is [beacontools.cc/privacy](https://beacontools.cc/privacy).

---

## The Short Version

- Settings, provider keys, snapshots, history, and logs normally stay on the device running Local Flight.
- The native desktop window is a real app, not an embedded browser. The LAN browser remains available when you deliberately open it from another device.
- LAN displays, Companion phones, and Matrix boards connect to your own Local Flight host first.
- A paired Companion phone can use encrypted away-from-home access while its host is online. The connection service routes the encrypted message but cannot read the board data or command inside it.
- Standalone mobile connects directly to the shared service for a simpler phone-only board. It has slower refresh limits and is separate from a paired Companion.
- The optional shared-data service can provide recent real-flight schedules without putting provider keys on every device. Shared real-aircraft radar is not included; BYOK and VATSIM radar remain available.
- Optional map and terrain layers request only the displayed airport area and are kept as bounded visual caches.
- Richer FIDS/Radar/History detail views reuse data Local Flight already fetched or stored locally. Opening a detail panel should not trigger surprise per-flight paid provider calls.
- Matrix gate/stand display uses existing real-world schedule fields when available. VATSIM Matrix presets hide gate data instead of inventing placeholders.
- Manual reports are sent only when you choose to send them. First-run setup asks how automatic diagnostics should work and defaults to manual-only reporting.
- Companion automatic diagnostics require two yeses: the mobile app's local diagnostics choice and the connected server's diagnostics mode.
- Mobile Standalone automatic diagnostics require the phone-local diagnostics choice because there is no paired server.
- Optional mobile support purchases are processed by Apple or Google. Local Flight never receives card details and does not keep the raw store proof after checking it.
- Optional Beacon Relay Access is an automatically renewing annual hosted-service entitlement for one main device. Stripe, App Store, and Google Play subscriptions map to the same portable license model. Verified earlier purchases, complimentary grants, and eligible early installs keep permanent access; support purchases remain separate and unlock nothing.
- Relay Access uses no profile or password. Email is required for Stripe delivery and optional for mobile recovery or transfer. The relay stores an email HMAC plus an encrypted notification copy, never a plain email field.
- Private reporting credentials stay on the hosted service, not in the app, installer, or documentation.
- Local Flight does not collect your email address during normal app use. If you email Beacon Tools directly, your email address and message are handled by the email provider so Beacon Tools can reply to you.
- Local Flight is an informational display aid, not a navigation, dispatch, operational-control, or safety system.

---

## What Stays Local

- Flight snapshots, config, history, and logs stay under `~/.localflight/`.
- The packaged Linux server uses its dedicated service home instead: `/var/lib/localflight/.localflight`.
- Your airport settings, display preferences, and personal API keys stay in your local config and `.env`.
- The native GUI, LAN browser UI, Companion, and matrix board all talk to your local Local Flight server first. Remote Companion is only a fallback for paired phones when LAN is unavailable and the relay-linked host is online. Native mode does not fetch online fonts, CDN assets, or a webview shell for the main UI.
- The optional local traffic log at `~/.localflight/requests.db` is visible only on your own Local Flight instance and is only enabled for explicit local network diagnostics.
- Optional radar map data is simplified and cached locally for display use. It is not stored as raw provider payloads in reports or ordinary UI surfaces.
- The Interstate 75 W board talks to your Local Flight server over your LAN. Its runtime settings live in `~/.localflight/matrix_config.json`.
- Matrix V2 device check-ins store only board identity, label, size, renderer support, assigned config, and last-seen time locally so the admin page can show whether the board is alive.
- VATSIM-specific matrix presets require source `virtual` and use VATSIM-backed rows/weather only; they do not quietly switch to real-world FIDS or real METAR data.
- Flight intelligence shown in FIDS, Radar, History, and Matrix is assembled from the current local snapshot, live radar cache, METAR/weather context, airport/surface context, and local history database. It is a display model, not a new background data-harvesting layer.
- History displays deduped flight movements. Raw fetched observations remain local diagnostics so repeated snapshots and codeshares do not inflate public/client-facing counts.
- Mobile Standalone stores its setup mode, relay install UUID, non-secret license summary, selected airport, appearance, diagnostics choice, pinned flight, any pending receiver-release marker, and local deduped movement history on the device. Real-flight Standalone additionally keeps one `relayDeviceCredential` in SecureStore; VATSIM does not require that credential. Standalone history is not stored on the hosted relay.
- Companion stores its paired server URL, companion ID, appearance, diagnostics choice, pinned flight, local profiles, and, when paired, a Remote Companion grant locally on the phone. The remote grant includes a public grant ref, relay URL, install ref, timestamps, revoked state, and a per-device AES-256-GCM secret kept on the phone and host, not on the relay.
- iOS and Android home-screen widgets read a bounded board snapshot written locally by the mobile app. The iOS copy lives in the Local Flight App Group and the Android copy stays in the app's private files directory. Widgets do not contact the LAN server, relay, or aviation providers themselves.
- Unfinished App Store/Play support transactions remain managed by the platform store until Local Flight can verify and finish/consume them. The mobile app does not keep a separate purchase-history database or paid entitlement because support products unlock nothing.

When you use the Matrix page to download a ready-to-flash `main.py`, the Wi-Fi details and server host are sent to your own Local Flight instance only long enough to render that file. They are not stored in `matrix_config.json`, the hosted relay, or crash reports.

---

## Why The Native GUI Exists

Local Flight started with a browser-based local UI because that made the project practical: one local app could run on Windows, macOS, Raspberry Pi, phones, and tablets. That browser/LAN UI remains supported. The native GUI was added because a general-purpose browser process is more machinery than a local airport board should need for everyday desktop use.

The privacy goal is data minimization and separation of purpose:

- The display shell should show Local Flight, not become another browser session.
- The app should not rely on a browser profile, browser sync, extensions, cookies, history, or default-browser integrations just to render the main UI.
- The main window should not need a webview engine or remote web assets when the backend is already local.
- Browser access remains available as a deliberate LAN access and display path. It is useful for headless installs, remote screens, tablets, browser-mode displays, and recovery.

Native mode does not change the aviation data sources you choose. If you enable Beacon Relay, BYOK, VATSIM, radar, METAR, update checks, or reports, the relevant network calls still happen as described below. The native GUI simply keeps the app window itself out of the browser-vendor data surface.

---

## When Local Flight Connects Online

### Shared Data And Connection Service

If you choose **Beacon Relay**, the Beacon Tools connection service can provide a recent shared copy of real-world schedules. This protects provider keys and lets several Local Flight installs reuse one safe result instead of making the same paid request repeatedly. Shared real-aircraft radar is not included in Relay Access; it remains available through appropriately licensed BYOK sources or VATSIM. Which commercial sources and capabilities can be enabled remains controlled separately by verified provider permissions; paying for Relay Access never overrides a provider agreement.

New Beacon Relay Access is an annual entitlement for one active main device, subject to authoritative subscription state, refund, abuse controls, provider permission, and service availability. That main device can be a Local Flight desktop using Beacon Relay or an official mobile installation using real-flight Standalone. LAN and encrypted Remote Companion clients attach to a licensed desktop host and do not use another license. A confirmed move keeps the previous main device active until the new credential has been stored, then revokes the old per-device credential as the new one is committed. Cancellation keeps access through the confirmed paid period; only authoritative active, grace, or cancelled-before-period-end states authorize hosted service. Existing verified lifetime and founder entitlements retain their permanent access contract.

Stripe handles website subscription checkout and its financial receipts. Beacon Tools sends a master license key to the checkout email and can reveal it once to the successful browser session. The desktop exchanges that key for a revocable per-device credential and does not retain the master key. On iOS and Android, the free app verifies the annual native-store subscription before activating real-flight Standalone. The relay checks the expected app, product, environment, signed transaction or purchase-token state, period boundary, renewal/grace state, and later server notifications. Apple original transaction identity and Google subscription lineage provide stable idempotency; raw signed evidence is processed transiently, while only a keyed lookup and encrypted reconciliation handle are retained when needed. Eligible prior paid-app or non-consumable owners can restore a permanent founder or legacy entitlement. An existing portable license can instead move to the official app through a short-lived verified activation grant. Mobile accepts and displays no master key until a mobile license is protected by verified email and retrieved through the confirmed web/email flow.

The service keeps only the information needed to connect an installation, share capacity fairly, and recover from failures. In technical terms, that can include:

- a random app-installation identifier
- a one-way form of the public Support ID
- per-install usage counts
- last-seen timestamps (heartbeat or relay activity, ~30 min coarse cadence — not real-time presence)
- a short non-secret part of the installation link
- references and coarse status for approved paired phones, when Remote Companion is enabled
- one-way network tags used to prevent abuse without storing raw addresses in the application database
- short-lived records of the requested airport and board window so a recent shared result can be reused
- short-lived shared schedule records, provider source, source-fetch time, coverage boundaries, and freshness information. Provider-derived cache records carry a policy expiry and are retained for no more than seven days by default; a shorter configured or provider limit still applies.
- a small coarse install profile sent with eligible periodic heartbeats or relay activity: app version, OS family/version/architecture, requested and effective GUI mode, source mode (`real` or `virtual`), diagnostics mode, companion count, Matrix count, and Matrix-online count. Standalone activity can also include the selected airport/timezone and coarse device type. This profile supports compatibility, reliability, and capacity planning without creating a user account.
- if the operator explicitly enables the optional surface/map overlay path: short-lived airport-surface and map-geometry cache entries derived from OpenStreetMap/Overpass so many installs looking at the same airport do not repeatedly query public map infrastructure
- for Relay Access: a random holder and license ID, normalized-email HMAC, encrypted recovery/security-notification address, entitlement kind, effective state, current period/grace boundaries, renewal state, product and purchase source, key-secret version and master-key HMAC/masked reference, one active receiver, device-credential HMAC/masked reference, and activation/revocation timestamps
- for Stripe, App Store, or Google Play ownership: provider purchase/event HMACs, encrypted reconciliation handles where needed, product identity, environment, state/reason, acknowledgement/reconciliation status, evidence hash, verification/change timestamps, and minimal event-processing references. Replays resolve to the existing license for that provider subscription or legacy purchase.
- for founder migration: a keyed legacy-install reference, immutable cutoff, eligibility reason, bridge expiry, claim state, and timestamps. No raw install ID or per-install activity history is exposed in migration reports.
- for key delivery: license/holder references, key version, delivery channel and purpose, state, attempt count, coarse error code, and timestamps. The outbox never stores the key or a plain email address.
- for an optional mobile support purchase: keyed transaction hash, short transaction reference, product ID, store platform/environment, verification status, install fingerprint, attempt timestamps, and coarse failure code. Raw Apple transaction payloads and raw Google purchase tokens are not retained.

The relay does **not** store:

- raw IP addresses in the Local Flight application database. Fly.io, Cloudflare, and other network providers may transiently process connection data in infrastructure/security logs under their own policies.
- personal API keys from your install
- readable personal identifiers
- your local flight history database
- your phone's standalone local history database
- your local app logs, unless you explicitly allow diagnostic reports with sanitized logs
- Remote Companion AES secrets, decrypted request paths, decrypted request bodies, decrypted responses, provider keys, local LAN URLs, or host logs
- payment-card details, Apple/Google account identity, raw signed Apple transaction payloads, or raw Google purchase tokens
- raw Relay Access master keys, raw per-device credentials, plain email database fields, or raw store-ownership evidence

Beacon Relay traffic has per-install quotas plus network/global safety caps. Duplicate reports are suppressed before routing to keep triage useful and avoid repeated reports of the same event.

The relay controls how often a shared airport snapshot can trigger a new upstream schedule fetch. Normal demand can trigger at most one shared upstream refresh for an airport every 15 minutes, subject to coverage, provider availability, and spending limits. Client settings may be slower and cannot shorten that server timer. This keeps the service fairly available when many people watch the same busy airport.

Mobile Standalone uses the same hosted relay but with stricter product limits: real airline-schedule refresh is 1 hour minimum. Shared real-aircraft radar is disabled. VATSIM radar uses sanitized virtual-data endpoints, ranges of `1`, `3`, `5`, and `10` NM, and needs no Relay Access credential.

Remote Companion uses the same hosted relay only as a routing layer for paired Companion phones. The host opens an outbound relay connection; there is no router port forwarding and no public tunnel to the host. The relay admits only active relay-linked installs and active, non-revoked grant refs. If the host is offline, the phone receives a clean offline state instead of an offline command queue.

### Away From Home: Remote Companion

Remote Companion encrypts each phone request and host response before it reaches the connection service. Only the paired phone and host have the shared secret. Each message is also tied to the approved installation, phone, request, and direction so copied or replayed messages are rejected.

The service can see limited delivery information needed to route and protect the connection:

- install ref and grant ref
- request id
- grant registration/revocation state
- status code category, latency, byte sizes, and rate-limit counters
- coarse relay activity timestamps

The service cannot read:

- the Companion API path or body
- Board, Radar, History, Matrix, or config payload contents
- provider keys or secrets
- local LAN URLs
- raw logs or request logs
- the AES secret shared by the paired phone and host

Remote Companion grants are explicit and revocable. The host can revoke a phone from Settings. The phone can forget its stored remote grant and pair again later while on the LAN.

### Bring Your Own Keys

If you choose **Bring your own keys**, your local app talks directly to the upstream providers you configured. Your provider keys stay in your local `.env` and are not sent to the Local Flight relay reporting gateway.

### VATSIM

If you choose **VATSIM**, the app uses virtual traffic data and does not need real-world schedule API keys.

Local Flight fetches the public VATSIM network feed and keeps only flight-board-relevant fields such as callsign, filed route, aircraft type, airport codes, planned times, current aircraft position, and the raw METAR line when available from ATIS/METAR text. It intentionally does not store or display VATSIM pilot names, controller names, CIDs/account IDs, server names, or other person-identifying network fields.

VATSIM views avoid passenger-only fields that do not belong to the virtual network source. Virtual FIDS, Matrix, native, LAN browser, and mobile detail views prioritize callsign, aircraft, filed route/flight rules, pilot track, XPDR, source freshness, weather/ATIS, and recent sessions while suppressing codeshares, sold-as labels, gates, terminals, stands, registrations, ICAO24, pilot/controller names, CIDs/account IDs, and server names.

---

## Diagnostics And Reports

Manual issue reports are always available from the in-app **Report** page. Automatic diagnostics are a separate install-level choice.

During first-run setup, Local Flight asks you to choose one of these modes and saves the choice in your local config:

- `Manual reports only`
- `Automatic crash reports`
- `Automatic crash reports + sanitized logs`

You can change that choice later from **Settings** or by re-running setup.

### Manual Reports

When you send a report yourself, Local Flight sends:

- the title and description you wrote
- Local Flight version
- install fingerprint
- operating system
- Python version
- configured airport and source mode
- schedule mode, diagnostics mode, and display window settings
- the reporting surface, such as native GUI, LAN browser UI, server, Companion, or Mobile Standalone
- optional mobile context if the report came from Companion or Mobile Standalone

Manual reports are sanitized locally, forwarded to the hosted relay reporting gateway, deduplicated/rate-limited there, and then filed into Linear as the developer triage inbox.

Public website bug reports use the same relay-owned triage pattern. They can include the text you write, optional reply email, product/surface/version/platform fields, and optional text/log uploads. Uploaded logs are capped, sanitized, and embedded as excerpts rather than stored as raw files.

The public website contact form is separate from bug triage. It sends the message you write, optional name/reply email, category, page context, and relay anti-spam metadata through the Beacon Tools relay to the support mailbox.

### Automatic Crash Reports

If you enable automatic diagnostics, Local Flight can send a crash report when a serious error is caught. Automatic reports use the same relay reporting gateway as manual reports.

An automatic crash report can contain:

- Local Flight version
- install fingerprint
- operating system
- Python version
- configured airport and source mode
- schedule mode, diagnostics mode, and display window settings
- crash context
- native GUI screen/action context, when the crash happened in the Qt shell
- traceback, when available

If you choose `Automatic crash reports + sanitized logs`, the report can also include:

- a sanitized recent log excerpt from the local app log

Automatic diagnostics do **not** intentionally contain:

- API keys
- provider keys, Relay Access device credentials, or master license keys
- raw IP addresses
- raw screenshots or screen recordings
- stored flight history
- full local logs
- account data, because there are no Local Flight accounts

Expo JS/React errors in the mobile app are covered by the current crash reporter. Native iOS crashes before JavaScript starts are not covered without adding a native crash-reporting service or relying on Apple crash logs.

---

## Mobile App

The mobile app stores its setup choice locally on the device with Expo storage APIs.

### Companion

Companion stores its server URL, companion ID, appearance choice, pinned flight, local profiles, and mobile diagnostics choice locally on the device.

When it connects to your Local Flight server, it reports a companion-specific ID plus platform/device labels so companion-originated actions can be distinguished from desktop/server actions. That ID is install-scoped. It is not a login, an account, or a person profile.

Companion uses the LAN path whenever the host is reachable. If Remote Companion has been paired, the same Companion surfaces can fall back to the relay when LAN is unreachable. Remote Companion does not create an account, does not open an inbound public tunnel to the host, does not queue commands while the host is offline, and does not expand Companion into arbitrary admin access.

Automatic companion reports only send when:

- the mobile diagnostics mode allows automatic reports
- the connected Local Flight server diagnostics mode also allows automatic reports

If either side is set to manual or unset, automatic mobile reporting stays off.

### Standalone

Standalone stores a separate relay install UUID, a non-secret license summary, selected airport, appearance choice, pinned flight, diagnostics choice, any pending receiver-release marker, and an on-device deduped movement history database locally on the device. Real-flight Standalone stores one Relay Access device credential in SecureStore; VATSIM does not. Legacy duplicated setup-state credentials are migrated out of setup JSON.

Standalone sends relay requests with:

- install UUID for relay rate limits
- revocable device credential for real-flight access; omitted for VATSIM
- app version
- client kind `mobile_standalone`
- coarse device type, such as phone or tablet
- selected airport/timezone
- diagnostics mode

Standalone does not send local phone history to the relay. Manual reports go directly to the relay reporting gateway. Automatic standalone reports only send when the mobile diagnostics choice is `auto` or `auto_logs`.

### Purchases and In-App Payments (IAP)

Relay Access is an automatically renewing annual hosted-service entitlement, not an unlock for the free, open-source desktop application. Stripe subscribers receive a master license key on the successful browser session and by email. The free iOS and Android apps activate real-flight Standalone only after their annual native-store subscription is verified. All three sources produce the same portable `beacon_relay_annual_v1` license type for one active desktop Beacon Relay installation or one official mobile real-flight Standalone installation. Companion and VATSIM work without buying Relay Access, while Remote Companion uses the licensed desktop host. Existing verified lifetime purchases, complimentary grants, and eligible founder installs preserve permanent access under their earlier authority.

For Stripe, the relay stores a keyed subscription/customer reference, product/environment/state, period and grace boundaries, evidence hash, license status, email HMAC, and an encrypted recovery/security-notification address. For iOS, it stores a one-way original-transaction lookup plus an encrypted reconciliation handle and the minimum state needed to interpret signed renewal, grace, expiry, or revocation results. For Android, it stores a one-way subscription-lineage lookup plus the purchase token encrypted for Google acknowledgement and reconciliation. It does not retain raw master keys, raw per-device credentials, raw signed store evidence, plain email database fields, card details, or store-account identities. Replayed events and repeated ownership checks return the same license for the same provider subscription. Duplicate purchases through unrelated providers remain separate entitlements rather than being silently merged.

Email is optional for mobile until you choose to protect, recover, or transfer its store-created license. Protecting it sends an address-confirmation link without exposing the key in the app. After confirmation, the website can reveal the existing key once and the delivery outbox sends the same key by email; initial delivery does not rotate it. One-time link secrets are placed in the URL fragment so they are not sent to the hosting service as part of the page request. These links provide short-lived license selection and transfer access without creating a password, profile, or general account. During a move, the old device remains active while the new credential is prepared and stored; a successful commit switches the main device and sends a security notice when the license has a protected email.

The three consumable support products remain a separate purchase path:

The mobile app can offer three optional one-time consumable support products through Apple App Store or Google Play. Support unlocks no feature, creates no account, and creates no durable entitlement. Store-owned localized pricing is shown before the system purchase sheet opens.

Apple or Google processes the payment and payment-card details under its own account and privacy terms. After the store reports success, Local Flight sends the product ID plus Apple transaction ID or Google purchase token over HTTPS to the Beacon Tools relay. The relay checks that evidence through Apple's App Store Server API or the Google Play Developer API. The app finishes/consumes the transaction only after verification succeeds, so an interrupted verification can be recovered without blindly accepting the client.

The relay immediately derives a keyed hash and short reference. Its ledger retains only that hash/reference, product ID, platform/environment, install fingerprint, verification status, timestamps, attempt count, and a coarse error code. It does not retain the raw evidence, price, currency, card details, Apple ID, Google account, or signed Apple transaction body. Purchase evidence is never added to diagnostics, Linear reports, heartbeats, or Network Admin views.

An unfinished purchase remains managed by Apple or Google until Local Flight can verify and finish/consume it. A pending, cancelled, rejected, refunded, or revoked purchase does not unlock or change any Local Flight feature. Removing Local Flight does not erase store records; store purchase history and refund requests remain subject to the applicable Apple or Google controls and terms. A Beacon Tools data request can use the public Support ID plus the short purchase reference or approximate purchase time to help locate the minimal verification record.

---

## Why The Service Keeps Limited Information

The service information described above is used only to deliver requested
features, keep shared capacity available, protect the service, answer support
requests, and verify optional purchases. It is not used for advertising or to
build a profile of where you travel.

Where data-protection law applies, Beacon Tools uses the following purposes and intended legal bases:

- **Service operation and security:** installation references, encrypted-delivery information, usage counters, and one-way network tags are processed to provide requested features, protect shared capacity, prevent abuse, and troubleshoot failures. The intended basis is legitimate interest in operating and securing the optional service, balanced against the app's data-minimizing design.
- **Diagnostics:** automatic diagnostics and optional log excerpts are processed only under the choice made in the app. You can change that choice or withdraw consent for future automatic reports at any time. Manual reports are processed because you asked Beacon Tools to investigate them.
- **Support:** contact details and messages are processed to answer the request you chose to send and to take steps you requested.
- **Optional purchases:** minimal transaction metadata is processed to perform the purchase you requested, prevent duplicate processing, and meet store/accounting/security requirements. Apple or Google separately processes the payment under its store terms.
- **Relay Access and recovery:** license, purchase, receiver, and encrypted notification details are processed to provide the hosted service, enforce one active receiver, deliver or recover access, handle refunds and revocations, and send security notices. Stripe or the selected mobile store processes payment separately.

Shared cache records follow service freshness and stale-fallback needs. Expired access challenges and old successful delivery/provider-event records are periodically removed; the minimal purchase, license, and activation audit is retained for service, fraud, refund, and recovery needs. Other hosted support, report, dedupe, and install-profile records may remain until operational cleanup or a valid deletion request. This is a transparency boundary for the current service, not permission to reuse the data for advertising or unrelated profiling.

Depending on applicable law, you may ask to access, correct, erase, restrict, object to, or obtain a portable copy of personal data associated with you. Because Local Flight has no account system, Beacon Tools may need the public install fingerprint, report reference, approximate time, or reply email you supplied to locate a record without collecting more identity data. Contact [privacy@beacontools.cc](mailto:privacy@beacontools.cc) or use [Privacy Choices](https://beacontools.cc/privacy/choices). You may also complain to the data-protection authority responsible for your location.

---

## Your Choices And Deletion

- Change automatic diagnostics from **Settings** at any time. Manual-only is
  always available.
- Revoke a Remote Companion phone from the host before forgetting it on the
  phone.
- Use the in-app reset controls when you want to clear normal Local Flight
  configuration and pairing state.
- Remove the mobile app to erase its app-local secure storage and database
  under the normal iOS or Android removal process.
- Use [Privacy Choices](https://beacontools.cc/privacy/choices) or email
  [privacy@beacontools.cc](mailto:privacy@beacontools.cc) for hosted-data
  questions or requests.

For an intentional manual desktop/Pi wipe, stop Local Flight and remove
`~/.localflight/`. Remove `~/.localflight_identity.json` as well only if you want
the next launch to become a new service installation. On a packaged Linux
server, the equivalent state directory is `/var/lib/localflight`.

---

## Third-Party Data Sources

When Local Flight fetches data, it may communicate with:

| Service | What is sent | Their privacy policy |
|---|---|---|
| AeroDataBox through a direct subscription, API.Market, or RapidAPI | BYOK/direct path: API key, airport IATA code, and requested board window. Relay-backed path: the hosted relay makes the upstream request with its own provider key and shared cache. | [aerodatabox.com/privacy](https://aerodatabox.com/privacy), [api.market privacy](https://api.market/privacy_policy), [rapidapi.com/privacy](https://rapidapi.com/privacy/) |
| AviationStack | BYOK/direct path: API key, airport IATA code, date/window request details. Relay-backed path: the hosted relay makes the upstream request with its own provider key and shared cache. | [aviationstack.com/privacy](https://aviationstack.com/privacy-policy) |
| ADS-B Exchange / JETNET | Direct path: API key and radar search coordinates. Beacon-managed provider requests remain disabled unless the applicable provider agreement expressly permits them. | [jetnet.com/privacy-policy](https://www.jetnet.com/legal/privacy-policy), [rapidapi.com/privacy](https://rapidapi.com/privacy/) |
| OpenSky Network | Radar search coordinates | [opensky-network.org/about/privacy](https://opensky-network.org/about/privacy) |
| VATSIM | Virtual network data for the configured airport/source mode | [vatsim.net/privacy-policy](https://vatsim.net/privacy-policy) |
| aviationweather.gov | ICAO code for METAR weather. Local Flight decodes the returned METAR locally into weather mood/icon/temperature fields; no extra weather provider is contacted for that UI. VATSIM mode can use VATSIM ATIS/METAR first and falls back here when unavailable. | Public government API |
| OurAirports | Public airport/runway CSV data may be bundled or refreshed/cached locally for runway IDs, headings, dimensions, and reference geometry. No account or user identifier is required. | [ourairports.com/data](https://ourairports.com/data/) |
| OpenStreetMap / Overpass | Only when optional radar surface/map layers are enabled or prepared: airport code/coordinates and bounded airport-area geometry requests. Local Flight stores simplified display geometry with attribution, not raw personal data. | [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright) |
| AWS Terrain Tiles | Optional radar terrain/relief layer requests public terrain tile data for the displayed airport area/range. It is cached locally and used only as a subtle visual layer. | [registry.opendata.aws/terrain-tiles](https://registry.opendata.aws/terrain-tiles/) |
| Fly.io | Hosts the Beacon Tools relay and may process connection/security logs at the infrastructure layer. | [fly.io/legal/privacy-policy](https://fly.io/legal/privacy-policy/) |
| Cloudflare | Hosts and protects the Beacon Tools public website and may process connection/security data at the infrastructure layer. | [cloudflare.com/privacypolicy](https://www.cloudflare.com/privacypolicy/) |
| Stripe | Hosts website Relay Access checkout, processes payment and financial receipts, and sends a signed purchase event to Beacon Relay. | [stripe.com/privacy](https://stripe.com/privacy) |
| Mailbox provider | Public website contact forms are delivered through the Beacon Tools relay to the configured support mailbox. This can include your optional name/reply email, selected category, subject, and message. Current provider details are available through the privacy contact. | Provider-specific policy available on request |
| Linear | Manual reports, public website bug reports, and automatic diagnostics are routed there after sanitization and relay-side dedupe/rate limiting. This can include the report title/description you wrote, optional reply email for website bug reports, sanitized technical metadata, crash context/traceback, and optional sanitized log excerpts. | [linear.app/privacy](https://linear.app/privacy) |
| Apple App Store | On iOS, Apple distributes the free app and processes the annual Relay Access subscription and optional consumable support purchases. Local Flight receives signed transaction evidence, not card details. | [apple.com/legal/privacy](https://www.apple.com/legal/privacy/) |
| Google Play | On Android, Google distributes the free app and processes the annual Relay Access subscription and optional consumable support purchases. Local Flight sends purchase tokens for server-side verification and uses a Play Integrity token only for a grant-based transfer; it receives no card details. | [policies.google.com/privacy](https://policies.google.com/privacy) |

Local Flight does not embed tracking or advertising SDKs from any of these services.
Provider data and API access are governed separately from the Local Flight MIT license. See [Third-Party Notices](THIRD_PARTY_NOTICES.md) for data-source and terms links.

---

## Data-Minimization Stance

Local Flight is designed to avoid collecting personal data in normal use:

- no user accounts
- no plain email database fields; Relay Access uses an email HMAC and encrypted notification copy only when checkout, recovery, protection, or transfer needs email
- no analytics profiles
- no ad tracking
- no raw IP storage in the Local Flight relay application database; hosting/CDN infrastructure may transiently process network logs

Technical identifiers, such as install fingerprints, companion IDs, and standalone mobile relay install IDs, can still be personal data in some contexts. Local Flight keeps them short-lived or install-scoped where practical, uses them for rate limiting and troubleshooting, and avoids turning them into account profiles.

For App Store/TestFlight and Play builds, the matching store privacy answers should conservatively disclose install-scoped identifiers, diagnostics/crash data when enabled or manually submitted, coarse relay/app-functionality usage metadata, selected airport/configuration details used for app functionality, optional purchase history/verification metadata, and any manual report title/description you choose to send. Local Flight does not use advertising identifiers, data brokers, or cross-app/site tracking.

Your local data is under your control. To wipe desktop/Pi runtime data, stop Local Flight and remove `~/.localflight/`. Local Flight also keeps a reset-safe identity anchor at `~/.localflight_identity.json`; remove that file too only when you intentionally want the next launch to become a new relay install. On mobile, revoke Remote Companion from the host before forgetting it on the phone, and remove the app to erase all app-local SecureStore and SQLite data.

---

## Data Summary

| Data | Where it lives | Who can see it |
|---|---|---|
| Flight snapshots | Your machine | You |
| Config and personal API keys | Your machine | You |
| Native GUI state and appearance | Your machine | You |
| Mobile appearance/setup choices, non-secret license summary, pending receiver release | Your phone/tablet | You |
| Mobile Relay device credential | Your phone/tablet SecureStore | You |
| Remote Companion phone grant secret | Your phone/tablet and paired Local Flight host | You |
| Standalone mobile history | Your phone/tablet | You |
| Local traffic log | Your machine | You, if network tools are enabled |
| Flight history | Your machine | You |
| Website contact messages | Hosted relay contact gateway, then support mailbox | Beacon Tools and the relay/mailbox providers |
| Manual reports, website bug reports, and automatic diagnostics | Hosted relay reporting gateway, then Linear developer triage inbox | Beacon Tools, relay hosting, and Linear |
| Beacon Relay/Standalone/Remote Companion operational metadata and shared schedule cache | Relay server | Beacon Tools and relay hosting provider |
| Relay Access license, hashed purchase/key/credential references, delivery states, email HMAC, encrypted notification address, and receiver history | Stripe or selected mobile store, then minimal relay license ledger | You, the payment/store provider, Beacon Tools, and relay hosting provider |
| Cached radar surface/map/terrain geometry | Your machine and, for relay-backed surface/map data, short-lived hosted relay cache when optional overlays are enabled | You and relay operator |
| Optional mobile support verification metadata | Apple App Store or Google Play, then minimal hashed relay ledger | You, the selected store, Beacon Tools, and relay hosting provider |
