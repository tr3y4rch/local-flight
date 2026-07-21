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
  return rows.filter((row) => {
    const movementTime = boardRowMovementTime(row);
    return movementTime == null || movementTime >= cutoff;
  });
}

export function projectStandaloneBoardLocally(
  board: MobileBoardResponse,
  now = Date.now()
): MobileBoardResponse {
  return {
    ...board,
    departures: currentStandaloneRows(board.departures || [], now),
    arrivals: currentStandaloneRows(board.arrivals || [], now)
  };
}
