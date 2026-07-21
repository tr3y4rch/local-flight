import type {
  FidsDetailResponse,
  FidsRow,
  FlightDetail,
  HistoryFlightRow,
  RadarBlip
} from "../api/types";
import { flightStablePinId } from "./pinnedFlight";
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
  const gate = row.terminal_gate_display || row.gate_display || "";
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
  const detail = value.detail as FlightDetail;
  if (!clean(detail.callsign) && !clean(detail.flight_number) && !clean(detail.flight_display)) {
    return null;
  }
  return detail;
}

function clean(value?: unknown): string {
  return String(value || "").trim();
}

function compactIdentity(value?: unknown): string {
  return clean(value).toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function isPublicFlightNumber(value?: unknown): boolean {
  return /^[A-Z0-9]{2,3}0*\d{1,5}[A-Z]?$/.test(compactIdentity(value));
}

function directionLabel(value?: string | null): string {
  const text = clean(value).toLowerCase();
  if (text === "arr" || text === "arrival" || text === "arrivals") return "arrivals";
  return "departures";
}

function routeForRow(row: FidsRow): string {
  return clean(row.route_code) || routeCode(row.route_display) || "";
}

export function fidsRowDetailResponse(row: FidsRow, airportCode = ""): FidsDetailResponse {
  const view = directionLabel(row.view);
  const route = routeForRow(row);
  const origin = view === "arrivals" ? route : airportCode;
  const destination = view === "departures" ? route : airportCode;
  return {
    detail: {
      callsign: row.callsign || row.operating_callsign || undefined,
      flight_number: isPublicFlightNumber(row.flight_number) ? row.flight_number : null,
      flight_display: row.flight_display || row.flight_number || row.callsign || row.id,
      airline: row.airline_display || row.marketing_airline_name || null,
      airline_iata: row.airline_iata || row.marketing_airline_iata || null,
      airline_icao: row.airline_icao || row.marketing_airline_icao || null,
      codeshares: row.codeshares || [],
      sold_as: row.sold_as || [],
      origin_iata: row.origin_iata || origin || null,
      origin_icao: row.origin_icao || null,
      origin_name: row.origin_name || null,
      dest_iata: row.dest_iata || destination || null,
      dest_icao: row.dest_icao || null,
      dest_name: row.dest_name || null,
      sched_time: row.sched_time || row.time_primary || row.display_time || null,
      est_time: row.est_time || null,
      actual_time: row.actual_time || null,
      delay_minutes: row.delay_minutes ?? null,
      delay_kind: row.delay_kind || null,
      delay_class: row.delay_class || null,
      gate: row.gate_display || row.terminal_gate_display || null,
      gate_display: row.gate_display || row.terminal_gate_display || null,
      terminal_display: row.terminal_display || null,
      terminal_gate_display: row.terminal_gate_display || row.gate_display || null,
      gate_source: row.gate_source || null,
      terminal_source: row.terminal_source || null,
      gate_confidence: row.gate_confidence || null,
      terminal_confidence: row.terminal_confidence || null,
      ops_location_notes: row.ops_location_notes || [],
      aircraft_type: row.aircraft_type || null,
      direction: view,
      status: row.status_display || row.status_kind || null,
      source: row.source_hint || "mobile",
      updated_at: row.updated_at || null,
      data_sources: {
        schedule: row.source_hint || "airline schedules",
        snapshot_generated_at: row.updated_at || null
      },
      enriched_by: row.live_hint || null,
      detail_mode: row.detail_mode || "real",
      operating_callsign: row.operating_callsign || null,
      identity_source: row.identity_source || null,
      provider_codeshare_status: row.provider_codeshare_status || null,
      provider_movement_key: row.provider_movement_key || null,
      identity_evidence: row.identity_evidence || []
    },
    history: []
  };
}

export function matchRadarBlipToFidsRows(blip: RadarBlip, rows: FidsRow[]): FidsRow | null {
  const registration = compactIdentity(blip.registration);
  const icao24 = compactIdentity(blip.icao24);
  const callsign = compactIdentity(blip.operating_callsign || blip.callsign);
  const flightNumber = isPublicFlightNumber(blip.flight_number) ? compactIdentity(blip.flight_number) : "";
  const ranked = rows.flatMap((row) => {
    const rowRegistration = compactIdentity(row.aircraft_registration);
    const rowIcao24 = compactIdentity(row.icao24);
    const rowCallsigns = new Set([
      compactIdentity(row.callsign),
      compactIdentity(row.operating_callsign)
    ].filter(Boolean));
    const rowFlight = isPublicFlightNumber(row.flight_number) ? compactIdentity(row.flight_number) : "";
    let score = 0;
    if (registration && rowRegistration && registration === rowRegistration) score = 100;
    if (icao24 && rowIcao24 && icao24 === rowIcao24) score = Math.max(score, 100);
    if (callsign && rowCallsigns.has(callsign)) score = Math.max(score, 90);
    if (flightNumber && rowFlight && flightNumber === rowFlight) score = Math.max(score, 80);
    return score ? [{ row, score }] : [];
  }).sort((a, b) => b.score - a.score);
  const top = ranked[0];
  if (!top) return null;
  const tied = ranked.filter((candidate) => candidate.score === top.score);
  return tied.length === 1 ? top.row : null;
}

export function radarBlipDetailResponse(
  blip: RadarBlip,
  scheduleRow?: FidsRow | null,
  airportCode = ""
): FidsDetailResponse {
  const callsign = clean(blip.callsign) || clean(blip.operating_callsign);
  const displayIdentity = clean(blip.display_title) || clean(blip.flight_number) || callsign || clean(blip.icao24) || "RADAR TRACK";
  const scheduleDetail = scheduleRow
    ? fidsRowDetailResponse(scheduleRow, airportCode).detail as FlightDetail
    : {};
  const publicFlightNumber = isPublicFlightNumber(blip.flight_number) ? clean(blip.flight_number) : null;
  const flightNumber = scheduleDetail.flight_number || publicFlightNumber;
  const flightDisplay = scheduleDetail.flight_display || publicFlightNumber || displayIdentity;
  return {
    detail: {
      ...scheduleDetail,
      callsign: callsign || undefined,
      flight_number: flightNumber || null,
      flight_display: flightDisplay,
      airline: scheduleDetail.airline || blip.airline_name || null,
      airline_iata: scheduleDetail.airline_iata || blip.airline_iata || null,
      airline_icao: scheduleDetail.airline_icao || blip.airline_icao || null,
      codeshares: scheduleDetail.codeshares || blip.codeshares || [],
      sold_as: scheduleDetail.sold_as || blip.sold_as || [],
      aircraft_type: scheduleDetail.aircraft_type || blip.aircraft_type || null,
      aircraft_registration: blip.registration || null,
      direction: scheduleDetail.direction || null,
      status: scheduleDetail.status || blip.radar_status_label || blip.radar_phase || "Tracked target",
      source: blip.source || blip.source_quality || "radar",
      enriched_by: blip.enriched ? "radar" : null,
      detail_mode: blip.detail_mode || "real",
      operating_callsign: blip.operating_callsign || callsign || null,
      identity_source: scheduleDetail.identity_source || blip.identity_source || "radar_callsign",
      position: {
        lat: blip.lat,
        lon: blip.lon,
        altitude_m: blip.altitude_m ?? blip.geo_altitude_m ?? null,
        altitude_baro_m: blip.altitude_m ?? null,
        altitude_geo_m: blip.geo_altitude_m ?? null,
        speed_ms: blip.speed_ms ?? null,
        heading: blip.heading_deg ?? blip.track_deg ?? blip.heading ?? null,
        vertical_rate: blip.vertical_rate ?? null,
        on_ground: blip.on_ground ?? null,
        icao24: blip.icao24 || null,
        squawk: blip.squawk || null,
        last_contact: null
      },
      intel: {
        schema_version: "flight-intel-v1",
        detail_mode: blip.detail_mode || "real",
        identity: {
          callsign: callsign || null,
          flight_display: flightDisplay,
          operating_callsign: blip.operating_callsign || callsign || null,
          airline_name: scheduleDetail.airline || blip.airline_name || null,
          airline_iata: scheduleDetail.airline_iata || blip.airline_iata || null,
          airline_icao: scheduleDetail.airline_icao || blip.airline_icao || null,
          codeshares: scheduleDetail.codeshares || blip.codeshares || [],
          sold_as: scheduleDetail.sold_as || blip.sold_as || []
        },
        aircraft: {
          type: blip.aircraft_type || null,
          registration: blip.registration || null,
          icao24: blip.icao24 || null,
          squawk: blip.squawk || null
        },
        operations: {},
        timing: {
          scheduled: scheduleDetail.sched_time || null,
          estimated: scheduleDetail.est_time || null,
          actual: scheduleDetail.actual_time || null,
          delay_minutes: scheduleDetail.delay_minutes ?? null,
          status: scheduleDetail.status || blip.board_status || blip.status || null
        },
        motion: {
          altitude_ft: blip.altitude_ft ?? blip.geo_altitude_ft ?? null,
          speed_kt: blip.speed_kt ?? null,
          heading_deg: blip.heading_deg ?? blip.track_deg ?? blip.heading ?? null,
          vertical_rate_fpm: blip.vertical_rate_fpm ?? null,
          on_ground: blip.on_ground ?? null
        },
        source_evidence: {
          position_source: blip.source || blip.source_quality || "radar"
        }
      }
    },
    history: []
  };
}

export function historyRowDetailResponse(row: HistoryFlightRow): FidsDetailResponse {
  const callsign = clean(row.callsign) || clean(row.operating_callsign);
  const displayIdentity = clean(row.flight_number) || callsign || clean(row.id) || "HISTORY MOVEMENT";
  return {
    detail: {
      callsign: callsign || undefined,
      flight_number: isPublicFlightNumber(row.flight_number) ? row.flight_number : null,
      flight_display: displayIdentity,
      airline_iata: row.airline_iata || null,
      codeshares: row.codeshares || [],
      sold_as: row.sold_as || [],
      origin_iata: row.origin_iata || null,
      dest_iata: row.dest_iata || null,
      sched_time: row.sched_time || null,
      actual_time: row.actual_time || null,
      delay_minutes: row.delay_minutes ?? null,
      gate: row.gate_display || row.terminal_gate_display || null,
      gate_display: row.gate_display || row.terminal_gate_display || null,
      terminal: row.terminal || null,
      aircraft_type: row.aircraft_type || null,
      direction: row.direction,
      status: row.status || "Tracked",
      source: row.source || "mobile_history",
      enriched_by: row.enriched_by || null,
      detail_mode: "real",
      operating_callsign: row.operating_callsign || null,
      identity_source: row.identity_source || null
    },
    history: [{
      date: clean(row.event_time || row.actual_time || row.sched_time || row.snapshot_ts),
      status: row.status,
      delay_minutes: row.delay_minutes,
      gate: row.gate,
      source: row.source,
      observations: row.observation_count || row.raw_observation_rows || 1
    }]
  };
}

export function historyRouteLabel(row: HistoryFlightRow): string {
  const direction = clean(row.direction).toLowerCase();
  if (direction === "arr") {
    return `FROM ${row.origin_iata || "---"}`;
  }
  if (direction === "dep") {
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
  return flightStablePinId(row);
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
