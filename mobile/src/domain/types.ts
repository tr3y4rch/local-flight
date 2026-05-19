import type {
  FidsRow,
  FlightView,
  HistoryDirection,
  MatrixRuntimeConfigSave,
  RadarBlip
} from "../api/types";

export type Screen = "fids" | "radar" | "history" | "control" | "help" | "settings";
export type StatusTone = "scheduled" | "departed" | "boarding" | "delayed" | "cancelled";
export type HistoryWindow = 24 | 72 | 168 | 720 | 2160;
export type RadarRadius = 1 | 2 | 3 | 5 | 10 | 20 | 40;
export type FeedbackTone = "ok" | "error";

export type RefreshOptions = {
  nextUrl?: string;
  target?: Screen;
  nextView?: FlightView;
  nextHistoryDirection?: HistoryDirection;
  nextHistoryHours?: HistoryWindow;
  nextRadarRadius?: RadarRadius;
  forceRadarGround?: boolean;
  includeDashboard?: boolean;
};

export type ProjectedBlip = {
  blip: RadarBlip;
  left: number;
  top: number;
  distanceNm: number;
  angleDeg: number;
};

export type MatrixDraftState = {
  saved: MatrixRuntimeConfigSave | null;
  draft: MatrixRuntimeConfigSave;
  dirty: boolean;
};

export function flightRowsWithPin(rows: FidsRow[], pinnedCallsign: string): FidsRow[] {
  if (!pinnedCallsign) return rows;
  const pinned = rows.find((row) => (row.callsign || row.id) === pinnedCallsign);
  if (!pinned) return rows;
  return [pinned, ...rows.filter((row) => (row.callsign || row.id) !== pinnedCallsign)];
}
