# Local Flight 0.6.1 - Reliability and Clearer Mobile Controls

Version 0.6.1 is a release candidate. Public desktop, Linux, and Raspberry Pi
downloads remain at 0.6.0 until replacement packages have been validated and
published. Mobile builds require separate TestFlight and Google Play processing;
source availability does not mean an update is available to testers yet.

## Mobile Improvements

- Board, Radar, and Settings retain useful content when an optional request fails.
- Settings use clearer language and more dependable sheets. The navigation bar
  follows scrolling without relying on a full page reload.
- Plain-language weather, aviation details, and raw METAR now show distinct
  information in the weather sheet and follow the selected device preference.
- Optional support remains at the bottom of Settings. New purchases wait for
  store and verification availability rather than leaving users guessing.
- Companion, Remote Companion, and Standalone retain their separate connection
  and access behavior. Network retries are bounded and do not bypass access limits.

## Flight Data and Access

- Shared schedule refreshes coordinate concurrent requests and preserve the
  original observation age. Reading a cached board does not make old data new.
- AeroDataBox and AviationStack can each provide schedules alone. Where both
  are configured and permitted, a working alternate is preferred to an older
  cached result when the primary source fails.
- Radar responses expose the normalized display data, not an entire provider feed.
- Relay Access recovery supports emailing the current key again without moving
  the active device. Replacing a lost key remains a separate confirmed action.
- Simultaneous activation and recovery requests retain the one-active-main-device
  rule. A saved purchase survives temporary email-delivery failures.

## What Remains Separate

Relay Access and optional support are different purchases. Support tips unlock
nothing and never create a Relay Access license. Store or web sales are available
only where explicitly enabled; this candidate does not open production sales.

Receipts come from the payment provider. Beacon Tools sends separate license
delivery and recovery emails. Instant delivery, inbox placement, provider uptime,
and perpetual hosted service cannot be guaranteed.

Existing installation identity, settings, and local data are preserved. Widgets
continue to use snapshots prepared by the app, not their own provider requests.

Local Flight is an informational display only. Flight, weather, radar, and map
data can be delayed, incomplete, cached, incorrect, or unavailable. Do not use
it for navigation, dispatch, flight planning, operational control, or safety decisions.
