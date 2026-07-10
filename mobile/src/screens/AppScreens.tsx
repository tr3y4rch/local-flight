import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import {
  ActivityIndicator,
  Animated,
  Easing,
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
import Svg, { Circle, ClipPath, Defs, G, Line, Path, Polygon, Polyline, Text as SvgText } from "react-native-svg";
import { CameraView, useCameraPermissions, type BarcodeScanningResult } from "expo-camera";

import { BeaconToolsMark } from "../components/BeaconToolsMark";
import { BrandWordmark } from "../components/Brand";
import { getConfig, getDoc, getHealth, getMobileSummary, getRootHealth, normalizeServerUrl, patchConfig, searchAirports } from "../api/client";
import { testRemoteCompanionProbe, type RemoteCompanionProbeResult } from "../api/remoteCompanion";
import { activateStandalone, resolveStandaloneAirport, searchStandaloneAirports } from "../api/standalone";
import {
  accessibleButton,
  compactTapTargetHitSlop,
  hideFromAccessibility,
  tapTargetHitSlop,
  useReducedMotionPreference
} from "../accessibility/mobileA11y";
import type {
  AppConfig,
  AppState,
  AirportResolved,
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
  MatrixRuntimeConfigSave,
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
import { pairingFingerprintProblem, pairingServerUrlProblem, parsePairingLink, type PairingLinkResult } from "../domain/pairing";
import { projectBlip, projectLatLonToScope, type ProjectedRadarPoint } from "../domain/radar";
import {
  deriveWidgetPreviewSnapshot,
  type WidgetFlightPreview,
  type WidgetPreviewSnapshot
} from "../domain/widgets";
import type { FeedbackTone, HistoryWindow, ProjectedBlip, RadarRadius, StatusTone } from "../domain/types";
import {
  loadMobileRelayInstallId,
  type ConfigProfile,
  type MobileDiagnosticsMode,
  type MobileRadarDrawingLayers,
  type MobileSetupMode,
  type MobileWidgetPreferences,
  type MobileWeatherDisplayMode,
  type RemoteCompanionGrant,
  type StandaloneAirport,
  saveProfiles
} from "../storage/settings";
import { LOCAL_FLIGHT_BRAND_ASSETS } from "../theme/brandAssets";
import { palette, styles } from "../theme/styleBridge";
import {
  ACTION_ICONS,
  LocalFlightIcon,
  SETUP_ICONS,
  TOOL_ICONS,
  type LocalFlightIconName,
  weatherIconForMetar
} from "../theme/icons";
import {
  MOBILE_SKIN_OPTIONS,
  MOBILE_THEME_OPTIONS,
  type MobileSkin,
  type MobileThemeMode
} from "../theme/tokens";
import { hapticLight, hapticSelection } from "../utils/haptics";
import { usePressScale } from "../utils/usePressScale";

type AppIconName = LocalFlightIconName;
export type DocSlug = "readme" | "install" | "display-modes" | "privacy" | "changelog";
export type ActivityStatus = {
  label: string;
  detail?: string;
  tone?: "sync" | "warn" | "ok";
};
export type ConnectionState = "lan" | "remote" | "live" | "retrying" | "offline";

const DOC_SOURCES: Record<DocSlug, { title: string; detail: string; externalUrl: string; externalLabel: string }> = {
  readme: {
    title: "Project Website",
    detail: "Friendly overview, path chooser, previews, support, and source links",
    externalUrl: "https://beacontools.cc/local-flight",
    externalLabel: "Open online"
  },
  install: {
    title: "Install Guide",
    detail: "Platform setup, Pi modes, source checkout, and mobile testing",
    externalUrl: "https://beacontools.cc/local-flight#install",
    externalLabel: "Open online"
  },
  "display-modes": {
    title: "Display Modes",
    detail: "Native, browser, Pi, mobile, and Matrix display choices",
    externalUrl: "https://beacontools.cc/local-flight#display-modes",
    externalLabel: "Open online"
  },
  privacy: {
    title: "Privacy",
    detail: "What stays local and what diagnostics can send",
    externalUrl: "https://beacontools.cc/privacy",
    externalLabel: "Open privacy policy"
  },
  changelog: {
    title: "Changelog",
    detail: "Release history and beta notes",
    externalUrl: "https://beacontools.cc/local-flight#release-notes",
    externalLabel: "Open online"
  }
};

function solidButtonInk(): string {
  return palette.themeMode === "light" && palette.skin === "high_contrast" ? "#ffffff" : "#051009";
}

function blueButtonInk(): string {
  return palette.themeMode === "light" && ["standard", "technical", "high_contrast"].includes(palette.skin) ? "#ffffff" : "#051009";
}

function flightRowAccessibilityLabel(row: FidsRow): string {
  const flight = cleanInfoValue(row.flight_display) || cleanInfoValue(row.callsign) || "Unknown flight";
  const route = cleanInfoValue(row.route_display) || cleanInfoValue(row.route_primary) || "unknown route";
  const time = cleanInfoValue(row.display_time) || cleanInfoValue(row.time_primary) || "time unavailable";
  const status = cleanInfoValue(row.status_display) || "status unavailable";
  const gate = cleanInfoValue(row.terminal_gate_display) || cleanInfoValue(row.gate_display) || cleanInfoValue(row.gate);
  const aircraft = cleanInfoValue(row.aircraft_type);
  return [flight, route, time, status, gate ? `gate ${gate}` : null, aircraft ? `aircraft ${aircraft}` : null]
    .filter(Boolean)
    .join(", ");
}

function radarBlipAccessibilityLabel(blip: RadarBlip): string {
  const title = cleanInfoValue(blip.display_title) || cleanInfoValue(blip.flight_number) || cleanInfoValue(blip.callsign) || "Tracked aircraft";
  const status = cleanInfoValue(blip.radar_status_label) || cleanInfoValue(blip.status) || cleanInfoValue(blip.radar_phase);
  const distance = blip.distance_nm != null ? `${blip.distance_nm.toFixed(1)} nautical miles` : null;
  const altitude = cleanInfoValue(blip.altitude_display) || (blip.altitude_ft != null ? formatFeetValue(blip.altitude_ft) : formatAltitudeFeet(blip.altitude_m));
  return [title, status, distance, altitude].filter(Boolean).join(", ");
}
const RADAR_GROUND_CLIP_ID = "mobile-radar-ground-clip";
const RADAR_SWEEP_CLIP_ID = "mobile-radar-sweep-clip";
const RADAR_SWEEP_WIDTH_DEG = 72;
const RADAR_SWEEP_INTERVAL_MS = 80;
const RADAR_SWEEP_STEP_DEG = 1.92;
const RADAR_BLIP_FADE_DEG = 75;
const RADAR_BLIP_BASE_OPACITY = 0.42;

export function ScreenActivity({
  activity,
  compact = false
}: {
  activity: ActivityStatus | null | undefined;
  compact?: boolean;
}) {
  if (!activity) return null;

  const toneStyle =
    activity.tone === "warn"
      ? styles.activityPillWarn
      : activity.tone === "ok"
        ? styles.activityPillOk
        : styles.activityPillSync;
  const iconColor = activity.tone === "warn" ? palette.amber : activity.tone === "ok" ? palette.green : palette.blue;

  return (
    <View
      style={[styles.activityPill, compact && styles.activityPillCompact, toneStyle]}
      accessibilityRole="text"
      accessibilityLabel={[activity.label, activity.detail].filter(Boolean).join(". ")}
    >
      {compact ? null : (
        <View style={styles.activitySpinnerWrap}>
          <ActivityIndicator size="small" color={iconColor} />
        </View>
      )}
      <View style={styles.activityCopy}>
        <Text style={styles.activityLabel}>{compact ? activity.label.replace(/^Talking to /i, "") : activity.label}</Text>
        {!compact && activity.detail ? <Text style={styles.activityDetail}>{activity.detail}</Text> : null}
      </View>
    </View>
  );
}

function pairingUrlFromQrPayload(rawValue: string): PairingLinkResult | { error: string } {
  const trimmed = String(rawValue || "").trim();
  const parsed = parsePairingLink(rawValue);
  if (!parsed && !/^https?:\/\//i.test(trimmed)) {
    return { error: "QR did not contain a Local Flight pairing link or LAN server URL." };
  }
  const serverUrl = parsed?.serverUrl || normalizeServerUrl(trimmed);
  const problem = pairingServerUrlProblem(serverUrl);
  if (problem) {
    return { error: problem };
  }
  return parsed || { serverUrl, source: "manual" };
}

function PairingScannerSheet({
  visible,
  onClose,
  onPairingUrl
}: {
  visible: boolean;
  onClose: () => void;
  onPairingUrl: (pairing: PairingLinkResult) => void;
}) {
  const [permission, requestPermission] = useCameraPermissions();
  const [scanned, setScanned] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!visible) return;
    setScanned(false);
    setMessage(null);
  }, [visible]);

  const ensurePermission = useCallback(async () => {
    const result = await requestPermission();
    if (!result.granted) {
      setMessage("Camera access is needed only to scan the Local Flight pairing QR. You can still enter the server URL manually.");
    }
  }, [requestPermission]);

  useEffect(() => {
    if (!visible || permission?.granted || permission?.canAskAgain === false) return;
    void ensurePermission();
  }, [ensurePermission, permission?.canAskAgain, permission?.granted, visible]);

  const handleScan = useCallback((result: BarcodeScanningResult) => {
    if (scanned) return;
    setScanned(true);
    const parsed = pairingUrlFromQrPayload(result.data || "");
    if ("error" in parsed) {
      setMessage(parsed.error);
      setScanned(false);
      hapticSelection();
      return;
    }
    hapticLight();
    onPairingUrl(parsed);
  }, [onPairingUrl, scanned]);

  return (
    <Modal visible={visible} transparent presentationStyle="overFullScreen" animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable
          style={styles.sheetBackdropPress}
          onPress={onClose}
          {...accessibleButton({ label: "Close pairing scanner" })}
        />
        <View style={[styles.sheetCard, styles.pairingScannerSheet]}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>PAIR MOBILE</Text>
              <Text style={styles.sheetTitle}>Scan Local Flight QR</Text>
            </View>
            <Pressable
              style={styles.sheetAction}
              onPress={onClose}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: "Close pairing scanner" })}
            >
              <Text style={styles.sheetActionText}>CLOSE</Text>
            </Pressable>
          </View>

          <View style={styles.pairingScannerBody}>
            {permission?.granted ? (
              <View style={styles.pairingCameraFrame}>
                <CameraView
                  style={styles.pairingCamera}
                  facing="back"
                  barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
                  onBarcodeScanned={scanned ? undefined : handleScan}
                  accessibilityLabel="Camera preview for Local Flight pairing QR code"
                />
                <View style={styles.pairingScannerReticle} pointerEvents="none">
                  <View style={styles.pairingScannerCorner} />
                </View>
              </View>
            ) : (
              <View style={styles.pairingPermissionCard}>
                <LocalFlightIcon name={SETUP_ICONS.scan} size={28} color={palette.blue2} />
                <Text style={styles.pairingPermissionTitle}>Camera permission</Text>
                <Text style={styles.pairingPermissionBody}>
                  Scan the QR shown by the desktop or Pi app, or close this sheet and enter the LAN URL manually.
                </Text>
                <Pressable
                  style={styles.connectButton}
                  onPress={() => void ensurePermission()}
                  {...accessibleButton({
                    label: "Allow camera",
                    hint: "Requests camera permission to scan Local Flight pairing QR codes."
                  })}
                >
                  <Text style={styles.connectButtonText}>ALLOW CAMERA</Text>
                </Pressable>
              </View>
            )}

            <Text style={styles.pairingScannerHint}>
              Point the camera at the Local Flight pairing QR. The QR should contain a localflight:// pairing link or a plain LAN server URL.
            </Text>
            {message ? <Text style={[styles.feedbackMessage, styles.feedbackMessageError]}>{message}</Text> : null}
          </View>
        </View>
      </View>
    </Modal>
  );
}

type AdminSettingsSection = "health" | "devices" | "reports" | "developer";
type MatrixSettingsSection = "status" | "look" | "runtime" | "motion";
type CompanionSetupStep =
  | "welcome"
  | "mode"
  | "pairing"
  | "server"
  | "airport"
  | "policy"
  | "diagnostics"
  | "ready";
type SetupUrlCheckState = "idle" | "checking" | "ok" | "error" | "invalid";
type DocHeading = {
  id: string;
  level: 1 | 2;
  title: string;
  index: number;
};
type CompanionSetupResult = {
  mode: "lan_companion";
  serverUrl: string;
  diagnosticsMode: MobileDiagnosticsMode;
  config: AppConfig;
  state: AppState;
};
type StandaloneSetupResult = {
  mode: "standalone";
  relayInstallId: string;
  relayActivationToken: string;
  airport: StandaloneAirport;
  diagnosticsMode: MobileDiagnosticsMode;
  activationStatus: string;
};
type MobileSetupResult = CompanionSetupResult | StandaloneSetupResult;

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
    keyedPart(row.movement_key),
    keyedPart(row.id),
    keyedPart(row.callsign),
    keyedPart(row.event_time),
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

function isVirtualFidsRow(row: FidsRow): boolean {
  const value = `${row.detail_mode || ""} ${row.source_hint || ""}`.toLowerCase();
  return value.includes("virtual") || value.includes("vatsim");
}

function airlineInfoFrames(row: FidsRow): RowInfoFrame[] {
  if (isVirtualFidsRow(row)) {
    return uniqueInfoFrames([
      row.callsign ? { label: "CALLSIGN", value: row.callsign, tone: "accent" } : null,
      row.aircraft_type && row.aircraft_type !== "-" ? { label: "A/C", value: row.aircraft_type.toUpperCase(), tone: "accent" } : null,
      row.flight_rules ? { label: "RULES", value: row.flight_rules, tone: "muted" } : null,
      row.planned_altitude ? { label: "CRUISE", value: row.planned_altitude, tone: "muted" } : null,
      row.altitude_ft != null ? { label: "ALT", value: formatFeetValue(row.altitude_ft), tone: "muted" } : null,
      row.ground_speed_kt != null ? { label: "GS", value: `${Math.round(row.ground_speed_kt)} kt`, tone: "muted" } : null,
      row.squawk || row.transponder ? { label: "XPDR", value: row.squawk || row.transponder || "", tone: "muted" } : null,
      row.source_hint ? { label: "DATA", value: row.source_hint, tone: "muted" } : null
    ]);
  }
  const soldAs = (row.sold_as || []).slice(0, 3).join(" / ");
  return uniqueInfoFrames([
    row.airline_display ? { label: "AIRLINE", value: row.airline_display, tone: "accent" } : null,
    row.flight_number && row.flight_number !== row.flight_display ? { label: "FLIGHT", value: row.flight_number, tone: "accent" } : null,
    row.codeshare_display ? { label: "ALSO", value: row.codeshare_display.replace(/^also\s+/i, ""), tone: "muted" } : null,
    soldAs ? { label: "SOLD AS", value: soldAs, tone: "muted" } : null,
    row.marketing_flight_number ? { label: "MARKETED", value: row.marketing_flight_number, tone: "muted" } : null,
    row.operating_callsign && row.operating_callsign !== row.callsign ? { label: "OPERATED", value: row.operating_callsign, tone: "muted" } : null,
    row.callsign && row.callsign !== row.flight_display ? { label: "CALLSIGN", value: row.callsign, tone: "muted" } : null
  ]);
}

function rowDetailFrames(row: FidsRow, gateLabel: string): RowInfoFrame[] {
  if (isVirtualFidsRow(row)) {
    return uniqueInfoFrames([
      row.aircraft_type && row.aircraft_type !== "-" ? { label: "A/C", value: row.aircraft_type.toUpperCase(), tone: "accent" } : null,
      row.flight_rules ? { label: "RULES", value: row.flight_rules, tone: "accent" } : null,
      row.planned_altitude ? { label: "CRUISE", value: row.planned_altitude, tone: "muted" } : null,
      row.altitude_ft != null ? { label: "ALT", value: formatFeetValue(row.altitude_ft), tone: "muted" } : null,
      row.ground_speed_kt != null ? { label: "GS", value: `${Math.round(row.ground_speed_kt)} kt`, tone: "muted" } : null,
      row.squawk || row.transponder ? { label: "XPDR", value: row.squawk || row.transponder || "", tone: "accent" } : null,
      row.status_kind ? { label: "STATE", value: row.status_kind.replace(/_/g, " "), tone: "muted" } : null,
      row.live_hint ? { label: "TRACK", value: row.live_hint, tone: "muted" } : null
    ]);
  }
  return uniqueInfoFrames([
    gateLabel ? { label: "GATE", value: gateLabel, tone: "accent" } : null,
    row.terminal_display ? { label: "TERM", value: row.terminal_display, tone: "accent" } : null,
    row.aircraft_type ? { label: "A/C", value: row.aircraft_type.toUpperCase(), tone: "accent" } : null,
    row.time_delta_text ? { label: "TIME", value: row.time_delta_text, tone: row.delay_kind === "bad" ? "warn" : "muted" } : null,
    row.status_kind ? { label: "STATE", value: row.status_kind.replace(/_/g, " "), tone: row.delay_kind === "bad" ? "warn" : "muted" } : null,
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
  return metar?.flight_cat || metar?.flight_category || metar?.category || "--";
}

function metarRawText(metar: Metar | null | undefined): string {
  return metar?.raw_text || "";
}

function metarTemperature(metar: Metar | null | undefined): string {
  if (typeof metar?.temperature_c === "number") {
    return `${Math.round(metar.temperature_c)}°C`;
  }
  if (typeof metar?.temp_c === "number") {
    return `${Math.round(metar.temp_c)}°C`;
  }
  const raw = metarRawText(metar);
  const match = raw.match(/\b(M?\d{1,2})\/(M?\d{1,2})\b/);
  if (!match) return "--";
  return `${(match[1] || "").replace("M", "-")}°C`;
}

function weatherCondition(metar: Metar | null | undefined): string {
  const semantic = metar?.weather_label || metar?.weather_summary || metar?.weather?.label || metar?.weather?.summary;
  if (semantic) return semantic;
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

function weatherSummaryForMode(metar: Metar | null | undefined, mode: MobileWeatherDisplayMode): string {
  if (!metar) return "Asking Local Flight";
  if (mode === "vatsim") return metar.raw_text || "Raw METAR unavailable";
  if (mode === "pilot") {
    const chips = weatherChips(metar);
    const visible = chips.slice(0, 3).map((chip) => `${chip.label} ${chip.value}`);
    return visible.length ? visible.join(" · ") : metar.weather_summary || metar.decoded_summary || metar.raw_text || "Weather available";
  }
  return metar.weather_summary || metar.decoded_summary || weatherCondition(metar);
}

function weatherChips(metar: Metar | null | undefined): Array<{ label: string; value: string }> {
  if (metar?.weather_chips?.length) {
    return metar.weather_chips;
  }
  if (metar?.weather?.chips?.length) {
    return metar.weather.chips;
  }
  const chips = parseMetarChips(metar?.raw_text || "");
  if (!chips.some((chip) => chip.label === "TMP")) {
    const temp = metarTemperature(metar);
    if (temp !== "--") chips.push({ label: "TMP", value: temp });
  }
  const qnh = metar?.qnh_hpa ?? metar?.altimeter_hpa;
  if (!chips.some((chip) => chip.label === "QNH") && qnh) {
    chips.push({ label: "QNH", value: String(qnh) });
  }
  const wind = metar?.wind_display || metar?.wind;
  if (!chips.some((chip) => chip.label === "WND") && wind) {
    chips.push({ label: "WND", value: wind });
  }
  return chips;
}

export function Header({
  variant = "expanded",
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
  onOpenBoard,
}: {
  variant?: "expanded" | "compact";
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
  onOpenDetail: (callsign: string, row?: FidsRow) => void;
  onOpenActions: (row: FidsRow) => void;
  onTogglePin: (row: FidsRow) => void;
  onOpenConfig: () => void;
  onOpenWeather: () => void;
  onOpenBoard: () => void;
}) {
  const category = metarCategory(metar);
  const accent = metarAccentColor(category);
  const longAirportName = airportName.length > 24;
  const hasAirportCode = Boolean(airportCode && airportCode !== "---");
  const effectiveConnectionState = connectionState || (!live ? "offline" : error ? "offline" : "live");
  const connectionAccent =
    effectiveConnectionState === "lan" || effectiveConnectionState === "live"
      ? palette.green
      : effectiveConnectionState === "remote"
        ? palette.blue2
        : effectiveConnectionState === "retrying"
          ? palette.amber
          : palette.red;
  const connectionLabel =
    effectiveConnectionState === "lan"
      ? "LAN"
      : effectiveConnectionState === "remote"
        ? "REMOTE"
        : effectiveConnectionState === "live"
          ? "LIVE"
          : effectiveConnectionState === "retrying"
            ? "RETRYING"
            : "OFFLINE";
  const railAirportCode = hasAirportCode ? airportCode : airportIcao;
  const dotOpacity = useRef(new Animated.Value(1)).current;
  const reduceMotion = useReducedMotionPreference();

  useEffect(() => {
    if (reduceMotion) {
      dotOpacity.setValue(1);
      return;
    }
    if (effectiveConnectionState === "offline") { dotOpacity.setValue(1); return; }
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(dotOpacity, { toValue: 0.2, duration: 850, useNativeDriver: true }),
        Animated.timing(dotOpacity, { toValue: 1, duration: 850, useNativeDriver: true })
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [dotOpacity, effectiveConnectionState, reduceMotion]);

  const renderTopRail = (isCompactHeader: boolean) => {
    if (!isCompactHeader) {
      return (
        <View style={[styles.headerCompactTopRail, styles.headerBoardTopRail]}>
          <Pressable
            style={[styles.headerCompactBrand, styles.headerBoardBrand]}
            onPress={() => {
              hapticSelection();
              onOpenBoard();
            }}
            hitSlop={tapTargetHitSlop}
            {...accessibleButton({
              label: "Local Flight board",
              hint: "Returns to the main flight board."
            })}
          >
            <BrandWordmark
              color={palette.text}
              size={19}
              numberOfLines={1}
              adjustsFontSizeToFit
              minimumFontScale={0.78}
            >
              Local Flight
            </BrandWordmark>
          </Pressable>
          <Pressable
            style={styles.headerBoardClock}
            onPress={() => {
              hapticSelection();
              onOpenBoard();
            }}
            hitSlop={tapTargetHitSlop}
            {...accessibleButton({
              label: `Open board. UTC ${utcTime}. Local ${localTime}.`,
              hint: "Returns to the main flight board."
            })}
          >
            <Text style={styles.headerCompactUtc}>{utcTime}<Text style={styles.utcSuffix}>Z</Text></Text>
            <Text style={styles.headerCompactLocal}>{localTime} <Text style={styles.localSuffix}>LT</Text></Text>
          </Pressable>
        </View>
      );
    }

    return (
      <View style={styles.headerCompactTopRail}>
        <View style={styles.headerCompactRightColumn}>
          <Pressable
            style={styles.headerCompactClock}
            onPress={() => {
              hapticSelection();
              onOpenBoard();
            }}
            hitSlop={tapTargetHitSlop}
            {...accessibleButton({
              label: `Open board. UTC ${utcTime}. Local ${localTime}.`,
              hint: "Returns to the main flight board."
            })}
          >
            <Text style={styles.headerCompactUtc}>{utcTime}<Text style={styles.utcSuffix}>Z</Text></Text>
            <Text style={styles.headerCompactLocal}>{localTime} <Text style={styles.localSuffix}>LT</Text></Text>
          </Pressable>
          {isCompactHeader && pinnedRow ? (
            <CompactRailFlightSummary
              row={pinnedRow}
              isPinned={islandPinned}
              live={live}
              onOpenDetail={onOpenDetail}
              onOpenActions={onOpenActions}
            />
          ) : null}
        </View>
        <View style={styles.headerCompactRow}>
          <Pressable
            style={styles.headerCompactBrand}
            onPress={() => {
              hapticSelection();
              onOpenBoard();
            }}
            hitSlop={tapTargetHitSlop}
            {...accessibleButton({
              label: "Open Local Flight board",
              hint: "Returns to the main flight board."
            })}
          >
            <BrandWordmark
              color={palette.text}
              size={19}
              numberOfLines={1}
              adjustsFontSizeToFit
              minimumFontScale={0.78}
            >
              Local Flight
            </BrandWordmark>
            <Text style={styles.headerCompactSubline} numberOfLines={1}>
              {isCompactHeader ? "TAP FOR BOARD" : "BOARD HOME"}
            </Text>
          </Pressable>
        </View>
        <Pressable
          style={styles.headerCompactWeather}
          onPress={() => {
            hapticLight();
            onOpenWeather();
          }}
          hitSlop={tapTargetHitSlop}
          {...accessibleButton({
            label: `Weather ${category}, ${metarTemperature(metar)}. UTC ${utcTime}. Local ${localTime}.`,
            hint: "Opens weather and control information."
          })}
        >
          <CompactRailWeather metar={metar} accent={accent} airportCode={railAirportCode} />
        </Pressable>
      </View>
    );
  };

  if (variant === "compact") {
    return (
      <View style={[styles.header, styles.headerCompact]}>
        <View style={[styles.headerAccentBar, { backgroundColor: accent }]} />
        {renderTopRail(true)}
      </View>
    );
  }

  return (
    <View style={styles.header}>
      <View style={[styles.headerAccentBar, { backgroundColor: accent }]} />
      {renderTopRail(false)}

      <View style={[styles.airportHeroRow, styles.airportHeroRowUnified, longAirportName && styles.airportHeroRowStacked]}>
        <Pressable
          style={[styles.airportHeroPressable, longAirportName && styles.airportHeroPressableStacked]}
          onPress={() => {
            hapticSelection();
            onOpenConfig();
          }}
          hitSlop={tapTargetHitSlop}
          {...accessibleButton({
            label: `${airportName}. ${airportLocation || "Airport location unavailable"}`,
            hint: "Opens airport and server configuration."
          })}
        >
          <Text
            style={[styles.airportHeroName, longAirportName && styles.airportHeroNameCompact]}
            numberOfLines={2}
            ellipsizeMode="tail"
          >
            {airportName}
          </Text>
          {airportLocation ? (
            <Text style={styles.airportHeroLocation} numberOfLines={1}>{airportLocation}</Text>
          ) : null}
          <View style={styles.configHint}>
            <LocalFlightIcon name={TOOL_ICONS.control} size={10} color={palette.textDim} />
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
          style={[styles.boardHeroWeatherCard, longAirportName && styles.boardHeroWeatherCardStacked]}
          onPress={() => {
            hapticLight();
            onOpenWeather();
          }}
          hitSlop={tapTargetHitSlop}
          {...accessibleButton({
            label: `Weather ${category}, ${metarTemperature(metar)}, ${weatherCondition(metar)}.`,
            hint: "Opens weather and control information."
          })}
        >
          <BoardHeroWeatherCard metar={metar} accent={accent} airportCode={railAirportCode} mode={weatherDisplayMode} />
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

function CompactRailWeather({
  metar,
  accent,
  airportCode
}: {
  metar: Metar | null;
  accent: string;
  airportCode: string;
}) {
  const category = metarCategory(metar);
  const temp = metarTemperature(metar);
  const iconName = weatherIconForMetar(metar);
  const iconOpacity = useRef(new Animated.Value(1)).current;
  const iconScale = useRef(new Animated.Value(1)).current;
  const [displayIcon, setDisplayIcon] = useState(iconName);
  const previousIcon = useRef(iconName);
  const reduceMotion = useReducedMotionPreference();

  useEffect(() => {
    if (previousIcon.current === iconName) return;
    previousIcon.current = iconName;
    if (reduceMotion) {
      setDisplayIcon(iconName);
      iconOpacity.setValue(1);
      iconScale.setValue(1);
      return;
    }
    Animated.parallel([
      Animated.timing(iconOpacity, { toValue: 0, duration: 80, useNativeDriver: true }),
      Animated.timing(iconScale, { toValue: 0.82, duration: 80, useNativeDriver: true })
    ]).start(({ finished }) => {
      if (!finished) return;
      setDisplayIcon(iconName);
      Animated.parallel([
        Animated.timing(iconOpacity, { toValue: 1, duration: 180, useNativeDriver: true }),
        Animated.spring(iconScale, { toValue: 1, damping: 11, stiffness: 180, mass: 0.45, useNativeDriver: true })
      ]).start();
    });
  }, [iconName, iconOpacity, iconScale, reduceMotion]);

  return (
    <View style={[styles.weatherRailGroup, { borderColor: `${accent}44`, backgroundColor: `${accent}12` }]}>
      <View style={styles.weatherRailTop}>
        <Animated.View style={{ opacity: iconOpacity, transform: [{ scale: iconScale }] }}>
          <LocalFlightIcon name={displayIcon} size={14} color={accent} />
        </Animated.View>
        <Text style={styles.weatherRailTemp} numberOfLines={1}>{temp}</Text>
      </View>
      <View style={styles.weatherRailPills}>
        <Text style={[styles.weatherRailPill, { borderColor: `${accent}55`, color: accent }]} numberOfLines={1}>
          {category}
        </Text>
        <Text style={styles.weatherRailPill} numberOfLines={1}>
          {airportCode || "---"}
        </Text>
      </View>
    </View>
  );
}

function BoardHeroWeatherCard({
  metar,
  accent,
  airportCode,
  mode
}: {
  metar: Metar | null;
  accent: string;
  airportCode: string;
  mode: MobileWeatherDisplayMode;
}) {
  const category = metarCategory(metar);
  const temp = metarTemperature(metar);
  const modeOption = weatherModeOption(mode);
  const summary = boardWeatherSummaryForMode(metar, mode);
  const rawMode = mode === "vatsim";
  const iconName = weatherIconForMetar(metar);
  const iconScale = useRef(new Animated.Value(0.78)).current;
  const bubbleScale = useRef(new Animated.Value(0.96)).current;
  const bubbleOpacity = useRef(new Animated.Value(0)).current;
  const reduceMotion = useReducedMotionPreference();

  useEffect(() => {
    if (reduceMotion) {
      iconScale.setValue(1);
      bubbleScale.setValue(1);
      bubbleOpacity.setValue(1);
      return;
    }
    iconScale.setValue(0.78);
    bubbleScale.setValue(0.96);
    bubbleOpacity.setValue(0);
    Animated.parallel([
      Animated.timing(bubbleOpacity, { toValue: 1, duration: 150, useNativeDriver: true }),
      Animated.spring(bubbleScale, { toValue: 1, damping: 14, stiffness: 180, mass: 0.55, useNativeDriver: true }),
      Animated.sequence([
        Animated.timing(iconScale, { toValue: 1.12, duration: 130, useNativeDriver: true }),
        Animated.spring(iconScale, { toValue: 1, damping: 10, stiffness: 210, mass: 0.45, useNativeDriver: true })
      ])
    ]).start();
  }, [bubbleOpacity, bubbleScale, iconScale, reduceMotion]);

  return (
    <Animated.View
      style={[
        styles.boardHeroWeatherInner,
        {
          borderColor: `${accent}44`,
          backgroundColor: `${accent}12`,
          opacity: bubbleOpacity,
          transform: [{ scale: bubbleScale }]
        }
      ]}
    >
      <View style={styles.boardHeroWeatherTop}>
        <Animated.View style={{ transform: [{ scale: iconScale }] }}>
          <LocalFlightIcon name={iconName} size={18} color={accent} />
        </Animated.View>
        <Text style={styles.boardHeroWeatherTemp} numberOfLines={1}>{temp}</Text>
      </View>
      <Text
        style={[styles.boardHeroWeatherCondition, rawMode && styles.boardHeroWeatherConditionRaw]}
        numberOfLines={rawMode ? 2 : 1}
        adjustsFontSizeToFit={rawMode}
        minimumFontScale={0.68}
      >
        {summary}
      </Text>
      <View style={styles.boardHeroWeatherPills}>
        <Text style={[styles.boardHeroWeatherPill, { borderColor: `${accent}55`, color: accent }]} numberOfLines={1}>
          {category}
        </Text>
        <Text style={styles.boardHeroWeatherPill} numberOfLines={1}>
          {modeOption.label}
        </Text>
        <Text style={styles.boardHeroWeatherPill} numberOfLines={1}>
          {airportCode || "---"}
        </Text>
      </View>
    </Animated.View>
  );
}

function boardWeatherSummaryForMode(metar: Metar | null, mode: MobileWeatherDisplayMode): string {
  if (mode === "vatsim") {
    return metarRawText(metar) || "Raw METAR unavailable";
  }
  if (mode === "pilot") {
    const chips = weatherChips(metar)
      .filter((chip) => ["WND", "VIS", "CLD", "QNH"].includes(chip.label))
      .slice(0, 4);
    if (chips.length) {
      return chips.map((chip) => `${chip.label} ${chip.value}`).join(" · ");
    }
    return weatherSummaryForMode(metar, mode);
  }
  return weatherCondition(metar);
}

function railStatusShort(status: string): string {
  const short = statusShort(status);
  if (short === "SCHEDULED") return "SCH";
  if (short === "BOARDING") return "BRD";
  if (short === "DEPARTED") return "DEP";
  if (short === "ARRIVED") return "ARR";
  if (short === "DELAYED") return "DLY";
  if (short === "CANCELLED") return "CXL";
  return short.slice(0, 3);
}

function CompactRailFlightSummary({
  row,
  isPinned,
  live,
  onOpenDetail,
  onOpenActions
}: {
  row: FidsRow;
  isPinned: boolean;
  live: boolean;
  onOpenDetail: (callsign: string, row?: FidsRow) => void;
  onOpenActions: (row: FidsRow) => void;
}) {
  const tone = statusTone(row.status_display);
  const flightNumber = cleanInfoValue(row.flight_display) || cleanInfoValue(row.callsign) || "--";
  const statusColor =
    tone === "delayed" ? palette.amber :
      tone === "cancelled" ? palette.red :
        tone === "boarding" || tone === "departed" ? palette.green :
          palette.blue2;

  return (
    <Pressable
      style={[styles.headerCompactFlightChip, isPinned && styles.headerCompactFlightChipPinned]}
      onPress={() => {
        if (row.callsign) onOpenDetail(row.callsign, row);
      }}
      onLongPress={() => onOpenActions(row)}
      delayLongPress={360}
      hitSlop={compactTapTargetHitSlop}
      {...accessibleButton({
        label: flightRowAccessibilityLabel(row),
        hint: "Opens flight details. Long press for pin actions.",
        selected: isPinned
      })}
    >
      <Text style={[styles.headerCompactFlightText, { color: live ? palette.blue2 : palette.textDim }]} numberOfLines={1}>
        {row.view === "arrivals" ? "ARR" : "DEP"} {flightNumber}
      </Text>
      <Text style={[styles.headerCompactFlightStatus, { color: statusColor }]} numberOfLines={1}>
        {row.display_time || "--:--"} {railStatusShort(row.status_display)}
      </Text>
    </Pressable>
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
  onOpenDetail: (callsign: string, row?: FidsRow) => void;
  onOpenActions: (row: FidsRow) => void;
  onTogglePin: (row: FidsRow) => void;
}) {
  const glow = useRef(new Animated.Value(0)).current;
  const reduceMotion = useReducedMotionPreference();

  useEffect(() => {
    if (reduceMotion) {
      glow.setValue(0);
      return;
    }
    if (!live || !row) {
      glow.setValue(0);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(glow, { toValue: 1, duration: 2400, easing: Easing.inOut(Easing.quad), useNativeDriver: false }),
        Animated.timing(glow, { toValue: 0, duration: 2400, easing: Easing.inOut(Easing.quad), useNativeDriver: false })
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [glow, live, row, reduceMotion]);

  const glowBorder = glow.interpolate({
    inputRange: [0, 1],
    outputRange: [hexToRgba(palette.blue, 0.20), hexToRgba(palette.blue, 0.46)]
  });

  return (
    <Animated.View style={[styles.islandShell, row && styles.islandShellActive, live && row ? { borderColor: glowBorder } : null]}>
      <Pressable
        style={styles.islandPressable}
        delayLongPress={360}
        onLongPress={() => {
          if (row) onOpenActions(row);
        }}
        onPress={() => {
          if (row?.callsign) {
            onOpenDetail(row.callsign, row);
          }
        }}
        hitSlop={tapTargetHitSlop}
        {...accessibleButton({
          label: row ? flightRowAccessibilityLabel(row) : `No featured flight. Status ${live ? "ready" : "offline"}.`,
          hint: row ? "Opens flight details. Long press for pin actions." : "Shows current board status.",
          disabled: !row
        })}
      >
        <View style={styles.islandCompactRow}>
          <View style={styles.islandLead}>
            <LocalFlightIcon
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
          hitSlop={compactTapTargetHitSlop}
          {...accessibleButton({
            label: isPinned ? "Unpin featured flight" : "Pin featured flight",
            hint: flightRowAccessibilityLabel(row),
            selected: isPinned
          })}
        >
          <LocalFlightIcon
            name={isPinned ? "pin-off" : "pin-outline"}
            size={15}
            color={isPinned ? palette.amber : palette.blue2}
          />
        </Pressable>
      ) : null}
    </Animated.View>
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
  const rowGap = compactLandscape ? 3 : 5;
  const chromeEstimate = compactLandscape ? 132 : tabletLandscape ? 188 : 164;
  const fittedRowHeight = Math.floor((height - chromeEstimate - rowGap * Math.max(0, targetVisibleRows - 1)) / targetVisibleRows);
  const rowHeight = compactLandscape
    ? Math.max(38, Math.min(44, fittedRowHeight))
    : tabletLandscape
      ? Math.max(58, Math.min(66, fittedRowHeight))
      : Math.max(50, Math.min(58, fittedRowHeight));
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
  const chips = compact ? [] : weatherChips(metar).slice(0, 5);
  const modeOption = weatherModeOption(mode);

  return (
    <View style={[styles.fullscreenWeatherHero, compact && styles.fullscreenWeatherHeroCompact, { borderColor: `${accent}34`, backgroundColor: `${accent}0f` }]}>
      <View style={[styles.fullscreenWeatherIcon, compact && styles.fullscreenWeatherIconCompact, { borderColor: `${accent}44`, backgroundColor: `${accent}18` }]}>
        <LocalFlightIcon name={weatherIconForMetar(metar)} size={compact ? 18 : 24} color={accent} />
      </View>
      <View style={styles.fullscreenWeatherCopy}>
        <View style={styles.fullscreenWeatherTitleRow}>
          <Text style={[styles.fullscreenWeatherCategory, compact && styles.fullscreenWeatherCategoryCompact, { color: accent }]}>{category}</Text>
          <Text style={styles.fullscreenWeatherTemp}>{metarTemperature(metar)}</Text>
          <Text style={styles.fullscreenWeatherMode}>{modeOption.label}</Text>
        </View>
        <Text style={[styles.fullscreenWeatherSummary, compact && styles.fullscreenWeatherSummaryCompact]} numberOfLines={1}>{summary}</Text>
      </View>
      {!compact ? (
        <View style={styles.fullscreenWeatherChips}>
          {chips.map((chip, index) => (
            <View key={`fullscreen-weather-${chip.label}-${chip.value}-${index}`} style={styles.fullscreenWeatherChip}>
              <Text style={styles.fullscreenWeatherChipLabel}>{chip.label}</Text>
              <Text style={styles.fullscreenWeatherChipValue}>{chip.value}</Text>
            </View>
          ))}
        </View>
      ) : null}
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
  standalone = false,
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
  onOpenDetail: (callsign: string, row?: FidsRow) => void;
  onOpenActions: (row: FidsRow) => void;
  pinnedCallsign: string;
  standalone?: boolean;
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
  const hasRows = displayRows.length > 0;
  const showInlineActivity = Boolean(activity && !refreshing && (hasRows || !error));
  const showInlineError = Boolean(error && !refreshing);

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
          {showInlineActivity ? <ScreenActivity activity={activity} compact={hasRows} /> : null}
          {showInlineError ? <ScreenError message={error ?? ""} onRetry={onRefresh} retrying={false} /> : null}

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
        loading && !error && !activity && !refreshing ? (
          <ActivityIndicator color={palette.blue} style={styles.loader} />
        ) : standalone ? (
          <StandaloneEmptyState
            title="Standalone board waiting"
            body="Pull to refresh when you want a relay check. Auto-refresh stays slow to protect shared schedule tokens."
          />
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

function delayBucketColor(bucket: string): string {
  switch (bucket) {
    case "early":
      return palette.green;
    case "on_time":
      return palette.blue;
    case "delayed_warn":
      return palette.amber;
    case "delayed_bad":
      return palette.red;
    default:
      return hexToRgba(palette.textMuted, 0.45);
  }
}

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
  standalone = false,
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
  onOpenDetail: (callsign: string, row?: HistoryFlightRow) => void;
  standalone?: boolean;
  contentPaddingBottom: number;
}) {
  const flights = data?.flights || [];
  const hasRows = flights.length > 0;
  const showInlineActivity = Boolean(activity && !refreshing && (hasRows || !error));
  const showInlineError = Boolean(error && !refreshing);
  const maxAirlineCount = Math.max(...(summary?.top_airlines?.map((a) => a.count) || [1]), 1);
  const maxRouteCount = Math.max(...(summary?.top_routes?.map((r) => r.count) || [1]), 1);
  const maxAircraftCount = Math.max(...(summary?.top_aircraft?.map((a) => a.count) || [1]), 1);
  const standaloneStorage = data?.standalone_storage || summary?.standalone_storage || null;
  const pendingFutureRows = data?.pending_future_rows ?? standaloneStorage?.pending_future_rows ?? 0;
  const lastStoreRows = standaloneStorage?.last_store_rows || 0;
  const standaloneEmptyBody = standaloneStorage?.last_store_error
    ? `Local history write failed: ${standaloneStorage.last_store_error}`
    : pendingFutureRows > 0
      ? `${pendingFutureRows} stored board row${pendingFutureRows === 1 ? "" : "s"} are waiting for their movement time before they count as history.`
      : lastStoreRows > 0
        ? `${lastStoreRows} board row${lastStoreRows === 1 ? "" : "s"} were stored. Adjust filters or wait until the movement time has passed.`
        : "Standalone history is stored on this device after successful board refreshes.";

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
          {showInlineActivity ? <ScreenActivity activity={activity} compact={hasRows} /> : null}
          {showInlineError ? <ScreenError message={error ?? ""} onRetry={onRefresh} retrying={false} /> : null}

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
            <Pressable
              style={styles.historyApplyButton}
              onPress={onApplyFilters}
              {...accessibleButton({
                label: "Apply history filters",
                hint: "Refreshes the history analytics with the selected direction, time window, callsign, and airline filters."
              })}
            >
              <Text style={styles.historyApplyButtonText}>APPLY</Text>
            </Pressable>
          </View>

          {standalone && standaloneStorage ? (
            <View style={styles.historyPanel}>
              <Text style={styles.historyPanelTitle}>LOCAL STORAGE</Text>
              <InfoLine label="Airport key" value={standaloneStorage.airport_key || "---"} />
              <InfoLine label="Last store" value={standaloneStorage.last_store_at ? formatRelative(standaloneStorage.last_store_at) : "Not yet"} />
              <InfoLine label="Rows stored" value={String(standaloneStorage.last_store_rows || 0)} />
              <InfoLine label="Pending movement time" value={String(pendingFutureRows)} />
              {standaloneStorage.last_store_error ? <InfoLine label="Last error" value={standaloneStorage.last_store_error} /> : null}
            </View>
          ) : null}

          {summary ? (
            <>
              <View style={styles.historyKpiGrid}>
                <View style={styles.historyKpiCard}>
                  <Text style={styles.historyKpiLabel}>MOVEMENTS</Text>
                  <Text style={styles.historyKpiValue}>{summary.total || "-"}</Text>
                  <Text style={styles.historyKpiNote}>
                    {summary.raw_observation_rows ? `${summary.raw_observation_rows} observations` : `${historyWindowLabel(hours)} window`}
                  </Text>
                </View>
                <View style={styles.historyKpiCard}>
                  <Text style={styles.historyKpiLabel}>DEPART.</Text>
                  <Text style={[styles.historyKpiValue, { color: palette.blue }]}>{summary.departures ?? "-"}</Text>
                  <Text style={styles.historyKpiNote}>outbound moves</Text>
                </View>
                <View style={styles.historyKpiCard}>
                  <Text style={styles.historyKpiLabel}>ARRIVE.</Text>
                  <Text style={[styles.historyKpiValue, { color: palette.green }]}>{summary.arrivals ?? "-"}</Text>
                  <Text style={styles.historyKpiNote}>inbound moves</Text>
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
                        style={{ width: `${Math.max(b.pct || 0, b.count ? 1 : 0)}%` as unknown as number, backgroundColor: delayBucketColor(b.bucket) }}
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
                      color={delayBucketColor(b.bucket)}
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
              <InfoCard label="MOVES" value={data ? String(data.count) : "..."} />
              <InfoCard label="FILTER" value={direction.toUpperCase()} tone="green" />
              <InfoCard label="WINDOW" value={historyWindowLabel(hours)} tone="amber" />
            </View>
          )}
        </>
      }
      ListEmptyComponent={
        loading && !error && !activity && !refreshing ? (
          <ActivityIndicator color={palette.blue} style={styles.loader} />
        ) : standalone ? (
          <StandaloneEmptyState
            title="No mobile history yet"
            body={standaloneEmptyBody}
          />
        ) : (
          <Text style={styles.empty}>No recent movements yet. Once matching flight times pass, movements will appear here.</Text>
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

function RadarLayerControls({
  layers,
  standalone,
  onChange
}: {
  layers: MobileRadarDrawingLayers;
  standalone: boolean;
  onChange: (value: MobileRadarDrawingLayers) => void;
}) {
  const options: Array<{ key: keyof MobileRadarDrawingLayers; label: string; detail: string }> = [
    { key: "runways", label: "Runways", detail: "Airport runway geometry" },
    { key: "surface", label: "Surface", detail: "Aprons, stands and taxiway hints" },
    { key: "terrain", label: "Terrain", detail: "Relief/context, Mobile only" }
  ];

  return (
    <View style={styles.radarLayerPanel}>
      <View style={styles.radarLayerHeader}>
        <Text style={styles.radarLayerTitle}>RADAR DRAWINGS</Text>
        <Text style={styles.radarLayerHint}>
          {standalone ? "Standalone uses runway and surface snapshots only." : "Choose which map layers Mobile draws."}
        </Text>
      </View>
      <View style={styles.radarLayerChips}>
        {options.filter((item) => !standalone || item.key !== "terrain").map((item) => {
          const active = Boolean(layers[item.key]);
          return (
            <Pressable
              key={item.key}
              style={[styles.radarLayerChip, active && styles.radarLayerChipActive]}
              hitSlop={tapTargetHitSlop}
              onPress={() => {
                hapticSelection();
                onChange({ ...layers, [item.key]: !active });
              }}
              {...accessibleButton({
                label: `${active ? "Hide" : "Show"} ${item.label}`,
                hint: item.detail,
                selected: active
              })}
            >
              <View style={[styles.radarLayerDot, active && styles.radarLayerDotActive]} />
              <View style={styles.radarLayerCopy}>
                <Text style={[styles.radarLayerLabel, active && styles.radarLayerLabelActive]}>{item.label}</Text>
                <Text style={styles.radarLayerDetail}>{item.detail}</Text>
              </View>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function radarBlipIsGround(blip: RadarBlip): boolean {
  const phase = `${blip.radar_phase || ""} ${blip.radar_status || ""} ${blip.radar_status_label || ""} ${blip.status || ""}`.toLowerCase();
  return blip.on_ground === true || /\b(ground|surface|taxi|parked|gate)\b/.test(phase);
}

function radarBlipVisibleForRadius(blip: RadarBlip, radiusNm: RadarRadius): boolean {
  const quality = `${blip.source_quality || ""} ${blip.radar_status || ""} ${blip.radar_status_label || ""}`.toLowerCase();
  if (/lost|missing|invalid/.test(quality)) {
    return false;
  }
  if (radiusNm > 5 && radarBlipIsGround(blip)) {
    return false;
  }
  return true;
}

function radarDisplayBlips(blips: RadarBlip[], radiusNm: RadarRadius): RadarBlip[] {
  return blips.filter((blip) => radarBlipVisibleForRadius(blip, radiusNm));
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
  drawingLayers,
  standalone = false,
  onDrawingLayersChange,
  onOpenDetail,
  compact = false,
  radiusOptions = RADAR_RADII,
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
  drawingLayers: MobileRadarDrawingLayers;
  standalone?: boolean;
  onDrawingLayersChange: (value: MobileRadarDrawingLayers) => void;
  onOpenDetail: (callsign: string, blip?: RadarBlip) => void;
  compact?: boolean;
  radiusOptions?: RadarRadius[];
  contentPaddingBottom: number;
}) {
  const blips = radarDisplayBlips(data?.blips || [], radiusNm);
  const hasRows = blips.length > 0;
  const showInlineActivity = Boolean(activity && !refreshing && (hasRows || !error));
  const showInlineError = Boolean(error && !refreshing);
  const effectiveLayerCount = standalone
    ? { runways: drawingLayers.runways, surface: drawingLayers.surface, terrain: false }
    : drawingLayers;
  const groundFeatureCount = radarGroundFeatureCount(groundData, effectiveLayerCount);
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
          {showInlineActivity ? <ScreenActivity activity={activity} compact={hasRows} /> : null}
          {showInlineError ? <ScreenError message={error ?? ""} onRetry={onRefresh} retrying={false} /> : null}

          <View style={styles.metricRow}>
            <InfoCard label="BLIPS" value={data ? String(blips.length) : "..."} />
            <InfoCard label="SOURCE" value={compactSourceLabel(data?.source) || "WAIT"} tone="green" />
            <InfoCard label="RANGE" value={`${radiusNm} NM`} tone="amber" />
            <InfoCard
              label="GROUND"
              value={groundFeatureCount ? String(groundFeatureCount) : groundUnavailable ? "OFF" : "WAIT"}
              tone={groundFeatureCount ? "green" : groundUnavailable ? "amber" : "blue"}
            />
          </View>

          <RadarLegendOverlay source={data?.source} ageSeconds={ageSeconds} />

          <RadarWeatherCard metar={metar} mode={weatherDisplayMode} />

          <RadarScope
            data={data}
            groundData={groundData}
            groundError={groundError}
            radiusNm={radiusNm}
            radiusOptions={radiusOptions}
            drawingLayers={drawingLayers}
            standalone={standalone}
            onRadiusChange={onRadiusChange}
            onOpenDetail={onOpenDetail}
            compact={compact}
          />

          <RadarLayerControls
            layers={drawingLayers}
            standalone={standalone}
            onChange={onDrawingLayersChange}
          />

          {hasRows ? (
            <View style={styles.radarLegend}>
              <View style={styles.radarLegendHeader}>
                <Text style={styles.radarLegendTitle}>AIRCRAFT</Text>
                <View style={styles.radarLegendMetaWrap}>
                  <Text style={styles.radarLegendSource}>{blips.length} TRACKS</Text>
                  <Text style={styles.radarLegendAge}>{radiusNm} NM</Text>
                </View>
              </View>
              <Text style={styles.radarLayerHint}>
                Tap a track for details. Ground tracks are hidden automatically on wider ranges.
              </Text>
            </View>
          ) : null}
        </>
      }
      ListEmptyComponent={
        loading && !error && !activity && !refreshing ? (
          <ActivityIndicator color={palette.blue} style={styles.loader} />
        ) : standalone ? (
          <StandaloneEmptyState
            title="Standalone radar waiting"
            body="Pull to refresh for the next relay radar check. Standalone radar is intentionally capped to short ranges."
          />
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
          <LocalFlightIcon name={weatherIconForMetar(metar)} size={21} color={accent} />
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

function MatrixScreen({
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
  const hasRows = rows.length > 0;
  const showInlineActivity = Boolean(activity && !refreshing && (hasRows || !error));
  const showInlineError = Boolean(error && !refreshing);

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
      {showInlineActivity ? <ScreenActivity activity={activity} compact={hasRows} /> : null}
      {showInlineError ? <ScreenError message={error ?? ""} onRetry={onRefresh} retrying={false} /> : null}

      <View style={styles.cardStack}>
        <HiddenToolHeader
          icon={TOOL_ICONS.matrix}
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
                  {...accessibleButton({
                    label: `Apply Matrix preset ${item.label}`,
                    hint: item.meta,
                    selected: active,
                    disabled,
                    busy: applying
                  })}
                >
                  <View style={styles.matrixPresetTop}>
                    <Text style={[styles.matrixPresetLabel, active && styles.matrixPresetLabelActive]}>{item.label}</Text>
                    {applying ? (
                      <ActivityIndicator size="small" color={palette.blue2} />
                    ) : active ? (
                      <LocalFlightIcon name={ACTION_ICONS.configured} size={14} color={palette.green} />
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
                  {...accessibleButton({
                    label: `Use Matrix ${item.label} palette`,
                    hint: item.meta,
                    selected: matrixPalette === item.id
                  })}
                >
                  <Text style={[styles.optionChipLabel, matrixPalette === item.id && styles.optionChipLabelActive]}>{item.label}</Text>
                  <Text style={[styles.optionChipMeta, matrixPalette === item.id && styles.optionChipMetaActive]}>{item.meta}</Text>
                  <View style={styles.paletteDots}>
                    {[item.colors.green, item.colors.white, item.colors.cyan, item.colors.amber, item.colors.red].map((color, index) => (
                      <View key={`${item.id}-${index}-${color}`} style={[styles.paletteDot, { backgroundColor: color }]} />
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
          onPress={() => {
            hapticLight();
            onReset();
          }}
          disabled={saving}
          {...accessibleButton({
            label: "Reset Matrix draft",
            disabled: saving
          })}
        >
          <Text style={styles.matrixActionSecondaryText}>RESET</Text>
        </Pressable>
        <Pressable
          style={[styles.matrixActionButton, styles.matrixActionPrimary, saving && styles.configApplyBtnBusy]}
          onPress={() => {
            hapticLight();
            onSave();
          }}
          disabled={saving}
          {...accessibleButton({
            label: "Save Matrix settings to server",
            disabled: saving,
            busy: saving
          })}
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
  const { scale, onPressIn, onPressOut } = usePressScale(0.92);
  return (
    <Animated.View style={{ transform: [{ scale }] }}>
      <Pressable
        onPress={() => {
          hapticSelection();
          onPress();
        }}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        hitSlop={tapTargetHitSlop}
        {...accessibleButton({
          label,
          selected: active
        })}
        style={[styles.dirButton, active && styles.dirButtonActive]}
      >
        <Text style={[styles.dirButtonText, active && styles.dirButtonTextActive]}>{label}</Text>
      </Pressable>
    </Animated.View>
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
  const { scale, onPressIn, onPressOut } = usePressScale(0.92);
  return (
    <Animated.View style={{ transform: [{ scale }] }}>
      <Pressable
        onPress={() => {
          hapticSelection();
          onPress();
        }}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        hitSlop={tapTargetHitSlop}
        {...accessibleButton({
          label,
          hint: meta,
          selected: active
        })}
        style={[styles.optionChip, active && styles.optionChipActive]}
      >
        <Text style={[styles.optionChipLabel, active && styles.optionChipLabelActive]}>{label}</Text>
        <Text style={[styles.optionChipMeta, active && styles.optionChipMetaActive]}>{meta}</Text>
      </Pressable>
    </Animated.View>
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
  onOpenDetail: (callsign: string, row?: FidsRow) => void;
  onOpenActions: (row: FidsRow) => void;
}) {
  const delayTagStyle =
    row.delay_kind === "early" ? styles.fidsDelayTagEarly
    : row.delay_kind === "warn" ? styles.fidsDelayTagWarn
    : row.delay_kind === "bad" ? styles.fidsDelayTagBad
    : null;
  const gateLabel = cleanInfoValue(row.terminal_gate_display) || cleanInfoValue(row.gate_display) || cleanInfoValue(row.gate);
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
      onPress={() => onOpenDetail(row.callsign, row)}
      hitSlop={compactTapTargetHitSlop}
      {...accessibleButton({
        label: flightRowAccessibilityLabel(row),
        hint: "Opens flight details. Long press for pin actions.",
        selected: isPinned
      })}
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
            {isPinned ? <LocalFlightIcon name={ACTION_ICONS.pin} size={11} color={palette.amber} /> : null}
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
          <StatusBadge
            status={row.status_display}
            statusClass={row.status_class}
            statusKind={row.status_kind}
            toneHint={row.tone}
            delayKind={row.delay_kind}
            compact
          />
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
  const reduceMotion = useReducedMotionPreference();
  const frame = frames.length ? frames[Math.abs(cycleTick + offset) % frames.length] : null;
  const frameKey = frame ? `${frame.label}:${frame.value}` : "empty";

  useEffect(() => {
    if (reduceMotion) {
      opacity.setValue(1);
      return;
    }
    opacity.setValue(0);
    Animated.timing(opacity, { toValue: 1, duration: 240, useNativeDriver: true }).start();
  }, [frameKey, opacity, reduceMotion]);

  if (!frame) return null;

  const lift = reduceMotion ? 0 : opacity.interpolate({ inputRange: [0, 1], outputRange: [4, 0] });
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
  const gateLabel = cleanInfoValue(row.terminal_gate_display) || cleanInfoValue(row.gate_display) || cleanInfoValue(row.gate);
  const airlineFrames = airlineInfoFrames(row);
  const detailFrames = rowDetailFrames(row, gateLabel);
  const routePrimary = cleanInfoValue(row.route_primary) || routeName(row.route_display);
  const routeSecondary = cleanInfoValue(row.route_code) || cleanInfoValue(row.route_caption) || routeMeta(row);
  const rowOffset = index % 3;

  return (
    <View style={[styles.fullscreenFidsRow, compact && styles.fullscreenFidsRowCompact, isPinned && styles.fullscreenFidsRowPinned, { minHeight: rowHeight }]}>
      <Text
        style={[styles.fullscreenFidsTime, compact && styles.fullscreenFidsTimeCompact, styles.fullscreenFidsTimeColumn, compact && styles.fullscreenFidsTimeColumnCompact]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.72}
      >
        {row.time_primary || row.display_time || "--:--"}
      </Text>
      <View style={[styles.fullscreenFidsFlightCell, styles.fullscreenFidsFlightColumn, compact && styles.fullscreenFidsFlightColumnCompact]}>
        <Text style={[styles.fullscreenFidsFlight, compact && styles.fullscreenFidsFlightCompact]} numberOfLines={1}>{row.flight_display || row.callsign || "-"}</Text>
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
        <Text style={[styles.fullscreenFidsRouteName, compact && styles.fullscreenFidsRouteNameCompact]} numberOfLines={1}>{routePrimary}</Text>
        <Text style={[styles.fullscreenFidsRouteMeta, compact && styles.fullscreenFidsRouteMetaCompact]} numberOfLines={1}>{routeSecondary}</Text>
      </View>
      <View style={[styles.fullscreenFidsStatusCell, compact && styles.fullscreenFidsStatusColumnCompact]}>
        <StatusBadge
          status={row.status_display}
          statusClass={row.status_class}
          statusKind={row.status_kind}
          toneHint={row.tone}
          delayKind={row.delay_kind}
        />
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

function HistoryRow({ row, onOpenDetail }: { row: HistoryFlightRow; onOpenDetail: (callsign: string, row?: HistoryFlightRow) => void }) {
  return (
    <Pressable
      style={styles.historyRow}
      onPress={() => onOpenDetail(row.callsign, row)}
      hitSlop={tapTargetHitSlop}
      {...accessibleButton({
        label: [
          row.flight_number || row.callsign || "Unknown flight",
          historyRouteLabel(row),
          row.status || "status unavailable",
          row.gate ? `gate ${row.gate}` : null
        ].filter(Boolean).join(", "),
        hint: "Opens flight details."
      })}
    >
      <View style={styles.historyTimeBox}>
        <Text style={styles.historyTime}>{formatClock(row.event_time || row.sched_time || row.snapshot_ts)}</Text>
        <Text style={styles.historyDate}>{formatClock(row.sched_time)}</Text>
      </View>

      <View style={styles.historyMain}>
        <Text style={styles.historyFlight}>{row.flight_number || row.callsign || "-"}</Text>
        <Text style={styles.historyRoute} numberOfLines={1}>{historyRouteLabel(row)}</Text>
        <Text style={styles.historyMeta} numberOfLines={1}>
          {row.aircraft_type || "Aircraft pending"} {row.gate ? `- Gate ${row.gate}` : ""}
          {row.delay_minutes ? ` - ${row.delay_minutes}m delay` : ""}
          {row.observation_count && row.observation_count > 1 ? ` - ${row.observation_count} obs` : ""}
        </Text>
      </View>

      <View style={styles.historyTrail}>
        <Text style={styles.historyDir}>{row.direction}</Text>
        <StatusBadge status={row.status} statusClass={row.status} compact />
      </View>
    </Pressable>
  );
}

function RadarBlipRow({ blip, onOpenDetail }: { blip: RadarBlip; onOpenDetail: (callsign: string, blip?: RadarBlip) => void }) {
  const title = cleanInfoValue(blip.display_title) || cleanInfoValue(blip.flight_number) || cleanInfoValue(blip.callsign) || "TRACK";
  const subtitle = cleanInfoValue(blip.callsign) && cleanInfoValue(blip.callsign) !== title
    ? cleanInfoValue(blip.callsign)
    : cleanInfoValue(blip.operating_callsign) || cleanInfoValue(blip.source_quality) || "LIVE";
  const status = cleanInfoValue(blip.radar_status_label) || cleanInfoValue(blip.status) || cleanInfoValue(blip.radar_phase) || "Tracked target";
  const altitude = cleanInfoValue(blip.altitude_display) || (blip.altitude_ft != null ? formatFeetValue(blip.altitude_ft) : formatAltitudeFeet(blip.altitude_m));
  const speed = cleanInfoValue(blip.speed_display) || (blip.speed_kt != null ? formatKnotsValue(blip.speed_kt) : formatSpeedKnots(blip.speed_ms));
  const motion = cleanInfoValue(blip.motion_display) || [altitude, speed, cleanInfoValue(blip.vertical_rate_display)].filter((item) => item && item !== "-").join(" · ") || "-";
  const route = cleanInfoValue(blip.route_display);
  const distance = blip.distance_nm != null ? `${blip.distance_nm.toFixed(1)} NM` : "";
  const meta = [route, distance, sourceMetric(blip.source_quality || blip.source)].filter((item) => item && item !== "-").join(" · ");
  const trail = cleanInfoValue(blip.radar_phase) || (blip.enriched ? "LIVE" : "RAW");

  return (
    <Pressable
      style={styles.historyRow}
      onPress={() => onOpenDetail(blip.callsign, blip)}
      hitSlop={tapTargetHitSlop}
      {...accessibleButton({
        label: radarBlipAccessibilityLabel(blip),
        hint: "Opens aircraft details."
      })}
    >
      <View style={styles.historyTimeBox}>
        <Text style={styles.historyTime}>{title}</Text>
        <Text style={styles.historyDate}>{subtitle}</Text>
      </View>

      <View style={styles.historyMain}>
        <Text style={styles.historyFlight}>{status}</Text>
        <Text style={styles.historyRoute} numberOfLines={1}>
          {motion}
        </Text>
        <Text style={styles.historyMeta} numberOfLines={1}>
          {meta || `${formatHeading(blip.heading_deg ?? blip.track_deg ?? blip.heading)} ${blip.on_ground ? "- on ground" : ""}`}
        </Text>
      </View>

      <View style={styles.historyTrail}>
        <Text style={styles.historyDir}>{trail.toUpperCase()}</Text>
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
  radiusOptions = RADAR_RADII,
  drawingLayers,
  standalone = false,
  onRadiusChange,
  compact = false,
  onOpenDetail
}: {
  data: RadarResponse | null;
  groundData: RadarMapResponse | null;
  groundError: string | null;
  radiusNm: RadarRadius;
  radiusOptions?: RadarRadius[];
  drawingLayers: MobileRadarDrawingLayers;
  standalone?: boolean;
  onRadiusChange: (value: RadarRadius) => void;
  compact?: boolean;
  onOpenDetail: (callsign: string, blip?: RadarBlip) => void;
}) {
  const [scopeSize, setScopeSize] = useState(280);
  const reduceMotion = useReducedMotionPreference();
  const pinchRef = useRef<{ distance: number; index: number } | null>(null);
  const effectiveLayers = standalone
    ? { runways: drawingLayers.runways, surface: drawingLayers.surface, terrain: false }
    : drawingLayers;
  const groundFeatureCount = radarGroundFeatureCount(groundData, effectiveLayers);
  const groundUnavailable = radarGroundUnavailable(groundData, groundError);
  const groundStatus = groundFeatureCount
    ? `${groundFeatureCount} ground drawings`
    : groundUnavailable
      ? "Ground layer unavailable"
      : "Ground layer waiting";
  const [sweepDeg, setSweepDeg] = useState(0);
  const projectedInRange = (data?.blips || [])
    .filter((blip) => radarBlipVisibleForRadius(blip, radiusNm))
    .map((blip) => data ? projectBlip(blip, data.center, radiusNm, scopeSize) : null)
    .filter((item): item is ProjectedBlip => Boolean(item));
  const projected = projectedInRange
    .map((item) => ({ item, opacity: radarSweepOpacity(item.angleDeg, sweepDeg) }))
    .sort((a, b) => a.item.distanceNm - b.item.distanceNm);

  useEffect(() => {
    const timer = setInterval(() => {
      setSweepDeg((value) => (value + RADAR_SWEEP_STEP_DEG) % 360);
    }, RADAR_SWEEP_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

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
      index: radiusOptions.indexOf(radiusNm)
    };
  }, [radiusNm, radiusOptions]);

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
    if (ratio > 1.14 && state.index < radiusOptions.length - 1) {
      const nextIndex = state.index + 1;
      onRadiusChange(radiusOptions[nextIndex]!);
      pinchRef.current = { distance, index: nextIndex };
    } else if (ratio < 0.88 && state.index > 0) {
      const nextIndex = state.index - 1;
      onRadiusChange(radiusOptions[nextIndex]!);
      pinchRef.current = { distance, index: nextIndex };
    }
  }, [handlePinchStart, onRadiusChange, radiusOptions]);

  const radiusLabel = `${radiusNm} NM`;

  return (
    <View
      style={styles.scopeCard}
      onLayout={(event) => setMeasuredSize(event.nativeEvent.layout.width)}
    >
      <Text style={styles.scopeTitle}>RADAR SCOPE</Text>
      <View
        style={[styles.scopeFrame, { width: scopeSize, height: scopeSize }]}
        accessibilityLabel={`Radar scope, ${radiusNm} nautical mile range, ${projectedInRange.length} aircraft in range.`}
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
          drawingLayers={effectiveLayers}
        />
        <RadarSweepLayer scopeSize={scopeSize} sweepDeg={sweepDeg} reducedMotion={reduceMotion} />
        <View style={styles.scopeRingOuter} />
        <View style={styles.scopeRingMid} />
        <View style={styles.scopeRingInner} />
        <View style={styles.scopeCrossVertical} />
        <View style={styles.scopeCrossHorizontal} />
        <View style={styles.scopeCenterDot} />

        {projected.map(({ item, opacity }, index) => (
          <Pressable
            key={`scope-${radarBlipKey(item.blip, index)}`}
            style={[styles.scopeDotWrap, { left: item.left, top: item.top, opacity }]}
            onPress={() => onOpenDetail(item.blip.callsign, item.blip)}
            hitSlop={compactTapTargetHitSlop}
            {...accessibleButton({
              label: radarBlipAccessibilityLabel(item.blip),
              hint: "Opens aircraft details."
            })}
          >
            <View style={[styles.scopeDot, { backgroundColor: radarTone(item.blip) }]} />
            {index < 10 ? (
              <Text style={styles.scopeLabel} numberOfLines={1}>
                {item.blip.callsign}
              </Text>
            ) : null}
          </Pressable>
        ))}

        {!data || projectedInRange.length === 0 ? (
          <View style={styles.scopeEmpty}>
            <Text style={styles.scopeEmptyText}>No targets in range</Text>
          </View>
        ) : null}
      </View>
      <View style={styles.scopeFooter}>
        <Text style={styles.scopeHint}>Pinch to zoom or choose a range below.</Text>
        <Text style={[styles.scopeGroundStatus, groundUnavailable && !groundFeatureCount && styles.scopeGroundStatusWarn]}>
          {groundStatus}
        </Text>
        <View style={styles.scopeChipRow}>
          {radiusOptions.map((item) => (
            <Pressable
              key={item}
              onPress={() => onRadiusChange(item)}
              style={[styles.scopeChip, radiusNm === item && styles.scopeChipActive]}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({
                label: `Set radar range to ${item} nautical miles`,
                selected: radiusNm === item
              })}
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

function RadarSweepLayer({ scopeSize, sweepDeg, reducedMotion }: { scopeSize: number; sweepDeg: number; reducedMotion: boolean }) {
  const center = scopeSize / 2;
  const radius = scopeSize * 0.44;
  const closing = radarSweepPoint(scopeSize, RADAR_SWEEP_WIDTH_DEG);
  const sweepFillOpacity = reducedMotion ? 0.07 : 0.16;
  const sweepSheenOpacity = reducedMotion ? 0.018 : 0.035;
  const sweepLineOpacity = reducedMotion ? 0.34 : 0.58;
  const sweepEdgeOpacity = reducedMotion ? 0.16 : 0.28;

  return (
    <Animated.View
      pointerEvents="none"
      {...hideFromAccessibility()}
      style={[
        styles.scopeSweepLayer,
        {
          width: scopeSize,
          height: scopeSize,
          transform: [{ rotate: `${sweepDeg}deg` }]
        }
      ]}
    >
      <Svg width={scopeSize} height={scopeSize} viewBox={`0 0 ${scopeSize} ${scopeSize}`}>
        <Defs>
          <ClipPath id={RADAR_SWEEP_CLIP_ID}>
            <Circle cx={center} cy={center} r={radius} />
          </ClipPath>
        </Defs>
        <G clipPath={`url(#${RADAR_SWEEP_CLIP_ID})`}>
          <Path d={radarSweepSectorPath(scopeSize)} fill={hexToRgba(palette.blue2, sweepFillOpacity)} />
          <Path d={radarSweepSectorPath(scopeSize)} fill={hexToRgba(palette.text, sweepSheenOpacity)} />
          <Line
            x1={center}
            y1={center}
            x2={center}
            y2={center - radius}
            stroke={hexToRgba(palette.blue2, sweepLineOpacity)}
            strokeWidth={1.4}
            strokeLinecap="round"
          />
          <Line
            x1={center}
            y1={center}
            x2={closing.x}
            y2={closing.y}
            stroke={hexToRgba(palette.blue2, sweepEdgeOpacity)}
            strokeWidth={1}
            strokeLinecap="round"
          />
        </G>
      </Svg>
    </Animated.View>
  );
}

function RadarGroundLayer({
  groundData,
  center,
  radiusNm,
  scopeSize,
  drawingLayers
}: {
  groundData: RadarMapResponse | null;
  center: RadarResponse["center"] | null;
  radiusNm: RadarRadius;
  scopeSize: number;
  drawingLayers: MobileRadarDrawingLayers;
}) {
  if (!groundData || !center) {
    return null;
  }

  const surfaceFeatures = drawingLayers.surface ? radarDrawableFeatures(groundData.surface_features) : [];
  const runwayFeatures = drawingLayers.runways ? radarDrawableFeatures(groundData.runways) : [];
  const terrainFeatures = drawingLayers.terrain ? radarDrawableFeatures(groundData.terrain?.features) : [];
  if (!surfaceFeatures.length && !runwayFeatures.length && !terrainFeatures.length) {
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
        {terrainFeatures.map((feature, index) => (
          <RadarGroundFeature
            key={radarGroundFeatureKey(feature, index, "terrain")}
            feature={feature}
            center={center}
            radiusNm={radiusNm}
            scopeSize={scopeSize}
            layer="terrain"
          />
        ))}
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
  layer: "surface" | "runway" | "terrain";
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

function radarSweepSectorPath(scopeSize: number): string {
  const center = scopeSize / 2;
  const radius = scopeSize * 0.44;
  const start = radarSweepPoint(scopeSize, 0);
  const end = radarSweepPoint(scopeSize, RADAR_SWEEP_WIDTH_DEG);
  const largeArc = RADAR_SWEEP_WIDTH_DEG > 180 ? 1 : 0;
  return [
    `M ${center.toFixed(1)} ${center.toFixed(1)}`,
    `L ${start.x.toFixed(1)} ${start.y.toFixed(1)}`,
    `A ${radius.toFixed(1)} ${radius.toFixed(1)} 0 ${largeArc} 1 ${end.x.toFixed(1)} ${end.y.toFixed(1)}`,
    "Z"
  ].join(" ");
}

function radarSweepPoint(scopeSize: number, clockwiseDegreesFromNorth: number): { x: number; y: number } {
  const center = scopeSize / 2;
  const radius = scopeSize * 0.44;
  const radians = ((clockwiseDegreesFromNorth - 90) * Math.PI) / 180;
  return {
    x: center + Math.cos(radians) * radius,
    y: center + Math.sin(radians) * radius
  };
}

function radarSweepOpacity(angleDeg: number, sweepDeg: number): number {
  const age = (sweepDeg - angleDeg + 360) % 360;
  if (age >= 356 || age <= 5) {
    return 1;
  }
  if (age <= RADAR_BLIP_FADE_DEG) {
    return Math.max(RADAR_BLIP_BASE_OPACITY, 1 - ((age - 5) / (RADAR_BLIP_FADE_DEG - 5)) * (1 - RADAR_BLIP_BASE_OPACITY));
  }
  return RADAR_BLIP_BASE_OPACITY;
}

function radarDrawableFeatures(features: RadarMapFeature[] | undefined): RadarMapFeature[] {
  return (features || []).filter((feature) => {
    const points = feature.points || [];
    return Array.isArray(points) && points.length >= 2;
  });
}

function radarGroundFeatureCount(groundData: RadarMapResponse | null, layers: MobileRadarDrawingLayers): number {
  if (!groundData) {
    return 0;
  }
  return (
    (layers.runways ? radarDrawableFeatures(groundData.runways).length : 0) +
    (layers.surface ? radarDrawableFeatures(groundData.surface_features).length : 0) +
    (layers.terrain ? radarDrawableFeatures(groundData.terrain?.features).length : 0)
  );
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
  layer: "surface" | "runway" | "terrain",
  radiusNm: RadarRadius
): { fill: string; stroke: string; strokeWidth: number } {
  const kind = String(feature.kind || "").toLowerCase();
  if (layer === "terrain") {
    return {
      fill: hexToRgba(palette.green, 0.055),
      stroke: hexToRgba(palette.green, radiusNm <= 5 ? 0.18 : 0.12),
      strokeWidth: radiusNm <= 5 ? 1 : 0.7
    };
  }
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
  const phase = `${blip.radar_phase || ""} ${blip.radar_status || ""} ${blip.radar_status_label || ""}`.toLowerCase();
  const quality = `${blip.source_quality || ""}`.toLowerCase();
  if (/lost|stale|missing|unknown/.test(quality)) return palette.red;
  if (blip.on_ground) return palette.amber;
  if (/arrival|approach|land/.test(phase)) return palette.green;
  if (/depart|climb/.test(phase)) return palette.blue2;
  if (/taxi|ground/.test(phase)) return palette.amber;
  if (blip.enriched || /live|matched|adsb|vatsim/.test(quality)) return palette.green;
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

function compactSourceLabel(value?: string | null): string {
  const text = String(value || "").trim().toLowerCase();
  if (!text) return "";
  if (text.includes("adsbexchange")) return text.includes("live") ? "ADS-B LIVE" : "ADS-B";
  if (text.includes("opensky")) return "OPENSKY";
  if (text.includes("vatsim")) return "VATSIM";
  if (text.includes("aerodatabox")) return "AEROBOX";
  if (text.includes("aviationstack")) return "AVSTACK";
  return sourceMetric(text);
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

function formatFeetValue(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "-";
  return `${Math.round(value).toLocaleString()} ft`;
}

function formatKnotsValue(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "-";
  return `${Math.round(value)} kt`;
}

function joinedIdentityList(values?: string[] | null): string {
  return (values || []).filter(Boolean).slice(0, 4).join(" / ") || "-";
}

function DetailSkeleton() {
  const opacity = useRef(new Animated.Value(0.5)).current;
  const reduceMotion = useReducedMotionPreference();
  useEffect(() => {
    if (reduceMotion) {
      opacity.setValue(0.62);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.85, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.4, duration: 700, useNativeDriver: true })
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [opacity, reduceMotion]);

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
  history: Array<{ date: string; status?: string | null; delay_minutes?: number | null; gate?: string | null; source?: string | null; observations?: number | null }>;
  loading: boolean;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const virtualDetail = isVirtualFlightDetail(detail);
  const intel = detail?.intel || null;
  const identity = intel?.identity || {};
  const motion = intel?.motion || {};
  const aircraftIntel = intel?.aircraft || {};
  const opsIntel = intel?.operations || {};
  const plan = detail?.flight_plan || {};
  const sources = detail?.data_sources || {};
  const altitudeMeters = detail?.position?.altitude_geo_m ?? detail?.position?.altitude_baro_m ?? detail?.position?.altitude_m;
  const aircraftLabel = detail?.aircraft_type_full || aircraftIntel.full_type || aircraftIntel.model || detail?.aircraft_type || aircraftIntel.type || "";
  const operatingLabel = detail?.operating_callsign || identity.operating_callsign || detail?.callsign || callsign;
  const soldAsLabel = joinedIdentityList(detail?.sold_as || identity.sold_as);
  const terminalGate = detail?.terminal_gate_display || [opsIntel.terminal || detail?.terminal, opsIntel.gate || detail?.gate].filter(Boolean).join(" · ");
  const sourceFreshness = sources.snapshot_age_seconds != null
    ? formatAgeSeconds(sources.snapshot_age_seconds)
    : formatRelative(sources.snapshot_generated_at || intel?.source_evidence?.snapshot_generated_at);
  const positionFreshness = sources.position_age_seconds != null
    ? formatAgeSeconds(sources.position_age_seconds)
    : formatRelative(detail?.position?.last_contact || motion.last_contact);
  const delayBadgeStyle = delayBadgeStyleFor(detail?.delay_minutes);
  const delayBadgeText = !virtualDetail && detail?.delay_minutes != null
    ? (detail.delay_minutes > 0 ? `+${detail.delay_minutes}m` : `${detail.delay_minutes}m`)
    : null;
  const gateBadgeText = !virtualDetail && terminalGate
    ? terminalGate
    : null;

  return (
    <Modal visible={visible} animationType="slide" transparent presentationStyle="overFullScreen" statusBarTranslucent>
      <View style={styles.sheetBackdrop}>
        <Pressable
          style={styles.sheetBackdropPress}
          onPress={onClose}
          {...accessibleButton({ label: "Close flight detail" })}
        />
        <View style={styles.sheetCard}>
          <View style={styles.sheetHandle} />

          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>FLIGHT DETAIL</Text>
              <Text style={styles.sheetTitle}>{detail?.flight_display || identity.flight_display || detail?.flight_number || callsign || "TRACKED FLIGHT"}</Text>
              <Text style={styles.sheetSubtitle}>{detailRouteLabel(detail, callsign)}</Text>
            </View>

            <View style={styles.sheetActions}>
              <Pressable
                style={styles.sheetAction}
                onPress={onRefresh}
                hitSlop={tapTargetHitSlop}
                {...accessibleButton({ label: "Refresh flight detail" })}
              >
                <Text style={styles.sheetActionText}>REFRESH</Text>
              </Pressable>
              <Pressable
                style={styles.sheetAction}
                onPress={onClose}
                hitSlop={tapTargetHitSlop}
                {...accessibleButton({ label: "Close flight detail" })}
              >
                <Text style={styles.sheetActionText}>CLOSE</Text>
              </Pressable>
            </View>
          </View>

          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}>
            {loading && !detail ? <DetailSkeleton /> : null}

            {!loading && detail ? (
              <>
                <View style={styles.sheetSummary}>
                  <StatusBadge
                    status={detail.status || "Tracked"}
                    statusClass={detail.status || ""}
                    statusKind={intel?.timing?.status || detail.status || undefined}
                    delayKind={detail.delay_kind || undefined}
                  />
                  {delayBadgeText && delayBadgeStyle ? (
                    <Text style={[styles.sheetSummaryBadge, delayBadgeStyle]}>{delayBadgeText}</Text>
                  ) : null}
                  {gateBadgeText ? (
                    <Text style={[styles.sheetSummaryBadge, styles.sheetSummaryGateBadge]}>GATE {gateBadgeText}</Text>
                  ) : null}
                  <Text style={styles.sheetSummaryText}>
                    {virtualDetail
                      ? `VATSIM ${aircraftLabel || "aircraft"}`
                      : `${detail.airline || identity.airline_name || "Unknown carrier"} ${aircraftLabel ? `- ${aircraftLabel}` : ""}`}
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
                  <SheetMetric label={virtualDetail ? "RULES" : "AIRLINE"} value={virtualDetail ? (plan.flight_rules || "-") : (detail.airline_iata || identity.airline_iata || detail.airline || "-")} />
                  <SheetMetric label="CALLSIGN" value={detail.callsign || identity.callsign || callsign || "-"} />
                </View>
                {!virtualDetail ? (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="OPERATED" value={operatingLabel || "-"} />
                    <SheetMetric label="SOLD AS" value={soldAsLabel} />
                  </View>
                ) : (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="AIRCRAFT" value={aircraftLabel || "-"} />
                    <SheetMetric label="TRACK" value={detail.position ? "AVAILABLE" : "FILED PLAN"} />
                  </View>
                )}
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label={virtualDetail ? "NETWORK" : "SOURCE"} value={sourceMetric(sources.schedule || intel?.source_evidence?.schedule_source || detail.source)} />
                  <SheetMetric label={virtualDetail ? "TRACK" : "ENRICHED"} value={sourceMetric(sources.enrichment || intel?.source_evidence?.position_source || detail.enriched_by)} />
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

                <SectionTitle label={virtualDetail ? "FILED TIMES" : "TIMES & GATE"} />
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label={virtualDetail ? "PLANNED" : "SCHEDULED"} value={formatDateTime(detail.sched_time)} />
                  <SheetMetric label={virtualDetail ? "DEPARTURE" : "ESTIMATED"} value={virtualDetail ? formatDateTime(plan.planned_departure) : formatDateTime(detail.est_time)} />
                </View>
                {!virtualDetail ? (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="ACTUAL" value={formatDateTime(detail.actual_time)} />
                    <SheetMetric label="DELAY" value={detail.delay_minutes != null ? `${detail.delay_minutes}m` : "-"} />
                  </View>
                ) : (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="ARRIVAL" value={formatDateTime(plan.planned_arrival)} />
                    <SheetMetric label="ENROUTE" value={formatEnrouteMinutes(plan.enroute_minutes)} />
                  </View>
                )}
                {!virtualDetail ? (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="GATE" value={detail.gate_display || opsIntel.gate || detail.gate || "-"} />
                    <SheetMetric label="TERMINAL" value={detail.terminal_display || opsIntel.terminal || detail.terminal || "-"} />
                  </View>
                ) : null}
                {!virtualDetail ? (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="AIRCRAFT" value={aircraftLabel || "-"} />
                    <SheetMetric label="STAND" value={opsIntel.stand || detail.stand || "-"} />
                  </View>
                ) : null}
                {!virtualDetail ? (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="REG" value={detail.aircraft_registration || aircraftIntel.registration || "-"} />
                    <SheetMetric label="FRESH" value={sourceFreshness} />
                  </View>
                ) : null}

                <SectionTitle label={virtualDetail ? "PILOT TRACK" : "LIVE TRACK"} />
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="ALTITUDE" value={motion.altitude_ft != null ? formatFeetValue(motion.altitude_ft) : formatAltitudeFeet(altitudeMeters)} />
                  <SheetMetric label="SPEED" value={motion.speed_kt != null ? formatKnotsValue(motion.speed_kt) : formatSpeedKnots(detail.position?.speed_ms)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="HEADING" value={formatHeading(motion.heading_deg ?? detail.position?.heading)} />
                  <SheetMetric label="GROUND" value={formatGroundState(motion.on_ground ?? detail.position?.on_ground)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="LAT" value={formatCoordinate(detail.position?.lat, "N", "S")} />
                  <SheetMetric label="LON" value={formatCoordinate(detail.position?.lon, "E", "W")} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label={virtualDetail ? "XPDR" : "VERT RATE"} value={virtualDetail ? (plan.assigned_transponder || detail.position?.squawk || aircraftIntel.squawk || "-") : motion.vertical_rate_fpm != null ? `${motion.vertical_rate_fpm} ft/min` : formatVerticalRate(detail.position?.vertical_rate)} />
                  <SheetMetric label="CONTACT" value={positionFreshness} />
                </View>
                {!virtualDetail ? (
                  <View style={styles.sheetMetricRow}>
                    <SheetMetric label="ICAO24" value={detail.position?.icao24 || aircraftIntel.icao24 || "-"} />
                    <SheetMetric label="SQUAWK" value={detail.position?.squawk || aircraftIntel.squawk || "-"} />
                  </View>
                ) : null}
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="DIRECTION" value={detail.direction ? detail.direction.toUpperCase() : "-"} />
                  <SheetMetric label="CONFIDENCE" value={sourceMetric(sources.confidence || intel?.source_evidence?.confidence)} />
                </View>

                <SectionTitle label={virtualDetail ? "RECENT SESSIONS" : "7-DAY HISTORY"} />
                {history.length > 0 ? (
                  history.map((item, index) => (
                    <View key={detailHistoryKey(item, index)} style={styles.sheetHistoryRow}>
                      <Text style={styles.sheetHistoryDate}>{item.date}</Text>
                      <Text style={styles.sheetHistoryStatus}>{item.status || "Tracked"}</Text>
                      <Text style={styles.sheetHistoryMeta}>
                        {virtualDetail
                          ? `${sourceMetric(item.source || "vatsim")}${item.observations ? ` - ${item.observations} obs` : ""}`
                          : `${item.gate ? `Gate ${item.gate}` : "Gate -"}${item.delay_minutes ? ` - ${item.delay_minutes}m` : ""}`}
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
    <Modal visible={visible} animationType="fade" transparent presentationStyle="overFullScreen" statusBarTranslucent>
      <View style={styles.sheetBackdrop}>
        <Pressable
          style={styles.sheetBackdropPress}
          onPress={onClose}
          {...accessibleButton({ label: "Close flight actions" })}
        />
        <View style={styles.actionSheetCard}>
          <View style={styles.sheetHandle} />
          <Text style={styles.sheetEyebrow}>FLIGHT ACTIONS</Text>
          <Text style={styles.actionSheetTitle}>{row.flight_display || row.callsign || "Tracked flight"}</Text>
          <Text style={styles.actionSheetSubtitle} numberOfLines={1}>
            {routeName(row.route_display)} - {row.display_time || "--:--"}
          </Text>

          <View style={styles.actionSheetButtons}>
            <Pressable
              style={styles.actionButton}
              onPress={() => onTogglePin(row)}
              {...accessibleButton({
                label: isPinned ? "Unpin flight" : "Pin flight to top",
                hint: flightRowAccessibilityLabel(row)
              })}
            >
              <LocalFlightIcon
                name={isPinned ? "pin-off" : "pin"}
                size={18}
                color={isPinned ? palette.amber : palette.blue}
              />
              <Text style={styles.actionButtonText}>{isPinned ? "UNPIN FLIGHT" : "PIN TO TOP"}</Text>
            </Pressable>
            <Pressable
              style={styles.actionButton}
              onPress={() => onOpenDetail(row.callsign)}
              {...accessibleButton({
                label: "Open flight detail",
                hint: flightRowAccessibilityLabel(row)
              })}
            >
              <LocalFlightIcon name={ACTION_ICONS.search} size={18} color={palette.blue} />
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
  statusKind,
  toneHint,
  delayKind,
  compact
}: {
  status: string;
  statusClass: string;
  statusKind?: string;
  toneHint?: string;
  delayKind?: string | null;
  compact?: boolean;
}) {
  const tone = statusBadgeTone(status, statusClass, statusKind, toneHint, delayKind);
  return (
    <View style={[styles.statusBadge, statusBadgeStyle(tone), compact && styles.statusBadgeCompact]}>
      <Text style={[styles.statusBadgeText, statusTextStyle(tone)]} numberOfLines={1}>
        {(status || "SCHED").replace(/\s+/g, " ").slice(0, compact ? 8 : 12)}
      </Text>
    </View>
  );
}

function statusBadgeTone(
  status: string,
  statusClass?: string,
  statusKind?: string,
  toneHint?: string,
  delayKind?: string | null
): StatusTone {
  const value = `${status || ""} ${statusClass || ""} ${statusKind || ""} ${toneHint || ""} ${delayKind || ""}`.toLowerCase();
  if (value.includes("cancel")) return "cancelled";
  if (
    value.includes("delay") ||
    value.includes("late") ||
    value.includes("warn") ||
    value.includes("bad") ||
    value.includes("caution")
  ) return "delayed";
  if (value.includes("departed") || value.includes("landed")) return "departed";
  if (
    value.includes("arrived") ||
    value.includes("arriving") ||
    value.includes("departing") ||
    value.includes("boarding") ||
    value.includes("at_gate") ||
    value.includes("approach") ||
    value.includes("good")
  ) return "boarding";
  return statusTone(value);
}

function AdminScreen({
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
  onBackSettings: () => void;
}) {
  const budget = snapshot.budget?.aviationstack;
  const sharedBudget = snapshot.budget?.shared_schedule_budget || budget?.shared_schedule_budget || null;
  const accessBudget = snapshot.budget?.schedule_access_budget || budget?.schedule_access_budget || null;
  const primaryBudget = (sharedBudget || budget || null) as {
    provider_label?: string;
    unit_label?: string;
    used?: number | null;
    limit?: number | null;
    remaining?: number | null;
    reset_at?: string | null;
    scope_label?: string;
  } | null;
  const budgetUnit = primaryBudget?.unit_label || "requests";
  const budgetRemaining = primaryBudget?.remaining;
  const budgetLimit = primaryBudget?.limit ?? budget?.monthly_limit;
  const budgetUsed = primaryBudget?.used ?? budget?.calls_this_month;
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
    `Reporter      ${companionIdentity?.clientName || "Local Flight Mobile"}`,
    `Mobile ID     ${companionIdentity?.companionId || "UNKNOWN"}`,
    `Mobile OS     ${companionIdentity?.mobileOs || "UNKNOWN"}`,
    `Build         ${companionIdentity?.appVersion || APP_VERSION}`,
    `Server ID     ${snapshot.system?.install_id || "UNKNOWN"}`,
    `Platform pair ${platformPair}`,
    `Airport       ${snapshot.config?.airport_iata || "---"}`,
    `Source        ${snapshot.state?.source_name || snapshot.config?.source || "UNKNOWN"}`
  ].join("\n");

  return (
    <View style={styles.cardStack}>
      <HiddenToolHeader
        icon={TOOL_ICONS.admin}
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
          <InfoCard
            label="API BUDGET"
            value={budgetRemaining != null ? `${budgetRemaining} ${budgetUnit.toUpperCase()} LEFT` : "SHARED CHECK"}
          />
          <InfoCard label="MEMORY" value={snapshot.system?.memory_mb != null ? `${snapshot.system.memory_mb} MB` : "-"} />
        </View>
        <InfoLine label="Server install" value={snapshot.system?.install_id || "Unknown"} />
        <InfoLine label="Airport" value={snapshot.config?.airport_iata || "---"} />
        <InfoLine label="Source" value={snapshot.state?.source_name || snapshot.config?.source || "Unknown"} />

        {budget ? (
          <>
            <Text style={styles.adminSubTitle}>SCHEDULE ACCESS</Text>
            <InfoLine label="Budget source" value={primaryBudget?.provider_label || budget.active_mode || budget.mode || "—"} />
            <InfoLine label="Used this window" value={budgetUsed != null && budgetLimit != null ? `${budgetUsed} / ${budgetLimit} ${budgetUnit}` : "—"} />
            <InfoLine label="Requests left" value={budgetRemaining != null ? `${budgetRemaining} ${budgetUnit}` : "Shared budget unavailable"} />
            <InfoLine label="Counter resets" value={primaryBudget?.reset_at || budget.month || "—"} />
            <InfoLine label="Scope" value={primaryBudget?.scope_label || "This install"} />
            {accessBudget?.limit != null ? (
              <InfoLine label="This install" value={`${accessBudget.used ?? 0} / ${accessBudget.limit} accesses used`} />
            ) : null}
            {budget.cost_estimate?.cadence_warning ? (
              <InfoLine label="Note" value={budget.cost_estimate.cadence_warning} />
            ) : null}
            {budgetLimit != null && budgetLimit > 0 && budgetRemaining != null ? (
              <View style={styles.adminBudgetTrack}>
                <View
                  style={{
                    height: 5,
                    borderRadius: 99,
                    backgroundColor: budgetRemaining > budgetLimit * 0.3
                      ? palette.green
                      : budgetRemaining > budgetLimit * 0.1
                      ? palette.amber
                      : palette.red,
                    width: `${Math.min(Math.round((budgetRemaining / budgetLimit) * 100), 100)}%` as unknown as number
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
            <InfoLine label="Movements" value={String(historyStats.total_movements ?? historyStats.total_rows)} />
            <InfoLine label="Raw observations" value={String(historyStats.total_rows)} />
            <InfoLine label="Airports" value={historyStats.airports?.join(", ") || "—"} />
            <InfoLine label="Oldest movement" value={(historyStats.oldest_movement || historyStats.oldest) ? formatRelative(historyStats.oldest_movement || historyStats.oldest) : "—"} />
            <InfoLine label="Newest movement" value={(historyStats.newest_movement || historyStats.newest) ? formatRelative(historyStats.newest_movement || historyStats.newest) : "—"} />
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
        <InfoLine label="Mobile ID" value={companionIdentity?.companionId || "Loading..."} />
        <InfoLine label="Mobile OS" value={companionIdentity?.mobileOs || "Loading..."} />
        <InfoLine label="Last check-in" value={companionRecord?.last_seen ? formatRelative(companionRecord.last_seen) : "Not seen yet"} />
        <InfoLine label="Matrix last seen" value={matrixLastSeen ? formatRelative(matrixLastSeen) : "Never pinged"} />
        <SettingsToolPill
          icon={TOOL_ICONS.matrix}
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
        <Pressable
          style={[styles.connectButton, feedbackSending && styles.connectButtonDisabled]}
          onPress={onSubmitFeedback}
          disabled={feedbackSending}
          {...accessibleButton({
            label: feedbackSending ? "Sending report" : "Send report",
            disabled: feedbackSending,
            busy: feedbackSending
          })}
        >
          {feedbackSending ? <ActivityIndicator color={solidButtonInk()} /> : <Text style={styles.connectButtonText}>SEND REPORT</Text>}
        </Pressable>
        {feedbackMessage ? (
          <Text style={[styles.feedbackMessage, feedbackTone === "ok" ? styles.feedbackMessageOk : styles.feedbackMessageError]}>
            {feedbackMessage}
          </Text>
        ) : null}
      </View>
      ) : null}

      {section === "developer" && __DEV__ ? (
        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>AUTO REPORT TEST</Text>
          <Text style={styles.moduleIntro}>
            Developer-only helpers to verify the mobile crash pipeline before a real failure happens.
          </Text>
          <Pressable
            style={styles.connectButton}
            onPress={onSendAutoReportTest}
            {...accessibleButton({ label: "Send automatic report test" })}
          >
            <Text style={styles.connectButtonText}>SEND AUTO TEST</Text>
          </Pressable>
          <Pressable
            style={[styles.connectButton, styles.crashButton]}
            onPress={() => {
              setTimeout(() => {
                throw new Error("Intentional mobile crash test");
              }, 10);
            }}
            {...accessibleButton({
              label: "Trigger test crash",
              hint: "Developer-only action that intentionally crashes the app."
            })}
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
  pairingUrl = "",
  pairingNonce = 0,
  pairingExpectedServerFingerprint = "",
  initialDiagnosticsMode,
  onPairingLoaded,
  onComplete
}: {
  initialUrl: string;
  pairingUrl?: string;
  pairingNonce?: number;
  pairingExpectedServerFingerprint?: string;
  initialDiagnosticsMode: MobileDiagnosticsMode;
  onPairingLoaded?: (pairing: PairingLinkResult) => void;
  onComplete: (result: MobileSetupResult) => Promise<void> | void;
}) {
  const [step, setStep] = useState<CompanionSetupStep>("welcome");
  const [setupMode, setSetupMode] = useState<MobileSetupMode>("lan_companion");
  const [serverInput, setServerInput] = useState(initialUrl);
  const [airportInput, setAirportInput] = useState("");
  const [airportResults, setAirportResults] = useState<AirportResult[]>([]);
  const [selectedStandaloneAirport, setSelectedStandaloneAirport] = useState<AirportResolved | null>(null);
  const [diagnosticsMode, setDiagnosticsMode] = useState<MobileDiagnosticsMode>(
    initialDiagnosticsMode === "unset" ? "manual" : initialDiagnosticsMode
  );
  const [testing, setTesting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [setupProgress, setSetupProgress] = useState<string | null>(null);
  const [urlCheckState, setUrlCheckState] = useState<SetupUrlCheckState>("idle");
  const [urlCheckMessage, setUrlCheckMessage] = useState("Enter the LAN address shown by the desktop or Pi app.");
  const [serverSummary, setServerSummary] = useState<CompanionSetupResult | null>(null);
  const [scannerVisible, setScannerVisible] = useState(false);
  const [keyboardInset, setKeyboardInset] = useState(0);
  const stepAnim = useRef(new Animated.Value(1)).current;
  const railAnim = useRef(new Animated.Value(0)).current;
  const progressAnim = useRef(new Animated.Value(1 / 6)).current;
  const stepDirectionRef = useRef<1 | -1>(1);
  const lastStepRef = useRef<CompanionSetupStep>("welcome");
  const reduceMotion = useReducedMotionPreference();
  const routeSteps: CompanionSetupStep[] = setupMode === "standalone"
    ? ["welcome", "mode", "airport", "policy", "diagnostics", "ready"]
    : ["welcome", "mode", "pairing", "server", "diagnostics", "ready"];
  const activeStepIndex = setupStepRank(step);
  const setupProgressRatio = Math.min(1, (activeStepIndex + 1) / routeSteps.length);

  const goToStep = useCallback((nextStep: CompanionSetupStep) => {
    Keyboard.dismiss();
    stepDirectionRef.current = setupStepRank(nextStep) >= setupStepRank(lastStepRef.current) ? 1 : -1;
    lastStepRef.current = nextStep;
    setStep(nextStep);
  }, []);

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
      duration: reduceMotion ? 150 : 220,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true
    }).start();
  }, [step, stepAnim, reduceMotion]);

  useEffect(() => {
    const nextValue = step === "welcome" ? 0 : 1;
    Animated.spring(railAnim, {
      toValue: nextValue,
      stiffness: reduceMotion ? 150 : 170,
      damping: reduceMotion ? 28 : 22,
      mass: 0.75,
      useNativeDriver: true
    }).start();
  }, [railAnim, reduceMotion, step]);

  useEffect(() => {
    Animated.timing(progressAnim, {
      toValue: setupProgressRatio,
      duration: reduceMotion ? 170 : 260,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: false
    }).start();
  }, [progressAnim, reduceMotion, setupProgressRatio]);

  useEffect(() => {
    const showEvent = Platform.OS === "ios" ? "keyboardWillShow" : "keyboardDidShow";
    const hideEvent = Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide";
    const show = Keyboard.addListener(showEvent, (event) => {
      setKeyboardInset(Math.max(0, event.endCoordinates?.height ?? 0));
    });
    const hide = Keyboard.addListener(hideEvent, () => setKeyboardInset(0));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);

  useEffect(() => {
    if (step !== "server") return;

    const input = serverInput.trim();
    if (!input) {
      setUrlCheckState("idle");
      setUrlCheckMessage("Enter the LAN address shown by the desktop or Pi app.");
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
      setUrlCheckMessage("Checking the Local Flight host on your LAN...");
      void getHealth(normalizedUrl)
        .then(() => {
          if (cancelled) return;
          setUrlCheckState("ok");
          setUrlCheckMessage("Host answered. You can continue with the full check.");
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

  useEffect(() => {
    if (step !== "airport") return;
    const text = airportInput.trim();
    if (text.length < 2) {
      setAirportResults([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      void searchStandaloneAirports(text, 8)
        .then((items) => {
          if (!cancelled) setAirportResults(items);
        })
        .catch(() => {
          if (!cancelled) setAirportResults([]);
        });
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [airportInput, step]);

  const runServerTest = useCallback(async (candidateUrl: string, expectedServerFingerprint = "") => {
    const input = candidateUrl.trim();
    const urlProblem = companionSetupUrlProblem(input);
    if (urlProblem) {
      setSetupError(urlProblem);
      setUrlCheckState("invalid");
      setUrlCheckMessage(urlProblem);
      return;
    }

    setTesting(true);
    setSetupError(null);
    setUrlCheckState("checking");
    setUrlCheckMessage("Running a full Local Flight check...");
    let rootHealthOk = false;
    try {
      const normalizedUrl = normalizeServerUrl(input);
      setSetupProgress("Checking the Local Flight host on your LAN...");
      await getRootHealth(normalizedUrl);
      rootHealthOk = true;
      setSetupProgress("Reading companion status and board configuration...");
      const mobileSummary = await getMobileSummary(normalizedUrl);
      const fingerprintProblem = pairingFingerprintProblem(
        expectedServerFingerprint,
        mobileSummary.system?.install_id
      );
      if (fingerprintProblem) {
        throw new Error(fingerprintProblem);
      }
      let state = mobileSummary.state;
      let config = mobileSummary.config;
      if (!state || !config) {
        const fallback = await Promise.all([
          state ? Promise.resolve(state) : getHealth(normalizedUrl),
          config ? Promise.resolve(config) : getConfig(normalizedUrl)
        ]);
        state = fallback[0];
        config = fallback[1];
      }
      if (!config || !state) {
        throw new Error("Local Flight mobile summary did not include server config and health.");
      }
      const summary = {
        mode: "lan_companion" as const,
        serverUrl: normalizedUrl,
        diagnosticsMode,
        config,
        state
      };
      setSetupProgress("Host answered. Moving to reports...");
      setServerInput(normalizedUrl);
      setUrlCheckState("ok");
      setUrlCheckMessage("Host and companion setup are ready.");
      setServerSummary(summary);
      goToStep("diagnostics");
    } catch (exc) {
      const detail = companionSetupErrorMessage(exc);
      const isPairingGuard = /Pairing QR|belongs to server|server fingerprint/i.test(detail);
      const message = rootHealthOk && !isPairingGuard
        ? "Local Flight is running, but first-time setup is not finished on the desktop or Pi yet. Finish setup there, then return here."
        : detail;
      setSetupError(
        message
      );
      setUrlCheckState("error");
      setUrlCheckMessage(rootHealthOk && !isPairingGuard
        ? "The host answered, but companion setup is not ready yet."
        : message);
    } finally {
      setTesting(false);
      setSetupProgress(null);
    }
  }, [diagnosticsMode, goToStep]);

  const testServer = useCallback(async () => {
    await runServerTest(serverInput);
  }, [runServerTest, serverInput]);

  const handleScannedServer = useCallback((pairing: PairingLinkResult) => {
    onPairingLoaded?.(pairing);
    setScannerVisible(false);
    setSetupMode("lan_companion");
    setServerInput(pairing.serverUrl);
    goToStep("server");
    setSetupError(null);
    setUrlCheckState("checking");
    setUrlCheckMessage("Pairing QR loaded. Testing this Local Flight host...");
    void runServerTest(pairing.serverUrl, pairing.expectedServerFingerprint);
  }, [goToStep, onPairingLoaded, runServerTest]);

  useEffect(() => {
    if (!pairingUrl || pairingNonce <= 0) return;
    setSetupMode("lan_companion");
    setServerInput(pairingUrl);
    goToStep("server");
    setSetupError(null);
    setUrlCheckState("checking");
    setUrlCheckMessage("Pairing QR loaded. Testing this Local Flight host...");
    const timer = setTimeout(() => {
      void runServerTest(pairingUrl, pairingExpectedServerFingerprint);
    }, 120);
    return () => clearTimeout(timer);
  }, [goToStep, pairingExpectedServerFingerprint, pairingNonce, pairingUrl, runServerTest]);

  const selectStandaloneAirport = useCallback((airport: AirportResult) => {
    const nextAirport: AirportResolved = {
      iata: airport.iata,
      icao: airport.icao,
      name: airport.name,
      city: airport.city,
      country: airport.country,
      timezone: airport.timezone,
      type: airport.type
    };
    setSelectedStandaloneAirport(nextAirport);
    setAirportInput(`${airport.iata || airport.icao} - ${airport.name}`);
    setSetupError(null);
    Keyboard.dismiss();
  }, []);

  const submitAirportSearch = useCallback(() => {
    if (selectedStandaloneAirport) {
      Keyboard.dismiss();
      return;
    }
    const firstAirport = airportResults[0];
    if (firstAirport) {
      selectStandaloneAirport(firstAirport);
      return;
    }
    Keyboard.dismiss();
  }, [airportResults, selectStandaloneAirport, selectedStandaloneAirport]);

  const finishSetup = useCallback(async () => {
    if (setupMode === "standalone") {
      if (!selectedStandaloneAirport) {
        goToStep("airport");
        setSetupError("Pick an airport before finishing standalone setup.");
        return;
      }
      setFinishing(true);
      setSetupError(null);
      try {
        const airportLookup = selectedStandaloneAirport.iata || selectedStandaloneAirport.icao;
        setSetupProgress("Resolving airport coordinates for radar drawings...");
        const resolvedAirport = selectedStandaloneAirport.lat == null || selectedStandaloneAirport.lon == null
          ? await resolveStandaloneAirport(airportLookup)
          : selectedStandaloneAirport;
        const relayInstallId = await loadMobileRelayInstallId();
        setSetupProgress("Activating this phone as a standalone relay client...");
        const activation = await activateStandalone({
          installId: relayInstallId,
          airport: resolvedAirport
        });
        setSetupProgress("Saving standalone setup on this device...");
        await onComplete({
          mode: "standalone",
          relayInstallId,
          relayActivationToken: activation.activationToken,
          airport: resolvedAirport,
          diagnosticsMode,
          activationStatus: activation.status
        });
      } catch (exc) {
        setSetupError(companionSetupErrorMessage(exc));
      } finally {
        setFinishing(false);
        setSetupProgress(null);
      }
      return;
    }

    if (!serverSummary) {
      goToStep("server");
      setSetupError("Test your Local Flight host before finishing setup.");
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
  }, [diagnosticsMode, goToStep, onComplete, selectedStandaloneAirport, serverSummary, setupMode]);

  const panelMotion = {
    opacity: stepAnim,
    transform: [
      {
        translateX: stepAnim.interpolate({
          inputRange: [0, 1],
          outputRange: [(reduceMotion ? 6 : 18) * stepDirectionRef.current, 0]
        })
      },
      {
        translateY: stepAnim.interpolate({ inputRange: [0, 1], outputRange: [reduceMotion ? 3 : 8, 0] })
      }
    ]
  };
  const compactRailMotion = {
    opacity: railAnim,
    transform: [
      {
        translateY: railAnim.interpolate({ inputRange: [0, 1], outputRange: [reduceMotion ? -4 : -10, 0] })
      },
      {
        scale: railAnim.interpolate({ inputRange: [0, 1], outputRange: [reduceMotion ? 0.992 : 0.975, 1] })
      }
    ]
  };
  const compactProgressWidth = progressAnim.interpolate({ inputRange: [0, 1], outputRange: ["0%", "100%"] });

  return (
    <KeyboardAvoidingView
      style={styles.companionSetupKeyboard}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
    >
    <ScrollView
      style={styles.companionSetupScroll}
      contentContainerStyle={[
        styles.companionSetupContent,
        { paddingBottom: Math.max(26, keyboardInset + 26) }
      ]}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}
    >
      <View style={styles.companionSetupGlowA} />
      <View style={styles.companionSetupGlowB} />
      <View style={styles.companionSetupShell}>
        {step === "welcome" ? (
        <Animated.View style={[styles.companionSetupHero, panelMotion]}>
          <View style={styles.companionSetupLogoWrap}>
            <View style={styles.companionSetupLogoRing} />
            <View style={styles.companionSetupLogoRingOuter} />
            <View style={styles.companionSetupLogoPlate}>
              <Image
                source={LOCAL_FLIGHT_BRAND_ASSETS[palette.themeMode].icon}
                resizeMode="contain"
                style={styles.companionSetupLogoMark}
              />
            </View>
          </View>
          <Text style={styles.companionSetupEyebrow}>
            <Text style={styles.companionSetupBrandText}>LOCAL FLIGHT</Text>
            <Text style={styles.companionSetupEyebrowSuffix}> MOBILE</Text>
          </Text>
          <Text style={styles.companionSetupTitle}>Set up your flight board</Text>
          <Text style={styles.companionSetupBody}>
            A calmer mobile board for flights, radar, and recent movement history. Pick the setup path that matches how you want this phone to connect.
          </Text>
          <View style={styles.companionSetupRoute}>
            {routeSteps.map((item, index) => (
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
        </Animated.View>
        ) : (
          <Animated.View style={[styles.companionSetupCompactRail, compactRailMotion]}>
            <View style={styles.companionSetupCompactBrand}>
              <View style={styles.companionSetupCompactLogo}>
                <Image
                  source={LOCAL_FLIGHT_BRAND_ASSETS[palette.themeMode].icon}
                  resizeMode="contain"
                  style={styles.companionSetupCompactLogoMark}
                />
              </View>
              <View style={styles.companionSetupCompactCopy}>
                <BrandWordmark
                  color={palette.text}
                  size={19}
                  style={styles.companionSetupCompactTitle}
                  numberOfLines={1}
                >
                  Local Flight
                </BrandWordmark>
                <Text style={styles.companionSetupCompactMeta}>
                  {setupStepTitle(step)} · {activeStepIndex + 1}/{routeSteps.length}
                </Text>
              </View>
            </View>
            <View style={styles.companionSetupCompactBeacon} {...hideFromAccessibility()}>
              <View style={styles.companionSetupCompactBeaconDot} />
              <View style={styles.companionSetupCompactBeaconLine} />
            </View>
            <View
              style={styles.companionSetupCompactProgress}
              accessibilityRole="progressbar"
              accessibilityValue={{
                min: 1,
                max: routeSteps.length,
                now: activeStepIndex + 1,
                text: `${setupStepTitle(step)} step ${activeStepIndex + 1} of ${routeSteps.length}`
              }}
            >
              <Animated.View style={[styles.companionSetupCompactProgressFill, { width: compactProgressWidth }]} />
            </View>
          </Animated.View>
        )}

        {step === "welcome" ? (
          <Animated.View style={[styles.companionSetupPanel, styles.companionSetupWelcomePanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Welcome to Local Flight Mobile</Text>
            <Text style={styles.companionSetupBody}>
              This phone can show your airport board, radar view, and recent flight history. Setup only asks for the connection path, an airport if needed, and your report preference.
            </Text>
            <View style={styles.companionSetupChecklist}>
              <SetupChecklistItem icon={SETUP_ICONS.server} title="One app, two paths" body="Use a Local Flight host, or run a lighter standalone board from the relay." />
              <SetupChecklistItem icon={SETUP_ICONS.lan} title="Easy to change later" body="You can rerun setup from Settings whenever your setup changes." />
              <SetupChecklistItem icon={SETUP_ICONS.privacy} title="You choose reports" body="Manual reports stay available. Automatic reports are optional." />
            </View>
            <Pressable
              style={styles.companionSetupPrimary}
              onPress={() => goToStep("mode")}
              {...accessibleButton({
                label: "Continue",
                hint: "Choose how this phone connects to Local Flight."
              })}
            >
              <LocalFlightIcon name={ACTION_ICONS.next} size={16} color={solidButtonInk()} />
              <Text style={styles.companionSetupPrimaryText}>CONTINUE</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {step === "mode" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>How should this phone connect?</Text>
            <Text style={styles.companionSetupBody}>
              Choose Companion if Local Flight already runs on a desktop or Pi. Companion keeps this phone as a remote and glance screen for your local host. Choose Standalone if this phone should use the hosted relay by itself.
            </Text>
            <View style={styles.companionSetupOptionStack}>
              {([
                ["lan_companion", "Companion", "Companion keeps this phone as a remote and glance screen. Connects to your desktop or Pi for Board, Radar, History, Control, Help, and Matrix tools."],
                ["standalone", "Standalone", "Simpler board. Uses the relay directly with Board, Radar, History, and Settings only."]
              ] as Array<[MobileSetupMode, string, string]>).map(([mode, title, body]) => (
                <Pressable
                  key={mode}
                  style={[
                    styles.companionSetupOption,
                    setupMode === mode && styles.companionSetupOptionActive
                  ]}
                  {...accessibleButton({
                    label: title,
                    hint: body,
                    selected: setupMode === mode
                  })}
                  onPress={() => {
                    setSetupMode(mode);
                    setSetupError(null);
                  }}
                >
                  <View style={styles.companionSetupOptionTop}>
                    <Text style={styles.companionSetupOptionTitle}>{title}</Text>
                    {mode === "lan_companion" ? <Text style={styles.companionSetupRecommended}>FULL</Text> : <Text style={styles.companionSetupRecommended}>SIMPLE</Text>}
                  </View>
                  <Text style={styles.companionSetupOptionBody}>{body}</Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.companionSetupInfoGrid}>
              <SetupInfoTile label="Mode" value={setupMode === "standalone" ? "Standalone" : "Companion"} />
              <SetupInfoTile label="Next" value={setupMode === "standalone" ? "Choose airport" : "Pair host"} />
            </View>
            <Pressable
              style={styles.companionSetupPrimary}
              onPress={() => goToStep(setupMode === "standalone" ? "airport" : "pairing")}
              {...accessibleButton({
                label: "Continue",
                hint: setupMode === "standalone" ? "Moves to airport search." : "Moves to pairing choices."
              })}
            >
              <LocalFlightIcon name={ACTION_ICONS.next} size={16} color={solidButtonInk()} />
              <Text style={styles.companionSetupPrimaryText}>CONTINUE</Text>
            </Pressable>
            <Pressable
              style={styles.companionSetupSecondary}
              onPress={() => goToStep("welcome")}
              {...accessibleButton({ label: "Back to welcome" })}
            >
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {step === "pairing" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Connect your Local Flight host</Text>
            <Text style={styles.companionSetupBody}>
              Open Local Flight Settings on the desktop or Pi. Scan its pairing QR, or enter the Wi-Fi address shown there.
            </Text>
            <View style={styles.pairingChoiceRow}>
              <Pressable
                style={styles.pairingChoiceCard}
                onPress={() => {
                  Keyboard.dismiss();
                  setScannerVisible(true);
                }}
                {...accessibleButton({
                  label: "Scan QR",
                  hint: "Opens the camera to scan the Local Flight pairing code."
                })}
              >
                <View style={styles.pairingChoiceIcon}>
                  <LocalFlightIcon name={SETUP_ICONS.scan} size={18} color={palette.blue2} />
                </View>
                <View style={styles.pairingChoiceCopy}>
                  <Text style={styles.pairingChoiceTitle}>Scan QR</Text>
                  <Text style={styles.pairingChoiceBody}>Fastest and safest. The code includes the host fingerprint.</Text>
                </View>
              </Pressable>
              <Pressable
                style={styles.pairingChoiceCard}
                onPress={() => goToStep("server")}
                {...accessibleButton({
                  label: "Enter address",
                  hint: "Type or paste the Local Flight server address."
                })}
              >
                <View style={styles.pairingChoiceIcon}>
                  <LocalFlightIcon name={SETUP_ICONS.keyboard} size={18} color={palette.blue2} />
                </View>
                <View style={styles.pairingChoiceCopy}>
                  <Text style={styles.pairingChoiceTitle}>Enter address</Text>
                  <Text style={styles.pairingChoiceBody}>Use this if the QR is not handy or the camera is unavailable.</Text>
                </View>
              </Pressable>
            </View>
            <View style={styles.companionSetupExampleBox}>
              <Text style={styles.companionSetupExampleLabel}>WHAT YOU NEED</Text>
              <Text style={styles.companionSetupExampleText}>Local Flight running on the same Wi-Fi</Text>
              <Text style={styles.companionSetupExampleText}>The mobile pairing QR or host address</Text>
            </View>
            <Pressable
              style={styles.companionSetupPrimary}
              onPress={() => goToStep("server")}
              {...accessibleButton({ label: "Enter address" })}
            >
              <LocalFlightIcon name={SETUP_ICONS.keyboard} size={16} color={solidButtonInk()} />
              <Text style={styles.companionSetupPrimaryText}>ENTER ADDRESS</Text>
            </Pressable>
            <Pressable
              style={styles.companionSetupSecondary}
              onPress={() => goToStep("mode")}
              {...accessibleButton({ label: "Back to connection mode" })}
            >
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
            <PairingScannerSheet
              visible={scannerVisible}
              onClose={() => setScannerVisible(false)}
              onPairingUrl={handleScannedServer}
            />
          </Animated.View>
        ) : null}

        {step === "server" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Test the host address</Text>
            <Text style={styles.companionSetupBody}>
              Enter the address shown by the desktop or Pi app. We will check that the host is reachable and ready for mobile.
            </Text>
            <View style={styles.companionSetupExampleBox}>
              <Text style={styles.companionSetupExampleLabel}>GOOD EXAMPLES</Text>
              <Text style={styles.companionSetupExampleText}>http://192.168.1.42:8000</Text>
              <Text style={styles.companionSetupExampleText}>http://localflight.local:8000</Text>
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
                returnKeyType="go"
                blurOnSubmit
                onSubmitEditing={() => {
                  Keyboard.dismiss();
                  void testServer();
                }}
                style={styles.companionSetupInput}
              />
              <View style={styles.companionSetupInputStatus}>
                {urlCheckState === "checking" ? (
                  <ActivityIndicator size="small" color={palette.blue2} />
                ) : (
                  <LocalFlightIcon
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
              label={setupProgress || "Waiting to test the host address."}
              steps={["Reach host", "Read status", "Load board"]}
            />
            <Pressable
              style={[styles.companionSetupPrimary, testing && styles.connectButtonDisabled]}
              onPress={() => {
                Keyboard.dismiss();
                void testServer();
              }}
              disabled={testing}
              {...accessibleButton({
                label: testing ? "Testing connection" : "Test connection",
                hint: "Checks the Local Flight host and board setup.",
                disabled: testing,
                busy: testing
              })}
            >
              {testing ? <ActivityIndicator color={solidButtonInk()} /> : <LocalFlightIcon name={ACTION_ICONS.connect} size={16} color={solidButtonInk()} />}
              <Text style={styles.companionSetupPrimaryText}>{testing ? "TESTING" : "TEST CONNECTION"}</Text>
            </Pressable>
            <Pressable
              style={styles.companionSetupSecondary}
              onPress={() => goToStep("pairing")}
              {...accessibleButton({ label: "Back to pairing choices" })}
            >
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {step === "airport" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Choose your airport</Text>
            <Text style={styles.companionSetupBody}>
              Standalone uses one airport at a time. Search by airport code, city, or airport name.
            </Text>
            <View style={styles.companionSetupInputWrap}>
              <TextInput
                autoCapitalize="characters"
                autoCorrect={false}
                placeholder="Search airport, e.g. ZRH, Munich, RJAA"
                placeholderTextColor={palette.textDim}
                value={airportInput}
                onChangeText={(value) => {
                  setAirportInput(value);
                  setSelectedStandaloneAirport(null);
                }}
                returnKeyType="search"
                blurOnSubmit
                onSubmitEditing={submitAirportSearch}
                style={styles.companionSetupInput}
              />
            </View>
            <View style={styles.companionSetupOptionStack}>
              {airportResults.slice(0, 6).map((airport, index) => {
                const airportKey = `${airport.iata || airport.icao}-${index}`;
                const active = selectedStandaloneAirport?.iata === airport.iata && selectedStandaloneAirport?.icao === airport.icao;
                return (
                  <Pressable
                    key={airportKey}
                    style={[styles.companionSetupOption, active && styles.companionSetupOptionActive]}
                    {...accessibleButton({
                      label: `${airport.iata || airport.icao}, ${airport.name}`,
                      hint: [airport.city, airport.country, airport.timezone].filter(Boolean).join(", "),
                      selected: active
                    })}
                    onPress={() => selectStandaloneAirport(airport)}
                  >
                    <View style={styles.companionSetupOptionTop}>
                      <Text style={styles.companionSetupOptionTitle}>{airport.iata || airport.icao}</Text>
                      <Text style={styles.companionSetupRecommended}>{airport.timezone || "UTC"}</Text>
                    </View>
                    <Text style={styles.companionSetupOptionBody}>
                      {[airport.name, airport.city, airport.country].filter(Boolean).join(" - ")}
                    </Text>
                  </Pressable>
                );
              })}
              {airportInput.trim().length >= 2 && !airportResults.length ? (
                <Text style={styles.companionSetupUrlHint}>No relay airport match yet. Try the IATA or ICAO code.</Text>
              ) : null}
            </View>
            <Pressable
              style={[styles.companionSetupPrimary, !selectedStandaloneAirport && styles.connectButtonDisabled]}
              onPress={() => selectedStandaloneAirport && goToStep("policy")}
              disabled={!selectedStandaloneAirport}
              {...accessibleButton({
                label: "Use this airport",
                disabled: !selectedStandaloneAirport
              })}
            >
              <LocalFlightIcon name={ACTION_ICONS.next} size={16} color={solidButtonInk()} />
              <Text style={styles.companionSetupPrimaryText}>USE THIS AIRPORT</Text>
            </Pressable>
            <Pressable
              style={styles.companionSetupSecondary}
              onPress={() => goToStep("mode")}
              {...accessibleButton({ label: "Back to connection mode" })}
            >
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {step === "policy" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Standalone stays lightweight</Text>
            <Text style={styles.companionSetupBody}>
              Standalone is built for quick checks when you do not have a Local Flight host nearby. It uses shared relay resources gently.
            </Text>
            <View style={styles.companionSetupChecklist}>
              <SetupChecklistItem icon={SETUP_ICONS.server} title="Board refreshes slowly" body="Flight boards refresh no faster than every 3 hours." />
              <SetupChecklistItem icon={SETUP_ICONS.lan} title="Radar is compact" body="Radar updates no faster than every 5 minutes and uses 1, 3, 5, or 10 NM ranges." />
              <SetupChecklistItem icon={SETUP_ICONS.privacy} title="Display aid only" body="Do not use this data for navigation, dispatch, safety, or operational decisions." />
            </View>
            <Pressable
              style={styles.companionSetupPrimary}
              onPress={() => goToStep("diagnostics")}
              {...accessibleButton({ label: "Continue to reports" })}
            >
              <LocalFlightIcon name={ACTION_ICONS.next} size={16} color={solidButtonInk()} />
              <Text style={styles.companionSetupPrimaryText}>CONTINUE</Text>
            </Pressable>
            <Pressable
              style={styles.companionSetupSecondary}
              onPress={() => goToStep("airport")}
              {...accessibleButton({ label: "Back to airport search" })}
            >
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {step === "diagnostics" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Choose how reports work</Text>
            <Text style={styles.companionSetupBody}>
              Manual reports are always available from Help. Automatic crash reports are optional and can be changed later in Settings.
            </Text>
            <View style={styles.companionSetupOptionStack}>
              {([
                ["manual", "Ask me first", "No automatic mobile reports. You can still send feedback yourself from Help."],
                ["auto", "Send crash reports", "Send serious mobile crashes with app state needed to fix the problem."],
                ["auto_logs", "Crash reports + context", "Adds a little more mobile context when available. Native device logs are not included."]
              ] as Array<[MobileDiagnosticsMode, string, string]>).map(([mode, title, body]) => (
                  <Pressable
                    key={mode}
                    style={[
                      styles.companionSetupOption,
                      diagnosticsMode === mode && styles.companionSetupOptionActive
                    ]}
                    {...accessibleButton({
                      label: title,
                      hint: body,
                      selected: diagnosticsMode === mode
                    })}
                    onPress={() => {
                      Keyboard.dismiss();
                      setDiagnosticsMode(mode);
                    }}
                  >
                  <View style={styles.companionSetupOptionTop}>
                    <Text style={styles.companionSetupOptionTitle}>{title}</Text>
                    {mode === "manual" ? <Text style={styles.companionSetupRecommended}>RECOMMENDED</Text> : null}
                  </View>
                  <Text style={styles.companionSetupOptionBody}>{body}</Text>
                </Pressable>
              ))}
            </View>
            <Pressable
              style={styles.companionSetupPrimary}
              onPress={() => goToStep("ready")}
              {...accessibleButton({ label: "Review setup" })}
            >
              <LocalFlightIcon name={ACTION_ICONS.checklist} size={16} color={solidButtonInk()} />
              <Text style={styles.companionSetupPrimaryText}>REVIEW</Text>
            </Pressable>
            <Pressable
              style={styles.companionSetupSecondary}
              onPress={() => goToStep(setupMode === "standalone" ? "policy" : "server")}
              {...accessibleButton({ label: "Back to previous setup step" })}
            >
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </Animated.View>
        ) : null}

        {step === "ready" ? (
          <Animated.View style={[styles.companionSetupPanel, panelMotion]}>
            <Text style={styles.companionSetupPanelTitle}>Review setup</Text>
            <Text style={styles.companionSetupBody}>
              {setupMode === "standalone"
                ? "We will save this airport and activate the standalone board on this phone."
                : "We will save this host on this phone and open the main mobile board."}
            </Text>
            <View style={styles.companionSetupSummary}>
              <InfoLine label="Mode" value={setupMode === "standalone" ? "Standalone relay client" : "Companion"} />
              <InfoLine label={setupMode === "standalone" ? "Airport" : "Host"} value={setupMode === "standalone" ? (selectedStandaloneAirport?.iata || "---") : (serverSummary?.serverUrl || normalizeServerUrl(serverInput) || "Not tested")} />
              <InfoLine label={setupMode === "standalone" ? "Refresh" : "Airport"} value={setupMode === "standalone" ? "3h board, 5m radar" : (serverSummary?.config.airport_iata || "---")} />
              <InfoLine label={setupMode === "standalone" ? "Status" : "Host status"} value={setupMode === "standalone" ? "Activation on finish" : (serverSummary?.state.ok === false ? "Needs attention" : "Ready")} />
              <InfoLine label="Reports" value={diagnosticsMode === "manual" ? "Ask me first" : diagnosticsMode === "auto" ? "Crash reports" : "Crash reports + context"} />
            </View>
            <SetupProgressRail
              active={finishing}
              label={setupProgress || (finishing ? "Saving setup..." : "Ready to save and open the board.")}
              steps={setupMode === "standalone" ? ["Resolve airport", "Activate relay", "Open board"] : ["Save host", "Save reports", "Open board"]}
            />
            <Pressable
              style={[styles.companionSetupPrimary, finishing && styles.connectButtonDisabled]}
              onPress={() => {
                Keyboard.dismiss();
                void finishSetup();
              }}
              disabled={finishing}
              {...accessibleButton({
                  label: finishing ? "Saving setup" : "Finish",
                disabled: finishing,
                busy: finishing
              })}
            >
              {finishing ? <ActivityIndicator color={solidButtonInk()} /> : <LocalFlightIcon name={ACTION_ICONS.finish} size={16} color={solidButtonInk()} />}
              <Text style={styles.companionSetupPrimaryText}>{finishing ? "SAVING" : "FINISH"}</Text>
            </Pressable>
            <Pressable
              style={styles.companionSetupSecondary}
              onPress={() => goToStep("diagnostics")}
              {...accessibleButton({ label: "Back to diagnostics choices" })}
            >
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
    </KeyboardAvoidingView>
  );
}

function SetupChecklistItem({ icon, title, body }: { icon: AppIconName; title: string; body: string }) {
  return (
    <View style={styles.companionSetupChecklistItem}>
      <View style={styles.companionSetupChecklistIcon}>
        <LocalFlightIcon name={icon} size={16} color={palette.blue2} />
      </View>
      <View style={styles.companionSetupChecklistCopy}>
        <Text style={styles.companionSetupChecklistTitle}>{title}</Text>
        <Text style={styles.companionSetupChecklistBody}>{body}</Text>
      </View>
    </View>
  );
}

function SetupProgressRail({ active, label, steps }: { active: boolean; label: string; steps: string[] }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const reduceMotion = useReducedMotionPreference();

  useEffect(() => {
    if (!active) {
      setActiveIndex(0);
      return;
    }
    const timer = setInterval(() => {
      setActiveIndex((value) => (value + 1) % Math.max(1, steps.length));
    }, reduceMotion ? 520 : 420);
    return () => clearInterval(timer);
  }, [active, reduceMotion, steps.length]);

  return (
    <View style={[styles.companionSetupProgressRail, active && styles.companionSetupProgressRailActive]}>
      <View style={styles.companionSetupProgressHeader}>
        {active ? <ActivityIndicator size="small" color={palette.blue} /> : <LocalFlightIcon name={ACTION_ICONS.progress} size={15} color={palette.textDim} />}
        <Text style={styles.companionSetupProgressText}>{label}</Text>
      </View>
      <View style={styles.companionSetupProgressSteps}>
        {steps.map((item, index) => (
          <View key={item} style={styles.companionSetupProgressStep}>
            <View style={[styles.companionSetupProgressDot, active && index <= activeIndex && styles.companionSetupProgressDotActive]} />
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

function setupUrlCheckIcon(state: SetupUrlCheckState): AppIconName {
  switch (state) {
    case "ok":
      return SETUP_ICONS.ok;
    case "error":
    case "invalid":
      return SETUP_ICONS.error;
    case "checking":
      return SETUP_ICONS.checking;
    default:
      return SETUP_ICONS.link;
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
  return {
    welcome: 0,
    mode: 1,
    pairing: 2,
    server: 3,
    airport: 2,
    policy: 3,
    diagnostics: 4,
    ready: 5
  }[step];
}

function setupStepTitle(step: CompanionSetupStep): string {
  return {
    welcome: "Start",
    mode: "Mode",
    pairing: "Pair",
    server: "Test",
    airport: "Airport",
    policy: "Limits",
    diagnostics: "Reports",
    ready: "Review"
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
      return "This phone cannot use localhost because that points back at the phone. Use the Pi or desktop LAN address, or localflight.local if it works on your Wi-Fi.";
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
    return "Could not reach Local Flight on the Wi-Fi network. Make sure this phone and the Pi or desktop are on the same Wi-Fi, Local Flight is running, and the address uses the server IP or localflight.local.";
  }
  return message;
}

function SettingsScreen({
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
          Start with the server link, then jump straight to the mobile tools you need.
        </Text>
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>CONNECTION & SYNC</Text>
        <View style={styles.metricRow}>
          <InfoCard label="SERVER" value={serverUrl ? "READY" : "SETUP"} tone={serverUrl ? "green" : "amber"} />
          <InfoCard label="REFRESH" value={refreshSeconds ? formatInterval(refreshSeconds).toUpperCase() : "WAIT"} />
          <InfoCard label="DISPLAYS" value={outputValue} tone="blue" />
        </View>
        <InfoLine label="Saved server" value={serverUrl || "Not set"} />
        <InfoLine label="Mobile build" value={APP_VERSION} />
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
                    {...accessibleButton({
                      label: `Apply profile ${profile.name}`,
                      hint: `${profile.iata}, ${profile.source === "virtual" ? "VATSIM" : "real"}, ${formatInterval(profile.refresh_seconds)}`,
                      selected: active,
                      disabled,
                      busy: applying
                    })}
                  >
                    <View style={styles.settingsProfileChipTop}>
                      <Text style={[styles.settingsProfileName, active && styles.settingsProfileNameActive]} numberOfLines={1}>
                        {profile.name}
                      </Text>
                      {applying ? (
                        <ActivityIndicator size="small" color={palette.blue2} />
                      ) : active ? (
                        <LocalFlightIcon name={ACTION_ICONS.configured} size={14} color={palette.green} />
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
          <Pressable
            style={styles.settingsCompactButton}
            onPress={() => setServerExpanded((value) => !value)}
            {...accessibleButton({
              label: serverExpanded ? "Hide server URL editor" : "Change server URL",
              expanded: serverExpanded
            })}
          >
            <Text style={styles.settingsCompactButtonText}>{serverExpanded ? "HIDE SERVER" : "CHANGE SERVER"}</Text>
          </Pressable>
          <Pressable
            style={[styles.settingsCompactButton, schedulerRestarting && styles.connectButtonDisabled]}
            onPress={onRestartScheduler}
            disabled={schedulerRestarting}
            {...accessibleButton({
              label: schedulerRestarting ? "Restarting fetch" : "Restart fetch",
              disabled: schedulerRestarting,
              busy: schedulerRestarting
            })}
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
            <Pressable
              style={styles.connectButton}
              onPress={onConnect}
              disabled={loading}
              {...accessibleButton({
                label: loading ? "Connecting" : "Connect to Local Flight server",
                disabled: loading,
                busy: loading
              })}
            >
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
            icon={TOOL_ICONS.appearance}
            label="Mobile Look"
            value={`${themeMode} · ${skin} · ${weatherModeOption(weatherDisplayMode).label} WX`}
            onPress={() => setAppearanceVisible(true)}
          />
          <SettingsQuickAction
            icon={TOOL_ICONS.matrix}
            label="Matrix Board"
            value="Status, look, runtime"
            onPress={onOpenMatrix}
          />
          <SettingsQuickAction
            icon={TOOL_ICONS.admin}
            label="Admin & Reports"
            value="Health and diagnostics"
            onPress={onOpenAdmin}
          />
          <SettingsQuickAction
            icon={TOOL_ICONS.history}
            label="History"
            value="Stored flight rows"
            onPress={onOpenHistory}
          />
          <SettingsQuickAction
            icon={TOOL_ICONS.docs}
            label="Docs"
            value="Install + display guide"
            onPress={() => onOpenDoc("install")}
          />
          <SettingsQuickAction
            icon={TOOL_ICONS.privacy}
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
          icon={TOOL_ICONS.displayModes}
          label="Display modes"
          value="Native, browser, Pi, mobile, and Matrix"
          onPress={() => onOpenDoc("display-modes")}
        />
        <SettingsToolPill
          icon={TOOL_ICONS.install}
          label="Project README"
          value="Overview and quick path chooser"
          onPress={() => onOpenDoc("readme")}
        />
        <SettingsToolPill
          icon={TOOL_ICONS.changelog}
          label="Changelog"
          value="Release history and version notes"
          onPress={() => onOpenDoc("changelog")}
        />
        <SettingsToolPill
          icon={TOOL_ICONS.setup}
          label="Rerun mobile setup"
          value="Revisit server pairing and diagnostics consent"
          onPress={onRerunSetup}
        />
      </View>

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

export function ControlScreen({
  snapshot,
  rows,
  view,
  pinnedCallsign,
  serverUrl,
  draftUrl,
  error,
  loading,
  isTablet,
  isLandscape,
  themeMode,
  skin,
  weatherDisplayMode,
  widgetPreferences,
  widgetSnapshotLabel,
  mobileDiagnosticsMode,
  outputs,
  refreshSeconds,
  schedulerRestarting,
  schedulerMessage,
  pairingNotice,
  serverPanelRequest,
  matrixRuntime,
  matrixDirty,
  matrixSaving,
  matrixSaveMessage,
  matrixSaveTone,
  companionIdentity,
  connected,
  connectionState,
  remoteCompanionGrant,
  onThemeModeChange,
  onSkinChange,
  onWeatherDisplayModeChange,
  onWidgetPreferencesChange,
  onMobileDiagnosticsModeChange,
  onMatrixPresetChange,
  onMatrixViewChange,
  onMatrixWeatherToggle,
  onMatrixGateToggle,
  onMatrixPaletteChange,
  onMatrixBrightnessChange,
  onMatrixRowsChange,
  onMatrixRotationChange,
  onMatrixAnimationModeChange,
  onMatrixAnimationSpeedChange,
  onMatrixStatusAnimationToggle,
  onMatrixRefreshChange,
  onMatrixSave,
  onMatrixReset,
  onOpenConfig,
  feedbackTitle,
  feedbackDescription,
  feedbackSending,
  feedbackMessage,
  feedbackTone,
  onFeedbackTitleChange,
  onFeedbackDescriptionChange,
  onSubmitFeedback,
  onRestartScheduler,
  onRerunSetup,
  onForgetRemoteCompanion,
  onChangeUrl,
  onPairingUrl,
  onConnect
}: {
  snapshot: DashboardSnapshot;
  rows: FidsRow[];
  view: FlightView;
  pinnedCallsign: string;
  serverUrl: string;
  draftUrl: string;
  error: string | null;
  loading: boolean;
  isTablet: boolean;
  isLandscape: boolean;
  themeMode: MobileThemeMode;
  skin: MobileSkin;
  weatherDisplayMode: MobileWeatherDisplayMode;
  widgetPreferences: MobileWidgetPreferences;
  widgetSnapshotLabel: string;
  mobileDiagnosticsMode: MobileDiagnosticsMode;
  profiles: ConfigProfile[];
  activeProfileId: string | null;
  applyingProfileId: string | null;
  outputs: string[];
  refreshSeconds: number | null;
  schedulerRestarting: boolean;
  schedulerMessage: string | null;
  pairingNotice?: string | null;
  serverPanelRequest?: number;
  matrixRuntime: MatrixRuntimeConfigSave;
  matrixDirty: boolean;
  matrixSaving: boolean;
  matrixSaveMessage: string | null;
  matrixSaveTone: FeedbackTone;
  companionIdentity: CompanionIdentity | null;
  connected: boolean;
  connectionState?: ConnectionState;
  remoteCompanionGrant?: RemoteCompanionGrant | null;
  onThemeModeChange: (value: MobileThemeMode) => void;
  onSkinChange: (value: MobileSkin) => void;
  onWeatherDisplayModeChange: (value: MobileWeatherDisplayMode) => void;
  onWidgetPreferencesChange: (value: MobileWidgetPreferences) => void;
  onMobileDiagnosticsModeChange: (value: MobileDiagnosticsMode) => void;
  onMatrixPresetChange: (value: MatrixPresetId) => void;
  onMatrixViewChange: (value: FlightView) => void;
  onMatrixWeatherToggle: (value: boolean) => void;
  onMatrixGateToggle: (value: boolean) => void;
  onMatrixPaletteChange: (value: MatrixPaletteId) => void;
  onMatrixBrightnessChange: (value: number) => void;
  onMatrixRowsChange: (value: number) => void;
  onMatrixRotationChange: (value: number) => void;
  onMatrixAnimationModeChange: (value: MatrixAnimationMode) => void;
  onMatrixAnimationSpeedChange: (value: number) => void;
  onMatrixStatusAnimationToggle: (value: boolean) => void;
  onMatrixRefreshChange: (value: number) => void;
  onMatrixSave: () => void;
  onMatrixReset: () => void;
  onApplyProfile: (profile: ConfigProfile) => void;
  onOpenConfig: () => void;
  feedbackTitle: string;
  feedbackDescription: string;
  feedbackSending: boolean;
  feedbackMessage: string | null;
  feedbackTone: FeedbackTone;
  onFeedbackTitleChange: (value: string) => void;
  onFeedbackDescriptionChange: (value: string) => void;
  onSubmitFeedback: () => void;
  onRestartScheduler: () => void;
  onRerunSetup: () => void;
  onForgetRemoteCompanion: () => void;
  onChangeUrl: (value: string) => void;
  onPairingUrl: (value: PairingLinkResult) => void;
  onConnect: () => void;
}) {
  const [activeSheet, setActiveSheet] = useState<"connection" | "appearance" | "matrix" | "widgets" | "help" | null>(null);
  const [activeControlSection, setActiveControlSection] = useState<ControlSection | null>(null);
  const outputValue = outputs.length ? outputs.join(", ").toUpperCase() : "WEB";
  const schedulerRunning = snapshot.scheduler?.running ?? false;
  const hostDiagnostics = snapshot.system?.client?.diagnostics_mode || snapshot.config?.diagnostics_mode || "manual";
  const companionCount = snapshot.connections?.companion_count ?? 0;
  const remoteReady = Boolean(remoteCompanionGrant && !remoteCompanionGrant.revokedAt);
  const remoteSummary = connectionState === "remote"
    ? "Remote Companion active"
    : remoteReady
      ? "remote fallback ready"
      : snapshot.config?.remote_companion_enabled
        ? "remote invite available"
        : "LAN first";
  const matrixPaletteOption = MATRIX_PALETTE_OPTIONS.find((item) => item.id === matrixRuntime.palette) || MATRIX_PALETTE_OPTIONS[0]!;
  const matrixShowWeather = Boolean(matrixRuntime.options.show_metar ?? matrixRuntime.options.show_weather);
  const updateValue = snapshot.updates?.update_available
    ? `V${snapshot.updates.latest || "NEW"} READY`
    : `V${snapshot.updates?.current || snapshot.system?.version || APP_VERSION}`;
  const widgetPreview = deriveWidgetPreviewSnapshot({
    rows,
    pinnedCallsign,
    airportCode: snapshot.config?.airport_iata || snapshot.config?.airport_icao || "---",
    airportName: snapshot.config?.display_name || snapshot.config?.airport_iata || "Local Flight Airport",
    updatedLabel: formatRelative(snapshot.state?.last_success_utc),
    view,
    preferences: widgetPreferences
  });
  const widgetSummary = widgetPreview.pinnedFlight
    ? `Pinned flight · ${widgetPreferences.mediumRowCount} rows`
    : `${widgetPreview.liveFlights.length ? "Pin a flight" : "Waiting for board"} · ${widgetPreferences.mediumRowCount} rows`;
  const feedbackContext = [
    `Reporter      ${companionIdentity?.clientName || "Local Flight Mobile"}`,
    `Mobile ID     ${companionIdentity?.companionId || "UNKNOWN"}`,
    `Mobile OS     ${companionIdentity?.mobileOs || "UNKNOWN"}`,
    `Build         ${companionIdentity?.appVersion || APP_VERSION}`,
    `Server ID     ${snapshot.system?.install_id || "UNKNOWN"}`,
    `Server        ${snapshot.system?.platform || "UNKNOWN"}`,
    `Airport       ${snapshot.config?.airport_iata || "---"}`,
    `Source        ${snapshot.state?.source_name || snapshot.config?.source || "UNKNOWN"}`
  ].join("\n");
  const openSheet = (sheet: "connection" | "appearance" | "matrix" | "widgets" | "help") => {
    setActiveControlSection(null);
    setActiveSheet(sheet);
  };
  const openConfig = () => {
    setActiveControlSection(null);
    onOpenConfig();
  };

  useEffect(() => {
    if (serverPanelRequest) {
      setActiveControlSection(null);
      setActiveSheet("connection");
    }
  }, [serverPanelRequest]);

  return (
    <View style={styles.cardStack}>
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>MOBILE CONTROL</Text>
        <Text style={styles.moduleIntro}>
          One-tap control center for pairing, board settings, Matrix, diagnostics, and help.
        </Text>
      </View>

      <ControlActionCard
        icon={TOOL_ICONS.setup}
        title="Connect to Local Flight"
        summary={serverUrl ? `${companionCount} mobiles · ${remoteSummary} · ${outputValue}` : "Pair this phone with your LAN server"}
        onPress={() => openSheet("connection")}
      />

      <ControlAccordionCard
        section="host"
        activeSection={activeControlSection}
        icon={TOOL_ICONS.admin}
        title="Host Information"
        summary={`${serverUrl ? "Ready" : "Setup"} · ${schedulerRunning ? "scheduler healthy" : "scheduler check"}`}
        onSelect={setActiveControlSection}
      >
        <View style={styles.metricRow}>
          <InfoCard label="SERVER" value={serverUrl ? "READY" : "SETUP"} tone={serverUrl ? "green" : "amber"} />
          <InfoCard label="SCHEDULER" value={schedulerRunning ? "HEALTHY" : "CHECK"} tone={schedulerRunning ? "green" : "amber"} />
          <InfoCard label="VERSION" value={`V${snapshot.system?.version || APP_VERSION}`} tone="blue" />
        </View>
        <InfoLine label="Airport" value={snapshot.config?.airport_iata || "---"} />
        <InfoLine label="Source" value={snapshot.state?.source_name || snapshot.config?.source || "Unknown"} />
        <InfoLine label="Last successful fetch" value={formatRelative(snapshot.state?.last_success_utc)} />
        <InfoLine label="Host install" value={snapshot.system?.install_id || "Unknown host"} />
      </ControlAccordionCard>

      <ControlActionCard
        icon={TOOL_ICONS.control}
        title="FIDS Display Settings"
        summary={`${snapshot.config?.airport_iata || "---"} · ${snapshot.config?.source || "unknown"} · ${refreshSeconds ? formatInterval(refreshSeconds) : "waiting"}`}
        onPress={openConfig}
      />

      <ControlActionCard
        icon={TOOL_ICONS.matrix}
        title="Matrix Board"
        summary={`${matrixPaletteOption.label} · ${matrixRuntime.max_rows} rows · WX ${matrixShowWeather ? "on" : "off"}`}
        onPress={() => openSheet("matrix")}
      />

      <ControlActionCard
        icon={TOOL_ICONS.appearance}
        title="Mobile Customization"
        summary={`${themeMode} · ${skin} · ${weatherModeOption(weatherDisplayMode).label} weather`}
        onPress={() => openSheet("appearance")}
      />

      <ControlActionCard
        icon={TOOL_ICONS.displayModes}
        title="Widgets & Glances"
        summary={widgetSummary}
        onPress={() => openSheet("widgets")}
      />

      <ControlAccordionCard
        section="diagnostics"
        activeSection={activeControlSection}
        icon={TOOL_ICONS.report}
        title="Diagnostics & Reset"
        summary={`${String(hostDiagnostics).replace(/_/g, " ")} host · ${mobileDiagnosticsMode.replace(/_/g, " ")} mobile`}
        onSelect={setActiveControlSection}
      >
        <InfoLine label="Host diagnostics" value={String(hostDiagnostics).replace(/_/g, " ").toUpperCase()} />
        <FilterSection title="MOBILE REPORTING">
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
        <Pressable
          style={[styles.connectButton, styles.crashButton]}
          onPress={onRerunSetup}
          {...accessibleButton({
            label: "Rerun mobile setup",
            hint: "Starts first launch setup again."
          })}
        >
          <Text style={styles.connectButtonText}>RERUN MOBILE SETUP</Text>
        </Pressable>
      </ControlAccordionCard>

      <ControlActionCard
        icon={TOOL_ICONS.help}
        title="Help & Reports"
        summary="Troubleshooting, reports, Beacon Tools, source"
        onPress={() => openSheet("help")}
      />

      <ConnectionPairingSheet
        visible={activeSheet === "connection"}
        snapshot={snapshot}
        serverUrl={serverUrl}
        draftUrl={draftUrl}
        error={error}
        loading={loading}
        isTablet={isTablet}
        isLandscape={isLandscape}
        outputs={outputs}
        refreshSeconds={refreshSeconds}
        schedulerRestarting={schedulerRestarting}
        schedulerMessage={schedulerMessage}
        pairingNotice={pairingNotice}
        connectionState={connectionState}
        remoteCompanionGrant={remoteCompanionGrant || null}
        onClose={() => setActiveSheet(null)}
        onRestartScheduler={onRestartScheduler}
        onForgetRemoteCompanion={onForgetRemoteCompanion}
        onChangeUrl={onChangeUrl}
        onPairingUrl={onPairingUrl}
        onConnect={onConnect}
      />

      <AppearanceSheet
        visible={activeSheet === "appearance"}
        themeMode={themeMode}
        skin={skin}
        weatherDisplayMode={weatherDisplayMode}
        onClose={() => setActiveSheet(null)}
        onThemeModeChange={onThemeModeChange}
        onSkinChange={onSkinChange}
        onWeatherDisplayModeChange={onWeatherDisplayModeChange}
      />
      <MatrixLiveSheet
        visible={activeSheet === "matrix"}
        matrixRuntime={matrixRuntime}
        matrixDirty={matrixDirty}
        matrixSaving={matrixSaving}
        matrixSaveMessage={matrixSaveMessage}
        matrixSaveTone={matrixSaveTone}
        onClose={() => setActiveSheet(null)}
        onMatrixPresetChange={onMatrixPresetChange}
        onMatrixViewChange={onMatrixViewChange}
        onMatrixWeatherToggle={onMatrixWeatherToggle}
        onMatrixGateToggle={onMatrixGateToggle}
        onMatrixPaletteChange={onMatrixPaletteChange}
        onMatrixBrightnessChange={onMatrixBrightnessChange}
        onMatrixRowsChange={onMatrixRowsChange}
        onMatrixRotationChange={onMatrixRotationChange}
        onMatrixAnimationModeChange={onMatrixAnimationModeChange}
        onMatrixAnimationSpeedChange={onMatrixAnimationSpeedChange}
        onMatrixStatusAnimationToggle={onMatrixStatusAnimationToggle}
        onMatrixRefreshChange={onMatrixRefreshChange}
        onMatrixSave={onMatrixSave}
        onMatrixReset={onMatrixReset}
      />
      <WidgetSettingsSheet
        visible={activeSheet === "widgets"}
        preview={widgetPreview}
        preferences={widgetPreferences}
        snapshotLabel={widgetSnapshotLabel}
        onPreferencesChange={onWidgetPreferencesChange}
        onClose={() => setActiveSheet(null)}
      />
      <HelpReportsSheet
        visible={activeSheet === "help"}
        mode="lan"
        connected={connected}
        updateValue={updateValue}
        schedulerRunning={schedulerRunning}
        feedbackContext={feedbackContext}
        feedbackTitle={feedbackTitle}
        feedbackDescription={feedbackDescription}
        feedbackSending={feedbackSending}
        feedbackMessage={feedbackMessage}
        feedbackTone={feedbackTone}
        onClose={() => setActiveSheet(null)}
        onFeedbackTitleChange={onFeedbackTitleChange}
        onFeedbackDescriptionChange={onFeedbackDescriptionChange}
        onSubmitFeedback={onSubmitFeedback}
      />
    </View>
  );
}

type ControlSection =
  | "connection"
  | "host"
  | "fids"
  | "matrix"
  | "appearance"
  | "widgets"
  | "diagnostics"
  | "help"
  | "standalone"
  | "board";

export function StandaloneSettingsScreen({
  snapshot,
  rows,
  view,
  pinnedCallsign,
  companionIdentity,
  connected,
  airportCode,
  airportName,
  relayTokenPrefix,
  themeMode,
  skin,
  weatherDisplayMode,
  widgetPreferences,
  widgetSnapshotLabel,
  mobileDiagnosticsMode,
  feedbackTitle,
  feedbackDescription,
  feedbackSending,
  feedbackMessage,
  feedbackTone,
  onThemeModeChange,
  onSkinChange,
  onWeatherDisplayModeChange,
  onWidgetPreferencesChange,
  onMobileDiagnosticsModeChange,
  onRerunSetup,
  onFeedbackTitleChange,
  onFeedbackDescriptionChange,
  onSubmitFeedback
}: {
  snapshot: DashboardSnapshot;
  rows: FidsRow[];
  view: FlightView;
  pinnedCallsign: string;
  companionIdentity: CompanionIdentity | null;
  connected: boolean;
  airportCode: string;
  airportName: string;
  relayTokenPrefix: string;
  themeMode: MobileThemeMode;
  skin: MobileSkin;
  weatherDisplayMode: MobileWeatherDisplayMode;
  widgetPreferences: MobileWidgetPreferences;
  widgetSnapshotLabel: string;
  mobileDiagnosticsMode: MobileDiagnosticsMode;
  feedbackTitle: string;
  feedbackDescription: string;
  feedbackSending: boolean;
  feedbackMessage: string | null;
  feedbackTone: FeedbackTone;
  onThemeModeChange: (value: MobileThemeMode) => void;
  onSkinChange: (value: MobileSkin) => void;
  onWeatherDisplayModeChange: (value: MobileWeatherDisplayMode) => void;
  onWidgetPreferencesChange: (value: MobileWidgetPreferences) => void;
  onMobileDiagnosticsModeChange: (value: MobileDiagnosticsMode) => void;
  onRerunSetup: () => void;
  onFeedbackTitleChange: (value: string) => void;
  onFeedbackDescriptionChange: (value: string) => void;
  onSubmitFeedback: () => void;
}) {
  const [activeSection, setActiveSection] = useState<ControlSection | null>(null);
  const [activeSheet, setActiveSheet] = useState<"appearance" | "widgets" | "help" | null>(null);
  const weatherOption = weatherModeOption(weatherDisplayMode);
  const airportLabel = [airportCode, airportName].filter(Boolean).join(" · ") || "Airport not set";
  const tokenRef = relayTokenPrefix || snapshot.system?.client?.activation_token_prefix || "not set";
  const widgetPreview = deriveWidgetPreviewSnapshot({
    rows,
    pinnedCallsign,
    airportCode,
    airportName,
    updatedLabel: formatRelative(snapshot.state?.last_success_utc),
    view,
    preferences: widgetPreferences
  });
  const widgetSummary = widgetPreview.pinnedFlight
    ? `Pinned flight · ${widgetPreferences.mediumRowCount} rows`
    : `${widgetPreview.liveFlights.length ? "Pin a flight" : "Waiting for board"} · ${widgetPreferences.mediumRowCount} rows`;
  const feedbackContext = [
    `Reporter      ${companionIdentity?.clientName || "Local Flight Mobile"}`,
    `Mobile ID     ${companionIdentity?.companionId || "UNKNOWN"}`,
    `Mobile OS     ${companionIdentity?.mobileOs || "UNKNOWN"}`,
    `Build         ${companionIdentity?.appVersion || APP_VERSION}`,
    `Mode          Standalone relay`,
    `Token ref     ${tokenRef}`,
    `Airport       ${snapshot.config?.airport_iata || airportCode || "---"}`,
    `Source        ${snapshot.state?.source_name || snapshot.config?.source || "relay"}`
  ].join("\n");
  const openSheet = (sheet: "appearance" | "widgets" | "help") => {
    setActiveSection(null);
    setActiveSheet(sheet);
  };

  return (
    <View style={styles.cardStack}>
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>MOBILE SETTINGS</Text>
        <Text style={styles.moduleIntro}>
          Standalone is the lighter mobile board: relay data, local history, appearance, diagnostics, and help without host controls.
        </Text>
      </View>

      <ControlAccordionCard
        section="standalone"
        activeSection={activeSection}
        icon={SETUP_ICONS.lan}
        title="Standalone Relay"
        summary={`${airportCode || "---"} · no desktop or Pi needed`}
        onSelect={setActiveSection}
      >
        <View style={styles.metricRow}>
          <InfoCard label="AIRPORT" value={airportCode || "---"} tone="blue" />
          <InfoCard label="MODE" value="RELAY" tone={connected ? "green" : "amber"} />
          <InfoCard label="POLICY" value="3H / 5M" tone="blue" />
        </View>
        <InfoLine label="Airport" value={airportLabel} />
        <InfoLine label="Relay token" value={tokenRef} />
        <InfoLine label="How it works" value="This phone asks the Local Flight relay directly. It does not need your desktop or Pi on the LAN." />
      </ControlAccordionCard>

      <ControlAccordionCard
        section="board"
        activeSection={activeSection}
        icon={TOOL_ICONS.displayModes}
        title="Board Data"
        summary="FIDS, radar, and local movement history"
        onSelect={setActiveSection}
      >
        <View style={styles.metricRow}>
          <InfoCard label="FIDS" value="3H" tone="blue" />
          <InfoCard label="RADAR" value="5M" tone="blue" />
          <InfoCard label="HISTORY" value="LOCAL" tone="green" />
        </View>
        <InfoLine label="FIDS board" value="Standalone refreshes the board no faster than every 3 hours to protect shared relay limits." />
        <InfoLine label="Radar" value="Radar refreshes no faster than every 5 minutes and supports 1, 3, 5, and 10 NM." />
        <InfoLine label="History" value="Successful board rows are stored on this device only for quick movement summaries." />
      </ControlAccordionCard>

      <ControlActionCard
        icon={TOOL_ICONS.appearance}
        title="Mobile Customization"
        summary={`${themeMode} · ${skin} · ${weatherOption.label} weather`}
        onPress={() => openSheet("appearance")}
      />

      <ControlActionCard
        icon={TOOL_ICONS.displayModes}
        title="Widgets & Glances"
        summary={widgetSummary}
        onPress={() => openSheet("widgets")}
      />

      <ControlAccordionCard
        section="diagnostics"
        activeSection={activeSection}
        icon={TOOL_ICONS.report}
        title="Diagnostics & Reset"
        summary={`${mobileDiagnosticsMode.replace(/_/g, " ")} reports · setup reset`}
        onSelect={setActiveSection}
      >
        <InfoLine label="Mobile diagnostics" value={mobileDiagnosticsMode.replace(/_/g, " ").toUpperCase()} />
        <FilterSection title="MOBILE REPORTING">
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
        <Pressable
          style={[styles.connectButton, styles.crashButton]}
          onPress={onRerunSetup}
          {...accessibleButton({
            label: "Rerun mobile setup",
            hint: "Starts the first launch setup flow again."
          })}
        >
          <Text style={styles.connectButtonText}>RERUN MOBILE SETUP</Text>
        </Pressable>
      </ControlAccordionCard>

      <ControlActionCard
        icon={TOOL_ICONS.help}
        title="Help & Reports"
        summary="Troubleshooting, reports, Beacon Tools, source"
        onPress={() => openSheet("help")}
      />

      <AppearanceSheet
        visible={activeSheet === "appearance"}
        themeMode={themeMode}
        skin={skin}
        weatherDisplayMode={weatherDisplayMode}
        onClose={() => setActiveSheet(null)}
        onThemeModeChange={onThemeModeChange}
        onSkinChange={onSkinChange}
        onWeatherDisplayModeChange={onWeatherDisplayModeChange}
      />
      <WidgetSettingsSheet
        visible={activeSheet === "widgets"}
        preview={widgetPreview}
        preferences={widgetPreferences}
        snapshotLabel={widgetSnapshotLabel}
        onPreferencesChange={onWidgetPreferencesChange}
        onClose={() => setActiveSheet(null)}
      />
      <HelpReportsSheet
        visible={activeSheet === "help"}
        mode="standalone"
        connected={connected}
        updateValue={tokenRef === "not set" ? "Relay setup needed" : "Relay token saved"}
        schedulerRunning={connected}
        feedbackContext={feedbackContext}
        feedbackTitle={feedbackTitle}
        feedbackDescription={feedbackDescription}
        feedbackSending={feedbackSending}
        feedbackMessage={feedbackMessage}
        feedbackTone={feedbackTone}
        onClose={() => setActiveSheet(null)}
        onFeedbackTitleChange={onFeedbackTitleChange}
        onFeedbackDescriptionChange={onFeedbackDescriptionChange}
        onSubmitFeedback={onSubmitFeedback}
      />
    </View>
  );
}

function WidgetSettingsSheet({
  visible,
  preview,
  preferences,
  snapshotLabel,
  onPreferencesChange,
  onClose
}: {
  visible: boolean;
  preview: WidgetPreviewSnapshot;
  preferences: MobileWidgetPreferences;
  snapshotLabel: string;
  onPreferencesChange: (value: MobileWidgetPreferences) => void;
  onClose: () => void;
}) {
  const pinned = preview.pinnedFlight;
  const sourceCopy = pinned ? "Pinned flight" : "Pin a flight";

  return (
    <Modal visible={visible} transparent presentationStyle="overFullScreen" animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable
          style={styles.sheetBackdropPress}
          onPress={onClose}
          {...accessibleButton({ label: "Close widget settings" })}
        />
        <View style={styles.sheetCard}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>WIDGETS & GLANCES</Text>
              <Text style={styles.sheetTitle}>Widget Preview</Text>
            </View>
            <Pressable
              style={styles.sheetAction}
              onPress={onClose}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: "Close widget settings" })}
            >
              <Text style={styles.sheetActionText}>DONE</Text>
            </Pressable>
          </View>

          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}>
            <View style={styles.widgetNotice}>
              <View style={styles.supportHeroIcon}>
                <LocalFlightIcon name={TOOL_ICONS.displayModes} size={22} color={palette.blue2} />
              </View>
              <View style={styles.supportHeroCopy}>
                <Text style={styles.supportHeroTitle}>Ready for iOS widgets.</Text>
                <Text style={styles.supportHeroBody}>
                  Widgets use the current pinned-flight and board snapshot. After installing, add Local Flight from the iOS widget gallery if it is not already on your Home Screen.
                </Text>
              </View>
            </View>

            <View style={styles.metricRow}>
              <InfoCard label="SMALL" value={sourceCopy.toUpperCase()} tone={pinned ? "green" : "amber"} />
              <InfoCard label="MEDIUM" value={`${preferences.mediumRowCount} ROWS`} tone="blue" />
              <InfoCard label="ISLAND" value={pinned ? "PINNED" : "WAITING"} tone={pinned ? "blue" : "amber"} />
            </View>

            <WidgetSmallPinnedPreview
              preview={preview}
              showGateTerminal={preferences.showGateTerminal}
            />

            <WidgetMediumFidsPreview
              preview={preview}
              showGateTerminal={preferences.showGateTerminal}
            />

            <FilterSection title="MEDIUM WIDGET ROWS">
              <View style={styles.filterRow}>
                {[2, 3].map((count) => (
                  <DirectionButton
                    key={count}
                    active={preferences.mediumRowCount === count}
                    label={`${count} ROWS`}
                    onPress={() => onPreferencesChange({ ...preferences, mediumRowCount: count as 2 | 3 })}
                  />
                ))}
              </View>
            </FilterSection>

            <FilterSection title="GATE / TERMINAL DETAIL">
              <View style={styles.filterRow}>
                <DirectionButton
                  active={preferences.showGateTerminal}
                  label="AUTO DETAIL"
                  onPress={() => onPreferencesChange({ ...preferences, showGateTerminal: true })}
                />
                <DirectionButton
                  active={!preferences.showGateTerminal}
                  label="MINIMAL"
                  onPress={() => onPreferencesChange({ ...preferences, showGateTerminal: false })}
                />
              </View>
            </FilterSection>

            <InfoLine label="Dynamic Island" value="Future iOS Live Activity stays pinned-flight-only: flight number and short status first, no mini FIDS board." />
            <InfoLine label="Snapshot" value={snapshotLabel} />
            <InfoLine label="Data source" value="Widgets read the app-written snapshot. They do not poll LAN or relay data directly." />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function WidgetSmallPinnedPreview({
  preview,
  showGateTerminal
}: {
  preview: WidgetPreviewSnapshot;
  showGateTerminal: boolean;
}) {
  const flight = preview.pinnedFlight;
  const directionLabel = preview.view === "arrivals" ? "ARR" : "DEP";
  const detail = flight && showGateTerminal ? widgetGateTerminal(flight) : "";

  return (
    <View style={[styles.widgetPreviewCard, styles.widgetSmallTracker]}>
      <View style={styles.widgetPreviewHeader}>
        <View>
          <Text style={styles.widgetPreviewTitle}>Small widget</Text>
          <Text style={styles.widgetPreviewMeta}>{preview.airportCode} · {directionLabel}</Text>
        </View>
        {flight ? <WidgetStatusPill flight={flight} /> : <Text style={styles.widgetPreviewMeta}>PINNED</Text>}
      </View>
      {flight ? (
        <>
          <Text style={styles.widgetFlightMain} numberOfLines={1}>{flight.flightDisplay}</Text>
          <Text style={styles.widgetFlightSub} numberOfLines={1}>
            {flight.displayTime} · {flight.routeCode || flight.routeName}{detail ? ` · ${detail}` : ""}
          </Text>
          <Text style={styles.widgetTrackerRoute} numberOfLines={1}>{flight.routeName}</Text>
        </>
      ) : (
        <View style={styles.widgetTrackerEmpty}>
          <Text style={styles.widgetEmptyTitle}>Pin a flight in Local Flight</Text>
          <Text style={styles.widgetEmptyText}>The small widget stays dedicated to the flight you choose on the board.</Text>
        </View>
      )}
    </View>
  );
}

function WidgetMediumFidsPreview({
  preview,
  showGateTerminal
}: {
  preview: WidgetPreviewSnapshot;
  showGateTerminal: boolean;
}) {
  const directionLabel = preview.view === "arrivals" ? "ARRIVALS" : "DEPARTURES";
  const routeHeading = preview.view === "arrivals" ? "FROM" : "TO";
  const rows = [
    ...(preview.pinnedFlight ? [preview.pinnedFlight] : []),
    ...preview.liveFlights
  ];

  return (
    <View style={styles.widgetFidsBoard}>
      <View style={styles.widgetFidsTop}>
        <View style={styles.widgetFidsBeaconWatermark} {...hideFromAccessibility()}>
          <BeaconToolsMark
            size={42}
            color={hexToRgba(palette.blue2, 0.20)}
            windowColor={palette.bg}
          />
        </View>
        <View style={styles.widgetFidsIdentity}>
          <Text
            style={styles.widgetFidsTitle}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.72}
          >
            {preview.airportName}
          </Text>
          <Text style={styles.widgetFidsBoardBadge}>{directionLabel}</Text>
        </View>
        <View style={styles.widgetFidsMeta}>
          <BrandWordmark
            color={palette.text}
            size={15}
            style={styles.widgetFidsBrand}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.68}
          >
            Local Flight
          </BrandWordmark>
          <Text style={styles.widgetFidsSource} numberOfLines={1}>
            {preview.updatedLabel.toUpperCase()}
          </Text>
        </View>
      </View>

      <View style={styles.widgetFidsColumns}>
        <Text style={[styles.widgetFidsColumnText, styles.widgetFidsTimeColumn]}>TIME</Text>
        <Text style={[styles.widgetFidsColumnText, styles.widgetFidsFlightColumn]}>FLIGHT</Text>
        <Text style={[styles.widgetFidsColumnText, styles.widgetFidsRouteColumn]}>{routeHeading}</Text>
        <Text style={[styles.widgetFidsColumnText, styles.widgetFidsStatusColumn]}>STATUS</Text>
        {showGateTerminal ? <Text style={[styles.widgetFidsColumnText, styles.widgetFidsInfoColumn]}>INFO</Text> : null}
      </View>

      <View style={styles.widgetFidsRows}>
        {rows.length ? rows.map((flight, index) => (
          <WidgetFidsPreviewRow
            key={`${flight.id}-${index}`}
            flight={flight}
            pinned={Boolean(preview.pinnedFlight && index === 0)}
            showGateTerminal={showGateTerminal}
          />
        )) : (
          <View style={styles.widgetFidsEmpty}>
            <Text style={styles.widgetEmptyTitle}>Waiting for board data</Text>
            <Text style={styles.widgetEmptyText}>The medium widget preview fills from the latest airport rows.</Text>
          </View>
        )}
      </View>
    </View>
  );
}

function WidgetFidsPreviewRow({
  flight,
  pinned,
  showGateTerminal
}: {
  flight: WidgetFlightPreview;
  pinned: boolean;
  showGateTerminal: boolean;
}) {
  const detail = showGateTerminal ? widgetGateTerminal(flight) : "";
  return (
    <View style={[styles.widgetFidsRow, pinned && styles.widgetFidsRowPinned]}>
      <Text
        style={[styles.widgetFidsTime, styles.widgetFidsTimeColumn]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.72}
      >
        {flight.displayTime}
      </Text>
      <View style={[styles.widgetFidsFlightCell, styles.widgetFidsFlightColumn]}>
        <Text style={styles.widgetFidsFlight} numberOfLines={1}>{flight.flightDisplay}</Text>
        <Text style={styles.widgetFidsSubline} numberOfLines={1}>{pinned ? "PINNED" : flight.direction.toUpperCase()}</Text>
      </View>
      <View style={[styles.widgetFidsRouteCell, styles.widgetFidsRouteColumn]}>
        <Text style={styles.widgetFidsRouteName} numberOfLines={1}>{flight.routeName}</Text>
        <Text style={styles.widgetFidsRouteMeta} numberOfLines={1}>{flight.routeCode || "-"}</Text>
      </View>
      <View style={styles.widgetFidsStatusColumn}>
        <WidgetStatusPill flight={flight} compact />
      </View>
      {showGateTerminal ? (
        <Text style={[styles.widgetFidsInfoValue, styles.widgetFidsInfoColumn]} numberOfLines={1}>{detail || "-"}</Text>
      ) : null}
    </View>
  );
}

function WidgetStatusPill({
  flight,
  compact = false
}: {
  flight: WidgetFlightPreview;
  compact?: boolean;
}) {
  return (
    <View style={[styles.statusBadge, statusBadgeStyle(flight.statusTone), compact && styles.statusBadgeCompact]}>
      <Text style={[styles.statusBadgeText, statusTextStyle(flight.statusTone)]} numberOfLines={1}>
        {flight.statusDisplay.slice(0, compact ? 8 : 10)}
      </Text>
    </View>
  );
}

function widgetGateTerminal(flight: WidgetFlightPreview): string {
  const parts = [
    flight.terminal ? `T${flight.terminal.replace(/^T/i, "")}` : "",
    flight.gate ? `G${flight.gate.replace(/^G/i, "")}` : ""
  ].filter(Boolean);
  return parts.join(" ");
}

function ControlActionCard({
  icon,
  title,
  summary,
  onPress
}: {
  icon: AppIconName;
  title: string;
  summary: string;
  onPress: () => void;
}) {
  return (
    <View style={[styles.settingsCard, styles.controlAccordionCard]}>
      <Pressable
        style={styles.controlAccordionHeader}
        onPress={() => {
          hapticSelection();
          onPress();
        }}
        {...accessibleButton({
          label: title,
          hint: summary
        })}
      >
        <View style={styles.settingsPillIcon}>
          <LocalFlightIcon name={icon} size={18} color={palette.blue2} />
        </View>
        <View style={styles.settingsPillCopy}>
          <Text style={styles.settingsPillLabel}>{title}</Text>
          <Text style={styles.settingsPillValue} numberOfLines={2}>{summary}</Text>
        </View>
        <LocalFlightIcon name={ACTION_ICONS.drillIn} size={18} color={palette.textDim} />
      </Pressable>
    </View>
  );
}

function ControlAccordionCard({
  section,
  activeSection,
  icon,
  title,
  summary,
  onSelect,
  children
}: {
  section: ControlSection;
  activeSection: ControlSection | null;
  icon: AppIconName;
  title: string;
  summary: string;
  onSelect: (section: ControlSection | null) => void;
  children: ReactNode;
}) {
  const expanded = section === activeSection;
  return (
    <View style={[styles.settingsCard, styles.controlAccordionCard]}>
      <Pressable
        style={styles.controlAccordionHeader}
        onPress={() => {
          hapticSelection();
          onSelect(expanded ? null : section);
        }}
        {...accessibleButton({
          label: title,
          hint: summary,
          expanded
        })}
      >
        <View style={styles.settingsPillIcon}>
          <LocalFlightIcon name={icon} size={18} color={palette.blue2} />
        </View>
        <View style={styles.settingsPillCopy}>
          <Text style={styles.settingsPillLabel}>{title}</Text>
          <Text style={styles.settingsPillValue} numberOfLines={2}>{summary}</Text>
        </View>
        <LocalFlightIcon
          name={expanded ? ACTION_ICONS.supportExpand : ACTION_ICONS.drillIn}
          size={18}
          color={expanded ? palette.blue2 : palette.textDim}
        />
      </Pressable>
      {expanded ? <View style={styles.controlAccordionBody}>{children}</View> : null}
    </View>
  );
}

function HelpReportsSheet({
  visible,
  mode,
  connected,
  updateValue,
  schedulerRunning,
  feedbackContext,
  feedbackTitle,
  feedbackDescription,
  feedbackSending,
  feedbackMessage,
  feedbackTone,
  onClose,
  onFeedbackTitleChange,
  onFeedbackDescriptionChange,
  onSubmitFeedback
}: {
  visible: boolean;
  mode: "lan" | "standalone";
  connected: boolean;
  updateValue: string;
  schedulerRunning: boolean;
  feedbackContext: string;
  feedbackTitle: string;
  feedbackDescription: string;
  feedbackSending: boolean;
  feedbackMessage: string | null;
  feedbackTone: FeedbackTone;
  onClose: () => void;
  onFeedbackTitleChange: (value: string) => void;
  onFeedbackDescriptionChange: (value: string) => void;
  onSubmitFeedback: () => void;
}) {
  const isLan = mode === "lan";
  const pairingLabel = isLan ? "Pairing & host" : "Relay setup";
  const pairingValue = isLan
    ? `${connected ? "Connected" : "Check connection"} · ${updateValue} · ${schedulerRunning ? "scheduler running" : "scheduler check"}`
    : `${connected ? "Relay reachable" : "Check internet"} · ${updateValue}`;
  const connectionLabel = isLan ? "Cannot connect" : "Relay check";
  const connectionValue = isLan
    ? "Confirm Local Flight is running on the same Wi-Fi and use the desktop or Pi LAN address, not phone localhost."
    : "If standalone requests fail, check internet access first. Standalone does not need your desktop or Pi.";
  const staleValue = isLan
    ? "Use Restart Fetch from the pairing sheet, then wait for the next snapshot push or open the board again."
    : "Standalone refreshes intentionally slowly; pull to refresh when you want to request the latest allowed board.";
  const titlePlaceholder = isLan
    ? "Short summary, for example Radar stopped updating"
    : "Short summary, for example Standalone board did not refresh";
  const descriptionPlaceholder = isLan
    ? "What happened, what you expected, and how to reproduce it"
    : "What happened, what you expected, and which airport/source you were using";

  return (
    <Modal visible={visible} transparent presentationStyle="overFullScreen" animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable
          style={styles.sheetBackdropPress}
          onPress={onClose}
          {...accessibleButton({ label: "Close help and reports" })}
        />
        <View style={styles.sheetCard}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>HELP & REPORTS</Text>
              <Text style={styles.sheetTitle}>Mobile Help</Text>
            </View>
            <Pressable
              style={styles.sheetAction}
              onPress={onClose}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: "Close help and reports" })}
            >
              <Text style={styles.sheetActionText}>DONE</Text>
            </Pressable>
          </View>

          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}>
            <InfoLine label={pairingLabel} value={pairingValue} />
            <InfoLine label={connectionLabel} value={connectionValue} />
            <InfoLine label="Board looks stale" value={staleValue} />
            <InfoLine
              label="Display data"
              value="Flight, weather, and radar information are for personal display only, not for navigation or safety decisions."
            />
            <SettingsToolPill
              icon={TOOL_ICONS.github}
              label="Project website"
              value="Docs, privacy, support, source, and releases"
              onPress={() => void Linking.openURL("https://beacontools.cc/local-flight")}
            />
            <Text style={styles.settingsProfileTitle}>REPORT PROBLEM</Text>
            <TextInput
              value={feedbackTitle}
              onChangeText={onFeedbackTitleChange}
              placeholder={titlePlaceholder}
              placeholderTextColor={palette.textDim}
              style={styles.serverInput}
            />
            <TextInput
              value={feedbackDescription}
              onChangeText={onFeedbackDescriptionChange}
              placeholder={descriptionPlaceholder}
              placeholderTextColor={palette.textDim}
              multiline
              textAlignVertical="top"
              style={[styles.serverInput, styles.feedbackInput]}
            />
            <View style={styles.feedbackContextBox}>
              <Text style={styles.feedbackContextText}>{feedbackContext}</Text>
            </View>
            <Pressable
              style={[styles.connectButton, feedbackSending && styles.connectButtonDisabled]}
              onPress={onSubmitFeedback}
              disabled={feedbackSending}
              {...accessibleButton({
                label: feedbackSending ? "Sending report" : "Send report",
                disabled: feedbackSending,
                busy: feedbackSending
              })}
            >
              {feedbackSending ? <ActivityIndicator color={solidButtonInk()} /> : <Text style={styles.connectButtonText}>SEND REPORT</Text>}
            </Pressable>
            {feedbackMessage ? (
              <Text style={[styles.feedbackMessage, feedbackTone === "ok" ? styles.feedbackMessageOk : styles.feedbackMessageError]}>
                {feedbackMessage}
              </Text>
            ) : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function ConnectionPairingSheet({
  visible,
  snapshot,
  serverUrl,
  draftUrl,
  error,
  loading,
  isTablet,
  isLandscape,
  outputs,
  refreshSeconds,
  schedulerRestarting,
  schedulerMessage,
  pairingNotice,
  connectionState,
  remoteCompanionGrant,
  onClose,
  onRestartScheduler,
  onForgetRemoteCompanion,
  onChangeUrl,
  onPairingUrl,
  onConnect
}: {
  visible: boolean;
  snapshot: DashboardSnapshot;
  serverUrl: string;
  draftUrl: string;
  error: string | null;
  loading: boolean;
  isTablet: boolean;
  isLandscape: boolean;
  outputs: string[];
  refreshSeconds: number | null;
  schedulerRestarting: boolean;
  schedulerMessage: string | null;
  pairingNotice?: string | null;
  connectionState?: ConnectionState;
  remoteCompanionGrant?: RemoteCompanionGrant | null;
  onClose: () => void;
  onRestartScheduler: () => void;
  onForgetRemoteCompanion: () => void;
  onChangeUrl: (value: string) => void;
  onPairingUrl: (value: PairingLinkResult) => void;
  onConnect: () => void;
}) {
  const [scannerVisible, setScannerVisible] = useState(false);
  const [remoteProbeTesting, setRemoteProbeTesting] = useState(false);
  const [remoteProbeResult, setRemoteProbeResult] = useState<RemoteCompanionProbeResult | null>(null);
  const outputValue = outputs.length ? outputs.join(", ").toUpperCase() : "WEB";
  const remoteReady = Boolean(remoteCompanionGrant && !remoteCompanionGrant.revokedAt);
  const pathLabel = connectionState === "remote"
    ? "REMOTE"
    : connectionState === "offline"
      ? "OFFLINE"
      : connectionState === "retrying"
        ? "RETRYING"
        : "LAN";
  const pathTone = connectionState === "remote"
    ? "blue"
    : connectionState === "offline"
      ? "red"
      : connectionState === "retrying"
        ? "amber"
        : "green";
  const remoteValue = connectionState === "remote"
    ? "Using encrypted Remote Companion now."
    : remoteReady
      ? "Ready when this phone is away from the LAN."
      : "Pair a Remote Companion QR from Local Flight Settings to use this phone away from Wi-Fi.";
  const runRemoteProbe = useCallback(async () => {
    if (remoteProbeTesting) return;
    setRemoteProbeTesting(true);
    try {
      setRemoteProbeResult(await testRemoteCompanionProbe(remoteCompanionGrant));
    } finally {
      setRemoteProbeTesting(false);
    }
  }, [remoteCompanionGrant, remoteProbeTesting]);
  const remoteProbeMessage = remoteProbeResult
    ? `${remoteProbeResult.message} ${remoteProbeResult.nextStep}${remoteProbeResult.attempts > 1 ? ` Tried ${remoteProbeResult.attempts} times.` : ""}`
    : "";

  return (
    <Modal visible={visible} transparent presentationStyle="overFullScreen" animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable
          style={styles.sheetBackdropPress}
          onPress={onClose}
          {...accessibleButton({ label: "Close connection settings" })}
        />
        <View style={styles.sheetCard}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>CONNECTION</Text>
              <Text style={styles.sheetTitle}>Pair Server & Refresh</Text>
            </View>
            <Pressable
              style={styles.sheetAction}
              onPress={onClose}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: "Close connection settings" })}
            >
              <Text style={styles.sheetActionText}>DONE</Text>
            </Pressable>
          </View>

          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.sheetContent}>
            <Text style={styles.moduleIntro}>
              Scan the fingerprint-bound QR from Local Flight Settings or enter the LAN IP manually. localflight.local is a fallback for one-server LANs.
            </Text>
            <View style={styles.metricRow}>
              <InfoCard label="PATH" value={pathLabel} tone={pathTone} />
              <InfoCard label="REFRESH" value={refreshSeconds ? formatInterval(refreshSeconds).toUpperCase() : "WAIT"} />
              <InfoCard label="DISPLAYS" value={outputValue} tone="blue" />
              <InfoCard label="LAYOUT" value={isTablet ? (isLandscape ? "IPAD LAND" : "IPAD PORT") : "IPHONE"} />
            </View>
            <InfoLine label="Saved server" value={serverUrl || "Not set"} />
            <InfoLine label="Host install" value={snapshot.system?.install_id || "Unknown"} />
            <InfoLine label="Remote Companion" value={remoteValue} />
            <InfoLine label="Mobile build" value={APP_VERSION} />
            {pairingNotice ? <Text style={[styles.feedbackMessage, styles.feedbackMessageOk]}>{pairingNotice}</Text> : null}

            <View style={styles.settingsInlineActions}>
              <Pressable
                style={styles.settingsCompactButton}
                onPress={() => setScannerVisible(true)}
                {...accessibleButton({
                  label: "Scan pairing QR code",
                  hint: "Opens the camera to scan the Local Flight pairing QR."
                })}
              >
                <LocalFlightIcon name={SETUP_ICONS.scan} size={14} color={palette.blue2} />
                <Text style={styles.settingsCompactButtonText}>SCAN QR</Text>
              </Pressable>
              <Pressable
                style={[styles.settingsCompactButton, schedulerRestarting && styles.connectButtonDisabled]}
                onPress={onRestartScheduler}
                disabled={schedulerRestarting}
                {...accessibleButton({
                  label: schedulerRestarting ? "Restarting fetch" : "Restart fetch",
                  disabled: schedulerRestarting,
                  busy: schedulerRestarting
                })}
              >
                {schedulerRestarting ? (
                  <ActivityIndicator size="small" color={palette.blue} />
                ) : (
                  <Text style={styles.settingsCompactButtonText}>RESTART FETCH</Text>
                )}
              </Pressable>
              {remoteReady ? (
                <Pressable
                  style={styles.settingsCompactButton}
                  onPress={runRemoteProbe}
                  disabled={remoteProbeTesting}
                  {...accessibleButton({
                    label: remoteProbeTesting ? "Testing Remote Companion" : "Test Remote Companion",
                    hint: "Sends one encrypted probe through the relay and retries once only for transient failures.",
                    disabled: remoteProbeTesting,
                    busy: remoteProbeTesting
                  })}
                >
                  {remoteProbeTesting ? (
                    <ActivityIndicator size="small" color={palette.blue} />
                  ) : (
                    <Text style={styles.settingsCompactButtonText}>TEST REMOTE</Text>
                  )}
                </Pressable>
              ) : null}
              {remoteReady ? (
                <Pressable
                  style={styles.settingsCompactButton}
                  onPress={onForgetRemoteCompanion}
                  {...accessibleButton({
                    label: "Forget Remote Companion fallback",
                    hint: "Removes this phone's stored remote grant. The host can still revoke the grant from Local Flight Settings."
                  })}
                >
                  <Text style={styles.settingsCompactButtonText}>FORGET REMOTE</Text>
                </Pressable>
              ) : null}
            </View>
            {remoteProbeResult ? (
              <Text
                style={[
                  styles.feedbackMessage,
                  remoteProbeResult.ok ? styles.feedbackMessageOk : styles.feedbackMessageError
                ]}
              >
                {remoteProbeMessage}
              </Text>
            ) : null}

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
            <Pressable
              style={styles.connectButton}
              onPress={onConnect}
              disabled={loading}
              {...accessibleButton({
                label: loading ? "Connecting" : "Connect to Local Flight server",
                disabled: loading,
                busy: loading
              })}
            >
              {loading ? <ActivityIndicator color={solidButtonInk()} /> : <Text style={styles.connectButtonText}>CONNECT</Text>}
            </Pressable>
            <Text style={styles.settingsHelp}>
              Use the LAN IP of the machine running Local Flight. Remote Companion keeps working away from Wi-Fi only after this phone pairs locally with a remote QR.
            </Text>
            {schedulerMessage ? <Text style={[styles.feedbackMessage, styles.feedbackMessageOk]}>{schedulerMessage}</Text> : null}
            {error ? <Text style={styles.errorText}>{error}</Text> : null}

            <PairingScannerSheet
              visible={scannerVisible}
              onClose={() => setScannerVisible(false)}
              onPairingUrl={(pairing) => {
                setScannerVisible(false);
                onPairingUrl(pairing);
              }}
            />
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

export function HelpScreen({
  snapshot,
  companionIdentity,
  connected,
  error,
  standalone = false,
  feedbackTitle,
  feedbackDescription,
  feedbackSending,
  feedbackMessage,
  feedbackTone,
  onFeedbackTitleChange,
  onFeedbackDescriptionChange,
  onSubmitFeedback,
  onBackControl
}: {
  snapshot: DashboardSnapshot;
  companionIdentity: CompanionIdentity | null;
  connected: boolean;
  error: string | null;
  standalone?: boolean;
  feedbackTitle: string;
  feedbackDescription: string;
  feedbackSending: boolean;
  feedbackMessage: string | null;
  feedbackTone: FeedbackTone;
  onFeedbackTitleChange: (value: string) => void;
  onFeedbackDescriptionChange: (value: string) => void;
  onSubmitFeedback: () => void;
  onBackControl?: () => void;
}) {
  const [helpPanel, setHelpPanel] = useState<"pairing" | "troubleshooting" | "report" | null>(null);
  const updateValue = snapshot.updates?.update_available
    ? `V${snapshot.updates.latest || "NEW"} READY`
    : `V${snapshot.updates?.current || snapshot.system?.version || APP_VERSION}`;
  const companionRecord =
    snapshot.connections?.companions?.find((item) => item.companion_id === companionIdentity?.companionId) || null;
  const tokenPrefix = snapshot.system?.client?.activation_token_prefix || "managed";
  const feedbackContext = standalone
    ? [
        `Reporter      ${companionIdentity?.clientName || "Local Flight Mobile"}`,
        `Mobile ID     ${companionIdentity?.companionId || "UNKNOWN"}`,
        `Mobile OS     ${companionIdentity?.mobileOs || "UNKNOWN"}`,
        `Build         ${companionIdentity?.appVersion || APP_VERSION}`,
        `Mode          Standalone relay`,
        `Token ref     ${tokenPrefix}`,
        `Airport       ${snapshot.config?.airport_iata || "---"}`,
        `Source        ${snapshot.state?.source_name || snapshot.config?.source || "UNKNOWN"}`
      ].join("\n")
    : [
        `Reporter      ${companionIdentity?.clientName || "Local Flight Mobile"}`,
        `Mobile ID     ${companionIdentity?.companionId || "UNKNOWN"}`,
        `Mobile OS     ${companionIdentity?.mobileOs || "UNKNOWN"}`,
        `Build         ${companionIdentity?.appVersion || APP_VERSION}`,
        `Server ID     ${snapshot.system?.install_id || "UNKNOWN"}`,
        `Server        ${snapshot.system?.platform || "UNKNOWN"}`,
        `Airport       ${snapshot.config?.airport_iata || "---"}`,
        `Source        ${snapshot.state?.source_name || snapshot.config?.source || "UNKNOWN"}`
      ].join("\n");

  return (
    <View style={styles.cardStack}>
      <View style={styles.settingsCard}>
        <View style={styles.helpHeaderRow}>
          <View style={styles.helpHeaderCopy}>
            <Text style={styles.settingsTitle}>HELP</Text>
          </View>
          {onBackControl ? (
            <Pressable
              style={styles.helpBackButton}
              onPress={onBackControl}
              {...accessibleButton({ label: "Back to Control" })}
            >
              <LocalFlightIcon name={ACTION_ICONS.back} size={14} color={palette.blue2} />
              <Text style={styles.helpBackText}>CONTROL</Text>
            </Pressable>
          ) : null}
        </View>
        <Text style={styles.moduleIntro}>
          {standalone
            ? "Standalone relay status, lightweight troubleshooting, and report flow for this mobile install."
            : "Pairing details, host identity, quick troubleshooting, and report flow for Mobile."}
        </Text>
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>HELP CENTER</Text>
        <SettingsToolPill
          icon={TOOL_ICONS.setup}
          label={standalone ? "Relay & app" : "Pairing & host"}
          value={standalone
            ? `${connected ? "Relay ready" : "Check"} · ${updateValue} · standalone`
            : `${connected ? "Connected" : "Check"} · ${updateValue} · ${snapshot.scheduler?.running ? "scheduler running" : "scheduler check"}`}
          onPress={() => setHelpPanel((value) => value === "pairing" ? null : "pairing")}
        />
        <SettingsToolPill
          icon={TOOL_ICONS.help}
          label="Troubleshooting"
          value={standalone ? "Relay access, stale board, and radar checks" : "Connection, stale board, and scheduler checks"}
          onPress={() => setHelpPanel((value) => value === "troubleshooting" ? null : "troubleshooting")}
        />
        <SettingsToolPill
          icon={TOOL_ICONS.report}
          label="Report problem"
          value={standalone ? "Send mobile context through the relay" : "Send mobile and host context through Local Flight"}
          onPress={() => setHelpPanel((value) => value === "report" ? null : "report")}
        />
      </View>

      {helpPanel === "pairing" ? (
        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>{standalone ? "RELAY & APP" : "PAIRING & HOST"}</Text>
          <View style={styles.metricRow}>
            <InfoCard label={standalone ? "RELAY" : "PAIRING"} value={connected ? (standalone ? "READY" : "CONNECTED") : "CHECK"} tone={connected ? "green" : "amber"} />
            <InfoCard label="VERSION" value={updateValue} />
            <InfoCard
              label={standalone ? "POLICY" : "SCHEDULER"}
              value={standalone ? "3H / 5M" : (snapshot.scheduler?.running ? "RUNNING" : "CHECK")}
              tone={standalone || snapshot.scheduler?.running ? "green" : "amber"}
            />
          </View>
          {standalone ? (
            <>
              <InfoLine label="Mode" value="Standalone relay client" />
              <InfoLine label="Token ref" value={tokenPrefix} />
            </>
          ) : (
            <>
              <InfoLine label="Host install" value={snapshot.system?.install_id || "Unknown host"} />
              <InfoLine label="Host platform" value={snapshot.system?.platform || "Unknown"} />
            </>
          )}
          <InfoLine label="Mobile app" value={companionIdentity?.appVersion || APP_VERSION} />
          <InfoLine label="Mobile ID" value={companionIdentity?.companionId || "Loading..."} />
          {standalone ? null : <InfoLine label="Check-in" value={companionRecord?.last_seen ? formatRelative(companionRecord.last_seen) : "Not seen yet"} />}
          <InfoLine label="Airport" value={snapshot.config?.airport_iata || "---"} />
          <InfoLine label="Source" value={snapshot.state?.source_name || snapshot.config?.source || "Unknown"} />
        </View>
      ) : null}

      {helpPanel === "troubleshooting" ? (
        <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>TROUBLESHOOTING</Text>
        <Text style={styles.moduleIntro}>
          {standalone
            ? "Standalone deliberately keeps the moving parts small: relay access, local history, slow FIDS refresh, and short-range radar."
            : "Start with the simple host-side checks first so the phone stays a quick mobile board instead of a maintenance console."}
        </Text>
        <InfoLine
          label={standalone ? "Relay check" : "Cannot connect"}
          value={standalone
            ? "If relay requests fail, check internet access first. Standalone does not need your desktop or Pi on the LAN."
            : "Confirm Local Flight is running on the same Wi-Fi and use the desktop or Pi LAN address, not phone localhost."}
        />
        <InfoLine
          label="Board looks stale"
          value={standalone
            ? "Standalone FIDS auto-refreshes no faster than every 3 hours to preserve shared provider tokens. Pull to refresh when you intentionally need a check."
            : "Use Restart Fetch from Control, then wait for the next snapshot push or open the board again."}
        />
        <InfoLine
          label={standalone ? "Radar limits" : "Scheduler warning"}
          value={standalone
            ? "Standalone radar refreshes at most every 5 minutes and only supports 1, 3, 5, and 10 NM ranges."
            : "If the scheduler is not running, reopen the host app first and then retry from Mobile."}
        />
        <InfoLine
          label="Display data"
          value="Flight, weather, and radar information are for personal display only. Do not use Local Flight for navigation, dispatch, operational control, or safety decisions."
        />
        <InfoLine label="Still stuck" value="Send a report below with what you expected, what happened, and the airport/source you were using." />
        </View>
      ) : null}

      {helpPanel === "report" ? (
        <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>REPORT PROBLEM</Text>
        <Text style={styles.moduleIntro}>
          {standalone
            ? "Sends directly through the hosted relay with mobile context attached. Manual reports are always available."
            : "Sends directly through the Local Flight feedback route with host and mobile context attached."}
        </Text>
        <TextInput
          value={feedbackTitle}
          onChangeText={onFeedbackTitleChange}
          placeholder="Short summary, for example Radar stopped updating"
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
        <Pressable
          style={[styles.connectButton, feedbackSending && styles.connectButtonDisabled]}
          onPress={onSubmitFeedback}
          disabled={feedbackSending}
          {...accessibleButton({
            label: feedbackSending ? "Sending report" : "Send report",
            disabled: feedbackSending,
            busy: feedbackSending
          })}
        >
          {feedbackSending ? <ActivityIndicator color={solidButtonInk()} /> : <Text style={styles.connectButtonText}>SEND REPORT</Text>}
        </Pressable>
        {feedbackMessage ? (
          <Text style={[styles.feedbackMessage, feedbackTone === "ok" ? styles.feedbackMessageOk : styles.feedbackMessageError]}>
            {feedbackMessage}
          </Text>
        ) : null}
        </View>
      ) : null}

      {error ? <Text style={styles.errorText}>{error}</Text> : null}
    </View>
  );
}

function DocsScreen({
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
  const externalUrl = document?.external_url || document?.github_url || source.externalUrl;
  const externalLabel = document?.external_label || source.externalLabel;
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
          icon={TOOL_ICONS.docs}
          title={title}
          detail={detail}
          onBack={onBackSettings}
        />

        <View style={styles.docsCard} onLayout={(event) => setDocCardY(event.nativeEvent.layout.y)}>
          {!loadingDoc && !docError && headings.length ? (
            <Pressable
              style={styles.docTocPill}
              onPress={() => setTocVisible(true)}
              {...accessibleButton({
                label: "Jump to document section",
                hint: `${headings.length} sections available.`
              })}
            >
              <LocalFlightIcon name={TOOL_ICONS.changelog} size={15} color={palette.blue2} />
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
            compact={Boolean(document?.content)}
          />
          {!loadingDoc && docError ? (
            <>
              <Text style={styles.sheetEmpty}>
                Could not load the bundled server document inside the app: {docError}
              </Text>
              <SettingsToolPill
                icon={ACTION_ICONS.openExternal}
                label={externalLabel}
                value="External website link opens only when you tap"
                onPress={() => void Linking.openURL(externalUrl)}
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
    <Modal visible={visible} transparent presentationStyle="overFullScreen" animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable
          style={styles.sheetBackdropPress}
          onPress={onClose}
          {...accessibleButton({ label: "Close document sections" })}
        />
        <View style={styles.docTocSheet}>
          <View style={styles.sheetHandle} />
          <View style={styles.docTocHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>DOCUMENT SECTIONS</Text>
              <Text style={styles.sheetTitle}>{title}</Text>
            </View>
            <Pressable
              style={styles.sheetAction}
              onPress={onClose}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: "Close document sections" })}
            >
              <Text style={styles.sheetActionText}>DONE</Text>
            </Pressable>
          </View>
          <ScrollView style={styles.sheetScroll} contentContainerStyle={styles.docTocContent}>
            {headings.map((heading) => (
              <Pressable
                key={heading.id}
                style={[styles.docTocItem, heading.level === 2 && styles.docTocItemNested]}
                onPress={() => onSelect(heading)}
                {...accessibleButton({
                  label: `Jump to ${heading.title}`,
                  hint: `Heading level ${heading.level}.`
                })}
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

function MatrixLiveSheet({
  visible,
  matrixRuntime,
  matrixDirty,
  matrixSaving,
  matrixSaveMessage,
  matrixSaveTone,
  onClose,
  onMatrixPresetChange,
  onMatrixViewChange,
  onMatrixWeatherToggle,
  onMatrixGateToggle,
  onMatrixPaletteChange,
  onMatrixBrightnessChange,
  onMatrixRowsChange,
  onMatrixRotationChange,
  onMatrixAnimationModeChange,
  onMatrixAnimationSpeedChange,
  onMatrixStatusAnimationToggle,
  onMatrixRefreshChange,
  onMatrixSave,
  onMatrixReset
}: {
  visible: boolean;
  matrixRuntime: MatrixRuntimeConfigSave;
  matrixDirty: boolean;
  matrixSaving: boolean;
  matrixSaveMessage: string | null;
  matrixSaveTone: FeedbackTone;
  onClose: () => void;
  onMatrixPresetChange: (value: MatrixPresetId) => void;
  onMatrixViewChange: (value: FlightView) => void;
  onMatrixWeatherToggle: (value: boolean) => void;
  onMatrixGateToggle: (value: boolean) => void;
  onMatrixPaletteChange: (value: MatrixPaletteId) => void;
  onMatrixBrightnessChange: (value: number) => void;
  onMatrixRowsChange: (value: number) => void;
  onMatrixRotationChange: (value: number) => void;
  onMatrixAnimationModeChange: (value: MatrixAnimationMode) => void;
  onMatrixAnimationSpeedChange: (value: number) => void;
  onMatrixStatusAnimationToggle: (value: boolean) => void;
  onMatrixRefreshChange: (value: number) => void;
  onMatrixSave: () => void;
  onMatrixReset: () => void;
}) {
  const matrixPaletteOption = MATRIX_PALETTE_OPTIONS.find((item) => item.id === matrixRuntime.palette) || MATRIX_PALETTE_OPTIONS[0]!;
  const matrixPresetOption = MATRIX_PRESETS.find((item) => item.id === matrixRuntime.preset) || MATRIX_PRESETS[0]!;
  const matrixShowWeather = Boolean(matrixRuntime.options.show_metar ?? matrixRuntime.options.show_weather);
  const matrixShowGates = Boolean(matrixRuntime.show_gate_info ?? matrixRuntime.options.show_gate_info);
  const matrixBrightnessPct = Math.round(matrixRuntime.brightness * 100);

  return (
    <Modal visible={visible} transparent presentationStyle="overFullScreen" animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable
          style={styles.sheetBackdropPress}
          onPress={onClose}
          {...accessibleButton({ label: "Close Matrix board controls" })}
        />
        <View style={[styles.sheetCard, styles.matrixLiveSheetCard]}>
          <View style={styles.sheetHandle} />
          <View style={[styles.sheetHeader, styles.matrixLiveSheetHeader]}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>MATRIX BOARD</Text>
              <Text style={[styles.sheetTitle, styles.matrixLiveSheetTitle]} numberOfLines={1}>Matrix Controls</Text>
            </View>
            <Pressable
              style={[styles.sheetAction, styles.matrixLiveSheetAction]}
              onPress={onClose}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: "Close Matrix board controls" })}
            >
              <Text style={styles.sheetActionText}>DONE</Text>
            </Pressable>
          </View>

          <ScrollView style={styles.sheetScroll} contentContainerStyle={[styles.sheetContent, styles.matrixLiveSheetContent]}>
            <View style={styles.matrixLiveStatusStrip}>
              <Text style={styles.matrixLiveStatusText} numberOfLines={1}>
                {matrixPresetOption.label} · {matrixPaletteOption.label}
              </Text>
              <Text
                style={[
                  styles.matrixLiveStatusText,
                  styles.matrixLiveStatusAccent,
                  matrixDirty && styles.matrixLiveStatusWarn
                ]}
                numberOfLines={1}
              >
                {matrixDirty ? "UNSAVED" : "SYNCED"}
              </Text>
            </View>

            <FilterSection title="DISPLAY PRESET">
              <View style={styles.matrixLivePresetRow}>
                {MATRIX_PRESETS.map((item) => (
                  <Pressable
                    key={item.id}
                    style={[styles.matrixLivePresetChip, matrixRuntime.preset === item.id && styles.matrixLivePresetChipActive]}
                    onPress={() => onMatrixPresetChange(item.id)}
                    hitSlop={tapTargetHitSlop}
                    {...accessibleButton({
                      label: `Use ${item.label} Matrix preset`,
                      hint: item.detail,
                      selected: matrixRuntime.preset === item.id
                    })}
                  >
                    <Text style={[styles.matrixLivePresetLabel, matrixRuntime.preset === item.id && styles.matrixPresetLabelActive]} numberOfLines={1}>
                      {item.label}
                    </Text>
                    <Text style={styles.matrixLivePresetMeta} numberOfLines={1}>{item.meta}</Text>
                  </Pressable>
                ))}
              </View>
            </FilterSection>

            <FilterSection title="BOARD OUTPUT">
              <View style={styles.filterRow}>
                <DirectionButton
                  active={matrixRuntime.default_view === "departures"}
                  label="DEPARTURES"
                  onPress={() => onMatrixViewChange("departures")}
                />
                <DirectionButton
                  active={matrixRuntime.default_view === "arrivals"}
                  label="ARRIVALS"
                  onPress={() => onMatrixViewChange("arrivals")}
                />
              </View>
              <View style={[styles.filterRow, styles.matrixLiveSubRow]}>
                <DirectionButton active={matrixShowWeather} label="WX ON" onPress={() => onMatrixWeatherToggle(true)} />
                <DirectionButton active={!matrixShowWeather} label="WX OFF" onPress={() => onMatrixWeatherToggle(false)} />
              </View>
              <View style={[styles.filterRow, styles.matrixLiveSubRow]}>
                <DirectionButton active={matrixShowGates} label="GATES ON" onPress={() => onMatrixGateToggle(true)} />
                <DirectionButton active={!matrixShowGates} label="GATES OFF" onPress={() => onMatrixGateToggle(false)} />
              </View>
            </FilterSection>

            <FilterSection title="COLOR LOOK">
              <View style={styles.matrixLivePaletteRow}>
                {MATRIX_PALETTE_OPTIONS.map((item) => (
                  <Pressable
                    key={item.id}
                    onPress={() => onMatrixPaletteChange(item.id)}
                    style={[styles.matrixLivePaletteChip, matrixRuntime.palette === item.id && styles.optionChipActive]}
                    hitSlop={tapTargetHitSlop}
                    {...accessibleButton({
                      label: `Use Matrix ${item.label} palette`,
                      hint: item.meta,
                      selected: matrixRuntime.palette === item.id
                    })}
                  >
                    <Text style={[styles.optionChipLabel, matrixRuntime.palette === item.id && styles.optionChipLabelActive]} numberOfLines={1}>
                      {item.label}
                    </Text>
                    <View style={styles.paletteDots}>
                      {[item.colors.green, item.colors.white, item.colors.cyan, item.colors.amber].map((color, index) => (
                        <View key={`${item.id}-${index}-${color}`} style={[styles.paletteDot, { backgroundColor: color }]} />
                      ))}
                    </View>
                  </Pressable>
                ))}
              </View>
            </FilterSection>

            <FilterSection title="DENSITY & TIMING">
              <View style={styles.filterWrap}>
                {MATRIX_ROWS.map((item) => (
                  <OptionChip
                    key={item}
                    active={matrixRuntime.max_rows === item}
                    label={`${item}`}
                    meta="rows"
                    onPress={() => onMatrixRowsChange(item)}
                  />
                ))}
              </View>
              <View style={styles.filterWrap}>
                {MATRIX_ROTATION_SECONDS.map((item) => (
                  <OptionChip
                    key={item}
                    active={matrixRuntime.page_rotation_seconds === item}
                    label={`${item}s`}
                    meta="cycle"
                    onPress={() => onMatrixRotationChange(item)}
                  />
                ))}
              </View>
            </FilterSection>

            <FilterSection title="MOTION & SPEED">
              <View style={styles.filterWrap}>
                {MATRIX_ANIMATION_MODES.map((item) => (
                  <OptionChip
                    key={item.id}
                    active={matrixRuntime.animation_mode === item.id}
                    label={item.label}
                    meta={item.meta}
                    onPress={() => onMatrixAnimationModeChange(item.id)}
                  />
                ))}
              </View>
              <View style={styles.filterWrap}>
                {MATRIX_ANIMATION_SPEEDS.map((item) => (
                  <OptionChip
                    key={item}
                    active={matrixRuntime.animation_speed === item}
                    label={`${item}`}
                    meta="speed"
                    onPress={() => onMatrixAnimationSpeedChange(item)}
                  />
                ))}
              </View>
              <View style={styles.filterRow}>
                <DirectionButton
                  active={matrixRuntime.status_animation_enabled}
                  label="STATUS MOTION"
                  onPress={() => onMatrixStatusAnimationToggle(true)}
                />
                <DirectionButton
                  active={!matrixRuntime.status_animation_enabled}
                  label="STATUS STATIC"
                  onPress={() => onMatrixStatusAnimationToggle(false)}
                />
              </View>
            </FilterSection>

            <FilterSection title="BRIGHTNESS & REFRESH">
              <View style={styles.filterWrap}>
                {MATRIX_BRIGHTNESS.map((item) => (
                  <OptionChip
                    key={item}
                    active={matrixRuntime.brightness === item}
                    label={`${Math.round(item * 100)}%`}
                    meta="LED"
                    onPress={() => onMatrixBrightnessChange(item)}
                  />
                ))}
              </View>
              <View style={styles.filterWrap}>
                {MATRIX_REFRESH_SECONDS.map((item) => (
                  <OptionChip
                    key={item}
                    active={matrixRuntime.refresh_seconds === item}
                    label={item >= 60 ? `${Math.round(item / 60)}m` : `${item}s`}
                    meta="server"
                    onPress={() => onMatrixRefreshChange(item)}
                  />
                ))}
              </View>
            </FilterSection>

            <View style={styles.matrixActionRow}>
              <Pressable
                style={[styles.matrixActionButton, styles.matrixActionSecondary, matrixSaving && styles.connectButtonDisabled]}
                onPress={onMatrixReset}
                disabled={matrixSaving}
                {...accessibleButton({
                  label: "Reset Matrix display settings",
                  disabled: matrixSaving
                })}
              >
                <Text style={styles.matrixActionSecondaryText}>RESET</Text>
              </Pressable>
              <Pressable
                style={[
                  styles.matrixActionButton,
                  styles.matrixActionPrimary,
                  (!matrixDirty || matrixSaving) && styles.connectButtonDisabled
                ]}
                onPress={onMatrixSave}
                disabled={!matrixDirty || matrixSaving}
                {...accessibleButton({
                  label: "Save Matrix display settings",
                  disabled: !matrixDirty || matrixSaving,
                  busy: matrixSaving
                })}
              >
                {matrixSaving ? (
                  <ActivityIndicator size="small" color={blueButtonInk()} />
                ) : (
                  <Text style={styles.matrixActionPrimaryText}>SAVE BOARD</Text>
                )}
              </Pressable>
            </View>
            {matrixSaveMessage ? (
              <Text style={[
                styles.feedbackMessage,
                matrixSaveTone === "ok" ? styles.feedbackMessageOk : styles.feedbackMessageError
              ]}>
                {matrixSaveMessage}
              </Text>
            ) : null}
          </ScrollView>
        </View>
      </View>
    </Modal>
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
    <Modal visible={visible} transparent presentationStyle="overFullScreen" animationType="slide" onRequestClose={onClose}>
      <View style={styles.sheetBackdrop}>
        <Pressable
          style={styles.sheetBackdropPress}
          onPress={onClose}
          {...accessibleButton({ label: "Close appearance settings" })}
        />
        <View style={styles.sheetCard}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <View style={styles.sheetHeaderText}>
              <Text style={styles.sheetEyebrow}>MOBILE LOOK</Text>
              <Text style={styles.sheetTitle}>Mobile Appearance</Text>
            </View>
            <Pressable
              style={styles.sheetAction}
              onPress={onClose}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: "Close appearance settings" })}
            >
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

function SettingsQuickAction({
  icon,
  label,
  value,
  onPress
}: {
  icon: AppIconName;
  label: string;
  value: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      style={styles.settingsQuickAction}
      onPress={onPress}
      {...accessibleButton({
        label,
        hint: value
      })}
    >
      <View style={styles.settingsQuickIcon}>
        <LocalFlightIcon name={icon} size={18} color={palette.blue2} />
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
  icon: AppIconName;
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
      {...accessibleButton({
        label,
        hint: value,
        disabled,
        busy: loading
      })}
    >
      <View style={styles.settingsPillIcon}>
        <LocalFlightIcon name={icon} size={18} color={palette.blue2} />
      </View>
      <View style={styles.settingsPillCopy}>
        <Text style={styles.settingsPillLabel}>{label}</Text>
        <Text style={styles.settingsPillValue}>{value}</Text>
      </View>
      {loading ? (
        <ActivityIndicator color={palette.blue} />
      ) : (
        <LocalFlightIcon name={ACTION_ICONS.drillIn} size={18} color={palette.textDim} />
      )}
    </Pressable>
  );
}

export function ConnectPrompt({ onSettings }: { onSettings: () => void }) {
  return (
    <Pressable
      style={styles.connectPrompt}
      onPress={onSettings}
      {...accessibleButton({
        label: "Connect Local Flight",
        hint: "Opens the server URL settings before live rows can load."
      })}
    >
      <Text style={styles.connectPromptTitle}>Connect Local Flight</Text>
      <Text style={styles.connectPromptBody}>Tap here to set the server URL before live rows can load.</Text>
    </Pressable>
  );
}

function StandaloneEmptyState({ title, body }: { title: string; body: string }) {
  return (
    <View style={styles.connectPrompt}>
      <Text style={styles.connectPromptTitle}>{title}</Text>
      <Text style={styles.connectPromptBody}>{body}</Text>
    </View>
  );
}

function HiddenToolHeader({
  icon,
  title,
  detail,
  onBack
}: {
  icon: AppIconName;
  title: string;
  detail: string;
  onBack: () => void;
}) {
  return (
    <View style={styles.hiddenToolHeader}>
      <View style={styles.hiddenToolTitleRow}>
        <View style={styles.hiddenToolIcon}>
          <LocalFlightIcon name={icon} size={18} color={palette.blue} />
        </View>
        <View style={styles.hiddenToolCopy}>
          <Text style={styles.hiddenToolTitle}>{title}</Text>
          <Text style={styles.hiddenToolDetail}>{detail}</Text>
        </View>
      </View>
      <Pressable
        style={styles.hiddenToolBack}
        onPress={onBack}
        hitSlop={tapTargetHitSlop}
        {...accessibleButton({
          label: "Back to settings",
          hint: `Leaves ${title}.`
        })}
      >
        <LocalFlightIcon name={ACTION_ICONS.back} size={18} color={palette.blue2} />
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
        <Pressable
          style={styles.errorRetryButton}
          onPress={onRetry}
          disabled={retrying}
          {...accessibleButton({
            label: retrying ? "Retrying" : "Retry",
            hint: message,
            disabled: retrying,
            busy: retrying
          })}
        >
          {retrying ? (
            <ActivityIndicator size="small" color={palette.amber} />
          ) : (
            <LocalFlightIcon name={ACTION_ICONS.retry} size={12} color={palette.red} />
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
      <Text style={styles.infoLabel} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7}>{label}</Text>
      <Text
        style={[styles.infoValue, { color: palette[tone] }]}
        numberOfLines={1}
        adjustsFontSizeToFit
        minimumFontScale={0.52}
        ellipsizeMode="tail"
      >
        {value}
      </Text>
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

export function StandaloneAirportSheet({
  visible,
  currentAirport,
  onClose,
  onApplied
}: {
  visible: boolean;
  currentAirport: StandaloneAirport | null;
  onClose: () => void;
  onApplied: (airport: StandaloneAirport) => Promise<void> | void;
}) {
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<AirportResult[]>([]);
  const [selectedAirport, setSelectedAirport] = useState<AirportResult | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!visible) return;
    setQuery("");
    setSearchResults([]);
    setSelectedAirport(null);
    setApplyError(null);
  }, [visible]);

  const doSearch = useCallback((text: string) => {
    if (text.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    void searchStandaloneAirports(text, 8)
      .then(setSearchResults)
      .catch(() => setSearchResults([]));
  }, []);

  const onQueryChange = useCallback((text: string) => {
    setQuery(text);
    setSelectedAirport(null);
    setApplyError(null);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => doSearch(text), 300);
  }, [doSearch]);

  const selectAirport = useCallback((airport: AirportResult) => {
    Keyboard.dismiss();
    setSelectedAirport(airport);
    setQuery(`${airport.iata || airport.icao} - ${airport.name}`);
    setSearchResults([]);
    setApplyError(null);
  }, []);

  const apply = useCallback(async () => {
    const lookup = selectedAirport?.iata || selectedAirport?.icao || query.trim();
    if (!lookup) {
      setApplyError("Search and select an airport first.");
      return;
    }
    Keyboard.dismiss();
    setApplying(true);
    setApplyError(null);
    try {
      const resolved = await resolveStandaloneAirport(lookup);
      await onApplied({
        iata: resolved.iata,
        icao: resolved.icao,
        name: resolved.name,
        city: resolved.city,
        country: resolved.country,
        timezone: resolved.timezone,
        lat: resolved.lat,
        lon: resolved.lon
      });
    } catch (exc) {
      setApplyError(companionSetupErrorMessage(exc));
    } finally {
      setApplying(false);
    }
  }, [onApplied, query, selectedAirport]);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      presentationStyle="overFullScreen"
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
              <Text style={styles.configSheetTitle}>CHANGE STANDALONE AIRPORT</Text>
              <Pressable
                onPress={() => {
                  Keyboard.dismiss();
                  onClose();
                }}
                style={styles.configSheetClose}
                hitSlop={tapTargetHitSlop}
                {...accessibleButton({ label: "Close standalone airport change" })}
              >
                <LocalFlightIcon name={ACTION_ICONS.close} size={20} color={palette.textMuted} />
              </Pressable>
            </View>

            <ScrollView
              style={styles.configSheetScroll}
              contentContainerStyle={styles.configSheetScrollContent}
              keyboardShouldPersistTaps="handled"
              keyboardDismissMode="interactive"
            >
              <Text style={styles.moduleIntro}>
                Change the airport without resetting this phone. Relay token, diagnostics, appearance, and install identity stay untouched.
              </Text>
              {currentAirport ? (
                <View style={styles.configSelectedAirport}>
                  <LocalFlightIcon name={ACTION_ICONS.configured} size={14} color={palette.green} />
                  <Text style={styles.configSelectedText}>
                    Current: {currentAirport.iata || currentAirport.icao}
                    {currentAirport.name ? ` - ${currentAirport.name}` : ""}
                  </Text>
                </View>
              ) : null}

              <Text style={styles.configSectionLabel}>AIRPORT</Text>
              <TextInput
                style={styles.configSearchInput}
                placeholder="Search by airport code, city, or name"
                placeholderTextColor={palette.textDim}
                value={query}
                onChangeText={onQueryChange}
                autoCapitalize="characters"
                returnKeyType="search"
                onSubmitEditing={() => {
                  const first = searchResults[0];
                  if (first) selectAirport(first);
                }}
              />

              {searchResults.length > 0 ? (
                <View style={styles.configSearchResults}>
                  {searchResults.map((airport, index) => {
                    const active = selectedAirport?.iata === airport.iata && selectedAirport?.icao === airport.icao;
                    return (
                      <Pressable
                        key={airportResultKey(airport, index)}
                        style={[styles.configSearchRow, active && styles.configSearchRowSelected]}
                        onPress={() => selectAirport(airport)}
                        {...accessibleButton({
                          label: `Select ${airport.iata || airport.icao}, ${airport.name}`,
                          hint: [airport.city, airport.country, airport.timezone].filter(Boolean).join(", "),
                          selected: active
                        })}
                      >
                        <Text style={styles.configSearchIata}>{airport.iata || airport.icao}</Text>
                        <View style={styles.configSearchInfo}>
                          <Text style={styles.configSearchName} numberOfLines={1}>{airport.name}</Text>
                          <Text style={styles.configSearchMeta}>{[airport.city, airport.country, airport.timezone].filter(Boolean).join(" · ")}</Text>
                        </View>
                      </Pressable>
                    );
                  })}
                </View>
              ) : null}

              {selectedAirport ? (
                <View style={styles.configSelectedAirport}>
                  <LocalFlightIcon name={ACTION_ICONS.configured} size={14} color={palette.green} />
                  <Text style={styles.configSelectedText}>
                    New: {selectedAirport.iata || selectedAirport.icao}
                    {selectedAirport.name ? ` - ${selectedAirport.name}` : ""}
                  </Text>
                </View>
              ) : null}

              <Pressable
                style={[styles.connectButton, applying && styles.connectButtonDisabled]}
                onPress={() => void apply()}
                disabled={applying}
                {...accessibleButton({
                  label: applying ? "Saving standalone airport" : "Save standalone airport",
                  disabled: applying,
                  busy: applying
                })}
              >
                {applying ? <ActivityIndicator color={solidButtonInk()} /> : <Text style={styles.connectButtonText}>SAVE AIRPORT</Text>}
              </Pressable>
              {applyError ? <Text style={styles.errorText}>{applyError}</Text> : null}
            </ScrollView>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
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
      presentationStyle="overFullScreen"
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
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: "Close server configuration" })}
            >
              <LocalFlightIcon name={ACTION_ICONS.close} size={20} color={palette.textMuted} />
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
                    {...accessibleButton({
                      label: `Select ${r.iata || r.icao}, ${r.name}`,
                      hint: [r.city, r.country].filter(Boolean).join(", "),
                      selected: selectedAirport?.iata === r.iata
                    })}
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
                <LocalFlightIcon name={ACTION_ICONS.configured} size={14} color={palette.green} />
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
                  {...accessibleButton({
                    label: opt === "real" ? "Use real flight data" : "Use virtual VATSIM data",
                    selected: source === opt
                  })}
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
                  {...accessibleButton({
                    label: `Refresh every ${opt.label}`,
                    selected: refreshSecs === opt.seconds
                  })}
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
                        {...accessibleButton({
                          label: `Load profile ${p.name}`,
                          hint: `${p.iata}, ${p.source === "virtual" ? "VATSIM" : "real"}, ${formatInterval(p.refresh_seconds)}`,
                          disabled: applyingProfileId !== null,
                          busy: isApplyingThis
                        })}
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
                            {...accessibleButton({
                              label: `Delete profile ${p.name}`,
                              disabled: applyingProfileId !== null
                            })}
                          >
                            <LocalFlightIcon name={ACTION_ICONS.delete} size={16} color={palette.textDim} />
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
                {...accessibleButton({
                  label: "Save airport profile",
                  disabled: !profileName.trim() || !selectedAirport
                })}
              >
                <Text style={styles.configSaveBtnText}>SAVE</Text>
              </Pressable>
            </View>

            {applyError ? <Text style={styles.configErrorText}>{applyError}</Text> : null}
            <Pressable
              style={[styles.configApplyBtn, applying && styles.configApplyBtnBusy]}
              onPress={() => void apply()}
              disabled={applying}
              {...accessibleButton({
                label: applying ? "Applying server configuration" : "Apply server configuration",
                disabled: applying,
                busy: applying
              })}
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
