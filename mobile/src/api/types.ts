export type FlightView = "departures" | "arrivals";
export type HistoryDirection = "both" | "dep" | "arr";

export type DocDocument = {
  slug: "readme" | "install" | "display-modes" | "privacy" | "changelog" | string;
  title: string;
  summary: string;
  filename: string;
  github_url: string;
  content: string;
  bundled?: boolean;
};

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
  diagnostics_mode?: "unset" | "manual" | "auto" | "auto_logs" | string;
  web_row_limit?: number;
  web_rotation_seconds?: number;
  display_grace_minutes?: number;
  display_horizon_hours?: number;
  radar_surface_enabled?: boolean;
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
  client?: {
    mode?: string;
    relay_url?: string | null;
    activation_token_present?: boolean;
    activation_token_prefix?: string;
    community_key_present?: boolean;
    managed_verified?: boolean;
    managed_status?: string;
    diagnostics_mode?: string;
    cost_estimate?: {
      enabled?: boolean;
      usage_model?: string;
      dates_touched?: number;
      page_size?: number;
      recent_avg_pages_per_direction?: number;
      estimated_calls_per_refresh?: number;
      estimated_calls_per_month?: number;
      refreshes_per_30_days?: number;
      cadence_warning?: string;
    };
    shared_snapshot?: {
      generated_at?: string;
      cache_state?: string;
      provider?: string;
      meta?: Record<string, unknown>;
      shared_stats?: {
        client_accesses?: number;
        upstream_pulls?: number;
        refresh_count?: number;
        cache_hits?: number;
        stale_serves?: number;
        cache_hit_rate_pct?: number;
        estimated_savings?: number;
      };
    };
  };
};

export type CompanionPresence = {
  companion_id: string;
  client_name: string;
  app_version: string;
  mobile_os: string;
  device_type: "phone" | "tablet" | "desktop" | "unknown" | string;
  platform_pair: string;
  last_seen: string;
};

export type AdminConnections = {
  count: number;
  matrix_last_seen?: string | null;
  companion_last_seen?: string | null;
  companion_count?: number;
  companions?: CompanionPresence[];
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

export type SchedulerStatus = {
  running: boolean;
  generation?: number;
  started_at?: string | null;
  thread_name?: string | null;
};

export type Budget = {
  client_polling_policy?: {
    mode?: string;
    jitter_ratio?: number;
    fids_fallback_seconds?: number;
    admin_fallback_seconds?: number;
    hidden_fallback_seconds?: number;
    radar_visible_min_seconds?: number;
    radar_hidden_min_seconds?: number;
    mobile_min_fallback_seconds?: number;
  };
  schedule_policy?: {
    shared_relay?: boolean;
    active_mode?: string;
    community_shared?: boolean;
    min_refresh_seconds?: number;
    allowed_refresh_seconds?: number[];
    reason?: string;
    cooldown_remaining_seconds?: number;
  };
  aviationstack?: {
    mode?: "community" | "managed" | "relay" | "byok" | "virtual" | string;
    active_mode?: "community" | "managed" | "relay" | "byok" | "virtual" | string;
    relay_url?: string;
    enabled?: boolean;
    shared_relay?: boolean;
    schedule_policy?: Budget["schedule_policy"];
    shared_snapshot?: {
      generated_at?: string;
      cache_state?: string;
      provider?: string;
      meta?: Record<string, unknown>;
      shared_stats?: {
        client_accesses?: number;
        upstream_pulls?: number;
        refresh_count?: number;
        cache_hits?: number;
        stale_serves?: number;
        cache_hit_rate_pct?: number;
        estimated_savings?: number;
      };
    };
    calls_this_month?: number;
    monthly_limit?: number;
    remaining?: number;
    month?: string;
    budget_ok?: boolean;
    error?: string;
    cost_estimate?: {
      enabled?: boolean;
      usage_model?: string;
      dates_touched?: number;
      page_size?: number;
      recent_avg_pages_per_direction?: number;
      estimated_calls_per_refresh?: number;
      estimated_calls_per_month?: number;
      refreshes_per_30_days?: number;
      cadence_warning?: string;
    };
    community?: {
      configured?: boolean;
      transport?: "relay" | "local_key" | string;
      relay_url?: string;
      key_present?: boolean;
      calls_this_month?: number;
      monthly_limit?: number;
      remaining?: number;
      month?: string;
      budget_ok?: boolean;
      shared_snapshot?: NonNullable<Budget["aviationstack"]>["shared_snapshot"];
    };
    managed?: {
      configured?: boolean;
      relay_url?: string;
      token_present?: boolean;
      token_prefix?: string;
      providers?: {
        aviationstack?: boolean;
        adsbexchange?: boolean;
      };
      status_ok?: boolean;
      status_error?: string;
      calls_this_month?: number;
      monthly_limit?: number;
      remaining?: number;
      month?: string;
      budget_ok?: boolean;
      shared_snapshot?: NonNullable<Budget["aviationstack"]>["shared_snapshot"];
    };
    byok?: {
      configured?: boolean;
      enabled?: boolean;
      calls_this_month?: number;
      monthly_limit?: number;
      ui_monthly_max?: number;
      remaining?: number;
      plan_remaining?: number;
      safety_reserve?: number;
      month?: string;
      budget_ok?: boolean;
    };
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
  flight_cat?: string;
  flight_cat_color?: string;
  flight_category?: string;
  category?: string;
  temperature_c?: number;
  temp_c?: number;
  dewpoint_c?: number;
  wind?: string;
  wind_display?: string;
  wind_dir_deg?: number | null;
  wind_speed_kt?: number | null;
  wind_gust_kt?: number | null;
  visibility_m?: number | null;
  visibility_sm?: number | null;
  ceiling_ft?: number | null;
  altimeter_hpa?: number | null;
  qnh_hpa?: number;
  wx_string?: string;
  clouds?: Array<Record<string, unknown>>;
  source?: string;
  weather?: {
    condition?: string;
    icon?: string;
    label?: string;
    tone?: string;
    summary?: string;
    hazards?: string[];
    chips?: Array<{ label: string; value: string }>;
    source?: string;
  };
  weather_condition?: string;
  weather_icon?: string;
  weather_label?: string;
  weather_tone?: string;
  weather_summary?: string;
  weather_hazards?: string[];
  weather_chips?: Array<{ label: string; value: string }>;
};

export type FlightPosition = {
  lat?: number | null;
  lon?: number | null;
  altitude_m?: number | null;
  altitude_baro_m?: number | null;
  altitude_geo_m?: number | null;
  speed_ms?: number | null;
  heading?: number | null;
  on_ground?: boolean | null;
  vertical_rate?: number | null;
  icao24?: string | null;
  squawk?: string | null;
  last_contact?: string | null;
};

export type FlightDetailSources = {
  schedule?: string | null;
  enrichment?: string | null;
  confidence?: "live_position_matched" | "position_from_snapshot" | "schedule_only" | "missing" | string | null;
  snapshot_generated_at?: string | null;
  snapshot_age_seconds?: number | null;
  position_last_contact?: string | null;
  position_age_seconds?: number | null;
};

export type FlightPlanDetail = {
  flight_rules?: string | null;
  route?: string | null;
  cruise_altitude?: string | null;
  planned_departure?: string | null;
  planned_arrival?: string | null;
  enroute_minutes?: number | null;
  cruise_tas?: number | null;
  alternate_icao?: string | null;
  assigned_transponder?: string | null;
};

export type FlightIntelAirportRef = {
  iata?: string | null;
  icao?: string | null;
  name?: string | null;
  code?: string | null;
};

export type FlightIntel = {
  schema_version: "flight-intel-v1" | string;
  detail_mode?: "real" | "virtual" | "missing" | string;
  identity?: {
    callsign?: string | null;
    flight_number?: string | null;
    flight_display?: string | null;
    airline_name?: string | null;
    airline_iata?: string | null;
    airline_icao?: string | null;
    codeshares?: string[];
    sold_as?: string[];
    marketing_airline_name?: string | null;
    marketing_airline_iata?: string | null;
    marketing_airline_icao?: string | null;
    marketing_flight_number?: string | null;
    operating_callsign?: string | null;
    identity_source?: string | null;
  };
  route?: {
    origin?: FlightIntelAirportRef;
    destination?: FlightIntelAirportRef;
    airport?: FlightIntelAirportRef;
    direction?: string | null;
    route_display?: string | null;
  };
  timing?: {
    scheduled?: string | null;
    estimated?: string | null;
    actual?: string | null;
    delay_minutes?: number | null;
    delay_bucket?: string;
    status?: string | null;
  };
  operations?: {
    terminal?: string | null;
    gate?: string | null;
    stand?: string | null;
    direction?: string | null;
  };
  aircraft?: {
    type?: string | null;
    model?: string | null;
    full_type?: string | null;
    registration?: string | null;
    icao24?: string | null;
    squawk?: string | null;
    selected_altitude_ft?: number | null;
    nav_modes?: string[] | null;
    category?: string | null;
  };
  motion?: {
    has_position?: boolean;
    lat?: number | null;
    lon?: number | null;
    altitude_m?: number | null;
    altitude_ft?: number | null;
    geo_altitude_m?: number | null;
    geo_altitude_ft?: number | null;
    speed_ms?: number | null;
    speed_kt?: number | null;
    vertical_rate_ms?: number | null;
    vertical_rate_fpm?: number | null;
    heading?: number | null;
    heading_deg?: number | null;
    on_ground?: boolean | null;
    last_contact?: string | null;
    position_age_seconds?: number | null;
    distance_nm?: number | null;
    radar_status?: string | null;
    radar_phase?: string | null;
    phase_reason?: string | null;
    source_quality?: string | null;
  };
  flight_plan?: FlightPlanDetail;
  weather?: {
    available?: boolean;
    summary?: string | null;
    flight_category?: string | null;
    temperature_c?: number | null;
    wind?: string | null;
    qnh?: number | null;
    icon?: string | null;
    source?: string | null;
  };
  history_summary?: {
    records?: number;
    last_seen?: string | null;
    avg_delay_minutes?: number | null;
    early_count?: number;
    on_time_count?: number;
    late_count?: number;
    delay_buckets?: Record<string, number>;
    recent?: FlightDetailHistoryRow[];
  };
  source_evidence?: {
    schedule_source?: string | null;
    position_source?: string | null;
    confidence?: "live_position_matched" | "position_from_snapshot" | "schedule_only" | "missing" | string | null;
    snapshot_generated_at?: string | null;
    snapshot_age_seconds?: number | null;
    fields_available?: string[];
  };
  privacy?: {
    vatsim_personal_identifiers?: boolean;
    notes?: string;
  };
};

export type FidsRow = {
  id: string;
  view: FlightView | string;
  display_time: string;
  time_primary?: string;
  time_delta_label?: string;
  time_delta_text?: string;
  delay_kind?: string;
  delay_minutes?: number | null;
  delay_class?: string;
  status_kind?: string;
  tone?: string;
  flight_display: string;
  airline_display?: string;
  codeshare_display?: string;
  flight_number?: string;
  airline_iata?: string;
  airline_icao?: string;
  codeshares?: string[];
  sold_as?: string[];
  marketing_airline_name?: string;
  marketing_airline_iata?: string;
  marketing_airline_icao?: string;
  marketing_flight_number?: string;
  operating_callsign?: string;
  identity_source?: string;
  route_display: string;
  route_primary?: string;
  route_code?: string;
  route_caption?: string;
  status_display: string;
  status_class: string;
  gate: string;
  terminal_gate_display?: string;
  gate_display?: string;
  terminal_display?: string;
  source_hint?: string;
  live_hint?: string;
  aircraft_type: string;
  callsign: string;
};

export type FlightDetail = {
  callsign?: string;
  flight_number?: string | null;
  flight_display?: string | null;
  airline?: string | null;
  airline_iata?: string | null;
  airline_icao?: string | null;
  codeshares?: string[];
  origin_iata?: string | null;
  origin_icao?: string | null;
  origin_name?: string | null;
  dest_iata?: string | null;
  dest_icao?: string | null;
  dest_name?: string | null;
  sched_time?: string | null;
  est_time?: string | null;
  actual_time?: string | null;
  delay_minutes?: number | null;
  delay_kind?: "none" | "early" | "warn" | "bad" | string | null;
  delay_class?: string | null;
  gate?: string | null;
  gate_display?: string | null;
  terminal?: string | null;
  terminal_display?: string | null;
  terminal_gate_display?: string | null;
  aircraft_type?: string | null;
  aircraft_type_full?: string | null;
  aircraft_registration?: string | null;
  stand?: string | null;
  direction?: string | null;
  status?: string | null;
  source?: string | null;
  enriched_by?: string | null;
  updated_at?: string | null;
  detail_mode?: "real" | "virtual" | string | null;
  data_sources?: FlightDetailSources | null;
  flight_plan?: FlightPlanDetail | null;
  position?: FlightPosition | null;
  sold_as?: string[];
  marketing_airline_name?: string | null;
  marketing_airline_iata?: string | null;
  marketing_airline_icao?: string | null;
  marketing_flight_number?: string | null;
  operating_callsign?: string | null;
  identity_source?: string | null;
  intel?: FlightIntel | null;
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
  intel?: FlightIntel;
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
  altitude_ft?: number | null;
  geo_altitude_m?: number | null;
  geo_altitude_ft?: number | null;
  heading?: number | null;
  heading_deg?: number | null;
  track_deg?: number | null;
  speed_ms?: number | null;
  speed_kt?: number | null;
  vertical_rate?: number | null;
  vertical_rate_fpm?: number | null;
  on_ground?: boolean | null;
  icao24?: string | null;
  squawk?: string | null;
  flight_number?: string | null;
  airline_name?: string | null;
  airline_iata?: string | null;
  airline_icao?: string | null;
  codeshares?: string[];
  sold_as?: string[];
  marketing_flight_number?: string | null;
  operating_callsign?: string | null;
  identity_source?: string | null;
  aircraft_type?: string | null;
  registration?: string | null;
  aircraft_category?: string | null;
  source?: string | null;
  source_quality?: string | null;
  detail_mode?: string | null;
  distance_nm?: number | null;
  route_display?: string | null;
  display_title?: string | null;
  altitude_display?: string | null;
  speed_display?: string | null;
  vertical_rate_display?: string | null;
  motion_display?: string | null;
  radar_phase?: string | null;
  radar_status?: string | null;
  radar_status_label?: string | null;
  phase_reason?: string | null;
  selected_altitude_ft?: number | null;
  nav_modes?: string[] | null;
  status?: string | null;
  enriched?: boolean;
};

export type RadarResponse = {
  center: RadarCenter;
  radius_nm: number;
  source: string;
  refresh_after_s?: number;
  count: number;
  radar_mode?: "surface" | "airborne" | string;
  ground_filtered?: number;
  airborne_filtered?: number;
  hidden_ground_count?: number;
  hidden_airborne_count?: number;
  traffic_filter?: string;
  altitude_filter?: {
    min_alt_ft?: number | null;
    max_alt_ft?: number | null;
  };
  user_filtered_count?: number;
  provider_radius_nm?: number;
  raw_provider_count?: number;
  blips: RadarBlip[];
};

export type RadarMapAttribution = {
  text?: string;
  url?: string;
};

export type RadarMapFeature = {
  kind: string;
  id?: string;
  label?: string;
  closed?: boolean;
  points?: number[][];
  confidence?: string;
  geometry_precision?: string;
  data_source?: string;
  validation?: Record<string, unknown>;
};

export type RadarMapResponse = {
  center: RadarCenter & {
    airport_iata?: string;
    airport_icao?: string;
  };
  radius_nm: number;
  schema_version?: string;
  runways?: RadarMapFeature[];
  surface_features?: RadarMapFeature[];
  map_features?: RadarMapFeature[];
  attribution?: RadarMapAttribution[];
  sources?: {
    runways?: string[] | string;
    surface?: string;
    surface_cache_state?: string;
    map?: string;
    map_cache_state?: string;
    terrain?: string;
    terrain_cache_state?: string;
  };
  confidence?: Record<string, unknown>;
};

export type RadarSurfaceResponse = {
  center: RadarMapResponse["center"];
  radius_nm: number;
  schema_version?: string;
  provider?: string;
  cache_state?: string;
  features?: RadarMapFeature[];
  attribution?: RadarMapAttribution;
  meta?: Record<string, unknown>;
  error?: string;
};

export type MatrixRuntimeConfig = {
  preset?: MatrixPresetId | string;
  brightness: number;
  max_rows: number;
  refresh_seconds: number;
  default_view: FlightView | string;
  page_rotation_seconds?: number;
  animation_enabled?: boolean;
  animation_mode?: MatrixAnimationMode | string;
  animation_speed?: number;
  status_animation_enabled?: boolean;
  show_gate_info?: boolean;
  palette?: MatrixPaletteId | string;
  options?: MatrixRuntimeOptions;
  skin?: string;
};

export type MatrixPresetId = "real_fids" | "vatsim_pilot" | "vatsim_atc";

export type MatrixPaletteId =
  | "pax_blue"
  | "solari_amber"
  | "tower_scope"
  | "vatsim_scope"
  | "night_ops"
  | "sunset_terminal"
  | "ice_white";

export type MatrixAnimationMode = "split_flap" | "slide_left" | "slide_right" | "static";

export type MatrixRuntimeOptions = {
  palette?: MatrixPaletteId | string;
  show_metar?: boolean;
  show_weather?: boolean;
  show_gate_info?: boolean;
  animation_mode?: MatrixAnimationMode | string;
};

export type MatrixRuntimeConfigSave = {
  preset: MatrixPresetId;
  brightness: number;
  max_rows: number;
  refresh_seconds: number;
  default_view: FlightView;
  page_rotation_seconds: number;
  animation_enabled: boolean;
  animation_mode: MatrixAnimationMode;
  animation_speed: number;
  status_animation_enabled: boolean;
  show_gate_info: boolean;
  palette: MatrixPaletteId;
  options: MatrixRuntimeOptions;
};

export type MatrixRuntimeConfigSaveResponse = MatrixRuntimeConfigSave & {
  ok: boolean;
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

export type AirportResolved = {
  iata: string;
  icao: string;
  name: string;
  city: string;
  country: string;
  timezone?: string;
  type?: string;
  lat?: number | null;
  lon?: number | null;
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

export type HistorySummaryBucket = {
  bucket: string;
  label: string;
  count: number;
  pct: number;
};

export type HistorySummaryStatus = {
  status: string;
  label: string;
  count: number;
  pct: number;
};

export type HistorySummaryAirline = {
  code: string;
  count: number;
  delay_rate_pct: number;
  on_time_pct: number;
  avg_delay_minutes?: number | null;
};

export type HistorySummaryRoute = {
  origin: string;
  destination: string;
  direction: string;
  count: number;
  delay_rate_pct: number;
};

export type HistorySummaryAircraft = {
  aircraft_type: string;
  count: number;
};

export type HistorySummaryVolume = {
  date: string;
  departures: number;
  arrivals: number;
  total: number;
  delayed: number;
};

export type HistorySummary = {
  airport_iata: string;
  hours: number;
  total: number;
  sample_rows?: number;
  departures: number;
  arrivals: number;
  delayed: number;
  delayed_pct: number;
  on_time_pct: number;
  avg_delay_minutes: number | null;
  delay_buckets: HistorySummaryBucket[];
  status_mix: HistorySummaryStatus[];
  top_airlines: HistorySummaryAirline[];
  top_routes: HistorySummaryRoute[];
  top_aircraft: HistorySummaryAircraft[];
  daily_volume: HistorySummaryVolume[];
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
  client_id?: string;
  platform?: string;
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
  scheduler: SchedulerStatus | null;
  metar: Metar | null;
};
