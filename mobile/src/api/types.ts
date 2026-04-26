export type FlightView = "departures" | "arrivals";

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
  uptime?: string | null;
  memory_mb?: number | null;
  cpu_pct?: number | null;
  snapshot_dir?: string | null;
};

export type Budget = {
  aviationstack?: {
    enabled?: boolean;
    used?: number;
    limit?: number;
    remaining?: number;
    month?: string;
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

export type DashboardSnapshot = {
  config: AppConfig | null;
  state: AppState | null;
  system: AdminSystem | null;
  budget: Budget | null;
  metar: Metar | null;
};
