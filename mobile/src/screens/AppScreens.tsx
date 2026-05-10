import { useCallback, useEffect, useRef, useState, type ComponentProps, type ReactNode } from "react";
import {
  ActivityIndicator,
  Animated,
  FlatList,
  Linking,
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View
} from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import Svg, { Circle, ClipPath, Defs, G, Polygon, Polyline, Text as SvgText } from "react-native-svg";

import { getDoc, normalizeServerUrl, patchConfig, searchAirports, testCompanionSetupServer } from "../api/client";
import type {
  AppConfig,
  AppState,
  AirportResult,
  ConfigPatch,
  DashboardSnapshot,
  DocDocument,
  FidsRow,
  FlightDetail,
  FlightView,
  HistoryDirection,
  HistoryFlightRow,
  HistoryResponse,
  MatrixAnimationMode,
  MatrixPaletteId,
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
import type { FeedbackTone, HistoryWindow, ProjectedBlip, RadarRadius, StatusTone } from "../domain/types";
import { type ConfigProfile, type MobileDiagnosticsMode, saveProfiles } from "../storage/settings";
import { palette, styles } from "../theme/styleBridge";
import {
  MOBILE_SKIN_OPTIONS,
  MOBILE_THEME_OPTIONS,
  type MobileSkin,
  type MobileThemeMode
} from "../theme/tokens";

type MaterialIconName = ComponentProps<typeof MaterialCommunityIcons>["name"];
export type DocSlug = "readme" | "privacy" | "changelog";

const DOC_SOURCES: Record<DocSlug, { title: string; detail: string; githubUrl: string }> = {
  readme: {
    title: "README",
    detail: "Project overview, install notes, and operating model",
    githubUrl: "https://github.com/tr3y4rch/local-flight#readme"
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
const RADAR_GROUND_CLIP_ID = "mobile-radar-ground-clip";

type AdminSettingsSection = "health" | "devices" | "reports" | "developer";
type MatrixSettingsSection = "status" | "look" | "runtime" | "motion";
type CompanionSetupStep = "welcome" | "server" | "diagnostics" | "ready";
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

function metarAccentColor(category: string): string {
  switch (category.toUpperCase()) {
    case "VFR":  return palette.green;
    case "MVFR": return palette.blue;
    case "IFR":  return palette.amber;
    case "LIFR": return palette.red;
    default:     return palette.blue;
  }
}

export function Header({
  airportCode,
  airportIcao,
  airportName,
  live,
  sourceLabel,
  utcTime,
  localTime,
  metarCategory,
  metarText,
  rowCount,
  view,
  pinnedRow,
  islandPinned,
  onOpenDetail,
  onOpenActions,
  onTogglePin,
  onOpenConfig,
}: {
  airportCode: string;
  airportIcao: string;
  airportName: string;
  live: boolean;
  sourceLabel: string;
  utcTime: string;
  localTime: string;
  metarCategory: string;
  metarText: string;
  rowCount: number;
  view: FlightView;
  pinnedRow: FidsRow | null;
  islandPinned: boolean;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
  onTogglePin: (row: FidsRow) => void;
  onOpenConfig: () => void;
}) {
  const accent = metarAccentColor(metarCategory);
  const dotOpacity = useRef(new Animated.Value(1)).current;
  const chips = parseMetarChips(metarText);

  useEffect(() => {
    if (!live) { dotOpacity.setValue(1); return; }
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(dotOpacity, { toValue: 0.2, duration: 850, useNativeDriver: true }),
        Animated.timing(dotOpacity, { toValue: 1, duration: 850, useNativeDriver: true })
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [dotOpacity, live]);

  return (
    <View style={styles.header}>
      {/* Left accent bar — color-coded to METAR category */}
      <View style={[styles.headerAccentBar, { backgroundColor: accent }]} />

      {/* Identity band — tap to configure */}
      <Pressable style={styles.identityBand} onPress={onOpenConfig}>
        <View style={styles.identityLeft}>
          <Text style={[styles.airportCode, {
            color: accent,
            textShadowColor: accent,
            textShadowOffset: { width: 0, height: 0 },
            textShadowRadius: 10
          }]}>
            {airportCode}
          </Text>
          <Text style={styles.airportName} numberOfLines={1}>
            {airportName}
            {airportIcao ? <Text style={styles.airportIcao}> · {airportIcao}</Text> : null}
          </Text>
          <View style={styles.configHint}>
            <MaterialCommunityIcons name="tune-variant" size={10} color={palette.textDim} />
            <Text style={styles.configHintText}>tap to configure</Text>
          </View>
        </View>
        <View style={styles.identityRight}>
          <Text style={styles.utcTime}>{utcTime}<Text style={styles.utcSuffix}>Z</Text></Text>
          <Text style={styles.localTime}>{localTime} <Text style={styles.localSuffix}>LOC</Text></Text>
          <View style={[styles.metarCatBadge, { borderColor: `${accent}55`, backgroundColor: `${accent}22` }]}>
            <Text style={[styles.metarCatBadgeText, { color: accent }]}>{metarCategory || "--"}</Text>
          </View>
        </View>
      </Pressable>

      {/* Telemetry strip */}
      <View style={styles.telemetryStrip}>
        <View style={[styles.livePill, !live && styles.livePillOff]}>
          <Animated.View style={[styles.liveDot, !live && styles.liveDotOff, { opacity: dotOpacity }]} />
          <Text style={[styles.liveText, !live && styles.liveTextOff]}>{live ? "LIVE" : "OFF"}</Text>
        </View>
        <View style={styles.sourcePill}>
          <Text style={styles.sourceText}>{sourceLabel.toUpperCase()}</Text>
        </View>
        <View style={styles.countPill}>
          <Text style={styles.countText}>
            {view === "departures" ? "↑" : "↓"}{rowCount}
          </Text>
        </View>
      </View>

      {/* Flight Island */}
      <FlightIsland
        row={pinnedRow}
        isPinned={islandPinned}
        live={live}
        utcTime={utcTime}
        onOpenDetail={onOpenDetail}
        onOpenActions={onOpenActions}
        onTogglePin={onTogglePin}
      />

      {/* METAR strip — decoded chips when parseable, raw text fallback */}
      <View style={styles.metarStrip}>
        {chips.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.metarChipRow}
          >
            {chips.map((chip, i) => (
              <View key={`metar-${keyedPart(chip.label)}-${keyedPart(chip.value)}-${i}`} style={styles.metarChip}>
                <Text style={styles.metarChipLabel}>{chip.label}</Text>
                <Text style={styles.metarChipValue}>{chip.value}</Text>
              </View>
            ))}
          </ScrollView>
        ) : (
          <Text style={styles.metarText} numberOfLines={1}>{metarText}</Text>
        )}
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
  pinnedCallsign: string;
}) {
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

  return (
    <View style={styles.fullscreenFidsShell}>
      <View style={styles.fullscreenFidsTop}>
        <View style={styles.fullscreenFidsIdentity}>
          <Text style={styles.fullscreenFidsKicker}>{airportCode} LOCAL FLIGHT</Text>
          <Text style={styles.fullscreenFidsTitle}>{boardTitle}</Text>
          <Text style={styles.fullscreenFidsAirport} numberOfLines={1}>{airportName}</Text>
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

      <View style={styles.fullscreenFidsColumns}>
        <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsTimeColumn]}>TIME</Text>
        <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsFlightColumn]}>FLIGHT</Text>
        <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsRouteColumn]}>{routeHeading}</Text>
        <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsStatusColumn]}>STATUS</Text>
        <Text style={[styles.fullscreenFidsColumnText, styles.fullscreenFidsAircraftColumn]}>A/C</Text>
      </View>

      <FlatList<FidsRow>
        data={displayRows}
        keyExtractor={fidsRowKey}
        renderItem={({ item }) => (
          <FullscreenFidsRow row={item} isPinned={flightPinKey(item) === pinnedCallsign} />
        )}
        style={styles.fullscreenFidsList}
        contentContainerStyle={styles.fullscreenFidsListContent}
        ListEmptyComponent={
          <View style={styles.fullscreenFidsEmpty}>
            <Text style={styles.fullscreenFidsEmptyTitle}>{emptyTitle}</Text>
            <Text style={styles.fullscreenFidsEmptyDetail}>{emptyDetail}</Text>
          </View>
        }
        showsVerticalScrollIndicator={false}
      />
    </View>
  );
}

export function FidsScreen({
  rows,
  view,
  loading,
  refreshing,
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
  const pinned = pinnedCallsign
    ? rows.find((row) => flightPinKey(row) === pinnedCallsign) || null
    : null;
  const displayRows = pinned
    ? [pinned, ...rows.filter((row) => flightPinKey(row) !== pinnedCallsign)]
    : rows;

  return (
    <FlatList<FidsRow>
      data={displayRows}
      keyExtractor={fidsRowKey}
      renderItem={({ item }) => (
        <View style={styles.fidsListItem}>
          <FidsRowView
            row={item}
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
          {error ? <ScreenError message={error} /> : null}

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
            <Text style={styles.fidsHeaderText}>TIME</Text>
            <Text style={styles.fidsHeaderText}>FLIGHT</Text>
            <Text style={styles.fidsHeaderText}>{view === "arrivals" ? "FROM" : "TO"}</Text>
            <Text style={styles.fidsHeaderText}>STATUS</Text>
            <Text style={[styles.fidsHeaderText, styles.alignRight]}>A/C</Text>
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

export function HistoryScreen({
  data,
  direction,
  hours,
  loading,
  refreshing,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefresh,
  onDirectionChange,
  onHoursChange,
  onOpenDetail,
  contentPaddingBottom
}: {
  data: HistoryResponse | null;
  direction: HistoryDirection;
  hours: HistoryWindow;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefresh: () => void;
  onDirectionChange: (value: HistoryDirection) => void;
  onHoursChange: (value: HistoryWindow) => void;
  onOpenDetail: (callsign: string) => void;
  contentPaddingBottom: number;
}) {
  const flights = data?.flights || [];

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
          {error ? <ScreenError message={error} /> : null}

          <FilterSection title="DIRECTION">
            <View style={styles.filterRow}>
              <DirectionButton active={direction === "both"} label="ALL" onPress={() => onDirectionChange("both")} />
              <DirectionButton active={direction === "dep"} label="DEPARTURES" onPress={() => onDirectionChange("dep")} />
              <DirectionButton active={direction === "arr"} label="ARRIVALS" onPress={() => onDirectionChange("arr")} />
            </View>
          </FilterSection>

          <FilterSection title="WINDOW">
            <View style={styles.filterRow}>
              {HISTORY_WINDOWS.map((item) => (
                <DirectionButton
                  key={item}
                  active={hours === item}
                  label={item === 168 ? "7 DAYS" : `${item} HOURS`}
                  onPress={() => onHoursChange(item)}
                />
              ))}
            </View>
          </FilterSection>

          <View style={styles.metricRow}>
            <InfoCard label="ROWS" value={data ? String(data.count) : "..."} />
            <InfoCard label="FILTER" value={direction.toUpperCase()} tone="green" />
            <InfoCard label="WINDOW" value={hours === 168 ? "7 DAYS" : `${hours}H`} tone="amber" />
          </View>
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

export function RadarScreen({
  data,
  groundData,
  groundError,
  radiusNm,
  loading,
  refreshing,
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
  radiusNm: RadarRadius;
  loading: boolean;
  refreshing: boolean;
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
          {error ? <ScreenError message={error} /> : null}

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
  matrixEnabled,
  matrixLastSeen,
  dirty,
  saving,
  saveMessage,
  saveTone,
  refreshing,
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
  matrixEnabled: boolean;
  matrixLastSeen: string | null;
  dirty: boolean;
  saving: boolean;
  saveMessage: string | null;
  saveTone: FeedbackTone;
  refreshing: boolean;
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
      {error ? <ScreenError message={error} /> : null}

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
          {saving ? <ActivityIndicator size="small" color={palette.bg} /> : <Text style={styles.matrixActionPrimaryText}>SAVE TO SERVER</Text>}
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
  isPinned,
  onOpenDetail,
  onOpenActions
}: {
  row: FidsRow;
  isPinned: boolean;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
}) {
  return (
    <Pressable
      style={[styles.fidsRow, isPinned && styles.fidsRowPinned]}
      delayLongPress={360}
      onLongPress={() => onOpenActions(row)}
      onPress={() => onOpenDetail(row.callsign)}
    >
      <Text style={styles.fidsTime}>{row.display_time || "--:--"}</Text>
      <View style={styles.fidsFlightWrap}>
        <Text style={styles.fidsFlight} numberOfLines={1}>{row.flight_display || row.callsign || "-"}</Text>
        {isPinned ? <MaterialCommunityIcons name="pin" size={11} color={palette.amber} /> : null}
      </View>
      <View style={styles.fidsDest}>
        <Text style={styles.fidsDestName} numberOfLines={1}>{routeName(row.route_display)}</Text>
        <Text style={styles.fidsDestCode}>{routeMeta(row)}</Text>
      </View>
      <StatusBadge status={row.status_display} statusClass={row.status_class} compact />
      <Text style={styles.fidsAircraft} numberOfLines={1}>{row.aircraft_type || "-"}</Text>
    </Pressable>
  );
}

function FullscreenFidsRow({ row, isPinned }: { row: FidsRow; isPinned: boolean }) {
  return (
    <View style={[styles.fullscreenFidsRow, isPinned && styles.fullscreenFidsRowPinned]}>
      <Text style={[styles.fullscreenFidsTime, styles.fullscreenFidsTimeColumn]}>{row.display_time || "--:--"}</Text>
      <View style={[styles.fullscreenFidsFlightCell, styles.fullscreenFidsFlightColumn]}>
        <Text style={styles.fullscreenFidsFlight} numberOfLines={1}>{row.flight_display || row.callsign || "-"}</Text>
        <Text style={styles.fullscreenFidsAirline} numberOfLines={1}>
          {row.airline_display || row.codeshare_display || row.callsign || "LOCAL FLIGHT"}
        </Text>
      </View>
      <View style={[styles.fullscreenFidsRouteCell, styles.fullscreenFidsRouteColumn]}>
        <Text style={styles.fullscreenFidsRouteName} numberOfLines={1}>{routeName(row.route_display)}</Text>
        <Text style={styles.fullscreenFidsRouteMeta} numberOfLines={1}>{routeMeta(row)}</Text>
      </View>
      <View style={styles.fullscreenFidsStatusCell}>
        <StatusBadge status={row.status_display} statusClass={row.status_class} />
      </View>
      <Text style={[styles.fullscreenFidsAircraft, styles.fullscreenFidsAircraftColumn]} numberOfLines={1}>
        {row.aircraft_type || "-"}
      </Text>
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
            {loading ? <ActivityIndicator color={palette.blue} style={styles.loader} /> : null}

            {!loading && detail ? (
              <>
                <View style={styles.sheetSummary}>
                  <StatusBadge status={detail.status || "Tracked"} statusClass={detail.status || ""} />
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
  companionIdentity,
  connected,
  error,
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
  companionIdentity: CompanionIdentity | null;
  connected: boolean;
  error: string | null;
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
          {feedbackSending ? <ActivityIndicator color="#000" /> : <Text style={styles.connectButtonText}>SEND REPORT</Text>}
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
  const [serverSummary, setServerSummary] = useState<CompanionSetupResult | null>(null);

  useEffect(() => {
    setServerInput(initialUrl);
  }, [initialUrl]);

  useEffect(() => {
    if (initialDiagnosticsMode !== "unset") {
      setDiagnosticsMode(initialDiagnosticsMode);
    }
  }, [initialDiagnosticsMode]);

  const testServer = useCallback(async () => {
    const urlProblem = companionSetupUrlProblem(serverInput);
    if (urlProblem) {
      setSetupError(urlProblem);
      return;
    }

    setTesting(true);
    setSetupError(null);
    try {
      const result = await testCompanionSetupServer(serverInput);
      const summary = {
        serverUrl: result.normalizedUrl,
        diagnosticsMode,
        config: result.config,
        state: result.state
      };
      setServerInput(result.normalizedUrl);
      setServerSummary(summary);
      setStep("diagnostics");
    } catch (exc) {
      setSetupError(companionSetupErrorMessage(exc));
    } finally {
      setTesting(false);
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

  return (
    <ScrollView style={styles.companionSetupScroll} contentContainerStyle={styles.companionSetupContent}>
      <View style={styles.companionSetupCard}>
        <Text style={styles.companionSetupEyebrow}>LOCAL FLIGHT COMPANION</Text>
        <Text style={styles.companionSetupTitle}>First launch setup</Text>
        <Text style={styles.companionSetupBody}>
          Pair this iPhone with a configured Local Flight server before the companion opens FIDS, Radar, History, or Settings.
        </Text>

        <View style={styles.companionSetupSteps}>
          {(["welcome", "server", "diagnostics", "ready"] as CompanionSetupStep[]).map((item) => (
            <View
              key={item}
              style={[
                styles.companionSetupStepDot,
                setupStepRank(item) <= setupStepRank(step) && styles.companionSetupStepDotActive
              ]}
            />
          ))}
        </View>

        {step === "welcome" ? (
          <View style={styles.companionSetupPanel}>
            <Text style={styles.companionSetupPanelTitle}>Local-first LAN companion</Text>
            <Text style={styles.companionSetupBody}>
              The mobile app talks to your desktop or Pi server. It does not call the relay directly, and it will stay locked here until pairing and diagnostics consent are complete.
            </Text>
            <View style={styles.companionSetupInfoGrid}>
              <SetupInfoTile label="Mode" value="LAN companion" />
              <SetupInfoTile label="Privacy" value="Server mediated" />
              <SetupInfoTile label="Needed" value="Configured desktop/Pi" />
              <SetupInfoTile label="Next" value="Test server URL" />
            </View>
            <Pressable style={styles.companionSetupPrimary} onPress={() => setStep("server")}>
              <Text style={styles.companionSetupPrimaryText}>START SETUP</Text>
            </Pressable>
          </View>
        ) : null}

        {step === "server" ? (
          <View style={styles.companionSetupPanel}>
            <Text style={styles.companionSetupPanelTitle}>Connect your Local Flight server</Text>
            <Text style={styles.companionSetupBody}>
              Use the LAN address shown by the desktop/Pi app, for example http://localflight.local:8000 or http://192.168.1.42:8000.
            </Text>
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
            <Pressable
              style={[styles.companionSetupPrimary, testing && styles.connectButtonDisabled]}
              onPress={() => void testServer()}
              disabled={testing}
            >
              {testing ? <ActivityIndicator color="#000" /> : <Text style={styles.companionSetupPrimaryText}>TEST SERVER</Text>}
            </Pressable>
            <Pressable style={styles.companionSetupSecondary} onPress={() => setStep("welcome")}>
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </View>
        ) : null}

        {step === "diagnostics" ? (
          <View style={styles.companionSetupPanel}>
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
                  <Text style={styles.companionSetupOptionTitle}>{title}</Text>
                  <Text style={styles.companionSetupOptionBody}>{body}</Text>
                </Pressable>
              ))}
            </View>
            <Pressable style={styles.companionSetupPrimary} onPress={() => setStep("ready")}>
              <Text style={styles.companionSetupPrimaryText}>REVIEW SETUP</Text>
            </Pressable>
            <Pressable style={styles.companionSetupSecondary} onPress={() => setStep("server")}>
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </View>
        ) : null}

        {step === "ready" ? (
          <View style={styles.companionSetupPanel}>
            <Text style={styles.companionSetupPanelTitle}>Ready for the board</Text>
            <Text style={styles.companionSetupBody}>
              The companion will save this pairing locally and open the main app.
            </Text>
            <View style={styles.companionSetupSummary}>
              <InfoLine label="Server" value={serverSummary?.serverUrl || normalizeServerUrl(serverInput) || "Not tested"} />
              <InfoLine label="Airport" value={serverSummary?.config.airport_iata || "---"} />
              <InfoLine label="Diagnostics" value={diagnosticsMode === "manual" ? "Manual reports only" : diagnosticsMode === "auto" ? "Automatic crash reports" : "Automatic crash reports + context"} />
            </View>
            <Pressable
              style={[styles.companionSetupPrimary, finishing && styles.connectButtonDisabled]}
              onPress={() => void finishSetup()}
              disabled={finishing}
            >
              {finishing ? <ActivityIndicator color="#000" /> : <Text style={styles.companionSetupPrimaryText}>FINISH SETUP</Text>}
            </Pressable>
            <Pressable style={styles.companionSetupSecondary} onPress={() => setStep("diagnostics")}>
              <Text style={styles.companionSetupSecondaryText}>BACK</Text>
            </Pressable>
          </View>
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

function SetupInfoTile({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.companionSetupInfoTile}>
      <Text style={styles.companionSetupInfoLabel}>{label}</Text>
      <Text style={styles.companionSetupInfoValue}>{value}</Text>
    </View>
  );
}

function setupStepRank(step: CompanionSetupStep): number {
  return { welcome: 0, server: 1, diagnostics: 2, ready: 3 }[step];
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
  mobileDiagnosticsMode,
  outputs,
  refreshSeconds,
  schedulerRestarting,
  schedulerMessage,
  onThemeModeChange,
  onSkinChange,
  onMobileDiagnosticsModeChange,
  onOpenHistory,
  onOpenAdmin,
  onOpenMatrix,
  onOpenDoc,
  onOpenCoffee,
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
  mobileDiagnosticsMode: MobileDiagnosticsMode;
  outputs: string[];
  refreshSeconds: number | null;
  schedulerRestarting: boolean;
  schedulerMessage: string | null;
  onThemeModeChange: (value: MobileThemeMode) => void;
  onSkinChange: (value: MobileSkin) => void;
  onMobileDiagnosticsModeChange: (value: MobileDiagnosticsMode) => void;
  onOpenHistory: () => void;
  onOpenAdmin: () => void;
  onOpenMatrix: () => void;
  onOpenDoc: (slug: DocSlug) => void;
  onOpenCoffee: () => void;
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
              {loading ? <ActivityIndicator color="#000" /> : <Text style={styles.connectButtonText}>CONNECT</Text>}
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
            value={`${themeMode} · ${skin}`}
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
            value="Bundled README"
            onPress={() => onOpenDoc("readme")}
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
        <Pressable style={styles.coffeeCard} onPress={onOpenCoffee}>
          <View style={styles.coffeeIcon}>
            <MaterialCommunityIcons name="coffee" size={19} color="#111" />
          </View>
          <View style={styles.coffeeCopy}>
            <Text style={styles.coffeeTitle}>BUY ME A COFFEE</Text>
            <Text style={styles.coffeeBody}>Support Local Flight and keep the boards glowing.</Text>
          </View>
          <MaterialCommunityIcons name="open-in-new" size={16} color={palette.amber} />
        </Pressable>
      </View>

      <AppearanceSheet
        visible={appearanceVisible}
        themeMode={themeMode}
        skin={skin}
        onClose={() => setAppearanceVisible(false)}
        onThemeModeChange={onThemeModeChange}
        onSkinChange={onSkinChange}
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

  const loadDoc = useCallback(async () => {
    setLoadingDoc(true);
    setDocError(null);
    setDocument(null);
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

  return (
    <ScrollView
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

        <View style={styles.docsCard}>
          {loadingDoc ? <ActivityIndicator color={palette.blue} style={styles.loader} /> : null}
          {!loadingDoc && docError ? (
            <>
              <Text style={styles.sheetEmpty}>
                Could not load the bundled server document inside the app: {docError}
              </Text>
              <SettingsToolPill
                icon="open-in-new"
                label="Open in GitHub"
                value="External fallback opened only when you tap"
                onPress={() => void Linking.openURL(githubUrl)}
              />
            </>
          ) : null}
          {!loadingDoc && !docError ? <MarkdownDocument content={document?.content || ""} /> : null}
        </View>
      </View>
    </ScrollView>
  );
}

function MarkdownDocument({ content }: { content: string }) {
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
      nodes.push(<Text key={`doc-title-${index}`} style={styles.docTitle}>{cleanMarkdownInline(line.replace(/^#\s+/, ""))}</Text>);
      return;
    }
    if (line.startsWith("## ")) {
      nodes.push(<Text key={`doc-heading-${index}`} style={styles.docHeading}>{cleanMarkdownInline(line.replace(/^##\s+/, ""))}</Text>);
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
        <Text style={styles.appearancePreviewBody}>Theme the companion without changing the server display.</Text>
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
  onClose,
  onThemeModeChange,
  onSkinChange
}: {
  visible: boolean;
  themeMode: MobileThemeMode;
  skin: MobileSkin;
  onClose: () => void;
  onThemeModeChange: (value: MobileThemeMode) => void;
  onSkinChange: (value: MobileSkin) => void;
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
              <Text style={styles.sheetSubtitle}>Theme the phone without changing the server display.</Text>
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

export function ScreenError({ message }: { message: string }) {
  return (
    <View style={styles.errorBanner}>
      <Text style={styles.errorBannerLabel}>DATA ISSUE</Text>
      <Text style={styles.errorBannerText}>{message}</Text>
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
  profiles,
  onClose,
  onApplied,
  onProfilesChange
}: {
  visible: boolean;
  serverUrl: string;
  currentConfig: AppConfig | null;
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
      onRequestClose={onClose}
    >
      <View style={styles.configSheetBg}>
        <View style={styles.configSheet}>
          <View style={styles.configSheetHandle} />
          <View style={styles.configSheetHeader}>
            <Text style={styles.configSheetTitle}>CONFIGURE SERVER</Text>
            <Pressable onPress={onClose} style={styles.configSheetClose}>
              <MaterialCommunityIcons name="close" size={20} color={palette.textMuted} />
            </Pressable>
          </View>

          <ScrollView style={styles.configSheetScroll} keyboardShouldPersistTaps="handled">
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
                    onPress={() => { setSelectedAirport(r); setQuery(""); setSearchResults([]); }}
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
              {REFRESH_OPTIONS.map((opt) => (
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
              Choices are 15, 30, 45, and 60 minutes, then 2, 4, 8, 12, or 24 hours. Shorter values keep local displays fresh; longer values are kinder to schedule providers. Community Relay may reuse an already-cached airport snapshot for about one hour even when this client checks more often.
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
                ? <ActivityIndicator size="small" color={palette.bg} />
                : <Text style={styles.configApplyBtnText}>APPLY TO SERVER</Text>
              }
            </Pressable>
            <View style={{ height: 36 }} />
          </ScrollView>
        </View>
      </View>
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
