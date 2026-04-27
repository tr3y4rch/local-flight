export type FlightView = "departures" | "arrivals";
export type HistoryDirection = "both" | "dep" | "arr";

export type AppConfig = {
  airport_iata: string;
  airport_icao: string;
  refresh_seconds: number;
  display_name: string;
  theme: string;
  source: "real" | "virtual" | string;
  timezone: string;
  skin: string;
  display_outputs: string[];
};

export type AppState = {
  ok: boolean;
  last_attempt_utc?: string | null;
  last_success_utc?: string | null;
  last_error?: string | null;
  source_name?: string | null;
  last_latency_ms?: number | null;
};

export type AdminSystem = {
  version: string;
  python: string;
  platform: string;
  install_id?: string | null;
  uptime?: string | null;
  memory_mb?: number | null;
  cpu_pct?: number | null;
  snapshot_dir?: string | null;
};

export type AdminConnections = {
  count: number;
  matrix_last_seen?: string | null;
};

export type AdminUpdates = {
  current: string;
  latest?: string | null;
  update_available: boolean;
  url?: string | null;
  error?: string | null;
};

export type SchedulerRestartResponse = {
  ok: boolean;
  status: string;
  message?: string;
  running?: boolean;
  started?: boolean;
  was_running?: boolean;
  generation?: number;
  started_at?: string | null;
  thread_name?: string | null;
};

export type Budget = {
  aviationstack?: {
    mode?: "relay" | "byok" | string;
    relay_url?: string;
    enabled?: boolean;
    calls_this_month?: number;
    monthly_limit?: number;
    remaining?: number;
    month?: string;
    budget_ok?: boolean;
    error?: string;
  };
  adsbexchange?: {
    available?: boolean;
    calls_this_month?: number;
    monthly_limit?: number;
    remaining?: number;
    month?: string;
    budget_ok?: boolean;
    error?: string;
  };
  adsbexchange_available?: boolean;
  opensky_available?: boolean;
};

export type Metar = {
  raw_text?: string;
  decoded_summary?: string;
  flight_category?: string;
  category?: string;
  temperature_c?: number;
  wind?: string;
  qnh_hpa?: number;
};

export type FlightPosition = {
  lat?: number | null;
  lon?: number | null;
  altitude_m?: number | null;
  speed_ms?: number | null;
  heading?: number | null;
  on_ground?: boolean | null;
  vertical_rate?: number | null;
};

export type FidsRow = {
  id: string;
  view: FlightView | string;
  display_time: string;
  flight_display: string;
  route_display: string;
  status_display: string;
  status_class: string;
  gate: string;
  aircraft_type: string;
  callsign: string;
};

export type FlightDetail = {
  callsign?: string;
  flight_number?: string | null;
  airline?: string | null;
  airline_iata?: string | null;
  origin_iata?: string | null;
  origin_name?: string | null;
  dest_iata?: string | null;
  dest_name?: string | null;
  sched_time?: string | null;
  est_time?: string | null;
  actual_time?: string | null;
  delay_minutes?: number | null;
  gate?: string | null;
  terminal?: string | null;
  aircraft_type?: string | null;
  direction?: string | null;
  status?: string | null;
  source?: string | null;
  enriched_by?: string | null;
  position?: FlightPosition | null;
};

export type FlightDetailHistoryRow = {
  date: string;
  status?: string | null;
  delay_minutes?: number | null;
  gate?: string | null;
};

export type FidsDetailResponse = {
  detail: FlightDetail | Record<string, never>;
  history: FlightDetailHistoryRow[];
};

export type HistoryFlightRow = {
  id: number;
  airport_iata: string;
  callsign: string;
  flight_number?: string | null;
  origin_iata?: string | null;
  dest_iata?: string | null;
  direction: string;
  status: string;
  gate?: string | null;
  terminal?: string | null;
  aircraft_type?: string | null;
  sched_time?: string | null;
  actual_time?: string | null;
  lat?: number | null;
  lon?: number | null;
  altitude_m?: number | null;
  source?: string | null;
  enriched_by?: string | null;
  snapshot_ts: string;
  delay_minutes?: number | null;
  airline_iata?: string | null;
};

export type HistoryResponse = {
  airport_iata: string;
  hours: number;
  count: number;
  flights: HistoryFlightRow[];
};

export type FlightHistoryResponse = {
  callsign: string;
  days: number;
  count: number;
  flights: HistoryFlightRow[];
};

export type RadarCenter = {
  lat: number;
  lon: number;
};

export type RadarBlip = {
  callsign: string;
  lat: number;
  lon: number;
  altitude_m?: number | null;
  heading?: number | null;
  speed_ms?: number | null;
  on_ground?: boolean | null;
  icao24?: string | null;
  squawk?: string | null;
  flight_number?: string | null;
  status?: string | null;
  enriched?: boolean;
};

export type RadarResponse = {
  center: RadarCenter;
  radius_nm: number;
  source: string;
  count: number;
  blips: RadarBlip[];
};

export type AirportResult = {
  iata: string;
  icao: string;
  name: string;
  city: string;
  country: string;
  type: string;
  timezone?: string;
};

export type AirportDetail = {
  iata: string;
  icao: string;
  name: string;
  city: string;
  country: string;
  region: string;
  type: string;
  lat?: number | null;
  lon?: number | null;
  timezone: string;
};

export type HistoryStats = {
  total_rows: number;
  oldest?: string | null;
  newest?: string | null;
  airports: string[];
  size_mb: number;
  db_path: string;
  error?: string;
};

export type ConfigPatch = {
  airport_iata?: string;
  airport_icao?: string;
  source?: "real" | "virtual";
  refresh_seconds?: number;
  timezone?: string;
  display_name?: string;
};

export type RequestLogEntry = {
  id: number;
  ts: string;
  method: string;
  path: string;
  status_code: number;
  latency_ms: number;
  ip: string;
  user_agent: string;
  client_type: "desktop" | "mobile" | "matrix" | "api" | "unknown";
};

export type RequestLogSummary = {
  hours: number;
  total: number;
  by_client: Record<string, number>;
  top_paths: Array<{ path: string; count: number }>;
  hourly: number[];
  error?: string;
};

export type RequestLogResponse = {
  requests: RequestLogEntry[];
  summary: RequestLogSummary;
};

export type DashboardSnapshot = {
  config: AppConfig | null;
  state: AppState | null;
  system: AdminSystem | null;
  connections: AdminConnections | null;
  updates: AdminUpdates | null;
  budget: Budget | null;
  metar: Metar | null;
};
