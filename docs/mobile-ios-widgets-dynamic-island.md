# Mobile iOS Widgets and Dynamic Island Design

This is the design and data-contract handoff for future iOS WidgetKit and ActivityKit work. The Expo app now writes a hardened widget snapshot, and `mobile/native/ios-widget/` contains the tracked native WidgetKit skeleton. The widget target is not wired into Xcode yet because production use still needs Apple Developer signing plus App Groups.

## Product Intent

Local Flight widgets should feel like a small, trustworthy airport-board glance surface rather than a mini app. The widget answers two questions quickly: "What happened to my pinned flight?" and "What else is moving at this airport?"

The Dynamic Island / Live Activity should be even quieter. It is for a pinned flight only, not a scrolling FIDS board.

## Widget Surfaces

### Small Widget: Pinned Flight

- Header: configured airport code and direction, for example `ZRH · DEP`.
- Main line: pinned flight number plus a text-coded status badge.
- Secondary line: display time plus route name or route code.
- Optional detail: gate or terminal only when it fits without shrinking critical text.
- Empty state: `Pin a flight in Local Flight`, with the airport code if configured.
- Stale state: keep the last pinned flight visible and add `STALE` / last updated time; do not silently switch to another flight.

### Medium Widget: Airport Board

- Top lane: Beacon Tools watermark at the left edge, airport name plus departure/arrival pill in the center, and the Local Flight wordmark plus last update status on the right.
- Board lane: horizontal-FIDS columns for time, flight, destination/origin, status, and optional gate/terminal detail.
- If a pinned flight exists, it stays as the first accented row.
- If no pinned flight exists, the medium widget remains a board glance with live rows and the small widget shows the pin prompt.
- If no rows exist, show `Waiting for board data` plus the last updated time.
- Rows use the same passenger vocabulary as Mobile FIDS: display time, flight, route, and status tone.

## Dynamic Island / Live Activity

### Minimal / Compact Island

- Content: flight number and short status only, for example `LX 177 · BOARD`.
- Use a small status accent, but keep text neutral and readable.
- Do not show route, airport name, gate, weather, or row lists.

### Expanded Island and Lock Screen

- Content: flight number, status, time, route code/name, optional gate, and last updated.
- If the pinned flight disappears from current board data, show `Flight stale`.
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

The app derives this from the existing `FidsRow` data and `pinnedCallsign` / `flightPinKey(row)` behavior. The snapshot refreshes after Board data changes, pin changes, setup airport changes, widget preference changes, and app foreground refreshes.

Current app-side file:

- Fallback app sandbox: `localflight-widget-snapshot.json` in the Expo document directory.
- Future App Group location: `group.com.localflight.companion/localflight-widget-snapshot.json`.
- Shared constants and validation: `mobile/src/domain/widgets.ts`.
- App writer: `mobile/src/storage/widgetSnapshot.ts`.
- Native skeleton reader: `mobile/native/ios-widget/WidgetSnapshot.swift`.
- Contract regression check: `cd mobile && npm run widget:contract`.

## Visual Rules

- Dark airport-board shell by default, matching Mobile's technical skin vocabulary.
- Green, amber, red, and blue status tones must always include readable text labels.
- Avoid tiny decorative labels as the only source of important information.
- Small widget critical text should stay readable on the smallest supported iPhone widget surface.
- Medium widget rows may truncate route names, but flight number, time, and status must remain visible.

## Preview Coverage

Static preview: `docs/previews/mobile-ios-widget-preview.svg`

Preview scenarios represented:

- Small widget with pinned flight.
- Medium widget with pinned flight plus three live rows.
- Compact Dynamic Island with flight number and status.
- Expanded/lock-screen Live Activity with status, time, route, gate, and update age.

Future native implementation smoke tests should cover:

- No pinned flight.
- No current rows.
- Stale snapshot.
- Long route names such as `Hong Kong International Airport`.
- Delayed, cancelled, boarding, departed, and scheduled statuses.
- iPhone SE-size, iPhone 16/17 Pro, Pro Max, iPad widget gallery, dark/light appearance.
