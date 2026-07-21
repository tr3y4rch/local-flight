import type { FidsRow } from "../api/types";

function clean(value: unknown): string {
  const text = String(value ?? "").trim();
  return text && text !== "-" ? text : "";
}

function compact(value: unknown): string {
  return clean(value).toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function publicFlightNumber(value: unknown): string {
  const text = compact(value);
  return /^[A-Z0-9]{2,3}0*\d{1,5}[A-Z]?$/.test(text) ? text : "";
}

function rowAliases(row: FidsRow): Set<string> {
  return new Set([
    row.flight_number,
    row.callsign,
    row.operating_callsign,
    row.marketing_flight_number,
    ...(row.codeshares || []),
    ...(row.sold_as || [])
  ].map(compact).filter(Boolean));
}

function sameMovementFrame(left: FidsRow, right: FidsRow): boolean {
  return left.view === right.view
    && compact(left.time_primary || left.display_time) === compact(right.time_primary || right.display_time)
    && compact(left.route_code || left.route_display) === compact(right.route_code || right.route_display);
}

function rowsAreLinked(left: FidsRow, right: FidsRow): boolean {
  if (!sameMovementFrame(left, right)) return false;
  const aliases = rowAliases(left);
  if ([...rowAliases(right)].some((alias) => aliases.has(alias))) return true;
  if (compact(left.aircraft_registration) && compact(left.aircraft_registration) === compact(right.aircraft_registration)) return true;
  if (compact(left.icao24) && compact(left.icao24) === compact(right.icao24)) return true;
  const providerKey = clean(left.provider_movement_key);
  if (!providerKey || providerKey !== clean(right.provider_movement_key)) return false;
  const statuses = new Set([
    compact(left.provider_codeshare_status),
    compact(right.provider_codeshare_status)
  ]);
  if (statuses.has("ISOPERATOR") && statuses.has("ISCODESHARED")) return true;
  const leftFlight = publicFlightNumber(left.flight_number);
  const rightFlight = publicFlightNumber(right.flight_number);
  const sameAirline = Boolean(
    [compact(left.airline_iata), compact(left.airline_icao)]
      .filter(Boolean)
      .some((code) => code === compact(right.airline_iata) || code === compact(right.airline_icao))
  );
  return sameAirline && Boolean(leftFlight) !== Boolean(rightFlight);
}

function rowScore(row: FidsRow): number {
  const status = compact(row.provider_codeshare_status);
  return (status === "ISOPERATOR" ? 100 : status === "ISCODESHARED" ? -20 : 0)
    + (publicFlightNumber(row.flight_number) ? 20 : 0)
    + [
      row.sched_time,
      row.est_time,
      row.actual_time,
      row.gate_display,
      row.terminal_display,
      row.aircraft_type,
      row.aircraft_registration
    ].filter((value) => clean(value)).length;
}

function mergeLinkedRows(rows: FidsRow[]): FidsRow {
  const ranked = [...rows].sort((left, right) => rowScore(right) - rowScore(left));
  const primary = ranked[0] ?? rows[0];
  if (!primary) throw new Error("Cannot merge an empty Board movement cluster");
  const primaryFlight = publicFlightNumber(primary.flight_number);
  const soldAs = new Set((primary.sold_as || []).map(clean).filter(Boolean));
  const codeshares = new Set((primary.codeshares || []).map(clean).filter(Boolean));
  for (const row of rows) {
    for (const value of [row.flight_number, ...(row.sold_as || []), ...(row.codeshares || [])]) {
      const identity = publicFlightNumber(value);
      if (identity && identity !== primaryFlight) {
        soldAs.add(clean(value));
        codeshares.add(clean(value));
      }
    }
  }
  const first = (key: keyof FidsRow) => ranked.find((row) => clean(row[key]))?.[key];
  return {
    ...primary,
    sold_as: [...soldAs],
    codeshares: [...codeshares],
    origin_iata: primary.origin_iata || first("origin_iata") as string | undefined,
    origin_icao: primary.origin_icao || first("origin_icao") as string | undefined,
    origin_name: primary.origin_name || first("origin_name") as string | undefined,
    dest_iata: primary.dest_iata || first("dest_iata") as string | undefined,
    dest_icao: primary.dest_icao || first("dest_icao") as string | undefined,
    dest_name: primary.dest_name || first("dest_name") as string | undefined,
    sched_time: primary.sched_time || first("sched_time") as string | undefined,
    est_time: primary.est_time || first("est_time") as string | undefined,
    actual_time: primary.actual_time || first("actual_time") as string | undefined,
    gate_display: primary.gate_display || first("gate_display") as string | undefined,
    terminal_display: primary.terminal_display || first("terminal_display") as string | undefined,
    terminal_gate_display: primary.terminal_gate_display || first("terminal_gate_display") as string | undefined,
    aircraft_type: primary.aircraft_type || first("aircraft_type") as string,
    aircraft_registration: primary.aircraft_registration || first("aircraft_registration") as string | undefined,
    icao24: primary.icao24 || first("icao24") as string | undefined,
    delay_minutes: primary.delay_minutes ?? first("delay_minutes") as number | null | undefined,
    updated_at: primary.updated_at || first("updated_at") as string | undefined
  };
}

export function dedupeBoardRows(rows: FidsRow[]): FidsRow[] {
  const clusters: FidsRow[][] = [];
  for (const row of rows) {
    const cluster = clusters.find((candidateRows) =>
      candidateRows.some((candidate) => rowsAreLinked(candidate, row))
    );
    if (!cluster) {
      clusters.push([row]);
      continue;
    }
    cluster.push(row);
  }
  return clusters.map(mergeLinkedRows);
}
