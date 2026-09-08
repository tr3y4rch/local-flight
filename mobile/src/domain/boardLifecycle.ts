import type { FidsRow, MobileBoardResponse } from "../api/types";

export const STANDALONE_COMPLETED_GRACE_MS = 15 * 60 * 1000;
export const STANDALONE_BOARD_PROJECTION_MS = 5 * 60 * 1000;

function parsedTime(value: unknown): number | null {
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function isCancelled(row: FidsRow): boolean {
  return `${row.status_kind || ""} ${row.status_class || ""} ${row.status_display || ""}`
    .toLowerCase()
    .includes("cancel");
}

export function boardRowMovementTime(row: FidsRow): number | null {
  if (isCancelled(row)) return parsedTime(row.sched_time);
  return parsedTime(row.actual_time) ?? parsedTime(row.est_time) ?? parsedTime(row.sched_time);
}

export function currentStandaloneRows(
  rows: FidsRow[],
  now = Date.now(),
  graceMs = STANDALONE_COMPLETED_GRACE_MS
): FidsRow[] {
  const cutoff = now - graceMs;
  return rows.map((original) => {
    const row = { ...original };
    for (const [field, evidence] of Object.entries(row.field_sources || {})) {
      const expiry = parsedTime(evidence.expires_at);
      if (expiry == null || expiry > now) continue;
      if (field === "gate") {
        row.gate = "";
        row.gate_display = "";
        row.terminal_gate_display = row.terminal_display || "";
      }
      if (field === "terminal") {
        row.terminal_display = "";
        row.terminal_gate_display = row.gate_display || "";
      }
      if (field === "aircraft_type" || field === "aircraft_type_full") row.aircraft_type = "";
      if (field === "airline_name") row.airline_display = "";
      if (field === "aircraft_registration") row.aircraft_registration = null;
    }
    return row;
  }).filter((row) => {
    const movementTime = boardRowMovementTime(row);
    return movementTime == null || movementTime >= cutoff;
  });
}

export function projectStandaloneBoardLocally(
  board: MobileBoardResponse,
  now = Date.now()
): MobileBoardResponse {
  const expired = parsedTime(board.expires_at);
  if (expired != null && expired <= now) return { ...board, cache_state: "expired", departures: [], arrivals: [] };
  const fetched = parsedTime(board.source_fetched_at || board.generated_at);
  const coverageEnd = parsedTime(board.coverage_to);
  if (board.source !== "virtual" && ((fetched != null && now - fetched > 86_400_000)
      || (coverageEnd != null && coverageEnd <= now))) {
    return { ...board, cache_state: "expired", departures: [], arrivals: [] };
  }
  return {
    ...board,
    cache_state: board.source !== "virtual" && fetched == null ? "unknown"
      : board.source !== "virtual" && fetched != null && now - fetched >= 900_000 ? "stale" : board.cache_state,
    departures: currentStandaloneRows(board.departures || [], now),
    arrivals: currentStandaloneRows(board.arrivals || [], now)
  };
}
