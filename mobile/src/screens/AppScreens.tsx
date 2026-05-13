import { useCallback, useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import {
  ActivityIndicator,
  Animated,
  FlatList,
  Image,
  Keyboard,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  useWindowDimensions,
  View
} from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import Svg, { Circle, ClipPath, Defs, G, Polygon, Polyline, Text as SvgText } from "react-native-svg";

import { getConfig, getDoc, getHealth, getRootHealth, normalizeServerUrl, patchConfig, searchAirports } from "../api/client";
import type {
  AppConfig,
  AppState,
  AirportResult,
  Budget,
  ConfigPatch,
  DashboardSnapshot,
  DocDocument,
  FidsRow,
  FlightDetail,
  FlightView,
  HistoryDirection,
  HistoryFlightRow,
  HistoryResponse,
  HistorySummary,
  HistoryStats,
  MatrixAnimationMode,
  MatrixPaletteId,
  MatrixPresetId,
  Metar,
  RadarBlip,
  RadarMapFeature,
  RadarMapResponse,
  RadarResponse
} from "../api/types";
import { platformPairLabel, type CompanionIdentity } from "../device/identity";
import {
  APP_VERSION,
  HISTORY_WINDOWS,
  MATRIX_ANIMATION_MODES,
  MATRIX_ANIMATION_SPEEDS,
  MATRIX_BRIGHTNESS,
  MATRIX_PRESETS,
  MATRIX_PALETTE_OPTIONS,
  MATRIX_REFRESH_SECONDS,
  MATRIX_ROTATION_SECONDS,
  MATRIX_ROWS,
  RADAR_RADII,
  REFRESH_OPTIONS
} from "../domain/constants";
import {
  detailRouteLabel,
  flightPinKey,
  formatAltitudeFeet,
  formatHeading,
  formatSpeedKnots,
  historyRouteLabel,
  routeMeta,
  routeName,
  statusShort,
  statusTone
} from "../domain/flights";
import {
  errorMessage,
  formatClock,
  formatDateTime,
  formatInterval,
  formatRelative,
  hexToRgba,
  parseMetarChips
} from "../domain/formatting";
import { MATRIX_LED_PALETTES, matrixPreviewLines } from "../domain/matrix";
import { projectBlip, projectLatLonToScope, type ProjectedRadarPoint } from "../domain/radar";
import {
  SUPPORT_WEB_FALLBACK_URL,
  supportProductPlaceholders,
  supportStubProvider,
  type SupportProduct
} from "../domain/support";
import type { FeedbackTone, HistoryWindow, ProjectedBlip, RadarRadius, StatusTone } from "../domain/types";
import { type ConfigProfile, type MobileDiagnosticsMode, type MobileWeatherDisplayMode, saveProfiles } from "../storage/settings";
import { palette, styles } from "../theme/styleBridge";
import {
  MOBILE_SKIN_OPTIONS,
  MOBILE_THEME_OPTIONS,
  type MobileSkin,
  type MobileThemeMode
} from "../theme/tokens";

type MaterialIconName = ComponentProps<typeof MaterialCommunityIcons>["name"];
export type DocSlug = "readme" | "install" | "display-modes" | "privacy" | "changelog";
export type ActivityStatus = {
  label: string;
  detail?: string;
  tone?: "sync" | "warn" | "ok";
};
export type ConnectionState = "live" | "retrying" | "offline";

const DOC_SOURCES: Record<DocSlug, { title: string; detail: string; githubUrl: string }> = {
  readme: {
    title: "README",
    detail: "Friendly overview, path chooser, previews, and operating model",
    githubUrl: "https://github.com/tr3y4rch/local-flight#readme"
  },
  install: {
    title: "Install Guide",
    detail: "Platform setup, Pi modes, source checkout, and mobile testing",
    githubUrl: "https://github.com/tr3y4rch/local-flight/blob/main/docs/install.md"
  },
  "display-modes": {
    title: "Display Modes",
    detail: "Native, browser, Pi, mobile, and Matrix display choices",
    githubUrl: "https://github.com/tr3y4rch/local-flight/blob/main/docs/display-modes.md"
  },
  privacy: {
    title: "Privacy",
    detail: "What stays local and what diagnostics can send",
    githubUrl: "https://github.com/tr3y4rch/local-flight/blob/main/PRIVACY.md"
  },
  changelog: {
    title: "Changelog",
    detail: "Release history and beta notes",
    githubUrl: "https://github.com/tr3y4rch/local-flight/blob/main/CHANGELOG.md"
  }
};

function solidButtonInk(): string {
  return palette.themeMode === "light" && palette.skin === "high_contrast" ? "#ffffff" : "#051009";
}

function blueButtonInk(): string {
  return palette.themeMode === "light" && ["standard", "technical", "high_contrast"].includes(palette.skin) ? "#ffffff" : "#051009";
}
const RADAR_GROUND_CLIP_ID = "mobile-radar-ground-clip";

export function ScreenActivity({ activity }: { activity: ActivityStatus | null | undefined }) {
  if (!activity) return null;

  const toneStyle =
    activity.tone === "warn"
      ? styles.activityPillWarn
      : activity.tone === "ok"
        ? styles.activityPillOk
        : styles.activityPillSync;
  const iconColor = activity.tone === "warn" ? palette.amber : activity.tone === "ok" ? palette.green : palette.blue;

  return (
    <View style={[styles.activityPill, toneStyle]}>
      <View style={styles.activitySpinnerWrap}>
        <ActivityIndicator size="small" color={iconColor} />
      </View>
      <View style={styles.activityCopy}>
        <Text style={styles.activityLabel}>{activity.label}</Text>
        {activity.detail ? <Text style={styles.activityDetail}>{activity.detail}</Text> : null}
      </View>
    </View>
  );
}

type AdminSettingsSection = "health" | "devices" | "reports" | "developer";
type MatrixSettingsSection = "status" | "look" | "runtime" | "motion";
type CompanionSetupStep = "welcome" | "server" | "diagnostics" | "ready";
type SetupUrlCheckState = "idle" | "checking" | "ok" | "error" | "invalid";
type DocHeading = {
  id: string;
  level: 1 | 2;
  title: string;
  index: number;
};
type CompanionSetupResult = {
  serverUrl: string;
  diagnosticsMode: MobileDiagnosticsMode;
  config: AppConfig;
  state: AppState;
};

function keyedPart(value: unknown): string {
  return String(value ?? "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-zA-Z0-9_.:-]/g, "")
    || "missing";
}

function fidsRowKey(row: FidsRow, index: number): string {
  return [
    "fids",
    keyedPart(row.view),
    keyedPart(row.id),
    keyedPart(row.callsign),
    keyedPart(row.display_time),
    index
  ].join(":");
}

function historyRowKey(row: HistoryFlightRow, index: number): string {
  return [
    "history",
    keyedPart(row.id),
    keyedPart(row.callsign),
    keyedPart(row.snapshot_ts),
    keyedPart(row.sched_time),
    index
  ].join(":");
}

function radarBlipKey(row: RadarBlip, index: number): string {
  return [
    "radar",
    keyedPart(row.callsign),
    keyedPart(row.flight_number),
    keyedPart(row.lat),
    keyedPart(row.lon),
    index
  ].join(":");
}

function detailHistoryKey(
  item: { date: string; status?: string | null; delay_minutes?: number | null; gate?: string | null },
  index: number
): string {
  return [
    "detail-history",
    keyedPart(item.date),
    keyedPart(item.status),
    keyedPart(item.gate),
    keyedPart(item.delay_minutes),
    index
  ].join(":");
}

function airportResultKey(row: AirportResult, index: number): string {
  return [
    "airport",
    keyedPart(row.iata),
    keyedPart(row.icao),
    keyedPart(row.name),
    index
  ].join(":");
}

function profileKey(row: ConfigProfile, index: number): string {
  return [
    "profile",
    keyedPart(row.id),
    keyedPart(row.name),
    keyedPart(row.iata),
    index
  ].join(":");
}

type RowInfoFrame = {
  label: string;
  value: string;
  tone?: "accent" | "muted" | "warn";
};

function cleanInfoValue(value?: string | number | null): string {
  const text = String(value ?? "").trim();
  if (!text || text === "-" || text.toLowerCase() === "none") return "";
  return text;
}

function uniqueInfoFrames(frames: Array<RowInfoFrame | null | undefined>): RowInfoFrame[] {
  const seen = new Set<string>();
  const result: RowInfoFrame[] = [];
  for (const frame of frames) {
    const label = cleanInfoValue(frame?.label).toUpperCase();
    const value = cleanInfoValue(frame?.value);
    if (!label || !value) continue;
    const key = `${label}:${value.toUpperCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push({ label, value, tone: frame?.tone });
  }
  return result;
}

function airlineInfoFrames(row: FidsRow): RowInfoFrame[] {
  return uniqueInfoFrames([
    row.airline_display ? { label: "AIRLINE", value: row.airline_display, tone: "accent" } : null,
    row.codeshare_display ? { label: "ALSO", value: row.codeshare_display.replace(/^also\s+/i, ""), tone: "muted" } : null,
    row.callsign && row.callsign !== row.flight_display ? { label: "CALLSIGN", value: row.callsign, tone: "muted" } : null
  ]);
}

function rowDetailFrames(row: FidsRow, gateLabel: string): RowInfoFrame[] {
  return uniqueInfoFrames([
    gateLabel ? { label: "GATE", value: gateLabel, tone: "accent" } : null,
    row.aircraft_type ? { label: "A/C", value: row.aircraft_type.toUpperCase(), tone: "accent" } : null,
    row.time_delta_text ? { label: "TIME", value: row.time_delta_text, tone: row.delay_kind === "bad" ? "warn" : "muted" } : null,
    row.live_hint ? { label: "LIVE", value: row.live_hint, tone: "muted" } : null,
    row.source_hint ? { label: "DATA", value: row.source_hint, tone: "muted" } : null,
    row.codeshare_display ? { label: "CODESHARE", value: row.codeshare_display.replace(/^also\s+/i, ""), tone: "muted" } : null
  ]);
}

function metarAccentColor(category: string): string {
  switch (category.toUpperCase()) {
    case "VFR":  return palette.green;
    case "MVFR": return palette.blue;
    case "IFR":  return palette.amber;
    case "LIFR": return palette.red;
    default:     return palette.blue;
  }
}

type WeatherDisplayOption = { id: MobileWeatherDisplayMode; label: string; meta: string; detail: string };

const PASSENGER_WEATHER_DISPLAY_OPTION: WeatherDisplayOption = {
  id: "passenger",
  label: "PAX",
  meta: "Friendly",
  detail: "Decoded weather for passengers and boards."
};

const WEATHER_DISPLAY_OPTIONS: WeatherDisplayOption[] = [
  PASSENGER_WEATHER_DISPLAY_OPTION,
  { id: "pilot", label: "PILOT", meta: "Brief", detail: "Wind, visibility, cloud, temp, and QNH chips." },
  { id: "vatsim", label: "VATSIM", meta: "Raw", detail: "Controller-style METAR text where space allows." }
];

function weatherModeOption(mode: MobileWeatherDisplayMode): WeatherDisplayOption {
  return WEATHER_DISPLAY_OPTIONS.find((item) => item.id === mode) || PASSENGER_WEATHER_DISPLAY_OPTION;
}

function metarCategory(metar: Metar | null | undefined): string {
  return metar?.flight_category || metar?.category || "--";
}

function metarRawText(metar: Metar | null | undefined): string {
  return metar?.raw_text || "";
}

function metarTemperature(metar: Metar | null | undefined): string {
  if (typeof metar?.temperature_c === "number") {
    return `${Math.round(metar.temperature_c)}°C`;
  }
  const raw = metarRawText(metar);
  const match = raw.match(/\b(M?\d{1,2})\/(M?\d{1,2})\b/);
  if (!match) return "--";
  return `${(match[1] || "").replace("M", "-")}°C`;
}

function weatherCondition(metar: Metar | null | undefined): string {
  const text = `${metar?.decoded_summary || ""} ${metar?.raw_text || ""}`.toLowerCase();
  if (!text.trim()) return "Weather unavailable";
  if (/thunder|tsra|ts\b/.test(text)) return "Storms nearby";
  if (/snow|\bsn\b/.test(text)) return "Snow";
  if (/rain|showers|\bra\b|drizzle|\bdz\b/.test(text)) return "Rain";
  if (/fog|mist|\bfg\b|\bbr\b/.test(text)) return "Low visibility";
  if (/overcast|broken|\bovc\b|\bbkn\b/.test(text)) return "Cloudy";
  if (/few|scattered|\bfew\b|\bsct\b/.test(text)) return "Partly cloudy";
  if (/cavok|clear|no significant/.test(text)) return "Clear";
  return metarCategory(metar) !== "--" ? `${metarCategory(metar)} conditions` : "Current weather";
}

function weatherIconName(metar: Metar | null | undefined): MaterialIconName {
  const text = `${metar?.decoded_summary || ""} ${metar?.raw_text || ""}`.toLowerCase();
  if (/thunder|tsra|ts\b/.test(text)) return "weather-lightning-rainy";
  if (/snow|\bsn\b/.test(text)) return "weather-snowy";
  if (/rain|showers|\bra\b|drizzle|\bdz\b/.test(text)) return "weather-rainy";
  if (/fog|mist|\bfg\b|\bbr\b/.test(text)) return "weather-fog";
  if (/overcast|broken|\bovc\b|\bbkn\b/.test(text)) return "weather-cloudy";
  if (/few|scattered|\bfew\b|\bsct\b/.test(text)) return "weather-partly-cloudy";
  return "weather-sunny";
}

function weatherSummaryForMode(metar: Metar | null | undefined, mode: MobileWeatherDisplayMode): string {
  if (!metar) return "Asking Local Flight";
  if (mode === "vatsim") return metar.raw_text || "Raw METAR unavailable";
  if (mode === "pilot") {
    const chips = parseMetarChips(metar.raw_text || metar.decoded_summary || "");
    const visible = chips.slice(0, 3).map((chip) => `${chip.label} ${chip.value}`);
    return visible.length ? visible.join(" · ") : metar.decoded_summary || metar.raw_text || "Weather available";
  }
  return metar.decoded_summary || weatherCondition(metar);
}

function weatherChips(metar: Metar | null | undefined): Array<{ label: string; value: string }> {
  const chips = parseMetarChips(metar?.raw_text || "");
  if (!chips.some((chip) => chip.label === "TMP")) {
    const temp = metarTemperature(metar);
    if (temp !== "--") chips.push({ label: "TMP", value: temp });
  }
  if (!chips.some((chip) => chip.label === "QNH") && metar?.qnh_hpa) {
    chips.push({ label: "QNH", value: String(metar.qnh_hpa) });
  }
  if (!chips.some((chip) => chip.label === "WND") && metar?.wind) {
    chips.push({ label: "WND", value: metar.wind });
  }
  return chips;
}

export function Header({
  airportCode,
  airportIcao,
  airportName,
  airportLocation,
  live,
  error,
  connectionState,
  sourceLabel,
  utcTime,
  localTime,
  metar,
  weatherDisplayMode,
  snapshotPulse,
  rowCount,
  view,
  pinnedRow,
  islandPinned,
  onOpenDetail,
  onOpenActions,
  onTogglePin,
  onOpenConfig,
  onOpenWeather,
}: {
  airportCode: string;
  airportIcao: string;
  airportName: string;
  airportLocation: string;
  live: boolean;
  error?: string | null;
  connectionState?: ConnectionState;
  sourceLabel: string;
  utcTime: string;
  localTime: string;
  metar: Metar | null;
  weatherDisplayMode: MobileWeatherDisplayMode;
  snapshotPulse?: Animated.Value;
  rowCount: number;
  view: FlightView;
  pinnedRow: FidsRow | null;
  islandPinned: boolean;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
  onTogglePin: (row: FidsRow) => void;
  onOpenConfig: () => void;
  onOpenWeather: () => void;
}) {
  const category = metarCategory(metar);
  const accent = metarAccentColor(category);
  const longAirportName = airportName.length > 24;
  const effectiveConnectionState = connectionState || (!live ? "offline" : error ? "offline" : "live");
  const connectionAccent =
    effectiveConnectionState === "live"
      ? palette.green
      : effectiveConnectionState === "retrying"
        ? palette.amber
        : palette.red;
  const connectionLabel =
    effectiveConnectionState === "live"
      ? "LIVE"
      : effectiveConnectionState === "retrying"
        ? "RETRYING"
        : "OFFLINE";
  const dotOpacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (effectiveConnectionState === "offline") { dotOpacity.setValue(1); return; }
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(dotOpacity, { toValue: 0.2, duration: 850, useNativeDriver: true }),
        Animated.timing(dotOpacity, { toValue: 1, duration: 850, useNativeDriver: true })
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [dotOpacity, effectiveConnectionState]);

  return (
    <View style={styles.header}>
      <View style={[styles.headerAccentBar, { backgroundColor: accent }]} />

      <View style={[styles.airportHeroRow, longAirportName && styles.airportHeroRowStacked]}>
        <Pressable
          style={[styles.airportHeroPressable, longAirportName && styles.airportHeroPressableStacked]}
          onPress={onOpenConfig}
        >
          <View style={[styles.airportHeroTopline, longAirportName && styles.airportHeroToplineStacked]}>
            <Text style={styles.airportHeroKicker}>LOCAL FLIGHT AIRPORT</Text>
            <View style={[styles.airportCodeBadges, longAirportName && styles.airportCodeBadgesStacked]}>
              <Text style={[styles.airportCodeBadge, { borderColor: `${accent}55`, color: accent }]}>{airportCode}</Text>
              {airportIcao ? <Text style={styles.airportCodeBadge}>{airportIcao}</Text> : null}
            </View>
          </View>
          <Text
            style={[styles.airportHeroName, longAirportName && styles.airportHeroNameCompact, { color: accent }]}
            numberOfLines={2}
            adjustsFontSizeToFit
            minimumFontScale={0.64}
          >
            {airportName}
          </Text>
          {airportLocation ? (
            <Text style={styles.airportHeroLocation} numberOfLines={1}>{airportLocation}</Text>
          ) : null}
          <View style={styles.configHint}>
            <MaterialCommunityIcons name="tune-variant" size={10} color={palette.textDim} />
            <Text style={styles.configHintText}>tap to change airport</Text>
          </View>
          <View style={styles.telemetryStrip}>
            <View
              style={[
                styles.livePill,
                {
                  borderColor: hexToRgba(connectionAccent, 0.28),
                  backgroundColor: hexToRgba(connectionAccent, 0.10)
                }
              ]}
            >
              <Animated.View style={[styles.liveDot, { backgroundColor: connectionAccent, opacity: dotOpacity }]} />
              <Text style={[styles.liveText, { color: connectionAccent }]}>{connectionLabel}</Text>
            </View>
            {snapshotPulse ? (
              <Animated.View
                style={[
                  styles.snapshotPulseDot,
                  {
                    opacity: snapshotPulse,
                    transform: [{
                      scale: snapshotPulse.interpolate({
                        inputRange: [0, 1],
                        outputRange: [0.65, 1.85]
                      })
                    }]
                  }
                ]}
              />
            ) : null}
            <View style={styles.sourcePill}>
              <Text style={styles.sourceText}>{sourceLabel.toUpperCase()}</Text>
            </View>
            <View style={styles.countPill}>
              <Text style={styles.countText}>
                {view === "departures" ? "↑" : "↓"}{rowCount}
              </Text>
            </View>
          </View>
        </Pressable>

        <Pressable
          style={[styles.headerWeatherRail, longAirportName && styles.headerWeatherRailStacked]}
          onPress={onOpenWeather}
        >
          <View style={longAirportName ? styles.headerClockStackInline : undefined}>
          <Text style={styles.utcTime}>{utcTime}<Text style={styles.utcSuffix}>Z</Text></Text>
          <Text style={styles.localTime}>{localTime} <Text style={styles.localSuffix}>LOC</Text></Text>
          </View>
          <CompactWeatherCapsule metar={metar} mode={weatherDisplayMode} accent={accent} />
        </Pressable>
      </View>

      <FlightIsland
        row={pinnedRow}
        isPinned={islandPinned}
        live={live}
        utcTime={utcTime}
        onOpenDetail={onOpenDetail}
        onOpenActions={onOpenActions}
        onTogglePin={onTogglePin}
      />
    </View>
  );
}

function CompactWeatherCapsule({
  metar,
  mode,
  accent
}: {
  metar: Metar | null;
  mode: MobileWeatherDisplayMode;
  accent: string;
}) {
  const category = metarCategory(metar);
  const temp = metarTemperature(metar);
  const label = mode === "vatsim" ? "VATSIM" : mode === "pilot" ? "PILOT" : category;
  const detail =
    mode === "vatsim"
      ? (metar?.raw_text || "METAR wait").replace(/^METAR\s+/, "").slice(0, 18)
      : mode === "pilot"
        ? weatherSummaryForMode(metar, "pilot")
        : weatherCondition(metar);

  return (
    <View style={[styles.weatherCompact, { borderColor: `${accent}44`, backgroundColor: `${accent}14` }]}>
      <MaterialCommunityIcons name={weatherIconName(metar)} size={18} color={accent} />
      <View style={styles.weatherCompactCopy}>
        <Text style={styles.weatherCompactTemp}>{temp}</Text>
        <Text style={styles.weatherCompactMeta} numberOfLines={1}>{label} · {detail}</Text>
      </View>
    </View>
  );
}

function FlightIsland({
  row,
  isPinned,
  live,
  utcTime,
  onOpenDetail,
  onOpenActions,
  onTogglePin
}: {
  row: FidsRow | null;
  isPinned: boolean;
  live: boolean;
  utcTime: string;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
  onTogglePin: (row: FidsRow) => void;
}) {
  return (
    <View style={[styles.islandShell, row && styles.islandShellActive]}>
      <Pressable
        style={styles.islandPressable}
        delayLongPress={360}
        onLongPress={() => {
          if (row) onOpenActions(row);
        }}
        onPress={() => {
          if (row?.callsign) {
            onOpenDetail(row.callsign);
          }
        }}
      >
        <View style={styles.islandCompactRow}>
          <View style={styles.islandLead}>
            <MaterialCommunityIcons
              name={row?.view === "arrivals" ? "airplane-landing" : "airplane-takeoff"}
              size={15}
              color={live ? palette.blue2 : palette.textDim}
            />
            <View style={styles.islandTextWrap}>
              <Text style={styles.islandFlight} numberOfLines={1}>
                {row?.flight_display || (live ? "LOCAL FLIGHT" : "OFFLINE")}
              </Text>
              <Text style={styles.islandMeta} numberOfLines={1}>
                {row ? `${routeName(row.route_display)} · ${row.display_time}` : `UTC ${utcTime}`}
              </Text>
            </View>
          </View>

          <View style={styles.islandTrail}>
            <Text style={[styles.islandStatus, { color: live ? palette.green : palette.red }]}>
              {row ? statusShort(row.status_display) : live ? "READY" : "OFF"}
            </Text>
            <Text style={styles.islandActionHint}>{row ? "DETAIL" : "STATUS"}</Text>
          </View>
        </View>
      </Pressable>

      {row ? (
        <Pressable
          style={[styles.islandPinButton, isPinned && styles.islandPinButtonActive]}
          onPress={() => onTogglePin(row)}
          hitSlop={10}
        >
          <MaterialCommunityIcons
            name={isPinned ? "pin-off" : "pin-outline"}
            size={15}
            color={isPinned ? palette.amber : palette.blue2}
          />
        </Pressable>
      ) : null}
    </View>
  );
}

export function FullscreenFidsDisplay({
  rows,
  view,
  loading,
  error,
  live,
  airportCode,
  airportName,
  sourceLabel,
  utcTime,
  localTime,
  metar,
  weatherDisplayMode,
  pinnedCallsign
}: {
  rows: FidsRow[];
  view: FlightView;
  loading: boolean;
  error: string | null;
  live: boolean;
  airportCode: string;
  airportName: string;
  sourceLabel: string;
  utcTime: string;
  localTime: string;
  metar: Metar | null;
  weatherDisplayMode: MobileWeatherDisplayMode;
  pinnedCallsign: string;
}) {
  const { width, height } = useWindowDimensions();
  const listRef = useRef<FlatList<FidsRow>>(null);
  const autoScrollIndex = useRef(0);
  const [infoCycleTick, setInfoCycleTick] = useState(0);
  const compactLandscape = height < 430 || width < 780;
  const tabletLandscape = width >= 900 && height >= 560;
  const targetVisibleRows = tabletLandscape ? 6 : compactLandscape ? 3 : 4;
  const rowHeight = compactLandscape ? 48 : tabletLandscape ? 64 : 58;
  const rowGap = compactLandscape ? 4 : 5;
  const pinned = pinnedCallsign
    ? rows.find((row) => flightPinKey(row) === pinnedCallsign) || null
    : null;
  const displayRows = pinned
    ? [pinned, ...rows.filter((row) => flightPinKey(row) !== pinnedCallsign)]
    : rows;
  const boardTitle = view === "arrivals" ? "ARRIVALS" : "DEPARTURES";
  const routeHeading = view === "arrivals" ? "FROM" : "TO";
  const emptyTitle = loading
    ? "LOADING FLIGHTS"
    : live
      ? "NO FLIGHTS ON BOARD"
      : "LOCAL SERVER OFFLINE";
  const emptyDetail = error || "Rows will appear here after the next Local Flight snapshot.";
  const autoScrollEnabled = displayRows.length > targetVisibleRows;

  useEffect(() => {
    const timer = setInterval(() => {
      setInfoCycleTick((value) => value + 1);
    }, 2800);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    autoScrollIndex.current = 0;
    listRef.current?.scrollToOffset({ offset: 0, animated: false });
    if (!autoScrollEnabled) return;

    const timer = setInterval(() => {
      const next = (autoScrollIndex.current + 1) % displayRows.length;
      autoScrollIndex.current = next;
      if (next === 0) {
        listRef.current?.scrollToOffset({ offset: 0, animated: true });
        return;
      }
      listRef.current?.scrollToIndex({
        index: next,
        animated: true,
        viewPosition: 0
      });
    }, 3600);

    return () => clearInterval(timer);
  }, [autoScrollEnabled, displayRows.length, view]);

  return (
    <View style={[styles.fullscreenFidsShell, compactLandscape && styles.fullscreenFidsShellCompact]}>
      <View style={[styles.fullscreenFidsTop, compactLandscape && styles.fullscreenFidsTopCompact]}>
        <View style={styles.fullscreenFidsIdentity}>
          <View style={styles.fullscreenFidsKickerRow}>
            <Text style={styles.fullscreenFidsKicker}>{airportCode}</Text>
            <Text style={styles.fullscreenFidsBoardBadge}>{boardTitle}</Text>
          </View>
          <Text
            style={[styles.fullscreenFidsTitle, compactLandscape && styles.fullscreenFidsTitleCompact]}
            numberOfLines={compactLandscape ? 1 : 2}
            adjustsFontSizeToFit
            minimumFontScale={compactLandscape ? 0.58 : 0.72}
          >
            {airportName}
          </Text>
        </View>

        <View style={styles.fullscreenFidsMeta}>
          <Text style={[styles.fullscreenFidsLive, live ? styles.fullscreenFidsLiveOn : styles.fullscreenFidsLiveOff]}>
            {live ? "LIVE" : "OFFLINE"}
          </Text>
          <Text style={styles.fullscreenFidsSource}>{sourceLabel.toUpperCase()}</Text>
          <Text style={styles.fullscreenFidsClock}>UTC {utcTime}</Text>
          <Text style={styles.fullscreenFidsLocal}>{localTime}</Text>
        </View>
      </View>

      <FullscreenWeatherHero metar={metar} mode={weatherDisplayMode} compact={compactLandscape} />

      <View style={[styles.fullscreenFidsColumns, compactLandscape && styles.fullscreenFidsColumnsCompact]}>
        <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsTimeColumn, compactLandscape && styles.fullscreenFidsTimeColumnCompact]}>TIME</Text>
        <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsFlightColumn, compactLandscape && styles.fullscreenFidsFlightColumnCompact]}>FLIGHT</Text>
        <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsRouteColumn]}>{routeHeading}</Text>
        <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsStatusColumn, compactLandscape && styles.fullscreenFidsStatusColumnCompact]}>STATUS</Text>
        {compactLandscape ? (
          <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsInfoColumn]}>INFO</Text>
        ) : (
          <>
            <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsAircraftColumn]}>A/C</Text>
            <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsGateColumn]}>GATE</Text>
          </>
        )}
      </View>

      <FlatList<FidsRow>
        ref={listRef}
        data={displayRows}
        keyExtractor={fidsRowKey}
        renderItem={({ item, index }) => (
          <FullscreenFidsRow
            row={item}
            index={index}
            compact={compactLandscape}
            cycleTick={infoCycleTick}
            rowHeight={rowHeight}
            isPinned={flightPinKey(item) === pinnedCallsign}
          />
        )}
        style={styles.fullscreenFidsList}
        contentContainerStyle={[styles.fullscreenFidsListContent, { gap: rowGap }]}
        getItemLayout={(_, index) => ({
          length: rowHeight + rowGap,
          offset: (rowHeight + rowGap) * index,
          index
        })}
        ListEmptyComponent={
          <View style={styles.fullscreenFidsEmpty}>
            <Text style={styles.fullscreenFidsEmptyTitle}>{emptyTitle}</Text>
            <Text style={styles.fullscreenFidsEmptyDetail}>{emptyDetail}</Text>
          </View>
        }
        onScrollToIndexFailed={({ index, averageItemLength }) => {
          listRef.current?.scrollToOffset({
            offset: Math.max(0, index * Math.max(averageItemLength || rowHeight + rowGap, rowHeight + rowGap)),
            animated: true
          });
        }}
        showsVerticalScrollIndicator={false}
      />
    </View>
  );
}

function FullscreenWeatherHero({
  metar,
  mode,
  compact
}: {
  metar: Metar | null;
  mode: MobileWeatherDisplayMode;
  compact?: boolean;
}) {
  const category = metarCategory(metar);
  const accent = metarAccentColor(category);
  const summary = weatherSummaryForMode(metar, mode);
  const chips = weatherChips(metar).slice(0, compact ? 2 : 5);
  const modeOption = weatherModeOption(mode);

  return (
    <View style={[styles.fullscreenWeatherHero, compact && styles.fullscreenWeatherHeroCompact, { borderColor: `${accent}34`, backgroundColor: `${accent}0f` }]}>
      <View style={[styles.fullscreenWeatherIcon, compact && styles.fullscreenWeatherIconCompact, { borderColor: `${accent}44`, backgroundColor: `${accent}18` }]}>
        <MaterialCommunityIcons name={weatherIconName(metar)} size={compact ? 18 : 24} color={accent} />
      </View>
      <View style={styles.fullscreenWeatherCopy}>
        <View style={styles.fullscreenWeatherTitleRow}>
          <Text style={[styles.fullscreenWeatherCategory, compact && styles.fullscreenWeatherCategoryCompact, { color: accent }]}>{category}</Text>
          <Text style={styles.fullscreenWeatherTemp}>{metarTemperature(metar)}</Text>
          <Text style={styles.fullscreenWeatherMode}>{modeOption.label}</Text>
        </View>
        {!compact ? <Text style={styles.fullscreenWeatherSummary} numberOfLines={1}>{summary}</Text> : null}
      </View>
      <View style={styles.fullscreenWeatherChips}>
        {chips.map((chip, index) => (
          <View key={`fullscreen-weather-${chip.label}-${chip.value}-${index}`} style={styles.fullscreenWeatherChip}>
            <Text style={styles.fullscreenWeatherChipLabel}>{chip.label}</Text>
            <Text style={styles.fullscreenWeatherChipValue}>{chip.value}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

export function FidsScreen({
  rows,
  view,
  loading,
  refreshing,
  activity,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefresh,
  onViewChange,
  onOpenDetail,
  onOpenActions,
  pinnedCallsign,
  contentPaddingBottom
}: {
  rows: FidsRow[];
  view: FlightView;
  loading: boolean;
  refreshing: boolean;
  activity?: ActivityStatus | null;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefresh: () => void;
  onViewChange: (view: FlightView) => void;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
  pinnedCallsign: string;
  contentPaddingBottom: number;
}) {
  const { width } = useWindowDimensions();
  const compactRows = width < 700;
  const [infoCycleTick, setInfoCycleTick] = useState(0);
  const pinned = pinnedCallsign
    ? rows.find((row) => flightPinKey(row) === pinnedCallsign) || null
    : null;
  const displayRows = pinned
    ? [pinned, ...rows.filter((row) => flightPinKey(row) !== pinnedCallsign)]
    : rows;

  useEffect(() => {
    const timer = setInterval(() => {
      setInfoCycleTick((value) => value + 1);
    }, 2800);
    return () => clearInterval(timer);
  }, []);

  return (
    <FlatList<FidsRow>
      data={displayRows}
      keyExtractor={fidsRowKey}
      renderItem={({ item, index }) => (
        <View style={styles.fidsListItem}>
          <FidsRowView
            row={item}
            index={index}
            compact={compactRows}
            cycleTick={infoCycleTick}
            isPinned={flightPinKey(item) === pinnedCallsign}
            onOpenDetail={onOpenDetail}
            onOpenActions={onOpenActions}
          />
        </View>
      )}
      style={styles.screenScroll}
      contentContainerStyle={[styles.screenContent, { paddingBottom: contentPaddingBottom }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={palette.blue}
          onRefresh={onRefresh}
        />
      }
      ListHeaderComponent={
        <>
          {showConnectPrompt ? <ConnectPrompt onSettings={onOpenSettings} /> : null}
          <ScreenActivity activity={activity} />
          {error ? <ScreenError message={error} onRetry={onRefresh} retrying={refreshing} /> : null}

          <View style={styles.dirToggle}>
            <DirectionButton
              active={view === "departures"}
              label="DEPARTURES"
              onPress={() => onViewChange("departures")}
            />
            <DirectionButton
              active={view === "arrivals"}
              label="ARRIVALS"
              onPress={() => onViewChange("arrivals")}
            />
          </View>

          <View style={styles.fidsHeader}>
            <Text style={[styles.fidsHeaderText, styles.fidsColTime]}>TIME</Text>
            <Text style={[styles.fidsHeaderText, styles.fidsColFlight]}>FLIGHT</Text>
            <Text style={[styles.fidsHeaderText, styles.fidsColRoute]}>{view === "arrivals" ? "FROM" : "TO"}</Text>
            <Text style={[styles.fidsHeaderText, styles.fidsColStatusText, compactRows && styles.fidsColStatusTextCompact]}>STATUS</Text>
            {!compactRows ? (
              <>
                <Text style={[styles.fidsHeaderText, styles.fidsColAircraft]}>A/C</Text>
                <Text style={[styles.fidsHeaderText, styles.fidsColGateText]}>GATE</Text>
              </>
            ) : null}
          </View>
        </>
      }
      ListEmptyComponent={
        loading ? (
          <ActivityIndicator color={palette.blue} style={styles.loader} />
        ) : (
          <Text style={styles.empty}>No rows yet. Complete setup or run a snapshot fetch on the server.</Text>
        )
      }
      showsVerticalScrollIndicator={false}
    />
  );
}

function historyWindowLabel(w: HistoryWindow): string {
  if (w === 720) return "30D";
  if (w === 2160) return "90D";
  if (w === 168) return "7D";
  return `${w}H`;
}

function HistoryBarRow({
  label,
  value,
  pct,
  meta,
  color
}: {
  label: string;
  value: number;
  pct: number;
  meta: string;
  color?: string;
}) {
  return (
    <View style={styles.historyBarRow}>
      <Text style={styles.historyBarLabel} numberOfLines={1}>{label}</Text>
      <View style={styles.historyBarTrack}>
        <View style={[styles.historyBarFill, { width: `${Math.max(pct, value ? 2 : 0)}%` as unknown as number, backgroundColor: color || palette.blue }]} />
      </View>
      <Text style={styles.historyBarValue} numberOfLines={1}>{meta}</Text>
    </View>
  );
}

const DELAY_BUCKET_COLORS: Record<string, string> = {
  early: "#18d66a",
  on_time: "#4a9eda",
  delayed_warn: "#f2b84b",
  delayed_bad: "#ff5d5d",
  unknown: "rgba(150,160,175,0.45)"
};

export function HistoryScreen({
  data,
  summary,
  direction,
  hours,
  callsign,
  airline,
  loading,
  refreshing,
  activity,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefresh,
  onDirectionChange,
  onHoursChange,
  onCallsignChange,
  onAirlineChange,
  onApplyFilters,
  onOpenDetail,
  contentPaddingBottom
}: {
  data: HistoryResponse | null;
  summary: HistorySummary | null;
  direction: HistoryDirection;
  hours: HistoryWindow;
  callsign: string;
  airline: string;
  loading: boolean;
  refreshing: boolean;
  activity?: ActivityStatus | null;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefresh: () => void;
  onDirectionChange: (value: HistoryDirection) => void;
  onHoursChange: (value: HistoryWindow) => void;
  onCallsignChange: (v: string) => void;
  onAirlineChange: (v: string) => void;
  onApplyFilters: () => void;
  onOpenDetail: (callsign: string) => void;
  contentPaddingBottom: number;
}) {
  const flights = data?.flights || [];
  const maxAirlineCount = Math.max(...(summary?.top_airlines?.map((a) => a.count) || [1]), 1);
  const maxRouteCount = Math.max(...(summary?.top_routes?.map((r) => r.count) || [1]), 1);
  const maxAircraftCount = Math.max(...(summary?.top_aircraft?.map((a) => a.count) || [1]), 1);

  return (
    <FlatList<HistoryFlightRow>
      data={flights}
      keyExtractor={historyRowKey}
      renderItem={({ item }) => (
        <HistoryRow row={item} onOpenDetail={onOpenDetail} />
      )}
      style={styles.screenScroll}
      contentContainerStyle={[styles.screenContent, { paddingBottom: contentPaddingBottom }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={palette.blue}
          onRefresh={onRefresh}
        />
      }
      ListHeaderComponent={
        <>
          {showConnectPrompt ? <ConnectPrompt onSettings={onOpenSettings} /> : null}
          <ScreenActivity activity={activity} />
          {error ? <ScreenError message={error} onRetry={onRefresh} retrying={refreshing} /> : null}

          <FilterSection title="DIRECTION">
            <View style={styles.filterRow}>
              <DirectionButton active={direction === "both"} label="ALL" onPress={() => onDirectionChange("both")} />
              <DirectionButton active={direction === "dep"} label="DEPARTURES" onPress={() => onDirectionChange("dep")} />
              <DirectionButton active={direction === "arr"} label="ARRIVALS" onPress={() => onDirectionChange("arr")} />
            </View>
          </FilterSection>

          <FilterSection title="PERIOD">
            <View style={styles.filterRow}>
              {HISTORY_WINDOWS.map((item) => (
                <DirectionButton
                  key={item}
                  active={hours === item}
                  label={historyWindowLabel(item)}
                  onPress={() => onHoursChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <View style={styles.historyFilterRow}>
            <TextInput
              style={styles.historyFilterInput}
              value={callsign}
              onChangeText={(v) => onCallsignChange(v.toUpperCase())}
              placeholder="CALLSIGN"
              placeholderTextColor={palette.textDim}
              autoCapitalize="characters"
              autoCorrect={false}
              maxLength={10}
              returnKeyType="search"
              onSubmitEditing={onApplyFilters}
            />
            <TextInput
              style={styles.historyFilterInput}
              value={airline}
              onChangeText={(v) => onAirlineChange(v.toUpperCase())}
              placeholder="AIRLINE"
              placeholderTextColor={palette.textDim}
              autoCapitalize="characters"
              autoCorrect={false}
              maxLength={3}
              returnKeyType="search"
              onSubmitEditing={onApplyFilters}
            />
            <Pressable style={styles.historyApplyButton} onPress={onApplyFilters}>
              <Text style={styles.historyApplyButtonText}>APPLY</Text>
            </Pressable>
          </View>

          {summary ? (
            <>
              <View style={styles.historyKpiGrid}>
                <View style={styles.historyKpiCard}>
                  <Text style={styles.historyKpiLabel}>FLIGHTS</Text>
                  <Text style={styles.historyKpiValue}>{summary.total || "-"}</Text>
                  <Text style={styles.historyKpiNote}>{historyWindowLabel(hours)} window</Text>
                </View>
                <View style={styles.historyKpiCard}>
                  <Text style={styles.historyKpiLabel}>DEPART.</Text>
                  <Text style={[styles.historyKpiValue, { color: palette.blue }]}>{summary.departures ?? "-"}</Text>
                  <Text style={styles.historyKpiNote}>outbound</Text>
                </View>
                <View style={styles.historyKpiCard}>
                  <Text style={styles.historyKpiLabel}>ARRIVE.</Text>
                  <Text style={[styles.historyKpiValue, { color: palette.green }]}>{summary.arrivals ?? "-"}</Text>
                  <Text style={styles.historyKpiNote}>inbound</Text>
                </View>
                <View style={styles.historyKpiCard}>
                  <Text style={styles.historyKpiLabel}>ON TIME</Text>
                  <Text style={[styles.historyKpiValue, { color: palette.green }]}>{summary.on_time_pct != null ? `${summary.on_time_pct}%` : "-"}</Text>
                  <Text style={styles.historyKpiNote}>±4m</Text>
                </View>
                <View style={styles.historyKpiCard}>
                  <Text style={styles.historyKpiLabel}>DELAYED</Text>
                  <Text style={[styles.historyKpiValue, { color: palette.amber }]}>{summary.delayed_pct != null ? `${summary.delayed_pct}%` : "-"}</Text>
                  <Text style={styles.historyKpiNote}>5m+</Text>
                </View>
                <View style={styles.historyKpiCard}>
                  <Text style={styles.historyKpiLabel}>AVG DELAY</Text>
                  <Text style={[styles.historyKpiValue, { fontSize: 16, lineHeight: 22, marginTop: 6 }]}>{summary.avg_delay_minutes != null ? `+${summary.avg_delay_minutes}m` : "-"}</Text>
                  <Text style={styles.historyKpiNote}>when late</Text>
                </View>
              </View>

              {(summary.delay_buckets?.length ?? 0) > 0 ? (
                <View style={styles.historyPanel}>
                  <Text style={styles.historyPanelTitle}>DELAY QUOTA</Text>
                  <View style={styles.historyDelayStack}>
                    {summary.delay_buckets.map((b) => (
                      <View
                        key={b.bucket}
                        style={{ width: `${Math.max(b.pct || 0, b.count ? 1 : 0)}%` as unknown as number, backgroundColor: DELAY_BUCKET_COLORS[b.bucket] || "#888" }}
                      />
                    ))}
                  </View>
                  {summary.delay_buckets.map((b) => (
                    <HistoryBarRow
                      key={b.bucket}
                      label={b.label}
                      value={b.count}
                      pct={b.pct || 0}
                      meta={String(b.count)}
                      color={DELAY_BUCKET_COLORS[b.bucket]}
                    />
                  ))}
                </View>
              ) : null}

              {(summary.top_airlines?.length ?? 0) > 0 ? (
                <View style={styles.historyPanel}>
                  <Text style={styles.historyPanelTitle}>AIRLINE PERFORMANCE</Text>
                  {summary.top_airlines.slice(0, 8).map((a) => (
                    <HistoryBarRow
                      key={a.code}
                      label={a.code || "-"}
                      value={a.count}
                      pct={Math.round((a.count / maxAirlineCount) * 100)}
                      meta={`${a.delay_rate_pct ?? 0}% delay | ${a.count}`}
                    />
                  ))}
                </View>
              ) : null}

              {(summary.top_routes?.length ?? 0) > 0 ? (
                <View style={styles.historyPanel}>
                  <Text style={styles.historyPanelTitle}>TOP ROUTES</Text>
                  {summary.top_routes.slice(0, 8).map((r, i) => (
                    <HistoryBarRow
                      key={`${r.origin}-${r.destination}-${i}`}
                      label={`${r.origin || "-"}›${r.destination || "-"}`}
                      value={r.count}
                      pct={Math.round((r.count / maxRouteCount) * 100)}
                      meta={`${r.delay_rate_pct ?? 0}% | ${r.count}`}
                    />
                  ))}
                </View>
              ) : null}

              {(summary.top_aircraft?.length ?? 0) > 0 ? (
                <View style={styles.historyPanel}>
                  <Text style={styles.historyPanelTitle}>TOP AIRCRAFT</Text>
                  {summary.top_aircraft.slice(0, 8).map((a) => (
                    <HistoryBarRow
                      key={a.aircraft_type}
                      label={a.aircraft_type}
                      value={a.count}
                      pct={Math.round((a.count / maxAircraftCount) * 100)}
                      meta={String(a.count)}
                    />
                  ))}
                </View>
              ) : null}
            </>
          ) : (
            <View style={styles.metricRow}>
              <InfoCard label="ROWS" value={data ? String(data.count) : "..."} />
              <InfoCard label="FILTER" value={direction.toUpperCase()} tone="green" />
              <InfoCard label="WINDOW" value={historyWindowLabel(hours)} tone="amber" />
            </View>
          )}
        </>
      }
      ListEmptyComponent={
        loading ? (
          <ActivityIndicator color={palette.blue} style={styles.loader} />
        ) : (
          <Text style={styles.empty}>No recent history yet. Once snapshots have run, flights will appear here.</Text>
        )
      }
      ItemSeparatorComponent={() => <View style={styles.historyGap} />}
      showsVerticalScrollIndicator={false}
    />
  );
}

function RadarLegendOverlay({ source, ageSeconds }: { source?: string | null; ageSeconds: number | null }) {
  const ageLabel = ageSeconds == null
    ? "no fix"
    : ageSeconds < 60
      ? `${ageSeconds}s ago`
      : `${Math.round(ageSeconds / 60)}m ago`;
  const ageTone = ageSeconds == null
    ? palette.textDim
    : ageSeconds < 30
      ? palette.green
      : ageSeconds < 120
        ? palette.amber
        : palette.red;
  return (
    <View style={styles.radarLegend}>
      <View style={styles.radarLegendHeader}>
        <Text style={styles.radarLegendTitle}>RADAR</Text>
        <View style={styles.radarLegendMetaWrap}>
          <Text style={styles.radarLegendSource} numberOfLines={1}>{(source || "wait").toUpperCase()}</Text>
          <Text style={[styles.radarLegendAge, { color: ageTone }]}>{ageLabel}</Text>
        </View>
      </View>
      <View style={styles.radarLegendChips}>
        <View style={styles.radarLegendChip}>
          <View style={[styles.radarLegendDot, { backgroundColor: palette.green }]} />
          <Text style={styles.radarLegendLabel}>ENRICHED</Text>
        </View>
        <View style={styles.radarLegendChip}>
          <View style={[styles.radarLegendDot, { backgroundColor: palette.blue2 }]} />
          <Text style={styles.radarLegendLabel}>AIRBORNE</Text>
        </View>
        <View style={styles.radarLegendChip}>
          <View style={[styles.radarLegendDot, { backgroundColor: palette.amber }]} />
          <Text style={styles.radarLegendLabel}>GROUND</Text>
        </View>
      </View>
    </View>
  );
}

export function RadarScreen({
  data,
  groundData,
  groundError,
  metar,
  weatherDisplayMode,
  radiusNm,
  loading,
  refreshing,
  activity,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefresh,
  onRadiusChange,
  onOpenDetail,
  compact = false,
  contentPaddingBottom
}: {
  data: RadarResponse | null;
  groundData: RadarMapResponse | null;
  groundError: string | null;
  metar: Metar | null;
  weatherDisplayMode: MobileWeatherDisplayMode;
  radiusNm: RadarRadius;
  loading: boolean;
  refreshing: boolean;
  activity?: ActivityStatus | null;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefresh: () => void;
  onRadiusChange: (value: RadarRadius) => void;
  onOpenDetail: (callsign: string) => void;
  compact?: boolean;
  contentPaddingBottom: number;
}) {
  const blips = data?.blips || [];
  const groundFeatureCount = radarGroundFeatureCount(groundData);
  const groundUnavailable = radarGroundUnavailable(groundData, groundError);

  const [fetchedAt, setFetchedAt] = useState<number | null>(null);
  const [, setTick] = useState(0);
  useEffect(() => {
    if (data) setFetchedAt(Date.now());
  }, [data]);
  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), 5000);
    return () => clearInterval(t);
  }, []);
  const ageSeconds = fetchedAt ? Math.max(0, Math.round((Date.now() - fetchedAt) / 1000)) : null;

  return (
    <FlatList<RadarBlip>
      data={blips}
      keyExtractor={radarBlipKey}
      renderItem={({ item }) => (
        <RadarBlipRow blip={item} onOpenDetail={onOpenDetail} />
      )}
      style={styles.screenScroll}
      contentContainerStyle={[styles.screenContent, { paddingBottom: contentPaddingBottom }]}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={palette.blue}
          onRefresh={onRefresh}
        />
      }
      ListHeaderComponent={
        <>
          {showConnectPrompt ? <ConnectPrompt onSettings={onOpenSettings} /> : null}
          <ScreenActivity activity={activity} />
          {error ? <ScreenError message={error} onRetry={onRefresh} retrying={refreshing} /> : null}

          <FilterSection title={compact ? "ZOOM" : "RADIUS"}>
            <View style={compact ? styles.filterWrap : styles.filterRow}>
              {RADAR_RADII.map((item) => (
                <OptionChip
                  key={item}
                  active={radiusNm === item}
                  label={`${item}`}
                  meta="NM"
                  onPress={() => onRadiusChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <View style={styles.metricRow}>
            <InfoCard label="BLIPS" value={data ? String(data.count) : "..."} />
            <InfoCard label="SOURCE" value={data?.source?.toUpperCase() || "WAIT"} tone="green" />
            <InfoCard label="RANGE" value={`${radiusNm} NM`} tone="amber" />
            <InfoCard
              label="GROUND"
              value={groundFeatureCount ? String(groundFeatureCount) : groundUnavailable ? "OFF" : "WAIT"}
              tone={groundFeatureCount ? "green" : groundUnavailable ? "amber" : "blue"}
            />
          </View>

          <RadarWeatherCard metar={metar} mode={weatherDisplayMode} />

          <RadarLegendOverlay source={data?.source} ageSeconds={ageSeconds} />

          <RadarScope
            data={data}
            groundData={groundData}
            groundError={groundError}
            radiusNm={radiusNm}
            onRadiusChange={onRadiusChange}
            onOpenDetail={onOpenDetail}
            compact={compact}
          />
        </>
      }
      ListEmptyComponent={
        loading ? (
          <ActivityIndicator color={palette.blue} style={styles.loader} />
        ) : (
          <Text style={styles.empty}>No radar tracks available for the current range.</Text>
        )
      }
      ItemSeparatorComponent={() => <View style={styles.historyGap} />}
      showsVerticalScrollIndicator={false}
    />
  );
}

function RadarWeatherCard({ metar, mode }: { metar: Metar | null; mode: MobileWeatherDisplayMode }) {
  const category = metarCategory(metar);
  const accent = metarAccentColor(category);
  const chips = weatherChips(metar);
  const raw = metar?.raw_text || "Raw METAR unavailable";
  const summary = weatherSummaryForMode(metar, mode);
  const modeOption = weatherModeOption(mode);
  const body = mode === "vatsim" ? raw : summary;

  return (
    <View style={[styles.radarWeatherCard, { borderColor: `${accent}38` }]}>
      <View style={styles.radarWeatherHeader}>
        <View style={[styles.radarWeatherIcon, { backgroundColor: `${accent}18`, borderColor: `${accent}44` }]}>
          <MaterialCommunityIcons name={weatherIconName(metar)} size={21} color={accent} />
        </View>
        <View style={styles.radarWeatherTitleWrap}>
          <Text style={styles.radarWeatherTitle}>{modeOption.label} WEATHER</Text>
          <Text style={styles.radarWeatherBody}>{body}</Text>
        </View>
        <View style={[styles.radarWeatherCategory, { backgroundColor: `${accent}18`, borderColor: `${accent}44` }]}>
          <Text style={[styles.radarWeatherCategoryText, { color: accent }]}>{category}</Text>
          <Text style={styles.radarWeatherTemp}>{metarTemperature(metar)}</Text>
        </View>
      </View>

      {mode === "vatsim" ? (
        <Text style={styles.radarWeatherRaw}>{raw}</Text>
      ) : (
        <View style={styles.radarWeatherChips}>
          {chips.slice(0, 5).map((chip, index) => (
            <View key={`radar-weather-${chip.label}-${chip.value}-${index}`} style={styles.metarChip}>
              <Text style={styles.metarChipLabel}>{chip.label}</Text>
              <Text style={styles.metarChipValue}>{chip.value}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

export function MatrixScreen({
  rows,
  view,
  brightness,
  maxRows,
  refreshSeconds,
  pageRotationSeconds,
  animationMode,
  animationSpeed,
  statusAnimationEnabled,
  showWeather,
  matrixPalette,
  preset,
  applyingPreset,
  matrixEnabled,
  matrixLastSeen,
  dirty,
  saving,
  saveMessage,
  saveTone,
  refreshing,
  activity,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefresh,
  onViewChange,
  onBrightnessChange,
  onRowsChange,
  onRefreshSecondsChange,
  onPageRotationChange,
  onAnimationModeChange,
  onAnimationSpeedChange,
  onStatusAnimationChange,
  onShowWeatherChange,
  onMatrixPaletteChange,
  onApplyPreset,
  onSave,
  onReset,
  onBackSettings,
  contentPaddingBottom
}: {
  rows: FidsRow[];
  view: FlightView;
  brightness: number;
  maxRows: number;
  refreshSeconds: number;
  pageRotationSeconds: number;
  animationMode: MatrixAnimationMode;
  animationSpeed: number;
  statusAnimationEnabled: boolean;
  showWeather: boolean;
  matrixPalette: MatrixPaletteId;
  preset: MatrixPresetId;
  applyingPreset: MatrixPresetId | null;
  matrixEnabled: boolean;
  matrixLastSeen: string | null;
  dirty: boolean;
  saving: boolean;
  saveMessage: string | null;
  saveTone: FeedbackTone;
  refreshing: boolean;
  activity?: ActivityStatus | null;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefresh: () => void;
  onViewChange: (value: FlightView) => void;
  onBrightnessChange: (value: number) => void;
  onRowsChange: (value: number) => void;
  onRefreshSecondsChange: (value: number) => void;
  onPageRotationChange: (value: number) => void;
  onAnimationModeChange: (value: MatrixAnimationMode) => void;
  onAnimationSpeedChange: (value: number) => void;
  onStatusAnimationChange: (value: boolean) => void;
  onShowWeatherChange: (value: boolean) => void;
  onMatrixPaletteChange: (value: MatrixPaletteId) => void;
  onApplyPreset: (value: MatrixPresetId) => void;
  onSave: () => void;
  onReset: () => void;
  onBackSettings: () => void;
  contentPaddingBottom: number;
}) {
  const lines = matrixPreviewLines(rows);
  const brightnessAlpha = Math.max(0.28, Math.min(1, brightness));
  const matrixColors = MATRIX_LED_PALETTES[matrixPalette] || MATRIX_LED_PALETTES.pax_blue;
  const selectedPalette = MATRIX_PALETTE_OPTIONS.find((item) => item.id === matrixPalette) || MATRIX_PALETTE_OPTIONS[0]!;
  const brightnessPct = Math.round(brightness * 100);
  const [section, setSection] = useState<MatrixSettingsSection>("status");

  return (
    <ScrollView
      style={styles.screenScroll}
      contentContainerStyle={[styles.screenContent, { paddingBottom: contentPaddingBottom }]}
      refreshControl={
        <RefreshControl refreshing={refreshing} tintColor={palette.blue} onRefresh={onRefresh} />
      }
      showsVerticalScrollIndicator={false}
    >
      {showConnectPrompt ? <ConnectPrompt onSettings={onOpenSettings} /> : null}
      <ScreenActivity activity={activity} />
      {error ? <ScreenError message={error} onRetry={onRefresh} retrying={refreshing} /> : null}

      <View style={styles.cardStack}>
        <HiddenToolHeader
          icon="view-grid"
          title="Matrix"
          detail="Board look, motion, and runtime"
          onBack={onBackSettings}
        />

        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>MATRIX BOARD</Text>
          <Text style={styles.moduleIntro}>
            Tune the physical board in focused passes. Save after each pass and the board will pull the update shortly.
          </Text>
          <View style={styles.matrixPresetRow}>
            {MATRIX_PRESETS.map((item) => {
              const active = preset === item.id;
              const applying = applyingPreset === item.id;
              const disabled = saving || applyingPreset !== null;
              return (
                <Pressable
                  key={item.id}
                  style={[
                    styles.matrixPresetChip,
                    active && styles.matrixPresetChipActive,
                    disabled && !applying && styles.matrixPresetChipDisabled
                  ]}
                  onPress={() => onApplyPreset(item.id)}
                  disabled={disabled}
                >
                  <View style={styles.matrixPresetTop}>
                    <Text style={[styles.matrixPresetLabel, active && styles.matrixPresetLabelActive]}>{item.label}</Text>
                    {applying ? (
                      <ActivityIndicator size="small" color={palette.blue2} />
                    ) : active ? (
                      <MaterialCommunityIcons name="check-circle" size={14} color={palette.green} />
                    ) : null}
                  </View>
                  <Text style={styles.matrixPresetMeta}>{item.meta}</Text>
                </Pressable>
              );
            })}
          </View>
          <View style={styles.settingsSectionGrid}>
            {([
              ["status", "Status", dirty ? "Draft" : "Saved"],
              ["look", "Look", selectedPalette.meta],
              ["runtime", "Runtime", `${maxRows} rows`],
              ["motion", "Motion", animationMode.replace("_", " ")]
            ] as Array<[MatrixSettingsSection, string, string]>).map(([id, label, meta]) => (
              <OptionChip key={id} active={section === id} label={label} meta={meta} onPress={() => setSection(id)} />
            ))}
          </View>
        </View>

        {section === "status" ? (
        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>BOARD STATUS</Text>
          <Text style={styles.moduleIntro}>
            {matrixEnabled
              ? "Matrix output is enabled on the server."
              : "Matrix output is not selected in server outputs yet. You can still prepare the board style here."}
          </Text>
          <InfoLine label="Last ping" value={matrixLastSeen ? formatRelative(matrixLastSeen) : "Never pinged"} />
          <InfoLine label="Current draft" value={`${selectedPalette.label} · ${animationMode.replace("_", " ")} · ${brightnessPct}%`} />
          <InfoLine label="Sync state" value={dirty ? "Unsaved changes" : "Saved"} />
        </View>
        ) : null}

        {section === "runtime" ? (
        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>RUNTIME</Text>
          <FilterSection title="VIEW">
            <View style={styles.filterRow}>
              <DirectionButton active={view === "departures"} label="DEPARTURES" onPress={() => onViewChange("departures")} />
              <DirectionButton active={view === "arrivals"} label="ARRIVALS" onPress={() => onViewChange("arrivals")} />
            </View>
          </FilterSection>

          <FilterSection title="ROWS">
            <View style={styles.filterWrap}>
              {MATRIX_ROWS.map((item) => (
                <OptionChip
                  key={item}
                  active={maxRows === item}
                  label={`${item}`}
                  meta="rows"
                  onPress={() => onRowsChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <FilterSection title="BRIGHTNESS">
            <View style={styles.filterWrap}>
              {MATRIX_BRIGHTNESS.map((item) => (
                <OptionChip
                  key={item}
                  active={brightness === item}
                  label={`${Math.round(item * 100)}%`}
                  meta="output"
                  onPress={() => onBrightnessChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <FilterSection title="REFRESH">
            <View style={styles.filterWrap}>
              {MATRIX_REFRESH_SECONDS.map((item) => (
                <OptionChip
                  key={item}
                  active={refreshSeconds === item}
                  label={item >= 60 ? `${Math.round(item / 60)}m` : `${item}s`}
                  meta="poll"
                  onPress={() => onRefreshSecondsChange(item)}
                />
              ))}
            </View>
          </FilterSection>
        </View>
        ) : null}

        {section === "look" ? (
        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>BOARD STYLE</Text>
          <Text style={styles.moduleIntro}>
            Pick the LED color language. This follows the cleaner web kiosk palette set, not the phone theme.
          </Text>
          <FilterSection title="BOARD STYLE">
            <View style={styles.filterWrap}>
              {MATRIX_PALETTE_OPTIONS.map((item) => (
                <Pressable
                  key={item.id}
                  onPress={() => onMatrixPaletteChange(item.id)}
                  style={[styles.paletteChip, matrixPalette === item.id && styles.optionChipActive]}
                >
                  <Text style={[styles.optionChipLabel, matrixPalette === item.id && styles.optionChipLabelActive]}>{item.label}</Text>
                  <Text style={[styles.optionChipMeta, matrixPalette === item.id && styles.optionChipMetaActive]}>{item.meta}</Text>
                  <View style={styles.paletteDots}>
                    {[item.colors.green, item.colors.white, item.colors.cyan, item.colors.amber, item.colors.red].map((color) => (
                      <View key={`${item.id}-${color}`} style={[styles.paletteDot, { backgroundColor: color }]} />
                    ))}
                  </View>
                </Pressable>
              ))}
            </View>
          </FilterSection>

          <View style={[styles.matrixToolShell, { marginHorizontal: 0, marginTop: 12, backgroundColor: matrixColors.off }]}>
            <View style={styles.matrixToolBezel}>
              <View style={styles.matrixToolHeader}>
                <Text style={[styles.matrixToolTitle, { color: matrixColors.green }]}>LIVE PREVIEW</Text>
                <Text style={[styles.matrixToolMeta, { color: matrixColors.dim }]}>ON BOARD</Text>
              </View>

              <View
                style={[
                  styles.matrixPixelBoard,
                  {
                    opacity: brightnessAlpha,
                    borderColor: hexToRgba(matrixColors.green, 0.18),
                    backgroundColor: matrixColors.off
                  }
                ]}
              >
                <Text style={[styles.matrixToolAirport, { color: matrixColors.green }]}>
                  {(rows[0]?.view || view) === "arrivals" ? "ARR" : "DEP"} · {selectedPalette.label.toUpperCase()}
                </Text>
                {lines.slice(0, 4).map((line, index) => (
                  <Text key={`${index}-${line}`} style={[styles.matrixPixelLine, { color: matrixColors.white }]}>
                    {line}
                  </Text>
                ))}
              </View>
            </View>
          </View>
        </View>
        ) : null}

        {section === "motion" ? (
        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>MOTION & PAGES</Text>
          <FilterSection title="MOTION">
            <View style={styles.filterWrap}>
              {MATRIX_ANIMATION_MODES.map((item) => (
                <OptionChip
                  key={item.id}
                  active={animationMode === item.id}
                  label={item.label}
                  meta={item.meta}
                  onPress={() => onAnimationModeChange(item.id)}
                />
              ))}
            </View>
          </FilterSection>

          <FilterSection title="MOTION SPEED">
            <View style={styles.filterWrap}>
              {MATRIX_ANIMATION_SPEEDS.map((item) => (
                <OptionChip
                  key={item}
                  active={animationSpeed === item}
                  label={String(item)}
                  meta={item <= 2 ? "easy" : item >= 5 ? "fast" : "speed"}
                  onPress={() => onAnimationSpeedChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <FilterSection title="ROTATION">
            <View style={styles.filterWrap}>
              {MATRIX_ROTATION_SECONDS.map((item) => (
                <OptionChip
                  key={item}
                  active={pageRotationSeconds === item}
                  label={`${item}s`}
                  meta="pages"
                  onPress={() => onPageRotationChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <FilterSection title="WEATHER & STATUS">
            <View style={styles.filterRow}>
              <DirectionButton active={showWeather} label="WEATHER" onPress={() => onShowWeatherChange(!showWeather)} />
              <DirectionButton active={statusAnimationEnabled} label="STATUS MOTION" onPress={() => onStatusAnimationChange(!statusAnimationEnabled)} />
            </View>
          </FilterSection>
        </View>
        ) : null}

        <MatrixSavePanel
          dirty={dirty}
          saving={saving}
          saveMessage={saveMessage}
          saveTone={saveTone}
          onSave={onSave}
          onReset={onReset}
        />
      </View>
    </ScrollView>
  );
}

function MatrixSavePanel({
  dirty,
  saving,
  saveMessage,
  saveTone,
  onSave,
  onReset
}: {
  dirty: boolean;
  saving: boolean;
  saveMessage: string | null;
  saveTone: FeedbackTone;
  onSave: () => void;
  onReset: () => void;
}) {
  return (
    <View style={styles.settingsCard}>
      <Text style={styles.settingsTitle}>{dirty ? "SAVE DRAFT" : "BOARD SAVED"}</Text>
      <Text style={styles.moduleIntro}>
        Only saved settings are sent to the physical board.
      </Text>
      <View style={styles.matrixActionRow}>
        <Pressable
          style={[styles.matrixActionButton, styles.matrixActionSecondary]}
          onPress={onReset}
          disabled={saving}
        >
          <Text style={styles.matrixActionSecondaryText}>RESET</Text>
        </Pressable>
        <Pressable
          style={[styles.matrixActionButton, styles.matrixActionPrimary, saving && styles.configApplyBtnBusy]}
          onPress={onSave}
          disabled={saving}
        >
          {saving ? <ActivityIndicator size="small" color={blueButtonInk()} /> : <Text style={styles.matrixActionPrimaryText}>SAVE TO SERVER</Text>}
        </Pressable>
      </View>

      {saveMessage ? (
        <Text style={[
          styles.feedbackMessage,
          saveTone === "ok" ? styles.feedbackMessageOk : styles.feedbackMessageError
        ]}>
          {saveMessage}
        </Text>
      ) : null}
    </View>
  );
}

function DirectionButton({ active, label, onPress }: { active: boolean; label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.dirButton, active && styles.dirButtonActive]}>
      <Text style={[styles.dirButtonText, active && styles.dirButtonTextActive]}>{label}</Text>
    </Pressable>
  );
}

function FilterSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <View style={styles.filterSection}>
      <Text style={styles.filterLabel}>{title}</Text>
      {children}
    </View>
  );
}

function OptionChip({
  active,
  label,
  meta,
  onPress
}: {
  active: boolean;
  label: string;
  meta: string;
  onPress: () => void;
}) {
  return (
    <Pressable onPress={onPress} style={[styles.optionChip, active && styles.optionChipActive]}>
      <Text style={[styles.optionChipLabel, active && styles.optionChipLabelActive]}>{label}</Text>
      <Text style={[styles.optionChipMeta, active && styles.optionChipMetaActive]}>{meta}</Text>
    </Pressable>
  );
}

function FidsRowView({
  row,
  index,
  compact,
  cycleTick,
  isPinned,
  onOpenDetail,
  onOpenActions
}: {
  row: FidsRow;
  index: number;
  compact: boolean;
  cycleTick: number;
  isPinned: boolean;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
}) {
  const delayTagStyle =
    row.delay_kind === "early" ? styles.fidsDelayTagEarly
    : row.delay_kind === "warn" ? styles.fidsDelayTagWarn
    : row.delay_kind === "bad" ? styles.fidsDelayTagBad
    : null;
  const gateLabel = row.terminal_gate_display || row.gate_display || row.gate;
  const airlineFrames = airlineInfoFrames(row);
  const detailFrames = rowDetailFrames(row, gateLabel);
  const routePrimary = cleanInfoValue(row.route_primary) || routeName(row.route_display);
  const routeSecondary = cleanInfoValue(row.route_code) || cleanInfoValue(row.route_caption) || routeMeta(row);
  const rowOffset = index % 3;

  return (
    <Pressable
      style={[styles.fidsRow, isPinned && styles.fidsRowPinned]}
      delayLongPress={360}
      onLongPress={() => onOpenActions(row)}
      onPress={() => onOpenDetail(row.callsign)}
    >
      <View style={styles.fidsRowMain}>
        <View style={[styles.fidsTimeCell, styles.fidsColTime]}>
          <Text style={styles.fidsTime}>{row.time_primary || row.display_time || "--:--"}</Text>
          {row.time_delta_label && delayTagStyle ? (
            <Text style={[styles.fidsDelayTag, delayTagStyle]}>{row.time_delta_label}</Text>
          ) : null}
        </View>
        <View style={[styles.fidsFlightWrap, styles.fidsColFlight]}>
          <View style={styles.fidsFlightTopRow}>
            <Text style={styles.fidsFlight} numberOfLines={1}>{row.flight_display || row.callsign || "-"}</Text>
            {isPinned ? <MaterialCommunityIcons name="pin" size={11} color={palette.amber} /> : null}
          </View>
          {airlineFrames.length ? (
            <RotatingInfoLine
              frames={airlineFrames}
              cycleTick={cycleTick}
              offset={rowOffset}
              showLabel={false}
              valueStyle={styles.fidsAirlineLine}
              labelStyle={styles.fidsAirlineLineLabel}
            />
          ) : null}
        </View>
        <View style={[styles.fidsDest, styles.fidsColRoute]}>
          <Text style={styles.fidsDestName} numberOfLines={1}>{routePrimary}</Text>
          <Text style={styles.fidsDestCode} numberOfLines={1}>{routeSecondary}</Text>
        </View>
        <View style={[styles.fidsColStatus, compact && styles.fidsColStatusCompact]}>
          <StatusBadge status={row.status_display} statusClass={row.status_class} compact />
        </View>
        {!compact ? (
          <>
            <Text style={[styles.fidsAircraft, styles.fidsColAircraft]} numberOfLines={1}>{row.aircraft_type || "-"}</Text>
            <View style={styles.fidsColGate}>
              {gateLabel ? (
                <Text style={styles.fidsGateVal} numberOfLines={1}>{gateLabel}</Text>
              ) : (
                <Text style={styles.fidsGateEmpty}>-</Text>
              )}
            </View>
          </>
        ) : null}
      </View>
      {compact && detailFrames.length ? (
        <RotatingInfoLine
          frames={detailFrames}
          cycleTick={cycleTick}
          offset={rowOffset + 1}
          containerStyle={styles.fidsInfoRail}
          labelStyle={styles.fidsInfoLabel}
          valueStyle={styles.fidsInfoValue}
        />
      ) : null}
    </Pressable>
  );
}

function RotatingInfoLine({
  frames,
  cycleTick,
  offset,
  containerStyle,
  labelStyle,
  valueStyle,
  showLabel = true
}: {
  frames: RowInfoFrame[];
  cycleTick: number;
  offset: number;
  containerStyle?: any;
  labelStyle?: any;
  valueStyle?: any;
  showLabel?: boolean;
}) {
  const opacity = useRef(new Animated.Value(1)).current;
  const frame = frames.length ? frames[Math.abs(cycleTick + offset) % frames.length] : null;
  const frameKey = frame ? `${frame.label}:${frame.value}` : "empty";

  useEffect(() => {
    opacity.setValue(0);
    Animated.timing(opacity, { toValue: 1, duration: 240, useNativeDriver: true }).start();
  }, [frameKey, opacity]);

  if (!frame) return null;

  const lift = opacity.interpolate({ inputRange: [0, 1], outputRange: [4, 0] });
  const toneStyle =
    frame.tone === "warn"
      ? styles.fidsInfoValueWarn
      : frame.tone === "accent"
        ? styles.fidsInfoValueAccent
        : null;

  return (
    <Animated.View style={[styles.fidsInfoLine, containerStyle, { opacity, transform: [{ translateY: lift }] }]}>
      {showLabel ? <Text style={[styles.fidsInfoLabel, labelStyle]} numberOfLines={1}>{frame.label}</Text> : null}
      <Text style={[styles.fidsInfoValue, toneStyle, valueStyle]} numberOfLines={1}>{frame.value}</Text>
    </Animated.View>
  );
}

function FullscreenFidsRow({
  row,
  index,
  compact,
  cycleTick,
  rowHeight,
  isPinned
}: {
  row: FidsRow;
  index: number;
  compact: boolean;
  cycleTick: number;
  rowHeight: number;
  isPinned: boolean;
}) {
  const gateLabel = row.terminal_gate_display || row.gate_display || row.gate;
  const airlineFrames = airlineInfoFrames(row);
  const detailFrames = rowDetailFrames(row, gateLabel);
  const routePrimary = cleanInfoValue(row.route_primary) || routeName(row.route_display);
  const routeSecondary = cleanInfoValue(row.route_code) || cleanInfoValue(row.route_caption) || routeMeta(row);
  const rowOffset = index % 3;

  return (
    <View style={[styles.fullscreenFidsRow, compact && styles.fullscreenFidsRowCompact, isPinned && styles.fullscreenFidsRowPinned, { minHeight: rowHeight }]}>
      <Text style={[styles.fullscreenFidsTime, styles.fullscreenFidsTimeColumn, compact && styles.fullscreenFidsTimeColumnCompact]}>{row.time_primary || row.display_time || "--:--"}</Text>
      <View style={[styles.fullscreenFidsFlightCell, styles.fullscreenFidsFlightColumn, compact && styles.fullscreenFidsFlightColumnCompact]}>
        <Text style={styles.fullscreenFidsFlight} numberOfLines={1}>{row.flight_display || row.callsign || "-"}</Text>
        {airlineFrames.length ? (
          <RotatingInfoLine
            frames={airlineFrames}
            cycleTick={cycleTick}
            offset={rowOffset}
            showLabel={false}
            valueStyle={styles.fullscreenFidsAirline}
          />
        ) : (
          <Text style={styles.fullscreenFidsAirline} numberOfLines={1}>{row.callsign || "LOCAL FLIGHT"}</Text>
        )}
      </View>
      <View style={[styles.fullscreenFidsRouteCell, styles.fullscreenFidsRouteColumn]}>
        <Text style={styles.fullscreenFidsRouteName} numberOfLines={1}>{routePrimary}</Text>
        <Text style={styles.fullscreenFidsRouteMeta} numberOfLines={1}>{routeSecondary}</Text>
      </View>
      <View style={[styles.fullscreenFidsStatusCell, compact && styles.fullscreenFidsStatusColumnCompact]}>
        <StatusBadge status={row.status_display} statusClass={row.status_class} />
      </View>
      {compact ? (
        <View style={styles.fullscreenFidsInfoColumn}>
          {detailFrames.length ? (
            <RotatingInfoLine
              frames={detailFrames}
              cycleTick={cycleTick}
              offset={rowOffset + 1}
              containerStyle={styles.fullscreenFidsInfoMini}
              labelStyle={styles.fullscreenFidsInfoLabel}
              valueStyle={styles.fullscreenFidsInfoValue}
            />
          ) : (
            <Text style={styles.fullscreenFidsInfoValue} numberOfLines={1}>-</Text>
          )}
        </View>
      ) : (
        <>
          <Text style={[styles.fullscreenFidsAircraft, styles.fullscreenFidsAircraftColumn]} numberOfLines={1}>
            {row.aircraft_type || "-"}
          </Text>
          <Text style={[styles.fullscreenFidsGate, styles.fullscreenFidsGateColumn]} numberOfLines={1}>
            {gateLabel || "-"}
          </Text>
        </>
      )}
    </View>
  );
}

function HistoryRow({ row, onOpenDetail }: { row: HistoryFlightRow; onOpenDetail: (callsign: string) => void }) {
  return (
    <Pressable style={styles.historyRow} onPress={() => onOpenDetail(row.callsign)}>
      <View style={styles.historyTimeBox}>
        <Text style={styles.historyTime}>{formatClock(row.snapshot_ts)}</Text>
        <Text style={styles.historyDate}>{formatClock(row.sched_time)}</Text>
      </View>

      <View style={styles.historyMain}>
        <Text style={styles.historyFlight}>{row.flight_number || row.callsign || "-"}</Text>
        <Text style={styles.historyRoute} numberOfLines={1}>{historyRouteLabel(row)}</Text>
        <Text style={styles.historyMeta} numberOfLines={1}>
          {row.aircraft_type || "Aircraft pending"} {row.gate ? `- Gate ${row.gate}` : ""}
          {row.delay_minutes ? ` - ${row.delay_minutes}m delay` : ""}
        </Text>
      </View>

      <View style={styles.historyTrail}>
        <Text style={styles.historyDir}>{row.direction}</Text>
        <StatusBadge status={row.status} statusClass={row.status} compact />
      </View>
    </Pressable>
  );
}

function RadarBlipRow({ blip, onOpenDetail }: { blip: RadarBlip; onOpenDetail: (callsign: string) => void }) {
  return (
    <Pressable style={styles.historyRow} onPress={() => onOpenDetail(blip.callsign)}>
      <View style={styles.historyTimeBox}>
        <Text style={styles.historyTime}>{blip.callsign || "TRACK"}</Text>
        <Text style={styles.historyDate}>{blip.flight_number || "LIVE"}</Text>
      </View>

      <View style={styles.historyMain}>
        <Text style={styles.historyFlight}>{blip.status || "Tracked target"}</Text>
        <Text style={styles.historyRoute} numberOfLines={1}>
          {formatAltitudeFeet(blip.altitude_m)} - {formatSpeedKnots(blip.speed_ms)}
        </Text>
        <Text style={styles.historyMeta} numberOfLines={1}>
          {formatHeading(blip.heading)} {blip.on_ground ? "- on ground" : ""}
        </Text>
      </View>

      <View style={styles.historyTrail}>
        <Text style={styles.historyDir}>{blip.enriched ? "LIVE" : "RAW"}</Text>
        <View style={[styles.radarDotLarge, { backgroundColor: radarTone(blip) }]} />
      </View>
    </Pressable>
  );
}

function RadarScope({
  data,
  groundData,
  groundError,
  radiusNm,
  onRadiusChange,
  compact = false,
  onOpenDetail
}: {
  data: RadarResponse | null;
  groundData: RadarMapResponse | null;
  groundError: string | null;
  radiusNm: RadarRadius;
  onRadiusChange: (value: RadarRadius) => void;
  compact?: boolean;
  onOpenDetail: (callsign: string) => void;
}) {
  const [scopeSize, setScopeSize] = useState(280);
  const pinchRef = useRef<{ distance: number; index: number } | null>(null);
  const groundFeatureCount = radarGroundFeatureCount(groundData);
  const groundUnavailable = radarGroundUnavailable(groundData, groundError);
  const groundStatus = groundFeatureCount
    ? `${groundFeatureCount} ground drawings`
    : groundUnavailable
      ? "Ground layer unavailable"
      : "Ground layer waiting";
  const projected = (data?.blips || [])
    .map((blip) => data ? projectBlip(blip, data.center, data.radius_nm, scopeSize) : null)
    .filter((item): item is ProjectedBlip => Boolean(item))
    .sort((a, b) => a.distanceNm - b.distanceNm);

  const setMeasuredSize = useCallback((width: number) => {
    const next = Math.max(220, Math.min(width - 28, compact ? 320 : 440));
    if (Math.abs(next - scopeSize) > 1) {
      setScopeSize(next);
    }
  }, [compact, scopeSize]);

  const handlePinchStart = useCallback((touches: Array<{ pageX: number; pageY: number }>) => {
    if (touches.length < 2) {
      pinchRef.current = null;
      return;
    }
    const [first, second] = touches;
    if (!first || !second) return;
    const distance = Math.hypot(second.pageX - first.pageX, second.pageY - first.pageY);
    pinchRef.current = {
      distance,
      index: RADAR_RADII.indexOf(radiusNm)
    };
  }, [radiusNm]);

  const handlePinchMove = useCallback((touches: Array<{ pageX: number; pageY: number }>) => {
    if (touches.length < 2) {
      pinchRef.current = null;
      return;
    }
    const state = pinchRef.current;
    const [first, second] = touches;
    if (!state || !first || !second) {
      handlePinchStart(touches);
      return;
    }
    const distance = Math.hypot(second.pageX - first.pageX, second.pageY - first.pageY);
    const ratio = distance / Math.max(1, state.distance);
    if (ratio > 1.14 && state.index < RADAR_RADII.length - 1) {
      const nextIndex = state.index + 1;
      onRadiusChange(RADAR_RADII[nextIndex]!);
      pinchRef.current = { distance, index: nextIndex };
    } else if (ratio < 0.88 && state.index > 0) {
      const nextIndex = state.index - 1;
      onRadiusChange(RADAR_RADII[nextIndex]!);
      pinchRef.current = { distance, index: nextIndex };
    }
  }, [handlePinchStart, onRadiusChange]);

  const radiusLabel = `${radiusNm} NM`;

  return (
    <View
      style={styles.scopeCard}
      onLayout={(event) => setMeasuredSize(event.nativeEvent.layout.width)}
    >
      <Text style={styles.scopeTitle}>RADAR SCOPE</Text>
      <View
        style={[styles.scopeFrame, { width: scopeSize, height: scopeSize }]}
        onTouchStart={(event) => handlePinchStart(event.nativeEvent.touches as Array<{ pageX: number; pageY: number }>)}
        onTouchMove={(event) => handlePinchMove(event.nativeEvent.touches as Array<{ pageX: number; pageY: number }>)}
        onTouchEnd={() => {
          pinchRef.current = null;
        }}
        onTouchCancel={() => {
          pinchRef.current = null;
        }}
      >
        <RadarGroundLayer
          groundData={groundData}
          center={data?.center || groundData?.center || null}
          radiusNm={radiusNm}
          scopeSize={scopeSize}
        />
        <View style={styles.scopeRingOuter} />
        <View style={styles.scopeRingMid} />
        <View style={styles.scopeRingInner} />
        <View style={styles.scopeCrossVertical} />
        <View style={styles.scopeCrossHorizontal} />
        <View style={styles.scopeCenterDot} />

        {projected.map((item, index) => (
          <Pressable
            key={`scope-${radarBlipKey(item.blip, index)}`}
            style={[styles.scopeDotWrap, { left: item.left, top: item.top }]}
            onPress={() => onOpenDetail(item.blip.callsign)}
          >
            <View style={[styles.scopeDot, { backgroundColor: radarTone(item.blip) }]} />
            {index < 10 ? (
              <Text style={styles.scopeLabel} numberOfLines={1}>
                {item.blip.callsign}
              </Text>
            ) : null}
          </Pressable>
        ))}

        {!data || projected.length === 0 ? (
          <View style={styles.scopeEmpty}>
            <Text style={styles.scopeEmptyText}>No targets in range</Text>
          </View>
        ) : null}
      </View>
      <View style={styles.scopeFooter}>
        <Text style={styles.scopeHint}>Pinch to zoom the scope.</Text>
        <Text style={[styles.scopeGroundStatus, groundUnavailable && !groundFeatureCount && styles.scopeGroundStatusWarn]}>
          {groundStatus}
        </Text>
        <View style={styles.scopeChipRow}>
          {RADAR_RADII.map((item) => (
            <Pressable
              key={item}
              onPress={() => onRadiusChange(item)}
              style={[styles.scopeChip, radiusNm === item && styles.scopeChipActive]}
            >
              <Text style={[styles.scopeChipText, radiusNm === item && styles.scopeChipTextActive]}>
                {item === radiusNm ? radiusLabel : `${item} NM`}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>
    </View>
  );
}

function RadarGroundLayer({
  groundData,
  center,
  radiusNm,
  scopeSize
}: {
  groundData: RadarMapResponse | null;
  center: RadarResponse["center"] | null;
  radiusNm: RadarRadius;
  scopeSize: number;
}) {
  if (!groundData || !center) {
    return null;
  }

  const surfaceFeatures = radarDrawableFeatures(groundData.surface_features);
  const runwayFeatures = radarDrawableFeatures(groundData.runways);
  if (!surfaceFeatures.length && !runwayFeatures.length) {
    return null;
  }

  return (
    <Svg
      pointerEvents="none"
      width={scopeSize}
      height={scopeSize}
      viewBox={`0 0 ${scopeSize} ${scopeSize}`}
      style={styles.scopeGroundSvg}
    >
      <Defs>
        <ClipPath id={RADAR_GROUND_CLIP_ID}>
          <Circle cx={scopeSize / 2} cy={scopeSize / 2} r={scopeSize * 0.44} />
        </ClipPath>
      </Defs>
      <G clipPath={`url(#${RADAR_GROUND_CLIP_ID})`}>
        {surfaceFeatures.map((feature, index) => (
          <RadarGroundFeature
            key={radarGroundFeatureKey(feature, index, "surface")}
            feature={feature}
            center={center}
            radiusNm={radiusNm}
            scopeSize={scopeSize}
            layer="surface"
          />
        ))}
        {runwayFeatures.map((feature, index) => (
          <RadarGroundFeature
            key={radarGroundFeatureKey(feature, index, "runway")}
            feature={feature}
            center={center}
            radiusNm={radiusNm}
            scopeSize={scopeSize}
            layer="runway"
          />
        ))}
        {radiusNm <= 5 ? runwayFeatures.map((feature, index) => (
          <RadarRunwayLabel
            key={`${radarGroundFeatureKey(feature, index, "label")}-label`}
            feature={feature}
            center={center}
            radiusNm={radiusNm}
            scopeSize={scopeSize}
          />
        )) : null}
      </G>
    </Svg>
  );
}

function RadarGroundFeature({
  feature,
  center,
  radiusNm,
  scopeSize,
  layer
}: {
  feature: RadarMapFeature;
  center: RadarResponse["center"];
  radiusNm: RadarRadius;
  scopeSize: number;
  layer: "surface" | "runway";
}) {
  const projected = projectRadarFeature(feature, center, radiusNm, scopeSize);
  if (projected.length < 2) {
    return null;
  }

  const points = projected.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const paint = radarGroundPaint(feature, layer, radiusNm);
  const isPolygon = Boolean(feature.closed && projected.length >= 3 && layer !== "runway");

  if (isPolygon) {
    return (
      <Polygon
        points={points}
        fill={paint.fill}
        stroke={paint.stroke}
        strokeWidth={paint.strokeWidth}
        strokeLinejoin="round"
      />
    );
  }

  return (
    <Polyline
      points={points}
      fill="none"
      stroke={paint.stroke}
      strokeWidth={paint.strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
}

function RadarRunwayLabel({
  feature,
  center,
  radiusNm,
  scopeSize
}: {
  feature: RadarMapFeature;
  center: RadarResponse["center"];
  radiusNm: RadarRadius;
  scopeSize: number;
}) {
  const label = String(feature.label || "").trim();
  if (!label) {
    return null;
  }
  const projected = projectRadarFeature(feature, center, radiusNm, scopeSize);
  if (projected.length < 2) {
    return null;
  }
  const midpoint = radarProjectedMidpoint(projected);
  if (!midpoint || midpoint.distanceNm > radiusNm * 1.05) {
    return null;
  }

  return (
    <SvgText
      x={midpoint.x}
      y={midpoint.y - 5}
      fill={hexToRgba(palette.text, 0.68)}
      fontSize={8}
      fontWeight="700"
      textAnchor="middle"
    >
      {label}
    </SvgText>
  );
}

function radarDrawableFeatures(features: RadarMapFeature[] | undefined): RadarMapFeature[] {
  return (features || []).filter((feature) => {
    const points = feature.points || [];
    return Array.isArray(points) && points.length >= 2;
  });
}

function radarGroundFeatureCount(groundData: RadarMapResponse | null): number {
  if (!groundData) {
    return 0;
  }
  return radarDrawableFeatures(groundData.runways).length + radarDrawableFeatures(groundData.surface_features).length;
}

function radarGroundUnavailable(groundData: RadarMapResponse | null, groundError: string | null): boolean {
  if (groundError) {
    return true;
  }
  const surfaceState = String(groundData?.sources?.surface_cache_state || "").trim().toLowerCase();
  const surfaceSource = String(groundData?.sources?.surface || "").trim().toLowerCase();
  return surfaceState === "disabled" || surfaceState === "error" || surfaceSource === "none";
}

function radarGroundFeatureKey(feature: RadarMapFeature, index: number, prefix: string): string {
  return [
    prefix,
    feature.kind,
    feature.id,
    feature.label,
    index
  ].filter(Boolean).join("-");
}

function projectRadarFeature(
  feature: RadarMapFeature,
  center: RadarResponse["center"],
  radiusNm: RadarRadius,
  scopeSize: number
): ProjectedRadarPoint[] {
  return (feature.points || [])
    .map((point) => {
      const lat = Number(point[0]);
      const lon = Number(point[1]);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
        return null;
      }
      return projectLatLonToScope(lat, lon, center, radiusNm, scopeSize);
    })
    .filter((point): point is ProjectedRadarPoint => Boolean(point));
}

function radarProjectedMidpoint(points: ProjectedRadarPoint[]): ProjectedRadarPoint | null {
  if (!points.length) {
    return null;
  }
  const index = Math.floor(points.length / 2);
  return points[index] || null;
}

function radarGroundPaint(
  feature: RadarMapFeature,
  layer: "surface" | "runway",
  radiusNm: RadarRadius
): { fill: string; stroke: string; strokeWidth: number } {
  const kind = String(feature.kind || "").toLowerCase();
  if (layer === "runway") {
    return {
      fill: "none",
      stroke: hexToRgba(palette.amber, 0.78),
      strokeWidth: radiusNm <= 5 ? 4.4 : 2.8
    };
  }
  if (kind === "taxiway") {
    return {
      fill: "none",
      stroke: hexToRgba(palette.blue2, 0.46),
      strokeWidth: radiusNm <= 5 ? 1.8 : 1.2
    };
  }
  if (kind === "apron") {
    return {
      fill: hexToRgba(palette.blue, 0.11),
      stroke: hexToRgba(palette.blue2, 0.22),
      strokeWidth: 1
    };
  }
  if (kind === "terminal" || kind === "building") {
    return {
      fill: hexToRgba(palette.amber, 0.12),
      stroke: hexToRgba(palette.amber, 0.28),
      strokeWidth: 1
    };
  }
  if (kind === "boundary") {
    return {
      fill: hexToRgba(palette.blue, 0.035),
      stroke: hexToRgba(palette.blue2, 0.18),
      strokeWidth: 0.9
    };
  }
  return {
    fill: hexToRgba(palette.blue, 0.07),
    stroke: hexToRgba(palette.blue2, 0.26),
    strokeWidth: 1
  };
}

function radarTone(blip: RadarBlip): string {
  if (blip.on_ground) return palette.amber;
  if (blip.enriched) return palette.green;
  return palette.blue2;
}

function airportMetric(code?: string | null, name?: string | null): string {
  if (code && name) return `${code} · ${name}`;
  return code || name || "-";
}

function formatCoordinate(value: number | null | undefined, positive: string, negative: string): string {
  if (value == null || Number.isNaN(value)) return "-";
  const suffix = value >= 0 ? positive : negative;
  return `${Math.abs(value).toFixed(4)}°${suffix}`;
}

function formatVerticalRate(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-";
  const feetPerMinute = Math.round(value * 196.8504);
  return `${feetPerMinute} ft/min`;
}

function formatGroundState(value: boolean | null | undefined): string {
  if (typeof value !== "boolean") return "-";
  return value ? "YES" : "NO";
}

function isVirtualFlightDetail(detail: FlightDetail | null): boolean {
  const value = `${detail?.detail_mode || ""} ${detail?.source || ""} ${detail?.data_sources?.schedule || ""}`.toLowerCase();
  return value.includes("virtual") || value.includes("vatsim");
}

function sourceMetric(value?: string | null): string {
  return value ? value.replace(/_/g, " ").toUpperCase() : "-";
}

function formatAgeSeconds(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "-";
  if (value < 90) return `${Math.max(0, Math.round(value))}s ago`;
  const minutes = Math.round(value / 60);
  if (minutes < 90) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}

function formatEnrouteMinutes(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "-";
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return hours ? `${hours}h ${String(minutes).padStart(2, "0")}m` : `${minutes}m`;
}

function DetailSkeleton() {
  const opacity = useRef(new Animated.Value(0.5)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.85, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.4, duration: 700, useNativeDriver: true })
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);

  return (
    <View style={styles.sheetSkeleton}>
      <Animated.View style={[styles.sheetSkeletonBar, { width: "55%", opacity }]} />
      <Animated.View style={[styles.sheetSkeletonBar, { width: "38%", height: 12, marginTop: 16, opacity }]} />
      {[0, 1, 2, 3].map((i) => (
        <View key={i} style={styles.sheetMetricRow}>
          <Animated.View style={[styles.sheetSkeletonCard, { opacity }]} />
          <Animated.View style={[styles.sheetSkeletonCard, { opacity }]} />
        </View>
      ))}
    </View>
  );
}

function delayBadgeStyleFor(minutes: number | null | undefined) {
  if (minutes == null) return null;
  if (minutes <= -1) return styles.sheetDelayBadgeEarly;
  if (minutes >= 15) return styles.sheetDelayBadgeBad;
  if (minutes >= 5) return styles.sheetDelayBadgeWarn;
  return styles.sheetDelayBadgeOnTime;
}

export function FlightDetailSheet({
  visible,
  callsign,
  detail,
  history,
  loading,
  onClose,
  onRefresh
}: {
  visible: boolean;
  callsign: string;
  detail: FlightDetail | null;
  history: Array<{ date: string; status?: string | null; delay_minutes?: number | null; gate?: string | null }>;
  loading: boolean;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const virtualDetail = isVirtualFlightDetail(detail);
  const plan = detail?.flight_plan || {};
  const sources = detail?.data_sources || {};
  const altitudeMeters = detail?.position?.altitude_geo_m ?? detail?.position?.altitude_baro_m ?? detail?.position?.altitude_m;
  const sourceFreshness = sources.snapshot_age_seconds != null
    ? formatAgeSeconds(sources.snapshot_age_seconds)
    : formatRelative(sources.snapshot_generated_at);
  const positionFreshness = sources.position_age_seconds != null
    ? formatAgeSeconds(sources.position_age_seconds)
    : formatRelative(detail?.position?.last_contact);
  const delayBadgeStyle = delayBadgeStyleFor(detail?.delay_minutes);
  const delayBadgeText = detail?.delay_minutes != null
    ? (detail.delay_minutes > 0 ? `+${detail.delay_minutes}m` : `${detail.delay_minutes}m`)
    : null;
  const gateBadgeText = !virtualDetail && (detail?.gate || detail?.terminal)
    ? [detail?.terminal, detail?.gate].filter(Boolean).join(" · ")
    : null;

  return (
    <Modal visible={visible} animationType="slide" transparent statusBarTranslucent>
      <View style={styles.sheetBackdrop}>
        <Pressable style={styles.sheetBackdropPress} onPress={onClose} />
        <View style={styles.sheetCard}>
          <View style={styles.sheetHandle} />

          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>FLIGHT DETAIL</Text>
              <Text style={styles.sheetTitle}>{detail?.flight_number || callsign || "TRACKED FLIGHT"}</Text>
              <Text style={styles.sheetSubtitle}>{detailRouteLabel(detail, callsign)}</Text>
            </View>

            <View style={styles.sheetActions}>
              <Pressable style={styles.sheetAction} onPress={onRefresh}>
                <Text style={styles.sheetActionText}>REFRESH</Text>
              </Pressable>
              <Pressable style={styles.sheetAction} onPress={onClose}>
                <Text style={styles.sheetActionText}>CLOSE</Text>
              </Pressable>
            </View>
          </View>

          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}>
            {loading && !detail ? <DetailSkeleton /> : null}

            {!loading && detail ? (
              <>
                <View style={styles.sheetSummary}>
                  <StatusBadge status={detail.status || "Tracked"} statusClass={detail.status || ""} />
                  {delayBadgeText && delayBadgeStyle ? (
                    <Text style={[styles.sheetSummaryBadge, delayBadgeStyle]}>{delayBadgeText}</Text>
                  ) : null}
                  {gateBadgeText ? (
                    <Text style={[styles.sheetSummaryBadge, styles.sheetSummaryGateBadge]}>GATE {gateBadgeText}</Text>
                  ) : null}
                  <Text style={styles.sheetSummaryText}>
                    {virtualDetail
                      ? `VATSIM ${detail.aircraft_type || "aircraft"}`
                      : `${detail.airline || "Unknown carrier"} ${detail.aircraft_type ? `- ${detail.aircraft_type}` : ""}`}
                  </Text>
                </View>

                <SectionTitle label={virtualDetail ? "VIRTUAL FLIGHT" : "ROUTE & DATA"} />
                <View style={styles.sheetMetricRow}>
                  <SheetMetric
                    label="FROM"
                    value={virtualDetail ? (detail.origin_icao || detail.origin_iata || "-") : airportMetric(detail.origin_iata, detail.origin_name)}
                  />
                  <SheetMetric
                    label="TO"
                    value={virtualDetail ? (detail.dest_icao || detail.dest_iata || "-") : airportMetric(detail.dest_iata, detail.dest_name)}
                  />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label={virtualDetail ? "RULES" : "AIRLINE"} value={virtualDetail ? (plan.flight_rules || "-") : (detail.airline_iata || detail.airline || "-")} />
                  <SheetMetric label="CALLSIGN" value={detail.callsign || callsign || "-"} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label={virtualDetail ? "NETWORK" : "SOURCE"} value={sourceMetric(sources.schedule || detail.source)} />
                  <SheetMetric label={virtualDetail ? "TRACK" : "ENRICHED"} value={sourceMetric(sources.enrichment || detail.enriched_by)} />
                </View>

                {virtualDetail ? (
                  <>
                    <SectionTitle label="FILED PLAN" />
                    <View style={styles.sheetMetricRow}>
                      <SheetMetric label="CRUISE" value={plan.cruise_altitude || "-"} />
                      <SheetMetric label="TAS" value={plan.cruise_tas != null ? `${plan.cruise_tas} kt` : "-"} />
                    </View>
                    <View style={styles.sheetMetricRow}>
                      <SheetMetric label="DEP" value={formatDateTime(plan.planned_departure)} />
                      <SheetMetric label="ARR" value={formatDateTime(plan.planned_arrival)} />
                    </View>
                    <View style={styles.sheetMetricRow}>
                      <SheetMetric label="ENROUTE" value={formatEnrouteMinutes(plan.enroute_minutes)} />
                      <SheetMetric label="ALTN" value={plan.alternate_icao || "-"} />
                    </View>
                    <View style={styles.sheetMetricRow}>
                      <SheetMetric label="XPDR" value={plan.assigned_transponder || "-"} />
                      <SheetMetric label="FRESH" value={sourceFreshness} />
                    </View>
                    {plan.route ? (
                      <View style={styles.sheetMetricRow}>
                        <SheetMetric label="ROUTE" value={plan.route} />
                      </View>
                    ) : null}
                  </>
                ) : null}

                <SectionTitle label={virtualDetail ? "TIMES" : "TIMES & GATE"} />
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="SCHEDULED" value={formatDateTime(detail.sched_time)} />
                  <SheetMetric label="ESTIMATED" value={formatDateTime(detail.est_time)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="ACTUAL" value={formatDateTime(detail.actual_time)} />
                  <SheetMetric label="DELAY" value={detail.delay_minutes != null ? `${detail.delay_minutes}m` : "-"} />
                </View>
                {!virtualDetail ? (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="GATE" value={detail.gate || "-"} />
                    <SheetMetric label="TERMINAL" value={detail.terminal || "-"} />
                  </View>
                ) : null}
                {!virtualDetail ? (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="REG" value={detail.aircraft_registration || "-"} />
                    <SheetMetric label="FRESH" value={sourceFreshness} />
                  </View>
                ) : null}

                <SectionTitle label={virtualDetail ? "PILOT TRACK" : "LIVE TRACK"} />
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="ALTITUDE" value={formatAltitudeFeet(altitudeMeters)} />
                  <SheetMetric label="SPEED" value={formatSpeedKnots(detail.position?.speed_ms)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="HEADING" value={formatHeading(detail.position?.heading)} />
                  <SheetMetric label="GROUND" value={formatGroundState(detail.position?.on_ground)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="LAT" value={formatCoordinate(detail.position?.lat, "N", "S")} />
                  <SheetMetric label="LON" value={formatCoordinate(detail.position?.lon, "E", "W")} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label={virtualDetail ? "XPDR" : "VERT RATE"} value={virtualDetail ? (plan.assigned_transponder || detail.position?.squawk || "-") : formatVerticalRate(detail.position?.vertical_rate)} />
                  <SheetMetric label="CONTACT" value={positionFreshness} />
                </View>
                {!virtualDetail ? (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="ICAO24" value={detail.position?.icao24 || "-"} />
                    <SheetMetric label="SQUAWK" value={detail.position?.squawk || "-"} />
                  </View>
                ) : null}
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="DIRECTION" value={detail.direction ? detail.direction.toUpperCase() : "-"} />
                  <SheetMetric label="CONFIDENCE" value={sourceMetric(sources.confidence)} />
                </View>

                <SectionTitle label="7-DAY HISTORY" />
                {history.length > 0 ? (
                  history.map((item, index) => (
                    <View key={detailHistoryKey(item, index)} style={styles.sheetHistoryRow}>
                      <Text style={styles.sheetHistoryDate}>{item.date}</Text>
                      <Text style={styles.sheetHistoryStatus}>{item.status || "Tracked"}</Text>
                      <Text style={styles.sheetHistoryMeta}>
                        {item.gate ? `Gate ${item.gate}` : "Gate -"}
                        {item.delay_minutes ? ` - ${item.delay_minutes}m` : ""}
                      </Text>
                    </View>
                  ))
                ) : (
                  <Text style={styles.sheetEmpty}>No recent history for this callsign yet.</Text>
                )}
              </>
            ) : null}

            {!loading && !detail ? (
              <>
                <Text style={styles.sheetEmpty}>
                  This flight is not in the current live snapshot. If it flew recently, its history still appears below.
                </Text>
                <SectionTitle label="7-DAY HISTORY" />
                {history.length > 0 ? (
                  history.map((item, index) => (
                    <View key={detailHistoryKey(item, index)} style={styles.sheetHistoryRow}>
                      <Text style={styles.sheetHistoryDate}>{item.date}</Text>
                      <Text style={styles.sheetHistoryStatus}>{item.status || "Tracked"}</Text>
                      <Text style={styles.sheetHistoryMeta}>
                        {item.gate ? `Gate ${item.gate}` : "Gate -"}
                        {item.delay_minutes ? ` - ${item.delay_minutes}m` : ""}
                      </Text>
                    </View>
                  ))
                ) : (
                  <Text style={styles.sheetEmpty}>No recent history available.</Text>
                )}
              </>
            ) : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

export function FlightActionSheet({
  row,
  visible,
  isPinned,
  onClose,
  onOpenDetail,
  onTogglePin
}: {
  row: FidsRow | null;
  visible: boolean;
  isPinned: boolean;
  onClose: () => void;
  onOpenDetail: (callsign: string) => void;
  onTogglePin: (row: FidsRow) => void;
}) {
  if (!row) return null;

  return (
    <Modal visible={visible} animationType="fade" transparent statusBarTranslucent>
      <View style={styles.sheetBackdrop}>
        <Pressable style={styles.sheetBackdropPress} onPress={onClose} />
        <View style={styles.actionSheetCard}>
          <View style={styles.sheetHandle} />
          <Text style={styles.sheetEyebrow}>FLIGHT ACTIONS</Text>
          <Text style={styles.actionSheetTitle}>{row.flight_display || row.callsign || "Tracked flight"}</Text>
          <Text style={styles.actionSheetSubtitle} numberOfLines={1}>
            {routeName(row.route_display)} - {row.display_time || "--:--"}
          </Text>

          <View style={styles.actionSheetButtons}>
            <Pressable style={styles.actionButton} onPress={() => onTogglePin(row)}>
              <MaterialCommunityIcons
                name={isPinned ? "pin-off" : "pin"}
                size={18}
                color={isPinned ? palette.amber : palette.blue}
              />
              <Text style={styles.actionButtonText}>{isPinned ? "UNPIN FLIGHT" : "PIN TO TOP"}</Text>
            </Pressable>
            <Pressable style={styles.actionButton} onPress={() => onOpenDetail(row.callsign)}>
              <MaterialCommunityIcons name="card-search-outline" size={18} color={palette.blue} />
              <Text style={styles.actionButtonText}>OPEN DETAIL</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function SectionTitle({ label }: { label: string }) {
  return <Text style={styles.sectionTitle}>{label}</Text>;
}

function SheetMetric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.sheetMetric}>
      <Text style={styles.sheetMetricLabel}>{label}</Text>
      <Text style={styles.sheetMetricValue}>{value}</Text>
    </View>
  );
}

function StatusBadge({
  status,
  statusClass,
  compact
}: {
  status: string;
  statusClass: string;
  compact?: boolean;
}) {
  const tone = statusTone(`${status} ${statusClass}`);
  return (
    <View style={[styles.statusBadge, statusBadgeStyle(tone), compact && styles.statusBadgeCompact]}>
      <Text style={[styles.statusBadgeText, statusTextStyle(tone)]} numberOfLines={1}>
        {(status || "SCHED").replace(/\s+/g, " ").slice(0, compact ? 8 : 12)}
      </Text>
    </View>
  );
}

export function AdminScreen({
  snapshot,
  historyStats,
  companionIdentity,
  connected,
  error,
  weatherDisplayMode,
  feedbackTitle,
  feedbackDescription,
  feedbackSending,
  feedbackMessage,
  feedbackTone,
  autoReportMessage,
  onFeedbackTitleChange,
  onFeedbackDescriptionChange,
  onSubmitFeedback,
  onSendAutoReportTest,
  onOpenMatrix,
  onOpenSupport,
  onBackSettings
}: {
  snapshot: DashboardSnapshot;
  historyStats: HistoryStats | null;
  companionIdentity: CompanionIdentity | null;
  connected: boolean;
  error: string | null;
  weatherDisplayMode: MobileWeatherDisplayMode;
  feedbackTitle: string;
  feedbackDescription: string;
  feedbackSending: boolean;
  feedbackMessage: string | null;
  feedbackTone: FeedbackTone;
  autoReportMessage: string | null;
  onFeedbackTitleChange: (value: string) => void;
  onFeedbackDescriptionChange: (value: string) => void;
  onSubmitFeedback: () => void;
  onSendAutoReportTest: () => void;
  onOpenMatrix: () => void;
  onOpenSupport: () => void;
  onBackSettings: () => void;
}) {
  const budget = snapshot.budget?.aviationstack;
  const matrixEnabled = snapshot.config?.display_outputs?.includes("matrix") || false;
  const matrixLastSeen = snapshot.connections?.matrix_last_seen;
  const companionRecord =
    snapshot.connections?.companions?.find((item) => item.companion_id === companionIdentity?.companionId) || null;
  const matrixOnline =
    !!matrixLastSeen && Date.now() - new Date(matrixLastSeen).getTime() < 5 * 60 * 1000;
  const updateValue = snapshot.updates?.update_available
    ? `V${snapshot.updates.latest || "NEW"} READY`
    : `V${snapshot.updates?.current || snapshot.system?.version || APP_VERSION}`;
  const platformPair = platformPairLabel(snapshot.system?.platform, companionIdentity?.mobileOs);
  const weatherMode = weatherModeOption(weatherDisplayMode);
  const adminWeatherSummary = weatherSummaryForMode(snapshot.metar, weatherDisplayMode);
  const adminWeatherChips = weatherChips(snapshot.metar);
  const [section, setSection] = useState<AdminSettingsSection>("health");
  const feedbackContext = [
    `Reporter      ${companionIdentity?.clientName || "Local Flight Companion"}`,
    `Companion ID  ${companionIdentity?.companionId || "UNKNOWN"}`,
    `Companion OS  ${companionIdentity?.mobileOs || "UNKNOWN"}`,
    `Build         ${companionIdentity?.appVersion || APP_VERSION}`,
    `Server ID     ${snapshot.system?.install_id || "UNKNOWN"}`,
    `Platform pair ${platformPair}`,
    `Airport       ${snapshot.config?.airport_iata || "---"}`,
    `Source        ${snapshot.state?.source_name || snapshot.config?.source || "UNKNOWN"}`
  ].join("\n");

  return (
    <View style={styles.cardStack}>
      <HiddenToolHeader
        icon="tools"
        title="Admin"
        detail="Server health, Linear reports, and diagnostics"
        onBack={onBackSettings}
      />

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>ADMIN SECTIONS</Text>
        <Text style={styles.moduleIntro}>
          Check health, device presence, and reports without digging through one long operations page.
        </Text>
        <View style={styles.settingsSectionGrid}>
          {([
            ["health", "Health", connected ? "Online" : "Check"],
            ["devices", "Devices", matrixOnline ? "Matrix" : "Links"],
            ["reports", "Reports", feedbackMessage ? "Sent" : "Linear"],
            ...(__DEV__ ? [["developer", "Dev", "Tests"] as [AdminSettingsSection, string, string]] : [])
          ] as Array<[AdminSettingsSection, string, string]>).map(([id, label, meta]) => (
            <OptionChip key={id} active={section === id} label={label} meta={meta} onPress={() => setSection(id)} />
          ))}
        </View>
      </View>

      {section === "health" ? (
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>SERVER HEALTH</Text>
        <Text style={styles.moduleIntro}>
          Quick operational pulse for the connected Local Flight server.
        </Text>
        <View style={styles.metricRow}>
          <InfoCard label="SERVER" value={connected ? "ONLINE" : "CHECK"} tone={connected ? "green" : "red"} />
          <InfoCard label="VERSION" value={snapshot.system?.version || APP_VERSION} />
          <InfoCard label="UPDATE" value={updateValue} tone={snapshot.updates?.update_available ? "amber" : "blue"} />
        </View>
        <View style={styles.metricRow}>
          <InfoCard label="LAST FETCH" value={formatRelative(snapshot.state?.last_success_utc)} tone="amber" />
          <InfoCard label="API BUDGET" value={budget?.remaining != null ? `${budget.remaining} LEFT` : "UNKNOWN"} />
          <InfoCard label="MEMORY" value={snapshot.system?.memory_mb != null ? `${snapshot.system.memory_mb} MB` : "-"} />
        </View>
        <InfoLine label="Server install" value={snapshot.system?.install_id || "Unknown"} />
        <InfoLine label="Airport" value={snapshot.config?.airport_iata || "---"} />
        <InfoLine label="Source" value={snapshot.state?.source_name || snapshot.config?.source || "Unknown"} />

        {budget ? (
          <>
            <Text style={styles.adminSubTitle}>SCHEDULE ACCESS</Text>
            <InfoLine label="Access mode" value={budget.active_mode || budget.mode || "—"} />
            <InfoLine label="Used this window" value={budget.calls_this_month != null ? String(budget.calls_this_month) : "—"} />
            <InfoLine label="Requests left" value={budget.remaining != null ? String(budget.remaining) : "—"} />
            <InfoLine label="Access window" value={budget.month || "—"} />
            {budget.cost_estimate?.cadence_warning ? (
              <InfoLine label="Note" value={budget.cost_estimate.cadence_warning} />
            ) : null}
            {budget.monthly_limit != null && budget.remaining != null ? (
              <View style={styles.adminBudgetTrack}>
                <View
                  style={{
                    height: 5,
                    borderRadius: 99,
                    backgroundColor: budget.remaining > budget.monthly_limit * 0.3
                      ? palette.green
                      : budget.remaining > budget.monthly_limit * 0.1
                      ? palette.amber
                      : palette.red,
                    width: `${Math.min(Math.round((budget.remaining / budget.monthly_limit) * 100), 100)}%` as unknown as number
                  }}
                />
              </View>
            ) : null}
          </>
        ) : null}

        {snapshot.metar ? (
          <>
            <Text style={styles.adminSubTitle}>AIRPORT WEATHER</Text>
            <View style={styles.adminMetarHero}>
              <View style={styles.adminMetarIcon}>
                <Text style={styles.adminMetarIconText}>
                  {snapshot.metar.flight_category === "VFR" ? "☀" :
                   snapshot.metar.flight_category === "MVFR" ? "⛅" :
                   snapshot.metar.flight_category === "IFR" ? "☁" :
                   snapshot.metar.flight_category === "LIFR" ? "🌫" : "•"}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <View style={styles.adminMetarTitleRow}>
                  <Text style={styles.adminMetarTitle}>{snapshot.metar.flight_category || "UNKNOWN"}</Text>
                  <View style={styles.adminMetarModePill}>
                    <Text style={styles.adminMetarModeText}>{weatherMode.label}</Text>
                  </View>
                </View>
                <Text style={styles.adminMetarSub}>{adminWeatherSummary || "No METAR data"}</Text>
                <View style={styles.adminMetarChipRow}>
                  {adminWeatherChips.slice(0, 5).map((chip, index) => (
                    <View key={`admin-weather-${chip.label}-${chip.value}-${index}`} style={styles.adminMetarChip}>
                      <Text style={styles.adminMetarChipText}>{chip.label} {chip.value}</Text>
                    </View>
                  ))}
                </View>
              </View>
            </View>
            <InfoLine label="Display style" value={`${weatherMode.label} · ${weatherMode.detail}`} />
            <InfoLine label="Wind" value={snapshot.metar.wind || "—"} />
            <InfoLine label="Temperature" value={snapshot.metar.temperature_c != null ? `${snapshot.metar.temperature_c}°C` : "—"} />
            <InfoLine label="QNH" value={snapshot.metar.qnh_hpa != null ? `${snapshot.metar.qnh_hpa} hPa` : "—"} />
            {snapshot.metar.raw_text && weatherDisplayMode !== "vatsim" ? (
              <InfoLine label="Raw METAR" value={snapshot.metar.raw_text} />
            ) : null}
          </>
        ) : null}

        {historyStats && !historyStats.error ? (
          <>
            <Text style={styles.adminSubTitle}>HISTORY DATABASE</Text>
            <InfoLine label="Total rows" value={String(historyStats.total_rows)} />
            <InfoLine label="Airports" value={historyStats.airports?.join(", ") || "—"} />
            <InfoLine label="Oldest record" value={historyStats.oldest ? formatRelative(historyStats.oldest) : "—"} />
            <InfoLine label="Newest record" value={historyStats.newest ? formatRelative(historyStats.newest) : "—"} />
            <InfoLine label="DB size" value={historyStats.size_mb != null ? `${historyStats.size_mb} MB` : "—"} />
          </>
        ) : null}
      </View>
      ) : null}

      {section === "devices" ? (
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>DEVICES</Text>
        <Text style={styles.moduleIntro}>
          Mobile, Matrix, and WebSocket presence for trusted-LAN devices.
        </Text>
        <View style={styles.metricRow}>
          <InfoCard label="PAIR" value={companionRecord?.platform_pair || platformPair} />
          <InfoCard label="WEBSOCKETS" value={String(snapshot.connections?.count ?? 0)} />
          <InfoCard label="MATRIX" value={matrixOnline ? "ONLINE" : matrixEnabled ? "WAITING" : "DISABLED"} tone={matrixOnline ? "green" : matrixEnabled ? "amber" : "red"} />
        </View>
        <InfoLine label="Companion ID" value={companionIdentity?.companionId || "Loading..."} />
        <InfoLine label="Companion OS" value={companionIdentity?.mobileOs || "Loading..."} />
        <InfoLine label="Last check-in" value={companionRecord?.last_seen ? formatRelative(companionRecord.last_seen) : "Not seen yet"} />
        <InfoLine label="Matrix last seen" value={matrixLastSeen ? formatRelative(matrixLastSeen) : "Never pinged"} />
        <SettingsToolPill
          icon="view-grid"
          label="Open Matrix Board"
          value={matrixEnabled ? "Tune board status, look, runtime, and motion" : "Prepare board settings before enabling output"}
          onPress={onOpenMatrix}
        />
      </View>
      ) : null}

      {section === "reports" ? (
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>REPORT TO DEVELOPER</Text>
        <Text style={styles.moduleIntro}>
          Sends directly to the dedicated Local Flight Reports Linear workspace.
        </Text>
        <TextInput
          value={feedbackTitle}
          onChangeText={onFeedbackTitleChange}
          placeholder="Short summary, for example Matrix not updating"
          placeholderTextColor={palette.textDim}
          style={styles.serverInput}
        />
        <TextInput
          value={feedbackDescription}
          onChangeText={onFeedbackDescriptionChange}
          placeholder="What happened, what you expected, and how to reproduce it"
          placeholderTextColor={palette.textDim}
          multiline
          textAlignVertical="top"
          style={[styles.serverInput, styles.feedbackInput]}
        />
        <View style={styles.feedbackContextBox}>
          <Text style={styles.feedbackContextText}>{feedbackContext}</Text>
        </View>
        <Pressable style={[styles.connectButton, feedbackSending && styles.connectButtonDisabled]} onPress={onSubmitFeedback} disabled={feedbackSending}>
          {feedbackSending ? <ActivityIndicator color={solidButtonInk()} /> : <Text style={styles.connectButtonText}>SEND REPORT</Text>}
        </Pressable>
        {feedbackMessage ? (
          <Text style={[styles.feedbackMessage, feedbackTone === "ok" ? styles.feedbackMessageOk : styles.feedbackMessageError]}>
            {feedbackMessage}
          </Text>
        ) : null}
        {feedbackMessage && feedbackTone === "ok" ? (
          <Pressable style={styles.feedbackSupportHint} onPress={onOpenSupport}>
            <Text style={styles.feedbackSupportText}>Thanks for helping Local Flight improve.</Text>
            <Text style={styles.feedbackSupportAction}>SUPPORT</Text>
          </Pressable>
        ) : null}
      </View>
      ) : null}

      {section === "developer" && __DEV__ ? (
        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>AUTO REPORT TEST</Text>
          <Text style={styles.moduleIntro}>
            Developer-only helpers to verify the mobile crash pipeline before a real failure happens.
          </Text>
          <Pressable style={styles.connectButton} onPress={onSendAutoReportTest}>
            <Text style={styles.connectButtonText}>SEND AUTO TEST</Text>
          </Pressable>
          <Pressable
            style={[styles.connectButton, styles.crashButton]}
            onPress={() => {
              setTimeout(() => {
                throw new Error("Intentional mobile crash test");
              }, 10);
            }}
          >
            <Text style={styles.connectButtonText}>TRIGGER TEST CRASH</Text>
          </Pressable>
          {autoReportMessage ? <Text style={[styles.feedbackMessage, styles.feedbackMessageOk]}>{autoReportMessage}</Text> : null}
        </View>
      ) : null}

      {error ? <Text style={styles.errorText}>{error}</Text> : null}
    </View>
  );
}

export function CompanionSetupScreen({
  initialUrl,
  initialDiagnosticsMode,
  onComplete
}: {
  initialUrl: string;
  initialDiagnosticsMode: MobileDiagnosticsMode;
  onComplete: (result: CompanionSetupResult) => Promise<void> | void;
}) {
  const [step, setStep] = useState<CompanionSetupStep>("welcome");
  const [serverInput, setServerInput] = useState(initialUrl);
  const [diagnosticsMode, setDiagnosticsMode] = useState<MobileDiagnosticsMode>(
    initialDiagnosticsMode === "unset" ? "manual" : initialDiagnosticsMode
  );
  const [testing, setTesting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [setupProgress, setSetupProgress] = useState<string | null>(null);
  const [urlCheckState, setUrlCheckState] = useState<SetupUrlCheckState>("idle");
  const [urlCheckMessage, setUrlCheckMessage] = useState("Enter the LAN URL shown by the desktop or Pi app.");
  const [serverSummary, setServerSummary] = useState<CompanionSetupResult | null>(null);
  const stepAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    setServerInput(initialUrl);
  }, [initialUrl]);

  useEffect(() => {
    if (initialDiagnosticsMode !== "unset") {
      setDiagnosticsMode(initialDiagnosticsMode);
    }
  }, [initialDiagnosticsMode]);

  useEffect(() => {
    stepAnim.setValue(0);
    Animated.timing(stepAnim, {
      toValue: 1,
      duration: 220,
      useNativeDriver: true
    }).start();
  }, [step, stepAnim]);

  useEffect(() => {
    if (step !== "server") return;

    const input = serverInput.trim();
    if (!input) {
      setUrlCheckState("idle");
      setUrlCheckMessage("Enter the LAN URL shown by the desktop or Pi app.");
      return;
    }

    const urlProblem = companionSetupUrlProblem(input);
    if (urlProblem) {
      setUrlCheckState("invalid");
      setUrlCheckMessage(urlProblem);
      return;
    }

    let cancelled = false;
    const timer = setTimeout(() => {
      const normalizedUrl = normalizeServerUrl(input);
      setUrlCheckState("checking");
      setUrlCheckMessage("Checking /api/health on the Local Flight server...");
      void getHealth(normalizedUrl)
        .then(() => {
          if (cancelled) return;
          setUrlCheckState("ok");
          setUrlCheckMessage("Server health answered. You can run the full setup test.");
        })
        .catch((exc) => {
          if (cancelled) return;
          setUrlCheckState("error");
          setUrlCheckMessage(companionSetupErrorMessage(exc));
        });
    }, 650);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [serverInput, step]);

  const testServer = useCallback(async () => {
    const urlProblem = companionSetupUrlProblem(serverInput);
    if (urlProblem) {
      setSetupError(urlProblem);
      setUrlCheckState("invalid");
      setUrlCheckMessage(urlProblem);
      return;
    }

    setTesting(true);
    setSetupError(null);
    setUrlCheckState("checking");
    setUrlCheckMessage("Running the full Local Flight setup check...");
    let rootHealthOk = false;
    try {
      const normalizedUrl = normalizeServerUrl(serverInput);
      setSetupProgress("Checking the Local Flight server on your LAN...");
      await getRootHealth(normalizedUrl);
      rootHealthOk = true;
      setSetupProgress("Reading companion health and server config...");
      const [state, config] = await Promise.all([
        getHealth(normalizedUrl),
        getConfig(normalizedUrl)
      ]);
      const summary = {
        serverUrl: normalizedUrl,
        diagnosticsMode,
        config,
        state
      };
      setSetupProgress("Server answered. Moving to diagnostics...");
      setServerInput(normalizedUrl);
      setUrlCheckState("ok");
      setUrlCheckMessage("Server and companion APIs are ready.");
      setServerSummary(summary);
      setStep("diagnostics");
    } catch (exc) {
      const message = rootHealthOk
        ? "Local Flight answered /health, but setup APIs are not ready. Finish Local Flight setup on the desktop/Pi first, then return here."
        : companionSetupErrorMessage(exc);
      setSetupError(
        message
      );
      setUrlCheckState("error");
      setUrlCheckMessage(
        rootHealthOk
          ? "Server health answered, but the companion APIs are not ready yet."
          : message
      );
    } finally {
      setTesting(false);
      setSetupProgress(null);
    }
  }, [diagnosticsMode, serverInput]);

  const finishSetup = useCallback(async () => {
    if (!serverSummary) {
      setStep("server");
      setSetupError("Test your Local Flight server before finishing setup.");
      return;
    }
    setFinishing(true);
    setSetupError(null);
    try {
      await onComplete({ ...serverSummary, diagnosticsMode });
    } catch (exc) {
      setSetupError(companionSetupErrorMessage(exc));
    } finally {
      setFinishing(false);
    }
  }, [diagnosticsMode, onComplete, serverSummary]);

  const activeStepIndex = setupStepRank(step);
  const panelMotion = {
    opacity: stepAnim,
    transform: [{
      translateY: stepAnim.interpolate({ inputRange: [0, 1], outputRange: [16, 0] })
    }]
  };

  return (
    <ScrollView style={styles.companionSetupScroll} contentContainerStyle={styles.companionSetupContent}>
      <View style={styles.companionSetupGlowA} />
      <View style={styles.companionSetupGlowB} />
      <View style={styles.companionSetupShell}>
        <View style={styles.companionSetupHero}>
          <View style={styles.companionSetupLogoWrap}>
            <View style={styles.companionSetupLogoRing} />
            <View style={styles.companionSetupLogoRingOuter} />
            <Image
              source={require("../../assets/localflight-logo.png")}
              resizeMode="contain"
              style={styles.companionSetupLogoMark}
            />
          </View>
          <Text style={styles.companionSetupEyebrow}>
            <Text style={styles.companionSetupBrandText}>LOCAL FLIGHT</Text>
            <Text style={styles.companionSetupEyebrowSuffix}> COMPANION</Text>
          </Text>
          <Text style={styles.companionSetupTitle}>Set up your flight board</Text>
          <Text style={styles.companionSetupBody}>
            Pair this device with your already-configured desktop or Pi server. The companion stays on this guided setup until LAN pairing and diagnostics consent are done.
          </Text>
          <View style={styles.companionSetupRoute}>
            {(["welcome", "server", "diagnostics", "ready"] as CompanionSetupStep[]).map((item, index) => (
              <View key={item} style={styles.companionSetupRouteItem}>
                <View
                  style={[
                    styles.companionSetupStepDot,
                    index <= activeStepIndex && styles.companionSetupStepDotActive
                  ]}
                >
                  <Text style={[styles.companionSetupStepNumber, index <= activeStepIndex && styles.companionSetupStepNumberActive]}>
                    {index + 1}
                  </Text>
                </View>
                <Text style={[styles.companionSetupStepLabel, index <= activeStepIndex && styles.companionSetupStepLabelActive]}>
                  {setupStepTitle(item)}
                </Text>
              </View>
            ))}
          </View>
        </View>

        {step === "welcome" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Local-first LAN companion</Text>
            <Text style={styles.companionSetupBody}>
              You only need your Local Flight server running on the same WiFi. The phone asks that server for FIDS, radar, history, docs, reports, and Matrix/Admin status.
            </Text>
            <View style={styles.companionSetupChecklist}>
              <SetupChecklistItem icon="server-network" title="Server first" body="Finish desktop/Pi setup before pairing the phone." />
              <SetupChecklistItem icon="wifi" title="Same LAN" body="Use localflight.local or the Pi/desktop IP address." />
              <SetupChecklistItem icon="shield-check" title="Privacy choice" body="Pick manual or automatic mobile diagnostics before entering the app." />
            </View>
            <View style={styles.companionSetupInfoGrid}>
              <SetupInfoTile label="Mode" value="LAN companion" />
              <SetupInfoTile label="Privacy" value="Server mediated" />
              <SetupInfoTile label="Needed" value="Configured desktop/Pi" />
              <SetupInfoTile label="Next" value="Test server URL" />
            </View>
            <Pressable style={styles.companionSetupPrimary} onPress={() => setStep("server")}>
              <MaterialCommunityIcons name="arrow-right" size={16} color={solidButtonInk()} />
              <Text style={styles.companionSetupPrimaryText}>START SETUP</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {step === "server" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Connect your Local Flight server</Text>
            <Text style={styles.companionSetupBody}>
              Use the LAN address shown by the desktop or Pi app. On a physical iPhone, localhost points at the phone, not the Local Flight server.
            </Text>
            <View style={styles.companionSetupExampleBox}>
              <Text style={styles.companionSetupExampleLabel}>GOOD EXAMPLES</Text>
              <Text style={styles.companionSetupExampleText}>http://localflight.local:8000</Text>
              <Text style={styles.companionSetupExampleText}>http://192.168.1.42:8000</Text>
            </View>
            <View
              style={[
                styles.companionSetupInputWrap,
                urlCheckState === "ok" && styles.companionSetupInputWrapOk,
                urlCheckState === "checking" && styles.companionSetupInputWrapChecking,
                (urlCheckState === "error" || urlCheckState === "invalid") && styles.companionSetupInputWrapError
              ]}
            >
              <TextInput
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
                placeholder="http://localflight.local:8000"
                placeholderTextColor={palette.textDim}
                value={serverInput}
                onChangeText={setServerInput}
                style={styles.companionSetupInput}
              />
              <View style={styles.companionSetupInputStatus}>
                {urlCheckState === "checking" ? (
                  <ActivityIndicator size="small" color={palette.blue2} />
                ) : (
                  <MaterialCommunityIcons
                    name={setupUrlCheckIcon(urlCheckState)}
                    size={16}
                    color={setupUrlCheckColor(urlCheckState)}
                  />
                )}
              </View>
            </View>
            <Text
              style={[
                styles.companionSetupUrlHint,
                urlCheckState === "ok" && styles.companionSetupUrlHintOk,
                (urlCheckState === "error" || urlCheckState === "invalid") && styles.companionSetupUrlHintError
              ]}
            >
              {urlCheckMessage}
            </Text>
            <SetupProgressRail
              active={testing}
              label={setupProgress || "Waiting to test the server URL."}
              steps={["LAN reachability", "Server health", "Companion config"]}
            />
            <Pressable
              style={[styles.companionSetupPrimary, testing && styles.connectButtonDisabled]}
              onPress={() => void testServer()}
              disabled={testing}
            >
              {testing ? <ActivityIndicator color={solidButtonInk()} /> : <MaterialCommunityIcons name="lan-connect" size={16} color={solidButtonInk()} />}
              <Text style={styles.companionSetupPrimaryText}>{testing ? "TESTING SERVER" : "TEST SERVER"}</Text>
            </Pressable>
            <Pressable style={styles.companionSetupSecondary} onPress={() => setStep("welcome")}>
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {step === "diagnostics" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Choose companion diagnostics</Text>
            <Text style={styles.companionSetupBody}>
              Manual reports are always available. Automatic reports only send when this device and the connected server both allow diagnostics.
            </Text>
            <View style={styles.companionSetupOptionStack}>
              {([
                ["manual", "Manual only", "No automatic companion reports. Send feedback yourself from Admin."],
                ["auto", "Auto crash reports", "Send serious React/JS companion crashes with app and server context."],
                ["auto_logs", "Auto + context", "Same as auto for now; native iOS logs are not collected in this pass."]
              ] as Array<[MobileDiagnosticsMode, string, string]>).map(([mode, title, body]) => (
                <Pressable
                  key={mode}
                  style={[
                    styles.companionSetupOption,
                    diagnosticsMode === mode && styles.companionSetupOptionActive
                  ]}
                  onPress={() => setDiagnosticsMode(mode)}
                >
                  <View style={styles.companionSetupOptionTop}>
                    <Text style={styles.companionSetupOptionTitle}>{title}</Text>
                    {mode === "manual" ? <Text style={styles.companionSetupRecommended}>RECOMMENDED</Text> : null}
                  </View>
                  <Text style={styles.companionSetupOptionBody}>{body}</Text>
                </Pressable>
              ))}
            </View>
            <Pressable style={styles.companionSetupPrimary} onPress={() => setStep("ready")}>
              <MaterialCommunityIcons name="clipboard-check-outline" size={16} color={solidButtonInk()} />
              <Text style={styles.companionSetupPrimaryText}>REVIEW SETUP</Text>
            </Pressable>
            <Pressable style={styles.companionSetupSecondary} onPress={() => setStep("server")}>
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {step === "ready" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Ready for the board</Text>
            <Text style={styles.companionSetupBody}>
              The companion will save this pairing locally, ask the Local Flight server for fresh FIDS rows, and open the main app.
            </Text>
            <View style={styles.companionSetupSummary}>
              <InfoLine label="Server" value={serverSummary?.serverUrl || normalizeServerUrl(serverInput) || "Not tested"} />
              <InfoLine label="Airport" value={serverSummary?.config.airport_iata || "---"} />
              <InfoLine label="Server status" value={serverSummary?.state.ok === false ? "Needs attention" : "Ready"} />
              <InfoLine label="Diagnostics" value={diagnosticsMode === "manual" ? "Manual reports only" : diagnosticsMode === "auto" ? "Automatic crash reports" : "Automatic crash reports + context"} />
            </View>
            <Pressable
              style={[styles.companionSetupPrimary, finishing && styles.connectButtonDisabled]}
              onPress={() => void finishSetup()}
              disabled={finishing}
            >
              {finishing ? <ActivityIndicator color={solidButtonInk()} /> : <MaterialCommunityIcons name="airplane-takeoff" size={16} color={solidButtonInk()} />}
              <Text style={styles.companionSetupPrimaryText}>{finishing ? "SAVING SETUP" : "FINISH SETUP"}</Text>
            </Pressable>
            <Pressable style={styles.companionSetupSecondary} onPress={() => setStep("diagnostics")}>
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {setupError ? (
          <View style={styles.companionSetupError}>
            <Text style={styles.companionSetupErrorLabel}>SETUP NEEDS ATTENTION</Text>
            <Text style={styles.companionSetupErrorText}>{setupError}</Text>
          </View>
        ) : null}
      </View>
    </ScrollView>
  );
}

function SetupChecklistItem({ icon, title, body }: { icon: MaterialIconName; title: string; body: string }) {
  return (
    <View style={styles.companionSetupChecklistItem}>
      <View style={styles.companionSetupChecklistIcon}>
        <MaterialCommunityIcons name={icon} size={16} color={palette.blue2} />
      </View>
      <View style={styles.companionSetupChecklistCopy}>
        <Text style={styles.companionSetupChecklistTitle}>{title}</Text>
        <Text style={styles.companionSetupChecklistBody}>{body}</Text>
      </View>
    </View>
  );
}

function SetupProgressRail({ active, label, steps }: { active: boolean; label: string; steps: string[] }) {
  return (
    <View style={[styles.companionSetupProgressRail, active && styles.companionSetupProgressRailActive]}>
      <View style={styles.companionSetupProgressHeader}>
        {active ? <ActivityIndicator size="small" color={palette.blue} /> : <MaterialCommunityIcons name="progress-clock" size={15} color={palette.textDim} />}
        <Text style={styles.companionSetupProgressText}>{label}</Text>
      </View>
      <View style={styles.companionSetupProgressSteps}>
        {steps.map((item, index) => (
          <View key={item} style={styles.companionSetupProgressStep}>
            <View style={[styles.companionSetupProgressDot, active && index === 0 && styles.companionSetupProgressDotActive]} />
            <Text style={styles.companionSetupProgressStepText}>{item}</Text>
          </View>
        ))}
      </View>
    </View>
  );
}

function SetupInfoTile({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.companionSetupInfoTile}>
      <Text style={styles.companionSetupInfoLabel}>{label}</Text>
      <Text style={styles.companionSetupInfoValue}>{value}</Text>
    </View>
  );
}

function setupUrlCheckIcon(state: SetupUrlCheckState): MaterialIconName {
  switch (state) {
    case "ok":
      return "check-circle";
    case "error":
    case "invalid":
      return "alert-circle";
    case "checking":
      return "progress-clock";
    default:
      return "link-variant";
  }
}

function setupUrlCheckColor(state: SetupUrlCheckState): string {
  switch (state) {
    case "ok":
      return palette.green;
    case "error":
    case "invalid":
      return palette.red;
    case "checking":
      return palette.blue2;
    default:
      return palette.textDim;
  }
}

function setupStepRank(step: CompanionSetupStep): number {
  return { welcome: 0, server: 1, diagnostics: 2, ready: 3 }[step];
}

function setupStepTitle(step: CompanionSetupStep): string {
  return {
    welcome: "Welcome",
    server: "Server",
    diagnostics: "Reports",
    ready: "Ready"
  }[step];
}

function companionSetupUrlProblem(input: string): string | null {
  const normalized = normalizeServerUrl(input);
  if (!normalized) {
    return "Enter the Local Flight server URL first.";
  }
  try {
    const parsed = new URL(normalized);
    const host = parsed.hostname.replace(/^\[|\]$/g, "").toLowerCase();
    if (["localhost", "127.0.0.1", "::1", "0.0.0.0"].includes(host)) {
      return "A physical iPhone cannot use localhost because that points at the phone. Use the Pi or desktop LAN IP, or localflight.local if mDNS works.";
    }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return "Use an http:// or https:// Local Flight server URL.";
    }
  } catch {
    return "Enter a valid Local Flight server URL, for example http://192.168.1.42:8000.";
  }
  return null;
}

function companionSetupErrorMessage(value: unknown): string {
  const message = errorMessage(value);
  if (/Network request failed/i.test(message)) {
    return "Could not reach Local Flight on the LAN. Make sure the iPhone and Pi/desktop are on the same Wi-Fi, Local Flight is running, and the URL uses the server IP or localflight.local.";
  }
  return message;
}

export function SettingsScreen({
  serverUrl,
  draftUrl,
  error,
  loading,
  isTablet,
  isLandscape,
  themeMode,
  skin,
  weatherDisplayMode,
  mobileDiagnosticsMode,
  profiles,
  activeProfileId,
  applyingProfileId,
  outputs,
  refreshSeconds,
  schedulerRestarting,
  schedulerMessage,
  onThemeModeChange,
  onSkinChange,
  onWeatherDisplayModeChange,
  onMobileDiagnosticsModeChange,
  onApplyProfile,
  onOpenHistory,
  onOpenAdmin,
  onOpenMatrix,
  onOpenDoc,
  onOpenSupport,
  onRestartScheduler,
  onRerunSetup,
  onChangeUrl,
  onConnect
}: {
  serverUrl: string;
  draftUrl: string;
  error: string | null;
  loading: boolean;
  isTablet: boolean;
  isLandscape: boolean;
  themeMode: MobileThemeMode;
  skin: MobileSkin;
  weatherDisplayMode: MobileWeatherDisplayMode;
  mobileDiagnosticsMode: MobileDiagnosticsMode;
  profiles: ConfigProfile[];
  activeProfileId: string | null;
  applyingProfileId: string | null;
  outputs: string[];
  refreshSeconds: number | null;
  schedulerRestarting: boolean;
  schedulerMessage: string | null;
  onThemeModeChange: (value: MobileThemeMode) => void;
  onSkinChange: (value: MobileSkin) => void;
  onWeatherDisplayModeChange: (value: MobileWeatherDisplayMode) => void;
  onMobileDiagnosticsModeChange: (value: MobileDiagnosticsMode) => void;
  onApplyProfile: (profile: ConfigProfile) => void;
  onOpenHistory: () => void;
  onOpenAdmin: () => void;
  onOpenMatrix: () => void;
  onOpenDoc: (slug: DocSlug) => void;
  onOpenSupport: () => void;
  onRestartScheduler: () => void;
  onRerunSetup: () => void;
  onChangeUrl: (value: string) => void;
  onConnect: () => void;
}) {
  const [serverExpanded, setServerExpanded] = useState(!serverUrl);
  const [appearanceVisible, setAppearanceVisible] = useState(false);
  const outputValue = outputs.length ? outputs.join(", ").toUpperCase() : "WEB";

  return (
    <View style={styles.cardStack}>
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>SETTINGS</Text>
        <Text style={styles.moduleIntro}>
          Start with the server link, then jump straight to the companion tools you need.
        </Text>
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>CONNECTION & SYNC</Text>
        <View style={styles.metricRow}>
          <InfoCard label="SERVER" value={serverUrl ? "READY" : "SETUP"} tone={serverUrl ? "green" : "amber"} />
          <InfoCard label="REFRESH" value={refreshSeconds ? formatInterval(refreshSeconds).toUpperCase() : "WAIT"} />
          <InfoCard label="OUTPUTS" value={outputValue} tone="blue" />
        </View>
        <InfoLine label="Saved server" value={serverUrl || "Not set"} />
        <InfoLine label="Companion build" value={APP_VERSION} />
        <InfoLine label="Layout" value={isTablet ? `iPad ${isLandscape ? "landscape" : "portrait"}` : "iPhone"} />

        {profiles.length > 1 ? (
          <View style={styles.settingsProfileBlock}>
            <View style={styles.settingsProfileHeader}>
              <Text style={styles.settingsProfileTitle}>AIRPORT PROFILES</Text>
              <Text style={styles.settingsProfileHint}>one-tap switch</Text>
            </View>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.settingsProfileChips}
            >
              {profiles.map((profile, index) => {
                const active = profile.id === activeProfileId;
                const applying = profile.id === applyingProfileId;
                const disabled = applyingProfileId !== null;
                return (
                  <Pressable
                    key={profileKey(profile, index)}
                    style={[
                      styles.settingsProfileChip,
                      active && styles.settingsProfileChipActive,
                      disabled && !applying && styles.settingsProfileChipDisabled
                    ]}
                    onPress={() => onApplyProfile(profile)}
                    disabled={disabled}
                  >
                    <View style={styles.settingsProfileChipTop}>
                      <Text style={[styles.settingsProfileName, active && styles.settingsProfileNameActive]} numberOfLines={1}>
                        {profile.name}
                      </Text>
                      {applying ? (
                        <ActivityIndicator size="small" color={palette.blue2} />
                      ) : active ? (
                        <MaterialCommunityIcons name="check-circle" size={14} color={palette.green} />
                      ) : null}
                    </View>
                    <Text style={styles.settingsProfileMeta} numberOfLines={1}>
                      {profile.iata} · {profile.source === "virtual" ? "VATSIM" : "REAL"} · {formatInterval(profile.refresh_seconds)}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        ) : null}

        <View style={styles.settingsInlineActions}>
          <Pressable style={styles.settingsCompactButton} onPress={() => setServerExpanded((value) => !value)}>
            <Text style={styles.settingsCompactButtonText}>{serverExpanded ? "HIDE SERVER" : "CHANGE SERVER"}</Text>
          </Pressable>
          <Pressable
            style={[styles.settingsCompactButton, schedulerRestarting && styles.connectButtonDisabled]}
            onPress={onRestartScheduler}
            disabled={schedulerRestarting}
          >
            {schedulerRestarting ? <ActivityIndicator size="small" color={palette.blue} /> : <Text style={styles.settingsCompactButtonText}>RESTART FETCH</Text>}
          </Pressable>
        </View>

        {serverExpanded ? (
          <>
            <TextInput
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              placeholder="http://192.168.1.42:8000"
              placeholderTextColor={palette.textDim}
              value={draftUrl}
              onChangeText={onChangeUrl}
              style={styles.serverInput}
            />
            <Pressable style={styles.connectButton} onPress={onConnect} disabled={loading}>
              {loading ? <ActivityIndicator color={solidButtonInk()} /> : <Text style={styles.connectButtonText}>CONNECT</Text>}
            </Pressable>
            <Text style={styles.settingsHelp}>
              Use the LAN IP of the machine running Local Flight. On a physical iPhone, localhost points at the phone itself.
            </Text>
          </>
        ) : null}
        {schedulerMessage ? <Text style={[styles.feedbackMessage, styles.feedbackMessageOk]}>{schedulerMessage}</Text> : null}
        {error ? <Text style={styles.errorText}>{error}</Text> : null}
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>QUICK ACTIONS</Text>
        <View style={styles.settingsQuickGrid}>
          <SettingsQuickAction
            icon="palette-outline"
            label="Mobile Look"
            value={`${themeMode} · ${skin} · ${weatherModeOption(weatherDisplayMode).label} WX`}
            onPress={() => setAppearanceVisible(true)}
          />
          <SettingsQuickAction
            icon="view-grid"
            label="Matrix Board"
            value="Status, look, runtime"
            onPress={onOpenMatrix}
          />
          <SettingsQuickAction
            icon="tools"
            label="Admin & Reports"
            value="Health and diagnostics"
            onPress={onOpenAdmin}
          />
          <SettingsQuickAction
            icon="history"
            label="History"
            value="Stored flight rows"
            onPress={onOpenHistory}
          />
          <SettingsQuickAction
            icon="book-open-variant"
            label="Docs"
            value="Install + display guide"
            onPress={() => onOpenDoc("install")}
          />
          <SettingsQuickAction
            icon="shield-lock-outline"
            label="Privacy"
            value="Local-first policy"
            onPress={() => onOpenDoc("privacy")}
          />
        </View>
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>HELP & SUPPORT</Text>
        <Text style={styles.moduleIntro}>
          Lower-frequency links and diagnostics controls live here so daily settings stay calm.
        </Text>
        <FilterSection title="MOBILE DIAGNOSTICS">
          <View style={styles.filterRow}>
            {([
              ["manual", "MANUAL"],
              ["auto", "AUTO"],
              ["auto_logs", "AUTO + CONTEXT"]
            ] as Array<[MobileDiagnosticsMode, string]>).map(([mode, label]) => (
              <DirectionButton
                key={mode}
                active={mobileDiagnosticsMode === mode}
                label={label}
                onPress={() => onMobileDiagnosticsModeChange(mode)}
              />
            ))}
          </View>
        </FilterSection>
        <SettingsToolPill
          icon="monitor-dashboard"
          label="Display modes"
          value="Native, browser, Pi, mobile, and Matrix"
          onPress={() => onOpenDoc("display-modes")}
        />
        <SettingsToolPill
          icon="book-open-page-variant"
          label="Project README"
          value="Overview and quick path chooser"
          onPress={() => onOpenDoc("readme")}
        />
        <SettingsToolPill
          icon="format-list-bulleted"
          label="Changelog"
          value="Release history and version notes"
          onPress={() => onOpenDoc("changelog")}
        />
        <SettingsToolPill
          icon="restart-alert"
          label="Rerun companion setup"
          value="Revisit server pairing and diagnostics consent"
          onPress={onRerunSetup}
        />
        <SettingsToolPill
          icon="github"
          label="Source & releases"
          value="github.com/tr3y4rch/local-flight"
          onPress={() => void Linking.openURL("https://github.com/tr3y4rch/local-flight")}
        />
      </View>

      <Pressable style={styles.supportFooter} onPress={onOpenSupport}>
        <MaterialCommunityIcons name="heart-outline" size={15} color={palette.amber} />
        <Text style={styles.supportFooterText}>Support Local Flight</Text>
        <MaterialCommunityIcons name="chevron-up" size={13} color={palette.textDim} />
      </Pressable>

      <AppearanceSheet
        visible={appearanceVisible}
        themeMode={themeMode}
        skin={skin}
        weatherDisplayMode={weatherDisplayMode}
        onClose={() => setAppearanceVisible(false)}
        onThemeModeChange={onThemeModeChange}
        onSkinChange={onSkinChange}
        onWeatherDisplayModeChange={onWeatherDisplayModeChange}
      />
    </View>
  );
}

export function DocsScreen({
  slug,
  serverUrl,
  onBackSettings,
  contentPaddingBottom
}: {
  slug: DocSlug;
  serverUrl: string;
  onBackSettings: () => void;
  contentPaddingBottom: number;
}) {
  const source = DOC_SOURCES[slug];
  const [document, setDocument] = useState<DocDocument | null>(null);
  const [loadingDoc, setLoadingDoc] = useState(true);
  const [docError, setDocError] = useState<string | null>(null);
  const [tocVisible, setTocVisible] = useState(false);
  const [docCardY, setDocCardY] = useState(0);
  const headingOffsets = useRef<Record<string, number>>({});
  const scrollRef = useRef<ScrollView>(null);

  const loadDoc = useCallback(async () => {
    setLoadingDoc(true);
    setDocError(null);
    setDocument(null);
    headingOffsets.current = {};
    try {
      setDocument(await getDoc(serverUrl, slug));
    } catch (exc) {
      setDocError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoadingDoc(false);
    }
  }, [serverUrl, slug]);

  useEffect(() => {
    void loadDoc();
  }, [loadDoc]);

  const title = document?.title || source.title;
  const detail = document?.summary || source.detail;
  const githubUrl = document?.github_url || source.githubUrl;
  const headings = extractDocHeadings(document?.content || "");

  const jumpToHeading = useCallback((heading: DocHeading) => {
    setTocVisible(false);
    const headingY = headingOffsets.current[heading.id];
    if (typeof headingY !== "number") return;
    scrollRef.current?.scrollTo({
      y: Math.max(0, docCardY + headingY - 12),
      animated: true
    });
  }, [docCardY]);

  const onHeadingLayout = useCallback((id: string, y: number) => {
    headingOffsets.current[id] = y;
  }, []);

  return (
    <ScrollView
      ref={scrollRef}
      style={styles.screenScroll}
      contentContainerStyle={[styles.screenContent, { paddingBottom: contentPaddingBottom }]}
      refreshControl={<RefreshControl refreshing={loadingDoc} tintColor={palette.blue} onRefresh={loadDoc} />}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.cardStack}>
        <HiddenToolHeader
          icon="book-open-variant"
          title={title}
          detail={detail}
          onBack={onBackSettings}
        />

        <View style={styles.docsCard} onLayout={(event) => setDocCardY(event.nativeEvent.layout.y)}>
          {!loadingDoc && !docError && headings.length ? (
            <Pressable style={styles.docTocPill} onPress={() => setTocVisible(true)}>
              <MaterialCommunityIcons name="format-list-bulleted" size={15} color={palette.blue2} />
              <Text style={styles.docTocPillText}>JUMP TO</Text>
              <Text style={styles.docTocPillCount}>{headings.length} SECTIONS</Text>
            </Pressable>
          ) : null}
          <ScreenActivity
            activity={
              loadingDoc
                ? {
                    label: `Loading ${source.title}`,
                    detail: "Asking the connected Local Flight server for bundled Markdown."
                  }
                : null
            }
          />
          {loadingDoc ? <ActivityIndicator color={palette.blue} style={styles.loader} /> : null}
          {!loadingDoc && docError ? (
            <>
              <Text style={styles.sheetEmpty}>
                Could not load the bundled server document inside the app: {docError}
              </Text>
              <SettingsToolPill
                icon="open-in-new"
                label="Open in GitHub"
                value="External GitHub link opens only when you tap"
                onPress={() => void Linking.openURL(githubUrl)}
              />
            </>
          ) : null}
          {!loadingDoc && !docError ? (
            <MarkdownDocument
              content={document?.content || ""}
              onHeadingLayout={onHeadingLayout}
            />
          ) : null}
        </View>
      </View>

      <DocTocSheet
        visible={tocVisible}
        title={title}
        headings={headings}
        onClose={() => setTocVisible(false)}
        onSelect={jumpToHeading}
      />
    </ScrollView>
  );
}

function MarkdownDocument({
  content,
  onHeadingLayout
}: {
  content: string;
  onHeadingLayout?: (id: string, y: number) => void;
}) {
  const nodes: ReactNode[] = [];
  const lines = content.split(/\r?\n/);
  let codeLines: string[] = [];
  let inCode = false;

  const flushCode = () => {
    if (!codeLines.length) return;
    nodes.push(
      <View key={`doc-code-${nodes.length}`} style={styles.docCodeBlock}>
        <Text style={styles.docCodeText}>{codeLines.join("\n")}</Text>
      </View>
    );
    codeLines = [];
  };

  lines.forEach((rawLine, index) => {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      if (inCode) {
        inCode = false;
        flushCode();
      } else {
        inCode = true;
      }
      return;
    }
    if (inCode) {
      codeLines.push(rawLine);
      return;
    }
    if (!line.trim()) {
      nodes.push(<View key={`space-${index}`} style={styles.docSpacer} />);
      return;
    }
    if (line.startsWith("# ")) {
      const title = cleanMarkdownInline(line.replace(/^#\s+/, ""));
      const id = docHeadingId(title, index);
      nodes.push(
        <View key={`doc-title-${index}`} onLayout={(event) => onHeadingLayout?.(id, event.nativeEvent.layout.y)}>
          <Text style={styles.docTitle}>{title}</Text>
        </View>
      );
      return;
    }
    if (line.startsWith("## ")) {
      const title = cleanMarkdownInline(line.replace(/^##\s+/, ""));
      const id = docHeadingId(title, index);
      nodes.push(
        <View key={`doc-heading-${index}`} onLayout={(event) => onHeadingLayout?.(id, event.nativeEvent.layout.y)}>
          <Text style={styles.docHeading}>{title}</Text>
        </View>
      );
      return;
    }
    if (line.startsWith("### ")) {
      nodes.push(<Text key={`doc-subheading-${index}`} style={styles.docSubheading}>{cleanMarkdownInline(line.replace(/^###\s+/, ""))}</Text>);
      return;
    }
    const bullet = line.match(/^[-*]\s+(.*)$/);
    if (bullet) {
      nodes.push(
        <View key={`doc-bullet-${index}`} style={styles.docBulletRow}>
          <Text style={styles.docBulletMark}>-</Text>
          <Text style={styles.docBody}>{cleanMarkdownInline(bullet[1] || "")}</Text>
        </View>
      );
      return;
    }
    const numbered = line.match(/^\d+\.\s+(.*)$/);
    if (numbered) {
      nodes.push(
        <View key={`doc-numbered-${index}`} style={styles.docBulletRow}>
          <Text style={styles.docBulletMark}>#</Text>
          <Text style={styles.docBody}>{cleanMarkdownInline(numbered[1] || "")}</Text>
        </View>
      );
      return;
    }
    nodes.push(<Text key={`doc-body-${index}`} style={styles.docBody}>{cleanMarkdownInline(line)}</Text>);
  });

  if (inCode) {
    flushCode();
  }

  return <>{nodes}</>;
}

function DocTocSheet({
  visible,
  title,
  headings,
  onClose,
  onSelect
}: {
  visible: boolean;
  title: string;
  headings: DocHeading[];
  onClose: () => void;
  onSelect: (heading: DocHeading) => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable style={styles.sheetBackdropPress} onPress={onClose} />
        <View style={styles.docTocSheet}>
          <View style={styles.sheetHandle} />
          <View style={styles.docTocHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>DOCUMENT SECTIONS</Text>
              <Text style={styles.sheetTitle}>{title}</Text>
            </View>
            <Pressable style={styles.sheetAction} onPress={onClose}>
              <Text style={styles.sheetActionText}>DONE</Text>
            </Pressable>
          </View>
          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.docTocContent}>
            {headings.map((heading) => (
              <Pressable
                key={heading.id}
                style={[styles.docTocItem, heading.level === 2 && styles.docTocItemNested]}
                onPress={() => onSelect(heading)}
              >
                <Text style={styles.docTocItemLevel}>H{heading.level}</Text>
                <Text style={styles.docTocItemText} numberOfLines={2}>{heading.title}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function extractDocHeadings(content: string): DocHeading[] {
  const headings: DocHeading[] = [];
  let inCode = false;
  content.split(/\r?\n/).forEach((rawLine, index) => {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      inCode = !inCode;
      return;
    }
    if (inCode) return;
    const match = line.match(/^(#{1,2})\s+(.+)$/);
    if (!match) return;
    const title = cleanMarkdownInline(match[2] || "");
    if (!title) return;
    headings.push({
      id: docHeadingId(title, index),
      level: match[1] === "#" ? 1 : 2,
      title,
      index
    });
  });
  return headings;
}

function docHeadingId(title: string, index: number): string {
  return `${index}-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "section"}`;
}

function cleanMarkdownInline(value: string): string {
  return value
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`]/g, "")
    .trim();
}

function AppearancePreviewStrip() {
  return (
    <View style={styles.appearancePreview}>
      <View style={styles.appearancePreviewCard}>
        <Text style={styles.appearancePreviewTitle}>LOCAL FLIGHT</Text>
      </View>
      <View style={styles.appearancePreviewRail}>
        <View style={[styles.appearancePreviewDot, { backgroundColor: palette.blue }]} />
        <View style={[styles.appearancePreviewDot, { backgroundColor: palette.green }]} />
        <View style={[styles.appearancePreviewDot, { backgroundColor: palette.amber }]} />
        <View style={[styles.appearancePreviewDot, { backgroundColor: palette.red }]} />
      </View>
    </View>
  );
}

function AppearanceSheet({
  visible,
  themeMode,
  skin,
  weatherDisplayMode,
  onClose,
  onThemeModeChange,
  onSkinChange,
  onWeatherDisplayModeChange
}: {
  visible: boolean;
  themeMode: MobileThemeMode;
  skin: MobileSkin;
  weatherDisplayMode: MobileWeatherDisplayMode;
  onClose: () => void;
  onThemeModeChange: (value: MobileThemeMode) => void;
  onSkinChange: (value: MobileSkin) => void;
  onWeatherDisplayModeChange: (value: MobileWeatherDisplayMode) => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable style={styles.sheetBackdropPress} onPress={onClose} />
        <View style={styles.sheetCard}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>MOBILE LOOK</Text>
              <Text style={styles.sheetTitle}>Companion Appearance</Text>
            </View>
            <Pressable style={styles.sheetAction} onPress={onClose}>
              <Text style={styles.sheetActionText}>DONE</Text>
            </Pressable>
          </View>

          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}>
            <FilterSection title="THEME">
              <View style={styles.filterRow}>
                {MOBILE_THEME_OPTIONS.map((item) => (
                  <DirectionButton
                    key={item.id}
                    active={themeMode === item.id}
                    label={item.label.toUpperCase()}
                    onPress={() => onThemeModeChange(item.id)}
                  />
                ))}
              </View>
            </FilterSection>

            <FilterSection title="SKIN">
              <View style={styles.filterWrap}>
                {MOBILE_SKIN_OPTIONS.map((item) => (
                  <OptionChip
                    key={item.id}
                    active={skin === item.id}
                    label={item.label}
                    meta={themeMode}
                    onPress={() => onSkinChange(item.id)}
                  />
                ))}
              </View>
            </FilterSection>

            <FilterSection title="WEATHER DISPLAY">
              <View style={styles.filterWrap}>
                {WEATHER_DISPLAY_OPTIONS.map((item) => (
                  <OptionChip
                    key={item.id}
                    active={weatherDisplayMode === item.id}
                    label={item.label}
                    meta={item.meta}
                    onPress={() => onWeatherDisplayModeChange(item.id)}
                  />
                ))}
              </View>
            </FilterSection>

            <AppearancePreviewStrip />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

export function SupportSheet({
  visible,
  onClose
}: {
  visible: boolean;
  onClose: () => void;
}) {
  const [products, setProducts] = useState<SupportProduct[]>(() => supportProductPlaceholders());
  const [busyTier, setBusyTier] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const showWebFallback = __DEV__;

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    setMessage(null);
    supportStubProvider.loadProducts()
      .then((loaded) => {
        if (!cancelled) {
          setProducts(loaded);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProducts(supportProductPlaceholders().map((item) => ({
            ...item,
            availability: "unavailable",
            statusLabel: "Unavailable"
          })));
          setMessage("Support products could not be loaded in this build.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [visible]);

  const handleTierPress = useCallback(async (tier: SupportProduct) => {
    setBusyTier(tier.id);
    try {
      const result = await supportStubProvider.purchaseTier(tier);
      setMessage(result.message);
    } finally {
      setBusyTier(null);
    }
  }, []);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable style={styles.sheetBackdropPress} onPress={onClose} />
        <View style={styles.sheetCard}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>TIP JAR</Text>
              <Text style={styles.sheetTitle}>Support Local Flight</Text>
            </View>
            <Pressable style={styles.sheetAction} onPress={onClose}>
              <Text style={styles.sheetActionText}>DONE</Text>
            </Pressable>
          </View>

          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}>
            <View style={styles.supportHero}>
              <View style={styles.supportHeroIcon}>
                <MaterialCommunityIcons name="heart-outline" size={23} color={palette.amber} />
              </View>
              <View style={styles.supportHeroCopy}>
                <Text style={styles.supportHeroTitle}>Optional tips help keep the boards glowing.</Text>
                <Text style={styles.supportHeroBody}>Local Flight stays fully usable either way.</Text>
              </View>
            </View>

            <View style={styles.supportTierGrid}>
              {products.map((tier) => {
                const busy = busyTier === tier.id;
                return (
                  <Pressable
                    key={tier.productId}
                    style={styles.supportTierCard}
                    onPress={() => void handleTierPress(tier)}
                    disabled={busyTier !== null}
                  >
                    <View style={styles.supportTierTop}>
                      <Text style={styles.supportTierAmount}>{tier.priceLabel}</Text>
                      {busy ? (
                        <ActivityIndicator size="small" color={palette.amber} />
                      ) : (
                        <Text style={styles.supportTierStatus}>{tier.statusLabel}</Text>
                      )}
                    </View>
                    <Text style={styles.supportTierLabel}>{tier.label}</Text>
                  </Pressable>
                );
              })}
            </View>

            {message ? <Text style={styles.supportMessage}>{message}</Text> : null}

            <Text style={styles.supportFinePrint}>No features are locked behind support.</Text>

            {showWebFallback ? (
              <Pressable
                style={styles.supportDevFallback}
                onPress={() => void Linking.openURL(SUPPORT_WEB_FALLBACK_URL)}
              >
                <Text style={styles.supportDevFallbackText}>DEV WEB SUPPORT FALLBACK</Text>
                <MaterialCommunityIcons name="open-in-new" size={13} color={palette.textDim} />
              </Pressable>
            ) : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function SettingsQuickAction({
  icon,
  label,
  value,
  onPress
}: {
  icon: MaterialIconName;
  label: string;
  value: string;
  onPress: () => void;
}) {
  return (
    <Pressable style={styles.settingsQuickAction} onPress={onPress}>
      <View style={styles.settingsQuickIcon}>
        <MaterialCommunityIcons name={icon} size={18} color={palette.blue2} />
      </View>
      <Text style={styles.settingsQuickLabel}>{label}</Text>
      <Text style={styles.settingsQuickValue} numberOfLines={2}>{value}</Text>
    </Pressable>
  );
}

function SettingsToolPill({
  icon,
  label,
  value,
  onPress,
  loading = false,
  disabled = false
}: {
  icon: MaterialIconName;
  label: string;
  value: string;
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
}) {
  return (
    <Pressable
      style={[styles.settingsPill, disabled && styles.settingsPillDisabled]}
      onPress={onPress}
      disabled={disabled}
    >
      <View style={styles.settingsPillIcon}>
        <MaterialCommunityIcons name={icon} size={18} color={palette.blue2} />
      </View>
      <View style={styles.settingsPillCopy}>
        <Text style={styles.settingsPillLabel}>{label}</Text>
        <Text style={styles.settingsPillValue}>{value}</Text>
      </View>
      {loading ? (
        <ActivityIndicator color={palette.blue} />
      ) : (
        <MaterialCommunityIcons name="chevron-right" size={18} color={palette.textDim} />
      )}
    </Pressable>
  );
}

export function ConnectPrompt({ onSettings }: { onSettings: () => void }) {
  return (
    <Pressable style={styles.connectPrompt} onPress={onSettings}>
      <Text style={styles.connectPromptTitle}>Connect Local Flight</Text>
      <Text style={styles.connectPromptBody}>Tap here to set the server URL before live rows can load.</Text>
    </Pressable>
  );
}

function HiddenToolHeader({
  icon,
  title,
  detail,
  onBack
}: {
  icon: MaterialIconName;
  title: string;
  detail: string;
  onBack: () => void;
}) {
  return (
    <View style={styles.hiddenToolHeader}>
      <View style={styles.hiddenToolTitleRow}>
        <View style={styles.hiddenToolIcon}>
          <MaterialCommunityIcons name={icon} size={18} color={palette.blue} />
        </View>
        <View style={styles.hiddenToolCopy}>
          <Text style={styles.hiddenToolTitle}>{title}</Text>
          <Text style={styles.hiddenToolDetail}>{detail}</Text>
        </View>
      </View>
      <Pressable style={styles.hiddenToolBack} onPress={onBack}>
        <MaterialCommunityIcons name="chevron-left" size={18} color={palette.blue2} />
        <Text style={styles.hiddenToolBackText}>SETTINGS</Text>
      </Pressable>
    </View>
  );
}

export function ScreenError({
  message,
  onRetry,
  retrying
}: {
  message: string;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  return (
    <View style={styles.errorBanner}>
      <View style={styles.errorBannerCopy}>
        <Text style={styles.errorBannerLabel}>{retrying ? "RETRYING" : "DATA ISSUE"}</Text>
        <Text style={styles.errorBannerText}>{message}</Text>
      </View>
      {onRetry ? (
        <Pressable style={styles.errorRetryButton} onPress={onRetry} disabled={retrying}>
          {retrying ? (
            <ActivityIndicator size="small" color={palette.amber} />
          ) : (
            <MaterialCommunityIcons name="refresh" size={12} color={palette.red} />
          )}
          <Text style={[styles.errorRetryText, retrying && { color: palette.amber }]}>{retrying ? "WAIT" : "RETRY"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function InfoCard({ label, value, tone = "blue" }: { label: string; value: string; tone?: "blue" | "green" | "amber" | "red" }) {
  return (
    <View style={styles.infoCard}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={[styles.infoValue, { color: palette[tone] }]}>{value}</Text>
    </View>
  );
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.infoLine}>
      <Text style={styles.infoLineLabel}>{label}</Text>
      <Text style={styles.infoLineValue}>{value}</Text>
    </View>
  );
}

export function AirportConfigSheet({
  visible,
  serverUrl,
  currentConfig,
  budget,
  profiles,
  onClose,
  onApplied,
  onProfilesChange
}: {
  visible: boolean;
  serverUrl: string;
  currentConfig: AppConfig | null;
  budget: Budget | null;
  profiles: ConfigProfile[];
  onClose: () => void;
  onApplied: (config: AppConfig) => void;
  onProfilesChange: (profiles: ConfigProfile[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<AirportResult[]>([]);
  const [selectedAirport, setSelectedAirport] = useState<AirportResult | null>(null);
  const [source, setSource] = useState<"real" | "virtual">("real");
  const [refreshSecs, setRefreshSecs] = useState(3600);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [profileName, setProfileName] = useState("");
  const [applyingProfileId, setApplyingProfileId] = useState<string | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const schedulePolicy = budget?.schedule_policy ?? budget?.aviationstack?.schedule_policy;
  const policyAllowed = source === "real" && schedulePolicy?.community_shared
    ? new Set((schedulePolicy.allowed_refresh_seconds ?? []).map((value) => Number(value)))
    : null;
  const refreshOptions = policyAllowed
    ? REFRESH_OPTIONS.filter((opt) => policyAllowed.has(opt.seconds))
    : REFRESH_OPTIONS;

  useEffect(() => {
    if (!visible) return;
    setSelectedAirport(
      currentConfig?.airport_iata
        ? {
            iata: currentConfig.airport_iata,
            icao: currentConfig.airport_icao || "",
            name: currentConfig.display_name || currentConfig.airport_iata,
            city: "",
            country: "",
            type: "",
            timezone: currentConfig.timezone
          }
        : null
    );
    setSource(currentConfig?.source === "virtual" ? "virtual" : "real");
    setRefreshSecs(currentConfig?.refresh_seconds || 3600);
    setQuery("");
    setSearchResults([]);
    setApplyError(null);
    setProfileName("");
  }, [visible, currentConfig]);

  useEffect(() => {
    if (refreshOptions.length > 0 && !refreshOptions.some((opt) => opt.seconds === refreshSecs)) {
      const minimum = Number(schedulePolicy?.min_refresh_seconds ?? 3600);
      const fallback = refreshOptions[0]?.seconds ?? 3600;
      const next = refreshOptions.find((opt) => opt.seconds >= minimum)?.seconds ?? fallback;
      setRefreshSecs(next);
    }
  }, [refreshOptions, refreshSecs, schedulePolicy?.min_refresh_seconds]);

  const doSearch = useCallback(
    (text: string) => {
      if (!text.trim()) { setSearchResults([]); return; }
      void searchAirports(serverUrl, text).then(setSearchResults).catch(() => {});
    },
    [serverUrl]
  );

  const onQueryChange = useCallback(
    (text: string) => {
      setQuery(text);
      if (searchTimer.current) clearTimeout(searchTimer.current);
      searchTimer.current = setTimeout(() => doSearch(text), 300);
    },
    [doSearch]
  );

  const apply = useCallback(async () => {
    Keyboard.dismiss();
    setApplying(true);
    setApplyError(null);
    try {
      const patch: ConfigPatch = { source, refresh_seconds: refreshSecs };
      if (selectedAirport) {
        patch.airport_iata = selectedAirport.iata;
        patch.airport_icao = selectedAirport.icao;
        if (selectedAirport.timezone) patch.timezone = selectedAirport.timezone;
      }
      onApplied(await patchConfig(serverUrl, patch));
    } catch (e) {
      setApplyError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  }, [onApplied, refreshSecs, selectedAirport, serverUrl, source]);

  const saveProfile = useCallback(async () => {
    if (!profileName.trim() || !selectedAirport) return;
    Keyboard.dismiss();
    const next: ConfigProfile[] = [
      ...profiles.filter((p) => p.name !== profileName.trim()),
      {
        id: String(Date.now()),
        name: profileName.trim(),
        iata: selectedAirport.iata,
        icao: selectedAirport.icao,
        timezone: selectedAirport.timezone,
        source,
        refresh_seconds: refreshSecs
      }
    ];
    await saveProfiles(next);
    onProfilesChange(next);
    setProfileName("");
  }, [onProfilesChange, profileName, profiles, refreshSecs, selectedAirport, source]);

  const deleteProfile = useCallback(
    async (id: string) => {
      const next = profiles.filter((p) => p.id !== id);
      await saveProfiles(next);
      onProfilesChange(next);
    },
    [onProfilesChange, profiles]
  );

  const applyProfile = useCallback(
    async (p: ConfigProfile) => {
      Keyboard.dismiss();
      setApplyingProfileId(p.id);
      setApplyError(null);
      try {
        const patch: ConfigPatch = {
          airport_iata: p.iata,
          airport_icao: p.icao,
          timezone: p.timezone,
          source: p.source,
          refresh_seconds: p.refresh_seconds
        };
        onApplied(await patchConfig(serverUrl, patch));
      } catch (e) {
        setApplyError(e instanceof Error ? e.message : String(e));
      } finally {
        setApplyingProfileId(null);
      }
    },
    [onApplied, serverUrl]
  );

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={() => {
        Keyboard.dismiss();
        onClose();
      }}
    >
      <KeyboardAvoidingView
        style={styles.configSheetKeyboard}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
      <View style={styles.configSheetBg}>
        <View style={styles.configSheet}>
          <View style={styles.configSheetHandle} />
          <View style={styles.configSheetHeader}>
            <Text style={styles.configSheetTitle}>CONFIGURE SERVER</Text>
            <Pressable
              onPress={() => {
                Keyboard.dismiss();
                onClose();
              }}
              style={styles.configSheetClose}
            >
              <MaterialCommunityIcons name="close" size={20} color={palette.textMuted} />
            </Pressable>
          </View>

          <ScrollView
            style={styles.configSheetScroll}
            contentContainerStyle={styles.configSheetScrollContent}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive"
          >
            <Text style={styles.configSectionLabel}>AIRPORT</Text>
            <TextInput
              style={styles.configSearchInput}
              placeholder="Search by name, IATA or city…"
              placeholderTextColor={palette.textDim}
              value={query}
              onChangeText={onQueryChange}
              autoCapitalize="characters"
              returnKeyType="search"
            />
            {searchResults.length > 0 && (
              <View style={styles.configSearchResults}>
                {searchResults.map((r, index) => (
                  <Pressable
                    key={airportResultKey(r, index)}
                    style={[
                      styles.configSearchRow,
                      selectedAirport?.iata === r.iata && styles.configSearchRowSelected
                    ]}
                    onPress={() => {
                      Keyboard.dismiss();
                      setSelectedAirport(r);
                      setQuery("");
                      setSearchResults([]);
                    }}
                  >
                    <Text style={styles.configSearchIata}>{r.iata}</Text>
                    <View style={styles.configSearchInfo}>
                      <Text style={styles.configSearchName} numberOfLines={1}>{r.name}</Text>
                      <Text style={styles.configSearchMeta}>{r.city} · {r.country}</Text>
                    </View>
                  </Pressable>
                ))}
              </View>
            )}
            {selectedAirport ? (
              <View style={styles.configSelectedAirport}>
                <MaterialCommunityIcons name="check-circle" size={14} color={palette.green} />
                <Text style={styles.configSelectedText}>
                  {selectedAirport.iata}
                  {selectedAirport.icao ? ` / ${selectedAirport.icao}` : ""}
                  {selectedAirport.name ? ` — ${selectedAirport.name}` : ""}
                </Text>
              </View>
            ) : null}

            <Text style={styles.configSectionLabel}>DATA SOURCE</Text>
            <View style={styles.configSegControl}>
              {(["real", "virtual"] as const).map((opt) => (
                <Pressable
                  key={opt}
                  style={[styles.configSegOption, source === opt && styles.configSegOptionActive]}
                  onPress={() => setSource(opt)}
                >
                  <Text style={[styles.configSegText, source === opt && styles.configSegTextActive]}>
                    {opt === "real" ? "REAL" : "VIRTUAL / VATSIM"}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Text style={styles.configSectionLabel}>REFRESH INTERVAL</Text>
            <View style={styles.configIntervalGrid}>
              {refreshOptions.map((opt) => (
                <Pressable
                  key={opt.seconds}
                  style={[styles.configIntervalCell, refreshSecs === opt.seconds && styles.configIntervalCellActive]}
                  onPress={() => setRefreshSecs(opt.seconds)}
                >
                  <Text style={[styles.configIntervalText, refreshSecs === opt.seconds && styles.configIntervalTextActive]}>
                    {opt.label}
                  </Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.configPolicyText}>
              {schedulePolicy?.community_shared && source === "real"
                ? schedulePolicy.reason || "Community Relay uses hourly-or-slower shared schedule snapshots to protect upstream providers."
                : "Refresh choices are 15, 30, 45, and 60 minutes, then longer options. Shorter values keep local displays fresh; longer values are kinder to schedule providers."}
            </Text>

            <Text style={styles.configSectionLabel}>PROFILES</Text>
            {profiles.length > 0 && (
              <View style={styles.configProfileList}>
                {profiles.map((p, index) => {
                  const isApplyingThis = applyingProfileId === p.id;
                  return (
                    <View key={profileKey(p, index)} style={styles.configProfileRow}>
                      <Pressable
                        style={styles.configProfileLoad}
                        onPress={() => void applyProfile(p)}
                        disabled={applyingProfileId !== null}
                      >
                        <Text style={styles.configProfileName}>{p.name}</Text>
                        <Text style={styles.configProfileMeta}>
                          {p.iata} · {p.source === "virtual" ? "VATSIM" : "REAL"} · {formatInterval(p.refresh_seconds)}
                        </Text>
                      </Pressable>
                      {isApplyingThis
                        ? <ActivityIndicator size="small" color={palette.blue2} style={{ marginRight: 14 }} />
                        : (
                          <Pressable
                            onPress={() => void deleteProfile(p.id)}
                            style={styles.configProfileDelete}
                            disabled={applyingProfileId !== null}
                          >
                            <MaterialCommunityIcons name="trash-can-outline" size={16} color={palette.textDim} />
                          </Pressable>
                        )
                      }
                    </View>
                  );
                })}
              </View>
            )}
            <View style={styles.configSaveRow}>
              <TextInput
                style={styles.configProfileInput}
                placeholder="Profile name…"
                placeholderTextColor={palette.textDim}
                value={profileName}
                onChangeText={setProfileName}
              />
              <Pressable
                style={[styles.configSaveBtn, (!profileName.trim() || !selectedAirport) && styles.configSaveBtnDisabled]}
                onPress={() => void saveProfile()}
                disabled={!profileName.trim() || !selectedAirport}
              >
                <Text style={styles.configSaveBtnText}>SAVE</Text>
              </Pressable>
            </View>

            {applyError ? <Text style={styles.configErrorText}>{applyError}</Text> : null}
            <Pressable
              style={[styles.configApplyBtn, applying && styles.configApplyBtnBusy]}
              onPress={() => void apply()}
              disabled={applying}
            >
              {applying
                ? <ActivityIndicator size="small" color={blueButtonInk()} />
                : <Text style={styles.configApplyBtnText}>APPLY TO SERVER</Text>
              }
            </Pressable>
            <View style={{ height: 36 }} />
          </ScrollView>
        </View>
      </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function statusBadgeStyle(tone: StatusTone) {
  switch (tone) {
    case "departed":
      return styles.status_departed;
    case "boarding":
      return styles.status_boarding;
    case "delayed":
      return styles.status_delayed;
    case "cancelled":
      return styles.status_cancelled;
    case "scheduled":
    default:
      return styles.status_scheduled;
  }
}

function statusTextStyle(tone: StatusTone) {
  switch (tone) {
    case "departed":
      return styles.statusText_departed;
    case "boarding":
      return styles.statusText_boarding;
    case "delayed":
      return styles.statusText_delayed;
    case "cancelled":
      return styles.statusText_cancelled;
    case "scheduled":
    default:
      return styles.statusText_scheduled;
  }
}
