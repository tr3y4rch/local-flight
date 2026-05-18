import type {
  FidsDetailResponse,
  FidsRow,
  FlightDetail,
  HistoryFlightRow
} from "../api/types";
import type { StatusTone } from "./types";

export function routeCode(route: string): string {
  const trimmed = route.trim();
  const match = trimmed.match(/\(([A-Z0-9]{3,4})\)/);
  if (match?.[1]) return match[1];
  const plainCode = trimmed.match(/^([A-Z0-9]{3,4})$/);
  return plainCode?.[1] || "";
}

export function routeName(route: string): string {
  const trimmed = route.trim();
  if (!trimmed) return "-";
  const code = routeCode(trimmed);
  if (code && trimmed === code) return code;
  return trimmed.replace(/\s*\([A-Z0-9]{3,4}\)\s*$/, "").trim() || code || "-";
}

export function routeMeta(row: FidsRow): string {
  const code = routeCode(row.route_display);
  const gate = row.gate && row.gate !== "-" ? `G${row.gate}` : "";
  if (code && gate) return `${code} · ${gate}`;
  if (code) return code;
  if (gate) return gate;
  return "---";
}

export function statusTone(status: string): StatusTone {
  const value = status.toLowerCase();
  if (value.includes("cancel")) return "cancelled";
  if (value.includes("delay") || value.includes("late")) return "delayed";
  if (value.includes("depart") || value.includes("dept")) return "departed";
  if (
    value.includes("board") ||
    value.includes("gate") ||
    value.includes("land") ||
    value.includes("arriv") ||
    value.includes("approach") ||
    value.includes("on time")
  ) return "boarding";
  return "scheduled";
}

export function formatAltitudeFeet(value?: number | null): string {
  if (value == null) return "-";
  return `${Math.round(value * 3.28084)} ft`;
}

export function formatSpeedKnots(value?: number | null): string {
  if (value == null) return "-";
  return `${Math.round(value * 1.94384)} kt`;
}

export function formatHeading(value?: number | null): string {
  if (value == null) return "-";
  return `${Math.round(value)} deg`;
}

export function detailOrNull(value: FidsDetailResponse | null): FlightDetail | null {
  if (!value?.detail || typeof value.detail !== "object") {
    return null;
  }
  if (!("callsign" in value.detail) || typeof value.detail.callsign !== "string") {
    return null;
  }
  return value.detail as FlightDetail;
}

export function historyRouteLabel(row: HistoryFlightRow): string {
  if (row.direction === "ARR") {
    return `FROM ${row.origin_iata || "---"}`;
  }
  if (row.direction === "DEP") {
    return `TO ${row.dest_iata || "---"}`;
  }
  return `${row.origin_iata || "---"} / ${row.dest_iata || "---"}`;
}

export function detailRouteLabel(detail: FlightDetail | null, fallback: string): string {
  if (!detail) return fallback;
  const sourceHint = `${detail.detail_mode || ""} ${detail.source || ""} ${detail.data_sources?.schedule || ""}`.toLowerCase();
  const virtual = sourceHint.includes("virtual") || sourceHint.includes("vatsim");
  const origin = (virtual ? detail.origin_icao : detail.origin_iata) || detail.origin_iata || detail.origin_icao || "---";
  const dest = (virtual ? detail.dest_icao : detail.dest_iata) || detail.dest_iata || detail.dest_icao || "---";
  return `${origin} -> ${dest}`;
}

export function flightPinKey(row: FidsRow): string {
  return row.callsign || row.id;
}

/**
 * Map any server-side status string to a 5-word PAX vocabulary.
 * Display labels are intentionally passenger-friendly and unambiguous.
 * Used by StatusBadge in FIDS rows and by FlightIsland.
 */
export function statusShort(status: string): string {
  const s = status.replace(/\s+/g, " ").trim().toUpperCase();
  if (!s) return "SCHEDULED";
  if (s.startsWith("CANCEL")) return "CANCELLED";
  if (s.startsWith("DELAY") || s.startsWith("LATE") || s.startsWith("+")) return "DELAYED";
  if (s.startsWith("BOARD") || s.startsWith("GATE") || s.startsWith("FINAL CALL") || s.startsWith("LAST CALL")) return "BOARDING";
  if (s.startsWith("DEPART") || s.startsWith("DEPT") || s.startsWith("TAKEOFF") || s.startsWith("AIRBORNE")) return "DEPARTED";
  if (
    s.startsWith("ARRIV") || s.startsWith("LAND") || s.startsWith("APPROACH") ||
    s.startsWith("ON FINAL") || s.startsWith("TAXI")
  ) return "ARRIVED";
  // "EARLY x" / "ON TIME" → still on the schedule, show as scheduled
  return "SCHEDULED";
}
