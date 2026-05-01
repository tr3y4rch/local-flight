import type {
  FidsRow,
  FlightView,
  HistoryDirection,
  MatrixRuntimeConfigSave,
  RadarBlip
} from "../api/types";

export type Screen = "fids" | "radar" | "history" | "matrix" | "admin" | "settings";
export type StatusTone = "scheduled" | "departed" | "boarding" | "delayed" | "cancelled";
export type HistoryWindow = 24 | 72 | 168;
export type RadarRadius = 10 | 20 | 40 | 80;
export type FeedbackTone = "ok" | "error";

export type MatrixPreset = {
  label: string;
  panelW: number;
  panelH: number;
  modules: string;
};

export type RefreshOptions = {
  nextUrl?: string;
  target?: Screen;
  nextView?: FlightView;
  nextHistoryDirection?: HistoryDirection;
  nextHistoryHours?: HistoryWindow;
  nextRadarRadius?: RadarRadius;
};

export type ProjectedBlip = {
  blip: RadarBlip;
  left: number;
  top: number;
  distanceNm: number;
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
