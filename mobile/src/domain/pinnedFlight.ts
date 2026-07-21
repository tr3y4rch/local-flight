import type { FidsRow } from "../api/types";

export type PinnedFlightReference = {
  version: 2;
  id: string;
  legacyKey?: string;
  direction: "dep" | "arr";
  providerMovementKey?: string;
  callsign?: string;
  flightNumber?: string;
  routeCode?: string;
  scheduledTime?: string;
};

function clean(value: unknown): string {
  return String(value || "").trim();
}

function compact(value: unknown): string {
  return clean(value).toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function direction(row: FidsRow): "dep" | "arr" {
  return row.view === "arrivals" ? "arr" : "dep";
}

function legacyKey(row: FidsRow): string {
  return clean(row.callsign) || clean(row.id);
}

function hash32(value: string, seed: number): string {
  let hash = seed >>> 0;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

function stablePinId(row: FidsRow): string {
  const providerMovementKey = compact(row.provider_movement_key);
  const flightNumber = compact(row.flight_number);
  const operationalIdentity = compact(row.operating_callsign || row.callsign);
  const fallbackID = compact(row.id);
  const identityAnchor = providerMovementKey
    ? `movement:${providerMovementKey}`
    : flightNumber
      ? `flight:${flightNumber}:${operationalIdentity}`
      : operationalIdentity
        ? `callsign:${operationalIdentity}`
        : `row:${fallbackID}`;
  const seed = [
    direction(row),
    identityAnchor,
    clean(row.sched_time),
    compact(row.route_code || row.route_display)
  ].join("|");
  return `pin:v2:${hash32(seed, 0x811c9dc5)}${hash32(seed, 0x9e3779b9)}`;
}

export function createPinnedFlightReference(row: FidsRow): PinnedFlightReference {
  return {
    version: 2,
    id: stablePinId(row),
    legacyKey: legacyKey(row) || undefined,
    direction: direction(row),
    providerMovementKey: clean(row.provider_movement_key) || undefined,
    callsign: clean(row.callsign) || undefined,
    flightNumber: clean(row.flight_number) || undefined,
    routeCode: clean(row.route_code || row.route_display) || undefined,
    scheduledTime: clean(row.sched_time) || undefined
  };
}

export function normalizePinnedFlightReference(value: unknown): PinnedFlightReference | null {
  if (!value) return null;
  if (typeof value === "string") {
    const legacy = clean(value);
    if (!legacy) return null;
    return {
      version: 2,
      id: legacy.startsWith("pin:v2:") ? legacy : "",
      legacyKey: legacy,
      direction: "dep"
    };
  }
  if (typeof value !== "object") return null;
  const raw = value as Partial<PinnedFlightReference>;
  const id = clean(raw.id);
  const old = clean(raw.legacyKey);
  if (!id && !old) return null;
  return {
    version: 2,
    id,
    legacyKey: old || undefined,
    direction: raw.direction === "arr" ? "arr" : "dep",
    providerMovementKey: clean(raw.providerMovementKey) || undefined,
    callsign: clean(raw.callsign) || undefined,
    flightNumber: clean(raw.flightNumber) || undefined,
    routeCode: clean(raw.routeCode) || undefined,
    scheduledTime: clean(raw.scheduledTime) || undefined
  };
}

export function pinnedFlightId(reference: PinnedFlightReference | null): string {
  return reference?.id || reference?.legacyKey || "";
}

export function pinnedFlightMatches(
  reference: PinnedFlightReference | string | null | undefined,
  row: FidsRow
): boolean {
  const normalized = normalizePinnedFlightReference(reference);
  if (!normalized) return false;
  if (normalized.id && normalized.id === stablePinId(row)) return true;
  if (normalized.legacyKey && normalized.legacyKey === legacyKey(row)) return true;
  if (
    normalized.providerMovementKey &&
    compact(normalized.providerMovementKey) === compact(row.provider_movement_key)
  ) return true;

  const sameDirection = normalized.direction === direction(row);
  const sameRoute = !normalized.routeCode || compact(normalized.routeCode) === compact(row.route_code || row.route_display);
  const sameTime = !normalized.scheduledTime || clean(normalized.scheduledTime) === clean(row.sched_time);
  const sameIdentity = Boolean(
    (normalized.callsign && compact(normalized.callsign) === compact(row.callsign)) ||
    (normalized.flightNumber && compact(normalized.flightNumber) === compact(row.flight_number))
  );
  return sameDirection && sameRoute && sameTime && sameIdentity;
}

export function findPinnedFlight(
  rows: FidsRow[],
  reference: PinnedFlightReference | string | null | undefined
): FidsRow | null {
  return rows.find((row) => pinnedFlightMatches(reference, row)) || null;
}

export function flightStablePinId(row: FidsRow): string {
  return stablePinId(row);
}
