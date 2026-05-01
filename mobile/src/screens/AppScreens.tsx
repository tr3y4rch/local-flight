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

import { patchConfig, searchAirports } from "../api/client";
import type {
  AppConfig,
  AirportResult,
  ConfigPatch,
  DashboardSnapshot,
  FidsRow,
  FlightDetail,
  FlightView,
  HistoryDirection,
  HistoryFlightRow,
  HistoryResponse,
  RadarBlip,
  RadarResponse
} from "../api/types";
import { platformPairLabel, type CompanionIdentity } from "../device/identity";
import {
  APP_VERSION,
  HISTORY_WINDOWS,
  MATRIX_BRIGHTNESS,
  MATRIX_PRESETS,
  MATRIX_REFRESH_SECONDS,
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
  formatClock,
  formatDateTime,
  formatInterval,
  formatRelative,
  hexToRgba,
  parseMetarChips
} from "../domain/formatting";
import { MATRIX_SKIN_PALETTES, matrixPreviewLines } from "../domain/matrix";
import { projectBlip } from "../domain/radar";
import type { FeedbackTone, HistoryWindow, MatrixPreset, ProjectedBlip, RadarRadius, StatusTone } from "../domain/types";
import { type ConfigProfile, saveProfiles } from "../storage/settings";
import { palette, styles } from "../theme/styleBridge";
import {
  MOBILE_SKIN_OPTIONS,
  MOBILE_THEME_OPTIONS,
  type MobileSkin,
  type MobileThemeMode
} from "../theme/tokens";

type MaterialIconName = ComponentProps<typeof MaterialCommunityIcons>["name"];
export type DocSlug = "readme" | "privacy" | "changelog";

const DOC_SOURCES: Record<DocSlug, { title: string; detail: string; url: string }> = {
  readme: {
    title: "README",
    detail: "Project overview, install notes, and operating model",
    url: "https://raw.githubusercontent.com/tr3y4rch/local-flight/main/README.md"
  },
  privacy: {
    title: "Privacy",
    detail: "What stays local and what diagnostics can send",
    url: "https://raw.githubusercontent.com/tr3y4rch/local-flight/main/PRIVACY.md"
  },
  changelog: {
    title: "Changelog",
    detail: "Release history and beta notes",
    url: "https://raw.githubusercontent.com/tr3y4rch/local-flight/main/CHANGELOG.md"
  }
};

type SettingsSection = "server" | "appearance" | "tools" | "about";

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
              <View key={i} style={styles.metarChip}>
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

export function LandscapeDisplay({
  primary,
  rows,
  view,
  radarData,
  radarRadius,
  refreshing,
  error,
  showConnectPrompt,
  onOpenSettings,
  onRefreshFids,
  onRefreshRadar,
  onViewChange,
  onRadiusChange,
  onOpenDetail,
  onOpenActions,
  pinnedCallsign,
  contentPaddingBottom
}: {
  primary: "fids" | "radar";
  rows: FidsRow[];
  view: FlightView;
  radarData: RadarResponse | null;
  radarRadius: RadarRadius;
  refreshing: boolean;
  error: string | null;
  showConnectPrompt: boolean;
  onOpenSettings: () => void;
  onRefreshFids: () => void;
  onRefreshRadar: () => void;
  onViewChange: (view: FlightView) => void;
  onRadiusChange: (value: RadarRadius) => void;
  onOpenDetail: (callsign: string) => void;
  onOpenActions: (row: FidsRow) => void;
  pinnedCallsign: string;
  contentPaddingBottom: number;
}) {
  const firstPane = primary === "fids"
    ? (
      <FidsScreen
        rows={rows}
        view={view}
        loading={refreshing}
        refreshing={refreshing}
        error={error}
        showConnectPrompt={showConnectPrompt}
        onOpenSettings={onOpenSettings}
        onRefresh={onRefreshFids}
        onViewChange={onViewChange}
        onOpenDetail={onOpenDetail}
        onOpenActions={onOpenActions}
        pinnedCallsign={pinnedCallsign}
        contentPaddingBottom={contentPaddingBottom}
      />
    )
    : (
      <RadarScreen
        data={radarData}
        radiusNm={radarRadius}
        loading={refreshing}
        refreshing={refreshing}
        error={error}
        showConnectPrompt={showConnectPrompt}
        onOpenSettings={onOpenSettings}
        onRefresh={onRefreshRadar}
        onRadiusChange={onRadiusChange}
        onOpenDetail={onOpenDetail}
        compact
        contentPaddingBottom={contentPaddingBottom}
      />
    );
  const secondPane = primary === "fids"
    ? (
      <RadarScreen
        data={radarData}
        radiusNm={radarRadius}
        loading={refreshing}
        refreshing={refreshing}
        error={null}
        showConnectPrompt={false}
        onOpenSettings={onOpenSettings}
        onRefresh={onRefreshRadar}
        onRadiusChange={onRadiusChange}
        onOpenDetail={onOpenDetail}
        compact
        contentPaddingBottom={contentPaddingBottom}
      />
    )
    : (
      <FidsScreen
        rows={rows}
        view={view}
        loading={refreshing}
        refreshing={refreshing}
        error={null}
        showConnectPrompt={false}
        onOpenSettings={onOpenSettings}
        onRefresh={onRefreshFids}
        onViewChange={onViewChange}
        onOpenDetail={onOpenDetail}
        onOpenActions={onOpenActions}
        pinnedCallsign={pinnedCallsign}
        contentPaddingBottom={contentPaddingBottom}
      />
    );

  return (
    <View style={styles.splitDisplay}>
      <View style={[styles.splitPane, styles.splitPanePrimary]}>{firstPane}</View>
      <View style={[styles.splitPane, styles.splitPaneSecondary]}>{secondPane}</View>
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
      keyExtractor={(row) => row.id}
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
      keyExtractor={(row) => String(row.id)}
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

  return (
    <FlatList<RadarBlip>
      data={blips}
      keyExtractor={(row, index) => `${row.callsign}-${index}`}
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
          </View>

          <RadarScope data={data} radiusNm={radiusNm} onRadiusChange={onRadiusChange} onOpenDetail={onOpenDetail} compact={compact} />
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
  preset,
  brightness,
  maxRows,
  refreshSeconds,
  configText,
  matrixSkin,
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
  onPresetChange,
  onBrightnessChange,
  onRowsChange,
  onRefreshSecondsChange,
  onSave,
  onReset,
  onBackSettings,
  contentPaddingBottom
}: {
  rows: FidsRow[];
  view: FlightView;
  preset: MatrixPreset;
  brightness: number;
  maxRows: number;
  refreshSeconds: number;
  configText: string;
  matrixSkin: MobileSkin;
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
  onPresetChange: (value: MatrixPreset) => void;
  onBrightnessChange: (value: number) => void;
  onRowsChange: (value: number) => void;
  onRefreshSecondsChange: (value: number) => void;
  onSave: () => void;
  onReset: () => void;
  onBackSettings: () => void;
  contentPaddingBottom: number;
}) {
  const lines = matrixPreviewLines(rows);
  const brightnessAlpha = Math.max(0.28, Math.min(1, brightness));
  const matrixColors = MATRIX_SKIN_PALETTES[matrixSkin] || MATRIX_SKIN_PALETTES.standard;
  const brightnessPct = Math.round(brightness * 100);

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
          detail="Panel preview and client staging"
          onBack={onBackSettings}
        />

        <View style={styles.metricRow}>
          <InfoCard label="PANEL" value={`${preset.panelW}x${preset.panelH}`} />
          <InfoCard label="ROWS" value={String(maxRows)} tone="green" />
          <InfoCard label="BRIGHT" value={`${brightnessPct}%`} tone="amber" />
        </View>

        <View style={styles.metricRow}>
          <InfoCard label="VIEW" value={view === "arrivals" ? "ARR" : "DEP"} />
          <InfoCard label="DEVICE" value={matrixEnabled ? "ENABLED" : "OFF"} tone={matrixEnabled ? "green" : "red"} />
          <InfoCard label="SYNC" value={dirty ? "DRAFT" : "SAVED"} tone={dirty ? "amber" : "green"} />
        </View>

        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>BOARD RUNTIME</Text>
          <Text style={styles.moduleIntro}>
            These controls write the same runtime config the desktop tool saves for the physical board.
          </Text>

          <View style={styles.infoLine}>
            <Text style={styles.infoLineLabel}>LAST PING</Text>
            <Text style={styles.infoLineValue}>{matrixLastSeen ? formatRelative(matrixLastSeen) : "Never pinged"}</Text>
          </View>

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

        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>PANEL PREVIEW</Text>
          <Text style={styles.moduleIntro}>
            Keep panel size local to the phone. This only affects the preview and generated `main.py`, not the saved server runtime.
          </Text>

          <FilterSection title="PANEL PRESET">
            <View style={styles.filterWrap}>
              {MATRIX_PRESETS.map((item) => (
                <OptionChip
                  key={item.label}
                  active={preset.label === item.label}
                  label={item.label}
                  meta={item.modules}
                  onPress={() => onPresetChange(item)}
                />
              ))}
            </View>
          </FilterSection>
        </View>

        <View style={[styles.matrixToolShell, { backgroundColor: matrixColors.off }]}>
          <View style={styles.matrixToolBezel}>
            <View style={styles.matrixToolHeader}>
              <Text style={[styles.matrixToolTitle, { color: matrixColors.green }]}>INTERSTATE 75 W PREVIEW</Text>
              <Text style={[styles.matrixToolMeta, { color: matrixColors.dim }]}>{preset.panelW}x{preset.panelH} · {preset.modules}</Text>
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
                {(rows[0]?.view || view) === "arrivals" ? "ARR" : "DEP"} · {preset.panelW}x{preset.panelH}
              </Text>
              {lines.map((line, index) => (
                <Text key={`${index}-${line}`} style={[styles.matrixPixelLine, { color: matrixColors.white }]}>
                  {line}
                </Text>
              ))}
            </View>
          </View>
        </View>

        <View style={styles.settingsCard}>
          <Text style={styles.settingsTitle}>MICROPYTHON CONFIG</Text>
          <Text style={styles.moduleIntro}>
            Paste this block into `client.py` later. It stays aligned with your selected panel preset and current server address.
          </Text>
          <View style={styles.feedbackContextBox}>
            <Text style={styles.feedbackContextText}>{configText}</Text>
          </View>
          <Text style={styles.settingsHelp}>
            The physical client still polls `/api/fids` and pings `/api/admin/ping`; this screen is the mobile staging tool for that output path.
          </Text>
        </View>
      </View>
    </ScrollView>
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
  radiusNm,
  onRadiusChange,
  compact = false,
  onOpenDetail
}: {
  data: RadarResponse | null;
  radiusNm: RadarRadius;
  onRadiusChange: (value: RadarRadius) => void;
  compact?: boolean;
  onOpenDetail: (callsign: string) => void;
}) {
  const [scopeSize, setScopeSize] = useState(280);
  const pinchRef = useRef<{ distance: number; index: number } | null>(null);
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
        <View style={styles.scopeRingOuter} />
        <View style={styles.scopeRingMid} />
        <View style={styles.scopeRingInner} />
        <View style={styles.scopeCrossVertical} />
        <View style={styles.scopeCrossHorizontal} />
        <View style={styles.scopeCenterDot} />

        {projected.map((item, index) => (
          <Pressable
            key={`${item.blip.callsign}-${index}`}
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
                    {detail.airline || "Unknown carrier"} {detail.aircraft_type ? `- ${detail.aircraft_type}` : ""}
                  </Text>
                </View>

                <SectionTitle label="ROUTE & DATA" />
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="FROM" value={airportMetric(detail.origin_iata, detail.origin_name)} />
                  <SheetMetric label="TO" value={airportMetric(detail.dest_iata, detail.dest_name)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="AIRLINE" value={detail.airline_iata || detail.airline || "-"} />
                  <SheetMetric label="CALLSIGN" value={detail.callsign || callsign || "-"} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="SOURCE" value={detail.source ? detail.source.toUpperCase() : "-"} />
                  <SheetMetric label="ENRICHED" value={detail.enriched_by ? detail.enriched_by.toUpperCase() : "-"} />
                </View>

                <SectionTitle label="TIMES & GATE" />
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="SCHEDULED" value={formatDateTime(detail.sched_time)} />
                  <SheetMetric label="ESTIMATED" value={formatDateTime(detail.est_time)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="ACTUAL" value={formatDateTime(detail.actual_time)} />
                  <SheetMetric label="DELAY" value={detail.delay_minutes != null ? `${detail.delay_minutes}m` : "-"} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="GATE" value={detail.gate || "-"} />
                  <SheetMetric label="TERMINAL" value={detail.terminal || "-"} />
                </View>

                <SectionTitle label="TRACK" />
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="ALTITUDE" value={formatAltitudeFeet(detail.position?.altitude_m)} />
                  <SheetMetric label="SPEED" value={formatSpeedKnots(detail.position?.speed_ms)} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="HEADING" value={formatHeading(detail.position?.heading)} />
                  <SheetMetric label="GROUND" value={detail.position?.on_ground ? "YES" : "NO"} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="LAT" value={formatCoordinate(detail.position?.lat, "N", "S")} />
                  <SheetMetric label="LON" value={formatCoordinate(detail.position?.lon, "E", "W")} />
                </View>
                <View style={styles.sheetMetricRow}>
                  <SheetMetric label="VERT RATE" value={formatVerticalRate(detail.position?.vertical_rate)} />
                  <SheetMetric label="DIRECTION" value={detail.direction ? detail.direction.toUpperCase() : "-"} />
                </View>

                <SectionTitle label="7-DAY HISTORY" />
                {history.length > 0 ? (
                  history.map((item) => (
                    <View key={`${item.date}-${item.status || "status"}`} style={styles.sheetHistoryRow}>
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
                  history.map((item) => (
                    <View key={`${item.date}-${item.status || "status"}`} style={styles.sheetHistoryRow}>
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
  rows,
  view,
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
  onBackSettings
}: {
  snapshot: DashboardSnapshot;
  companionIdentity: CompanionIdentity | null;
  connected: boolean;
  error: string | null;
  rows: FidsRow[];
  view: FlightView;
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

      <View style={styles.metricRow}>
        <InfoCard label="SERVER" value={connected ? "ONLINE" : "CHECK"} tone={connected ? "green" : "red"} />
        <InfoCard label="VERSION" value={snapshot.system?.version || APP_VERSION} />
        <InfoCard
          label="UPDATE"
          value={updateValue}
          tone={snapshot.updates?.update_available ? "amber" : "blue"}
        />
      </View>
      <View style={styles.metricRow}>
        <InfoCard label="LAST FETCH" value={formatRelative(snapshot.state?.last_success_utc)} tone="amber" />
        <InfoCard label="WEBSOCKETS" value={String(snapshot.connections?.count ?? 0)} />
        <InfoCard label="API BUDGET" value={budget?.remaining != null ? `${budget.remaining} LEFT` : "UNKNOWN"} />
      </View>
      <View style={styles.metricRow}>
        <InfoCard label="PAIR" value={companionRecord?.platform_pair || platformPair} />
        <InfoCard label="MEMORY" value={snapshot.system?.memory_mb != null ? `${snapshot.system.memory_mb} MB` : "-"} />
        <InfoCard label="MATRIX" value={matrixOnline ? "ONLINE" : matrixEnabled ? "WAITING" : "DISABLED"} tone={matrixOnline ? "green" : matrixEnabled ? "amber" : "red"} />
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>COMPANION LINK</Text>
        <Text style={styles.moduleIntro}>
          Separate mobile identity used for server presence, request tracing, and Linear reports.
        </Text>
        <InfoLine label="Companion ID" value={companionIdentity?.companionId || "Loading..."} />
        <InfoLine label="Companion OS" value={companionIdentity?.mobileOs || "Loading..."} />
        <InfoLine label="Server install" value={snapshot.system?.install_id || "Unknown"} />
        <InfoLine label="Platform pair" value={companionRecord?.platform_pair || platformPair} />
        <InfoLine label="Last check-in" value={companionRecord?.last_seen ? formatRelative(companionRecord.last_seen) : "Not seen yet"} />
      </View>

      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>MATRIX OUTPUT</Text>
        <Text style={styles.moduleIntro}>
          Mirrors the LED output path from the main app using the same `/api/fids` rows.
        </Text>
        <InfoLine label="Enabled" value={matrixEnabled ? "Yes, matrix is selected in server outputs." : "No, enable Matrix in desktop Settings first."} />
        <InfoLine label="Last seen" value={matrixLastSeen ? formatRelative(matrixLastSeen) : "Never pinged"} />
        <InfoLine label="Preview mode" value={`${snapshot.config?.airport_iata || "---"} ${view === "arrivals" ? "ARRIVALS" : "DEPARTURES"}`} />

        <View style={styles.matrixBoard}>
          <View style={styles.matrixHeaderRow}>
            <Text style={styles.matrixBoardTitle}>INTERSTATE 75 W</Text>
            <Text style={styles.matrixBoardSub}>{matrixOnline ? "LIVE PANEL" : "SIM PREVIEW"}</Text>
          </View>
          {matrixPreviewLines(rows).map((line, index) => (
            <Text key={`${index}-${line}`} style={styles.matrixBoardLine}>
              {line}
            </Text>
          ))}
        </View>

        <Text style={styles.settingsHelp}>
          The physical matrix client polls the server directly and reports here through `/api/admin/ping`.
        </Text>
      </View>

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

      {__DEV__ ? (
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

export function SettingsScreen({
  serverUrl,
  draftUrl,
  error,
  loading,
  isTablet,
  isLandscape,
  themeMode,
  skin,
  outputs,
  refreshSeconds,
  schedulerRestarting,
  schedulerMessage,
  onThemeModeChange,
  onSkinChange,
  onOpenHistory,
  onOpenAdmin,
  onOpenMatrix,
  onOpenDoc,
  onOpenCoffee,
  onRestartScheduler,
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
  outputs: string[];
  refreshSeconds: number | null;
  schedulerRestarting: boolean;
  schedulerMessage: string | null;
  onThemeModeChange: (value: MobileThemeMode) => void;
  onSkinChange: (value: MobileSkin) => void;
  onOpenHistory: () => void;
  onOpenAdmin: () => void;
  onOpenMatrix: () => void;
  onOpenDoc: (slug: DocSlug) => void;
  onOpenCoffee: () => void;
  onRestartScheduler: () => void;
  onChangeUrl: (value: string) => void;
  onConnect: () => void;
}) {
  const [section, setSection] = useState<SettingsSection>("server");

  return (
    <View style={styles.cardStack}>
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>SETTINGS</Text>
        <Text style={styles.moduleIntro}>
          Keep the main companion calm: connection, looks, tools, and documents live here.
        </Text>
        <View style={styles.settingsSectionGrid}>
          {([
            ["server", "Server", "LAN"],
            ["appearance", "Looks", themeMode],
            ["tools", "Tools", "Ops"],
            ["about", "Docs", "Read"]
          ] as Array<[SettingsSection, string, string]>).map(([id, label, meta]) => (
            <OptionChip
              key={id}
              active={section === id}
              label={label}
              meta={meta}
              onPress={() => setSection(id)}
            />
          ))}
        </View>
      </View>

      {section === "server" ? (
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>LOCAL SERVER</Text>
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
        {error ? <Text style={styles.errorText}>{error}</Text> : null}
        <InfoLine label="Saved server" value={serverUrl || "Not set"} />
        <InfoLine label="Companion build" value={APP_VERSION} />
        <InfoLine label="Layout" value={isTablet ? `iPad ${isLandscape ? "landscape" : "portrait"}` : "iPhone"} />
        <InfoLine label="Outputs" value={outputs.length ? outputs.join(", ").toUpperCase() : "WEB"} />
        <InfoLine label="Update interval" value={refreshSeconds ? formatInterval(refreshSeconds) : "Not synced"} />
        <Text style={styles.settingsHelp}>
          Use the LAN IP of the machine running Local Flight. On a physical iPhone, localhost points at the phone itself.
        </Text>
      </View>
      ) : null}

      {section === "appearance" ? (
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>APPEARANCE</Text>
        <Text style={styles.moduleIntro}>
          Mobile looks stay independent from the desktop skin. Pick the companion mood that feels right for the phone or tablet.
        </Text>

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
      </View>
      ) : null}

      {section === "tools" ? (
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>TOOLS</Text>
        <SettingsToolPill
          icon="restart"
          label="Restart scheduler"
          value={schedulerMessage || "Reload config and run a fresh fetch cycle"}
          onPress={onRestartScheduler}
          loading={schedulerRestarting}
          disabled={schedulerRestarting}
        />
        <SettingsToolPill
          icon="history"
          label="History"
          value="Browse stored flights without crowding the main nav"
          onPress={onOpenHistory}
        />
        <SettingsToolPill
          icon="view-grid"
          label="Matrix panel"
          value="Preview and configure HUB75 output"
          onPress={onOpenMatrix}
        />
        <SettingsToolPill
          icon="tools"
          label="Admin panel"
          value="Diagnostics, budgets, and reports"
          onPress={onOpenAdmin}
        />
      </View>
      ) : null}

      {section === "about" ? (
      <View style={styles.settingsCard}>
        <Text style={styles.settingsTitle}>ABOUT</Text>
        <Text style={styles.settingsHelp}>
          Local Flight is a local-first flight information display. All flight data, history, and config stay on your machine — nothing is uploaded, synced, or tracked beyond the configured aviation data sources.
        </Text>
        <Text style={styles.settingsHelp}>
          The only data that leaves your machine without your action is an automatic crash report if the server encounters an unhandled error. It contains the version, OS, airport code, and a traceback — no API keys, no IP address, no personal information.
        </Text>
        <SettingsToolPill
          icon="book-open-variant"
          label="Local docs"
          value="Read README inside the companion"
          onPress={() => onOpenDoc("readme")}
        />
        <SettingsToolPill
          icon="shield-lock-outline"
          label="Privacy"
          value="What stays local and what the crash reporter sends"
          onPress={() => onOpenDoc("privacy")}
        />
        <SettingsToolPill
          icon="github"
          label="Source & releases"
          value="github.com/tr3y4rch/local-flight"
          onPress={() => void Linking.openURL("https://github.com/tr3y4rch/local-flight")}
        />
        <SettingsToolPill
          icon="format-list-bulleted"
          label="Changelog"
          value="Release history and version notes"
          onPress={() => onOpenDoc("changelog")}
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
      ) : null}
    </View>
  );
}

export function DocsScreen({
  slug,
  onBackSettings,
  contentPaddingBottom
}: {
  slug: DocSlug;
  onBackSettings: () => void;
  contentPaddingBottom: number;
}) {
  const source = DOC_SOURCES[slug];
  const [content, setContent] = useState("");
  const [loadingDoc, setLoadingDoc] = useState(true);
  const [docError, setDocError] = useState<string | null>(null);

  const loadDoc = useCallback(async () => {
    setLoadingDoc(true);
    setDocError(null);
    try {
      const response = await fetch(source.url, { headers: { Accept: "text/plain" } });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      setContent(await response.text());
    } catch (exc) {
      setDocError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoadingDoc(false);
    }
  }, [source.url]);

  useEffect(() => {
    void loadDoc();
  }, [loadDoc]);

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
          title={source.title}
          detail={source.detail}
          onBack={onBackSettings}
        />

        <View style={styles.docsCard}>
          {loadingDoc ? <ActivityIndicator color={palette.blue} style={styles.loader} /> : null}
          {!loadingDoc && docError ? (
            <>
              <Text style={styles.sheetEmpty}>
                Could not load the GitHub document inside the app: {docError}
              </Text>
              <SettingsToolPill
                icon="open-in-new"
                label="Open in GitHub"
                value="Fallback if the phone has no GitHub raw access"
                onPress={() => void Linking.openURL(source.url.replace("raw.githubusercontent.com/tr3y4rch/local-flight/main", "github.com/tr3y4rch/local-flight/blob/main"))}
              />
            </>
          ) : null}
          {!loadingDoc && !docError ? <MarkdownDocument content={content} /> : null}
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
      <View key={`code-${nodes.length}`} style={styles.docCodeBlock}>
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
      nodes.push(<Text key={index} style={styles.docTitle}>{cleanMarkdownInline(line.replace(/^#\s+/, ""))}</Text>);
      return;
    }
    if (line.startsWith("## ")) {
      nodes.push(<Text key={index} style={styles.docHeading}>{cleanMarkdownInline(line.replace(/^##\s+/, ""))}</Text>);
      return;
    }
    if (line.startsWith("### ")) {
      nodes.push(<Text key={index} style={styles.docSubheading}>{cleanMarkdownInline(line.replace(/^###\s+/, ""))}</Text>);
      return;
    }
    const bullet = line.match(/^[-*]\s+(.*)$/);
    if (bullet) {
      nodes.push(
        <View key={index} style={styles.docBulletRow}>
          <Text style={styles.docBulletMark}>-</Text>
          <Text style={styles.docBody}>{cleanMarkdownInline(bullet[1] || "")}</Text>
        </View>
      );
      return;
    }
    const numbered = line.match(/^\d+\.\s+(.*)$/);
    if (numbered) {
      nodes.push(
        <View key={index} style={styles.docBulletRow}>
          <Text style={styles.docBulletMark}>#</Text>
          <Text style={styles.docBody}>{cleanMarkdownInline(numbered[1] || "")}</Text>
        </View>
      );
      return;
    }
    nodes.push(<Text key={index} style={styles.docBody}>{cleanMarkdownInline(line)}</Text>);
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
                {searchResults.map((r) => (
                  <Pressable
                    key={r.iata}
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

            <Text style={styles.configSectionLabel}>PROFILES</Text>
            {profiles.length > 0 && (
              <View style={styles.configProfileList}>
                {profiles.map((p) => {
                  const isApplyingThis = applyingProfileId === p.id;
                  return (
                    <View key={p.id} style={styles.configProfileRow}>
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
