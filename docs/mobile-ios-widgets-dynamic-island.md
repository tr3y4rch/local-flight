# Mobile Home-Screen Widgets and Live Activity

This is the implementation and data-contract handoff for Local Flight home-screen widgets. The hardened `0.5.2` testing source targets iOS build `12` and Android versionCode `15`. Expo config plugins generate the iOS WidgetKit extension/App Group and Android `AppWidgetProvider` from the tracked templates under `mobile/native/ios-widget/` and `mobile/native/android-widget/`. Dynamic Island and Live Activities are capability-gated and remain local snapshot consumers without extension-side networking.

## Product Intent

Local Flight widgets should feel like a small, trustworthy airport-board glance surface rather than a mini app. The widget answers two questions quickly: "What happened to my pinned flight?" and "What else is moving at this airport?"

The Dynamic Island / Live Activity should be even quieter. It is for a pinned flight only, not a scrolling FIDS board.

## Widget Surfaces

### Small Widget: Pinned Flight

- Header: a quiet `Pinned flight` label and airport context.
- Main line: pinned flight identity plus its operational status.
- Secondary line: display time, route, and supplied gate or terminal when space permits.
- Optional detail: gate or terminal only when it fits without shrinking critical text.
- Empty state: `Pin a flight in Local Flight`, with the airport code if configured.
- Update-needed state: keep the last pinned flight visible and qualify freshness separately; do not replace its operational status or silently switch flights.

### Medium Widget: Airport Board

- Header: airport, direction, and quiet freshness.
- Board body: two or three separated movement rows with time, flight, route, operational status, and optional gate/terminal detail.
- If a pinned flight exists, it stays as the first accented row.
- If no pinned flight exists, the medium widget remains a board glance with live rows and the small widget shows the pin prompt.
- If no rows exist, show `Waiting for board data` plus the last updated time.
- Rows use the same passenger vocabulary as Mobile FIDS: display time, flight, route, and status tone.

### Android Home-Screen Widget

- Uses one resizable widget rather than separate small/medium definitions.
- Compact widths show one primary row; wider widths show up to three rows.
- Tapping the widget opens Board. A contextual refresh route may ask the app for one bounded refresh after it opens; the widget itself never fetches data.
- Android also performs its normal low-frequency widget refresh, limited to 30 minutes.

## Dynamic Island / Live Activity

### Minimal / Compact Island

- Content: flight number and short status only, for example `LX 177 · BOARD`.
- Use a small status accent, but keep text neutral and readable.
- Do not show route, airport name, gate, weather, or row lists.

### Expanded Island and Lock Screen

- Content: flight number, status, time, route code/name, optional gate, and last updated.
- Keep operational status primary. Qualify freshness separately as cached or update needed when the pinned flight expires or can no longer be resolved.
- The Live Activity should remain pinned-flight-only; it must not mirror the full board.

## Snapshot Contract

The app writes one app-owned snapshot for the widget extension to read. The widget extension must not fetch LAN or relay data directly.

```ts
type LocalFlightWidgetSnapshot = {
  schemaVersion: 1;
  generatedAt: string; // ISO UTC
  expiresAt: string; // ISO UTC
  mode: "lan_companion" | "standalone";
  stale: boolean;
  airport: {
    code: string;
    name: string;
    view: "departures" | "arrivals";
  };
  source: {
    label: string;
    lastUpdatedLabel: string;
  };
  preferences: {
    mediumRowCount: 2 | 3;
    showGateTerminal: boolean;
  };
  small: {
    source: "pinned" | "empty";
    flight: WidgetFlight | null;
  };
  medium: {
    rowCount: 2 | 3;
    rows: Array<WidgetFlight & { pinned: boolean }>;
  };
  liveActivity: {
    flight: WidgetFlight | null;
    stale: boolean;
  };
};

type WidgetFlight = {
  id: string;
  flightDisplay: string;
  direction: "dep" | "arr";
  routeName: string;
  routeCode: string;
  displayTime: string;
  statusDisplay: string;
  statusTone: "scheduled" | "boarding" | "departed" | "delayed" | "cancelled";
  gate?: string;
  terminal?: string;
};
```

The app derives this from existing `FidsRow` data and a versioned `PinnedFlightReference`. The stable pin reference preserves direction, movement key, callsign, flight number, route, and scheduled time without conflating those identities. The snapshot refreshes after Board data changes, pin changes, setup airport changes, widget preference changes, explicit widget refreshes, source timestamp changes, and app foreground refreshes.

Current app-side file:

- Android/private fallback: `localflight-widget-snapshot.json` in the Expo document directory, which maps to the app's private files directory on Android.
- iOS shared location: `group.cc.beacontools.localflight/localflight-widget-snapshot.json`.
- Shared constants and validation: `mobile/src/domain/widgets.ts`.
- App writer: `mobile/src/storage/widgetSnapshot.ts`.
- iOS reader: `mobile/native/ios-widget/WidgetSnapshot.swift`.
- Android reader: `mobile/native/android-widget/LocalFlightWidgetProvider.kt`.
- Contract regression checks: `cd mobile && npm run widget:contract && npm run native-widget:contract`.

Both native readers enforce schema version `1`, reject files larger than 64 KiB,
bound row/text output, and mark expired data stale. Neither native widget is
allowed to open LAN, relay, or provider connections.

## Visual Rules

- Warm cloud/ivory and midnight V2 surfaces follow the app appearance.
- Green, amber, red, and blue status tones must always include readable text labels.
- Avoid tiny decorative labels as the only source of important information.
- Small widget critical text should stay readable on the smallest supported iPhone widget surface.
- Medium widget rows may truncate route names, but display identity, time, and operational status must remain visible.

## Preview Coverage

Static preview: `docs/previews/mobile-ios-widget-preview.svg`

Preview scenarios represented:

- Small widget with pinned flight.
- Medium widget with a pinned flight plus up to two additional rows.
- Compact Dynamic Island with flight number and status.
- Expanded/lock-screen Live Activity with status, time, route, gate, and update age.

Native widget smoke tests should cover:

- No pinned flight.
- No current rows.
- Stale snapshot.
- Long route names such as `Hong Kong International Airport`.
- Delayed, cancelled, boarding, departed, and scheduled statuses.
- iPhone SE-size, iPhone 16/17 Pro, Pro Max, iPad widget gallery, dark/light appearance.
- Compact and expanded Android widgets on a Pixel-style launcher and Samsung One UI.
