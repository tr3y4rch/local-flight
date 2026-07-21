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
  nextHistoryCallsign?: string;
  nextHistoryAirline?: string;
  nextRadarRadius?: RadarRadius;
  forceRadarGround?: boolean;
  includeDashboard?: boolean;
  includeBoardSnapshot?: boolean;
  background?: boolean;
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
