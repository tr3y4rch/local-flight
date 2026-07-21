import type { FidsRow, FlightView } from "../api/types";
import { flightPinKey, routeCode, routeName, statusShort, statusTone } from "./flights";
import type { StatusTone } from "./types";
import type { MobileWidgetPreferences } from "../storage/settings";
import {
  findPinnedFlight,
  type PinnedFlightReference
} from "./pinnedFlight";

export type WidgetFlightPreview = {
  id: string;
  flightDisplay: string;
  direction: "dep" | "arr";
  routeName: string;
  routeCode: string;
  displayTime: string;
  statusDisplay: string;
  statusTone: StatusTone;
  gate?: string;
  terminal?: string;
};

export type WidgetPreviewSnapshot = {
  airportCode: string;
  airportName: string;
  updatedLabel: string;
  view: FlightView;
  smallSource: "pinned" | "empty";
  pinnedFlight: WidgetFlightPreview | null;
  liveFlights: WidgetFlightPreview[];
};

export const WIDGET_SNAPSHOT_SCHEMA_VERSION = 1;
export const WIDGET_APP_GROUP_ID = "group.cc.beacontools.localflight";
export const WIDGET_SNAPSHOT_FILENAME = "localflight-widget-snapshot.json";
export const WIDGET_SNAPSHOT_STALE_AFTER_MS = 60 * 60 * 1000;
export const WIDGET_STANDALONE_STALE_AFTER_MS = 90 * 60 * 1000;
export const WIDGET_SNAPSHOT_MAX_BYTES = 64 * 1024;
const WIDGET_MAX_MEDIUM_ROWS_WITH_PIN = 3;

export type WidgetSnapshotMode = "lan_companion" | "standalone";

export type LocalFlightWidgetSnapshot = {
  schemaVersion: typeof WIDGET_SNAPSHOT_SCHEMA_VERSION;
  generatedAt: string;
  expiresAt: string;
  mode: WidgetSnapshotMode;
  stale: boolean;
  airport: {
    code: string;
    name: string;
    view: FlightView;
  };
  source: {
    label: string;
    lastUpdatedLabel: string;
    updatedAt: string;
  };
  preferences: MobileWidgetPreferences;
  small: {
    source: "pinned" | "empty";
    flight: WidgetFlightPreview | null;
  };
  medium: {
    rowCount: 2 | 3;
    rows: Array<WidgetFlightPreview & { pinned: boolean }>;
  };
  liveActivity: {
    flight: WidgetFlightPreview | null;
    stale: boolean;
  };
};

function cleanWidgetValue(value?: string | null): string {
  const cleaned = String(value || "").trim();
  return cleaned && cleaned !== "-" ? cleaned : "";
}

function clampWidgetText(value: string, max = 80): string {
  const cleaned = cleanWidgetValue(value);
  return cleaned.length > max ? cleaned.slice(0, max).trim() : cleaned;
}

function normalizeStatusTone(value: unknown): StatusTone {
  switch (value) {
    case "departed":
    case "boarding":
    case "delayed":
    case "cancelled":
      return value;
    default:
      return "scheduled";
  }
}

function normalizeDirection(value: unknown): "dep" | "arr" {
  return value === "arr" ? "arr" : "dep";
}

function normalizeView(value: unknown): FlightView {
  return value === "arrivals" ? "arrivals" : "departures";
}

function normalizeWidgetPreferences(value: unknown): MobileWidgetPreferences {
  if (!value || typeof value !== "object") {
    return { mediumRowCount: 3, showGateTerminal: true, automaticRefresh: true, liveActivityEnabled: false };
  }
  const raw = value as Partial<MobileWidgetPreferences>;
  return {
    mediumRowCount: raw.mediumRowCount === 2 ? 2 : 3,
    showGateTerminal: raw.showGateTerminal !== false,
    automaticRefresh: raw.automaticRefresh !== false,
    liveActivityEnabled: raw.liveActivityEnabled === true
  };
}

export function widgetSnapshotStaleAfterMs(
  mode: WidgetSnapshotMode,
  refreshSeconds?: number | null
): number {
  if (mode === "standalone") return WIDGET_STANDALONE_STALE_AFTER_MS;
  const configuredMs = Math.max(0, Number(refreshSeconds || 0)) * 1000;
  return Math.min(24 * 60 * 60 * 1000, Math.max(WIDGET_SNAPSHOT_STALE_AFTER_MS, configuredMs * 2));
}

function parseWidgetDate(value: unknown): number | null {
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) ? parsed : null;
}

export function isWidgetSnapshotExpired(
  snapshot: Pick<LocalFlightWidgetSnapshot, "expiresAt">,
  now = new Date()
): boolean {
  const expiresAt = parseWidgetDate(snapshot.expiresAt);
  return expiresAt == null || expiresAt <= now.getTime();
}

function rowDirection(row: FidsRow): "dep" | "arr" {
  return row.view === "arrivals" ? "arr" : "dep";
}

function rowToWidgetFlight(row: FidsRow): WidgetFlightPreview {
  const fallbackRouteCode = routeCode(row.route_display);
  return {
    id: flightPinKey(row),
    flightDisplay: cleanWidgetValue(row.flight_display) || cleanWidgetValue(row.callsign) || "--",
    direction: rowDirection(row),
    routeName: routeName(row.route_display),
    routeCode: cleanWidgetValue(row.route_code) || fallbackRouteCode,
    displayTime: cleanWidgetValue(row.display_time) || "--:--",
    statusDisplay: statusShort(row.status_display),
    statusTone: statusTone(row.status_display),
    gate: cleanWidgetValue(row.terminal_gate_display) || cleanWidgetValue(row.gate_display),
    terminal: cleanWidgetValue(row.terminal_display)
  };
}

export function deriveWidgetPreviewSnapshot({
  rows,
  pinnedCallsign,
  airportCode,
  airportName,
  updatedLabel,
  view,
  preferences
}: {
  rows: FidsRow[];
  pinnedCallsign: string | PinnedFlightReference | null;
  airportCode: string;
  airportName: string;
  updatedLabel?: string;
  view: FlightView;
  preferences: MobileWidgetPreferences;
}): WidgetPreviewSnapshot {
  const pinnedRow = findPinnedFlight(rows, pinnedCallsign);
  const liveRows = rows
    .filter((row) => (row.view === "arrivals" ? "arrivals" : "departures") === view)
    .filter((row) => !pinnedRow || flightPinKey(row) !== flightPinKey(pinnedRow))
    .slice(0, preferences.mediumRowCount)
    .map(rowToWidgetFlight);

  return {
    airportCode: airportCode || "---",
    airportName: airportName || "Local Flight Airport",
    updatedLabel: cleanWidgetValue(updatedLabel) || (rows.length ? "Updated now" : "Waiting"),
    view,
    smallSource: pinnedRow ? "pinned" : "empty",
    pinnedFlight: pinnedRow ? rowToWidgetFlight(pinnedRow) : null,
    liveFlights: liveRows
  };
}

export function normalizeWidgetFlight(value: unknown): WidgetFlightPreview | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<WidgetFlightPreview>;
  const id = clampWidgetText(String(raw.id || ""), 96);
  const flightDisplay = clampWidgetText(String(raw.flightDisplay || raw.id || ""), 24);
  if (!id && !flightDisplay) return null;
  return {
    id: id || flightDisplay,
    flightDisplay: flightDisplay || "--",
    direction: normalizeDirection(raw.direction),
    routeName: clampWidgetText(String(raw.routeName || ""), 64) || "-",
    routeCode: clampWidgetText(String(raw.routeCode || ""), 8),
    displayTime: clampWidgetText(String(raw.displayTime || ""), 12) || "--:--",
    statusDisplay: clampWidgetText(String(raw.statusDisplay || ""), 20) || "SCHEDULE",
    statusTone: normalizeStatusTone(raw.statusTone),
    gate: clampWidgetText(String(raw.gate || ""), 16) || undefined,
    terminal: clampWidgetText(String(raw.terminal || ""), 16) || undefined
  };
}

export function buildWidgetExchangeSnapshot({
  preview,
  preferences,
  mode,
  generatedAt = new Date(),
  stale = false,
  sourceLabel = "mobile",
  sourceUpdatedAt,
  staleAfterMs
}: {
  preview: WidgetPreviewSnapshot;
  preferences: MobileWidgetPreferences;
  mode: WidgetSnapshotMode;
  generatedAt?: Date;
  stale?: boolean;
  sourceLabel?: string;
  sourceUpdatedAt?: string | null;
  staleAfterMs?: number;
}): LocalFlightWidgetSnapshot {
  const normalizedPreferences = normalizeWidgetPreferences(preferences);
  const pinned = preview.pinnedFlight ? normalizeWidgetFlight(preview.pinnedFlight) : null;
  const pinnedForMedium = pinned && (
    (preview.view === "arrivals" && pinned.direction === "arr") ||
    (preview.view === "departures" && pinned.direction === "dep")
  ) ? pinned : null;
  const mediumRows = [
    ...(pinnedForMedium ? [{ ...pinnedForMedium, pinned: true }] : []),
    ...preview.liveFlights
      .map((flight) => normalizeWidgetFlight(flight))
      .filter((flight): flight is WidgetFlightPreview => Boolean(flight))
      .slice(0, normalizedPreferences.mediumRowCount - (pinnedForMedium ? 1 : 0))
      .map((flight) => ({ ...flight, pinned: false }))
  ].slice(0, normalizedPreferences.mediumRowCount);

  const parsedSourceUpdatedAt = parseWidgetDate(sourceUpdatedAt);
  const effectiveSourceUpdatedAt = parsedSourceUpdatedAt == null ? generatedAt.getTime() : parsedSourceUpdatedAt;
  const effectiveStaleAfterMs = Math.max(
    15 * 60 * 1000,
    Number(staleAfterMs || widgetSnapshotStaleAfterMs(mode))
  );

  return {
    schemaVersion: WIDGET_SNAPSHOT_SCHEMA_VERSION,
    generatedAt: generatedAt.toISOString(),
    expiresAt: new Date(effectiveSourceUpdatedAt + effectiveStaleAfterMs).toISOString(),
    mode,
    stale,
    airport: {
      code: clampWidgetText(preview.airportCode, 8) || "---",
      name: clampWidgetText(preview.airportName, 80) || "Local Flight Airport",
      view: normalizeView(preview.view)
    },
    source: {
      label: clampWidgetText(sourceLabel, 32) || "mobile",
      lastUpdatedLabel: clampWidgetText(preview.updatedLabel, 32) || "Waiting",
      updatedAt: new Date(effectiveSourceUpdatedAt).toISOString()
    },
    preferences: normalizedPreferences,
    small: {
      source: pinned ? "pinned" : "empty",
      flight: pinned
    },
    medium: {
      rowCount: normalizedPreferences.mediumRowCount,
      rows: mediumRows
    },
    liveActivity: {
      flight: pinned,
      stale: stale || !pinned
    }
  };
}

export function normalizeWidgetExchangeSnapshot(value: unknown): LocalFlightWidgetSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<LocalFlightWidgetSnapshot>;
  if (raw.schemaVersion !== WIDGET_SNAPSHOT_SCHEMA_VERSION) return null;
  const generatedAt = parseWidgetDate(raw.generatedAt);
  if (generatedAt == null) return null;
  const expiresAt = parseWidgetDate(raw.expiresAt) ?? generatedAt + WIDGET_SNAPSHOT_STALE_AFTER_MS;
  const preferences = normalizeWidgetPreferences(raw.preferences);
  const pinned = raw.small?.source === "pinned" ? normalizeWidgetFlight(raw.small.flight) : null;
  const mediumRows = Array.isArray(raw.medium?.rows)
    ? raw.medium.rows
      .map((flight) => {
        const normalized = normalizeWidgetFlight(flight);
        return normalized ? { ...normalized, pinned: Boolean((flight as { pinned?: unknown }).pinned) } : null;
      })
      .filter((flight): flight is WidgetFlightPreview & { pinned: boolean } => Boolean(flight))
      .slice(0, Math.min(WIDGET_MAX_MEDIUM_ROWS_WITH_PIN, preferences.mediumRowCount))
    : [];
  const expired = expiresAt <= Date.now();

  return {
    schemaVersion: WIDGET_SNAPSHOT_SCHEMA_VERSION,
    generatedAt: new Date(generatedAt).toISOString(),
    expiresAt: new Date(expiresAt).toISOString(),
    mode: raw.mode === "standalone" ? "standalone" : "lan_companion",
    stale: Boolean(raw.stale) || expired,
    airport: {
      code: clampWidgetText(String(raw.airport?.code || ""), 8) || "---",
      name: clampWidgetText(String(raw.airport?.name || ""), 80) || "Local Flight Airport",
      view: normalizeView(raw.airport?.view)
    },
    source: {
      label: clampWidgetText(String(raw.source?.label || ""), 32) || "mobile",
      lastUpdatedLabel: clampWidgetText(String(raw.source?.lastUpdatedLabel || ""), 32) || "Waiting",
      updatedAt: new Date(parseWidgetDate(raw.source?.updatedAt) ?? generatedAt).toISOString()
    },
    preferences,
    small: {
      source: pinned ? "pinned" : "empty",
      flight: pinned
    },
    medium: {
      rowCount: preferences.mediumRowCount,
      rows: mediumRows
    },
    liveActivity: {
      flight: pinned,
      stale: Boolean(raw.liveActivity?.stale) || expired || !pinned
    }
  };
}

export function serializeWidgetExchangeSnapshot(snapshot: LocalFlightWidgetSnapshot): string {
  const json = JSON.stringify(normalizeWidgetExchangeSnapshot(snapshot) || snapshot);
  let bytes = 0;
  for (const character of json) {
    const codePoint = character.codePointAt(0) || 0;
    bytes += codePoint <= 0x7f ? 1 : codePoint <= 0x7ff ? 2 : codePoint <= 0xffff ? 3 : 4;
  }
  if (bytes > WIDGET_SNAPSHOT_MAX_BYTES) {
    throw new Error("Widget snapshot exceeds the 64 KiB safety limit.");
  }
  return json;
}

export function parseWidgetExchangeSnapshot(json: string): LocalFlightWidgetSnapshot | null {
  try {
    return normalizeWidgetExchangeSnapshot(JSON.parse(json));
  } catch {
    return null;
  }
}

export function widgetSnapshotSemanticKey(snapshot: LocalFlightWidgetSnapshot): string {
  const normalized = normalizeWidgetExchangeSnapshot(snapshot) || snapshot;
  return JSON.stringify({
    ...normalized,
    generatedAt: "",
    expiresAt: ""
  });
}
