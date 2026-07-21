import type { FidsRow, FlightView } from "../api/types";
import { dedupeBoardRows } from "../domain/boardDedupe";
import { flightPinKey, routeMeta, routeName, statusTone } from "../domain/flights";
import type { StatusTone } from "../domain/types";

export { dedupeBoardRows } from "../domain/boardDedupe";

export type BoardSourceKind = "airline" | "vatsim";

export type BoardRowViewModel = {
  id: string;
  callsign: string;
  view: FlightView;
  time: string;
  timeDetail: string;
  flight: string;
  airline: string;
  routeName: string;
  routeCode: string;
  status: string;
  statusTone: StatusTone;
  aircraft: string;
  gate: string;
  terminal: string;
  sourceKind: BoardSourceKind;
  aviationDetail: string;
  pinned: boolean;
  raw: FidsRow;
};

function clean(value: unknown): string {
  const text = String(value ?? "").trim();
  return text && text !== "-" ? text : "";
}

function rowView(row: FidsRow): FlightView {
  return row.view === "arrivals" ? "arrivals" : "departures";
}

function isVatsimRow(row: FidsRow): boolean {
  if (row.detail_mode) return row.detail_mode === "virtual";
  const sourceHint = `${clean(row.source_hint)} ${clean(row.live_hint)}`.toLowerCase();
  return sourceHint.includes("vatsim") || sourceHint.includes("virtual");
}

function boardRowIdentity(row: FidsRow): string {
  return [
    rowView(row),
    clean(row.provider_movement_key) || clean(row.id) || clean(row.callsign),
    clean(row.time_primary) || clean(row.display_time),
    clean(row.route_code) || clean(row.route_display),
    clean(row.flight_display) || clean(row.callsign)
  ].join(":");
}

export function boardRowViewModel(
  row: FidsRow,
  pinnedCallsign = "",
  instanceId = boardRowIdentity(row)
): BoardRowViewModel {
  const virtual = isVatsimRow(row);
  const gate = virtual ? "" : clean(row.terminal_gate_display) || clean(row.gate_display) || clean(row.gate);
  const terminal = virtual ? "" : clean(row.terminal_display);
  const routePrimary = clean(row.route_primary) || routeName(row.route_display) || "Route unavailable";
  const routeSecondary = clean(row.route_code) || clean(row.route_caption) || routeMeta(row) || "";
  const aviationParts = virtual
    ? [
        clean(row.flight_rules),
        clean(row.planned_altitude),
        clean(row.squawk || row.transponder),
        clean(row.aircraft_type)
      ]
    : [terminal && `Terminal ${terminal}`, clean(row.aircraft_type), clean(row.codeshare_display)];

  return {
    id: instanceId,
    callsign: clean(row.callsign) || clean(row.flight_number) || clean(row.flight_display) || clean(row.id),
    view: rowView(row),
    time: clean(row.time_primary) || clean(row.display_time) || "--:--",
    timeDetail: clean(row.time_delta_text) || clean(row.time_delta_label),
    flight: clean(row.flight_display) || clean(row.callsign) || "Flight unavailable",
    airline: clean(row.airline_display) || clean(row.callsign),
    routeName: routePrimary,
    routeCode: routeSecondary,
    status: clean(row.status_display) || "Scheduled",
    statusTone: statusTone(row.status_display || row.status_class),
    aircraft: clean(row.aircraft_type),
    gate,
    terminal,
    sourceKind: virtual ? "vatsim" : "airline",
    aviationDetail: aviationParts.filter(Boolean).join(" · "),
    pinned: Boolean(pinnedCallsign && flightPinKey(row) === pinnedCallsign),
    raw: row
  };
}

export function boardRowsViewModel(rows: FidsRow[], pinnedCallsign = ""): BoardRowViewModel[] {
  const occurrenceByIdentity = new Map<string, number>();
  const mapped = dedupeBoardRows(rows).map((row) => {
    const identity = boardRowIdentity(row);
    const occurrence = occurrenceByIdentity.get(identity) || 0;
    occurrenceByIdentity.set(identity, occurrence + 1);
    return boardRowViewModel(row, pinnedCallsign, `${identity}:${occurrence}`);
  });
  if (!pinnedCallsign) return mapped;
  return [...mapped].sort((a, b) => Number(b.pinned) - Number(a.pinned));
}
