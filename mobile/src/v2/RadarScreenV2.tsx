import { useEffect, useMemo, useState } from "react";
import {
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  SafeAreaView,
  StyleSheet,
  View
} from "react-native";

import type { Metar, RadarBlip, RadarMapResponse, RadarResponse } from "../api/types";
import { accessibleButton, tapTargetHitSlop } from "../accessibility/mobileA11y";
import { MotionPressable } from "../components/MotionPressable";
import { V2Text as Text } from "../components/V2Text";
import { englishCopy } from "../content/en";
import type { RadarRadius } from "../domain/types";
import type { MobileRadarDrawingLayers } from "../storage/settings";
import { LocalFlightIcon } from "../theme/icons";
import { useMobileTheme } from "../theme/runtime";
import { BOARD_FONT_FAMILY, type MobileAppearance } from "../theme/tokens";
import { hapticLight, hapticSelection } from "../utils/haptics";
import type { LayoutWidthClass } from "../utils/layout";
import { RadarScopeV2 } from "./RadarScopeV2";

export type RadarScreenV2Props = {
  data: RadarResponse | null;
  groundData: RadarMapResponse | null;
  groundError: string | null;
  metar: Metar | null;
  radiusNm: RadarRadius;
  radiusOptions: RadarRadius[];
  drawingLayers: MobileRadarDrawingLayers;
  standalone: boolean;
  refreshing: boolean;
  error: string | null;
  updatedLabel: string;
  layoutClass: LayoutWidthClass;
  contentPaddingBottom: number;
  /** True only while UIKit owns the compact iPhone tab bar. */
  nativeNavigation?: boolean;
  dismissRequestKey?: number;
  onRefresh: () => void;
  onRadiusChange: (value: RadarRadius) => void;
  onDrawingLayersChange: (value: MobileRadarDrawingLayers) => void;
  onOpenDetail: (callsign: string, blip?: RadarBlip) => void;
  onOpenWeather: () => void;
};

function clean(value: unknown): string {
  const text = String(value ?? "").trim();
  return text && text !== "-" ? text : "";
}

function weatherSummary(metar: Metar | null): string {
  return clean(metar?.weather_summary) || clean(metar?.decoded_summary) || clean(metar?.weather_label) || "Weather unavailable";
}

function temperature(metar: Metar | null): string {
  const value = metar?.temperature_c ?? metar?.temp_c;
  return typeof value === "number" ? `${Math.round(value)}°` : "--°";
}

function altitude(blip: RadarBlip): string {
  if (clean(blip.altitude_display)) return clean(blip.altitude_display);
  if (typeof blip.altitude_ft === "number") return `${Math.round(blip.altitude_ft).toLocaleString()} ft`;
  if (typeof blip.altitude_m === "number") return `${Math.round(blip.altitude_m * 3.28084).toLocaleString()} ft`;
  return "Altitude unavailable";
}

function speed(blip: RadarBlip): string {
  if (clean(blip.speed_display)) return clean(blip.speed_display);
  if (typeof blip.speed_kt === "number") return `${Math.round(blip.speed_kt)} kt`;
  if (typeof blip.speed_ms === "number") return `${Math.round(blip.speed_ms * 1.94384)} kt`;
  return "Speed unavailable";
}

function radarStatus(blip: RadarBlip): string {
  return clean(blip.radar_status_label) || clean(blip.radar_phase) || "Tracked";
}

function toneForBlip(blip: RadarBlip, appearance: MobileAppearance): string {
  const phase = radarStatus(blip).toLowerCase();
  if (/approach|final|arrival/.test(phase)) return appearance.green;
  if (/ground|taxi/.test(phase)) return appearance.amber;
  if (/depart|climb/.test(phase)) return appearance.blue;
  return appearance.blue2;
}

function AviationDetails({
  props,
  appearance,
  styles
}: {
  props: RadarScreenV2Props;
  appearance: MobileAppearance;
  styles: ReturnType<typeof makeStyles>;
}) {
  const layerOptions: Array<{ key: keyof MobileRadarDrawingLayers; label: string; detail: string }> = [
    { key: "runways", label: "Runways", detail: "Airport runway geometry" },
    { key: "surface", label: "Surface map", detail: "Taxiways, aprons and nearby ground context" },
    { key: "terrain", label: "Terrain", detail: "Cached elevation bands and contours" }
  ];
  return (
    <View style={styles.detailsBody}>
      <Text style={styles.detailsHeading}>Aviation details</Text>
      <Text style={styles.detailsIntro}>Optional map context and source information for pilots and aviation enthusiasts.</Text>

      <Text style={styles.detailsSectionTitle}>Map layers</Text>
      {layerOptions.map((option) => {
        const selected = props.drawingLayers[option.key];
        return (
          <Pressable
            key={option.key}
            style={({ pressed }) => [styles.layerRow, pressed && styles.pressed]}
            onPress={() => {
              hapticSelection();
              props.onDrawingLayersChange({ ...props.drawingLayers, [option.key]: !selected });
            }}
            {...accessibleButton({ label: `${selected ? "Hide" : "Show"} ${option.label}`, selected })}
          >
            <View style={[styles.layerCheck, selected && styles.layerCheckSelected]}>
              {selected ? <LocalFlightIcon name="check" size={15} color={appearance.bg} /> : null}
            </View>
            <View style={styles.layerCopy}>
              <Text style={styles.layerTitle}>{option.label}</Text>
              <Text style={styles.layerDetail}>{option.detail}</Text>
            </View>
          </Pressable>
        );
      })}

      <Text style={styles.detailsSectionTitle}>Current source</Text>
      <View style={styles.sourceCard}>
        <View style={styles.sourceRow}>
          <Text style={styles.sourceLabel}>Aircraft tracks</Text>
          <Text style={styles.sourceValue}>{clean(props.data?.source) || "Waiting"}</Text>
        </View>
        <View style={styles.sourceRow}>
          <Text style={styles.sourceLabel}>Range</Text>
          <Text style={styles.sourceValue}>{props.radiusNm} NM</Text>
        </View>
        <View style={styles.sourceRow}>
          <Text style={styles.sourceLabel}>Ground context</Text>
          <Text style={styles.sourceValue}>{props.groundData ? "Available" : props.groundError ? "Unavailable" : "Waiting"}</Text>
        </View>
      </View>
      {props.groundError ? <Text style={styles.groundNote}>Ground map note: {props.groundError}</Text> : null}

      <Text style={styles.informationalNote}>{englishCopy.app.informationalDisclaimer}</Text>
    </View>
  );
}

export function RadarScreenV2(props: RadarScreenV2Props) {
  const { appearance } = useMobileTheme();
  const expanded = props.layoutClass === "expanded" || props.layoutClass === "large";
  const styles = useMemo(() => makeStyles(appearance, props.layoutClass), [appearance, props.layoutClass]);
  const [detailsVisible, setDetailsVisible] = useState(false);

  useEffect(() => {
    if (props.dismissRequestKey) setDetailsVisible(false);
  }, [props.dismissRequestKey]);
  const blips = (props.data?.blips || []).filter((blip) => {
    if (typeof blip.distance_nm === "number" && blip.distance_nm > props.radiusNm) return false;
    if (props.radiusNm > 5 && (blip.on_ground || /ground|taxi/i.test(blip.radar_phase || ""))) return false;
    return true;
  });

  const details = <AviationDetails props={props} appearance={appearance} styles={styles} />;
  const header = (
    <>
      <View style={styles.titleRow}>
        <View style={styles.titleCopy}>
          <Text style={styles.eyebrow}>{props.updatedLabel}</Text>
          <Text style={styles.title}>Radar</Text>
          <Text style={styles.subtitle}>{blips.length} aircraft in the {props.radiusNm} NM view</Text>
        </View>
        <MotionPressable
          style={styles.detailsButton}
          interactiveStyle={styles.pressed}
          onPress={() => {
            hapticLight();
            setDetailsVisible((visible) => !visible);
          }}
          {...accessibleButton({ label: "Open Aviation Details" })}
        >
          <LocalFlightIcon name="tune-variant" size={19} color={appearance.blue} />
          <Text style={styles.detailsButtonText}>Aviation details</Text>
        </MotionPressable>
      </View>

      {props.error ? (
        <Pressable style={styles.errorCard} onPress={props.onRefresh} {...accessibleButton({ label: `${props.error}. Try again.` })}>
          <LocalFlightIcon name="alert-circle-outline" size={20} color={appearance.red} />
          <View style={styles.errorCopy}>
            <Text style={styles.errorTitle}>Radar could not refresh</Text>
            <Text style={styles.errorBody}>{props.error}</Text>
          </View>
        </Pressable>
      ) : null}

      <View style={styles.scopeGrid}>
        <View style={styles.scopeColumn}>
          <View style={styles.quietOverlay} pointerEvents="none">
            <View style={styles.overlayPill}>
              <Text style={styles.overlayLabel}>{props.radiusNm} NM</Text>
            </View>
            <View style={styles.overlayPill}>
              <Text style={styles.overlayLabel}>{props.updatedLabel}</Text>
            </View>
          </View>
          <RadarScopeV2
            data={props.data}
            groundData={props.groundData}
            groundError={props.groundError}
            radiusNm={props.radiusNm}
            radiusOptions={props.radiusOptions}
            drawingLayers={props.drawingLayers}
            onRadiusChange={props.onRadiusChange}
            onOpenDetail={props.onOpenDetail}
          />
        </View>
        {expanded && detailsVisible ? <View style={styles.inspector}>{details}</View> : null}
      </View>

      <MotionPressable style={styles.weatherCard} interactiveStyle={styles.pressed} onPress={props.onOpenWeather} {...accessibleButton({ label: `${weatherSummary(props.metar)}, ${temperature(props.metar)}. Opens weather details.` })}>
        <View style={styles.weatherIcon}>
          <LocalFlightIcon name="weather-partly-cloudy" size={21} color={appearance.blue} />
        </View>
        <View style={styles.weatherCopy}>
          <Text style={styles.weatherTitle}>{weatherSummary(props.metar)}</Text>
          <Text style={styles.weatherMeta}>Airport weather · tap for plain language, aviation details, or Raw METAR</Text>
        </View>
        <Text style={styles.weatherTemperature}>{temperature(props.metar)}</Text>
        <LocalFlightIcon name="chevron-right" size={18} color={appearance.textDim} />
      </MotionPressable>

      <View style={styles.trackHeading}>
        <Text style={styles.trackTitle}>Aircraft</Text>
        <Text style={styles.trackHint}>Tap a track for details</Text>
      </View>
    </>
  );

  return (
    <>
      <FlatList
        data={blips}
        keyExtractor={(blip, index) => `${blip.icao24 || blip.callsign}-${index}`}
        contentContainerStyle={[styles.content, { paddingBottom: props.contentPaddingBottom }]}
        contentInsetAdjustmentBehavior={props.nativeNavigation ? "automatic" : "never"}
        refreshControl={<RefreshControl refreshing={props.refreshing} tintColor={appearance.blue} onRefresh={props.onRefresh} />}
        ListHeaderComponent={header}
        renderItem={({ item }) => {
          const tone = toneForBlip(item, appearance);
          const boardStatus = clean(item.board_status);
          const phase = radarStatus(item);
          return (
            <MotionPressable
              style={styles.trackRow}
              interactiveStyle={styles.pressed}
              onPress={() => props.onOpenDetail(item.callsign, item)}
              hitSlop={tapTargetHitSlop}
              {...accessibleButton({ label: `${item.callsign}, ${phase}, ${altitude(item)}, ${speed(item)}. Opens aircraft details.` })}
            >
              <View style={[styles.trackDot, { backgroundColor: tone }]} />
              <View style={styles.trackIdentity}>
                <Text style={styles.callsign}>{clean(item.display_title) || item.callsign}</Text>
                <Text style={styles.route} numberOfLines={1}>{clean(item.route_display) || clean(item.aircraft_type) || "Live aircraft track"}</Text>
              </View>
              <View style={styles.trackMotion}>
                <Text style={styles.motionPrimary}>{altitude(item)}</Text>
                <Text style={styles.motionSecondary}>{speed(item)}</Text>
              </View>
              <View style={styles.trackState}>
                <Text style={[styles.phase, { color: tone }]}>{phase}</Text>
                {boardStatus && boardStatus.toLowerCase() !== phase.toLowerCase() ? <Text style={styles.boardStatus}>Board: {boardStatus}</Text> : null}
              </View>
              <LocalFlightIcon name="chevron-right" size={18} color={appearance.textDim} />
            </MotionPressable>
          );
        }}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
        ListEmptyComponent={
          <View style={styles.empty}>
            <LocalFlightIcon name="radar" size={34} color={appearance.textMuted} />
            <Text style={styles.emptyTitle}>No aircraft in range</Text>
            <Text style={styles.emptyBody}>No current tracks match this radar view. Change the range or refresh later.</Text>
          </View>
        }
        showsVerticalScrollIndicator={false}
      />

      {!expanded ? (
        <Modal visible={detailsVisible} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => setDetailsVisible(false)}>
          <SafeAreaView style={styles.sheetSafe}>
            <View style={styles.sheetHeader}>
              <Text style={styles.sheetHeaderTitle}>Aviation details</Text>
              <Pressable style={styles.closeButton} onPress={() => setDetailsVisible(false)} {...accessibleButton({ label: "Close Aviation Details" })}>
                <LocalFlightIcon name="close" size={21} color={appearance.text} />
              </Pressable>
            </View>
            {details}
          </SafeAreaView>
        </Modal>
      ) : null}
    </>
  );
}

function makeStyles(a: MobileAppearance, layoutClass: LayoutWidthClass) {
  const expanded = layoutClass === "expanded" || layoutClass === "large";
  return StyleSheet.create({
    content: { width: "100%", maxWidth: 1220, alignSelf: "center", paddingHorizontal: expanded ? 30 : 16, paddingTop: expanded ? 26 : 17 },
    titleRow: { flexDirection: "row", alignItems: "flex-start", gap: 14, marginBottom: 14 },
    titleCopy: { flex: 1 },
    eyebrow: { color: a.textMuted, fontSize: 13, marginBottom: 4 },
    title: { color: a.text, fontSize: expanded ? 34 : 28, lineHeight: expanded ? 40 : 34, fontWeight: "700" },
    subtitle: { color: a.textMuted, fontSize: 14, marginTop: 5 },
    detailsButton: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 7, paddingHorizontal: 13, borderRadius: 15, backgroundColor: `${a.blue}12` },
    detailsButtonText: { color: a.blue, fontSize: 13, fontWeight: "600" },
    errorCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 18, backgroundColor: `${a.red}12`, marginBottom: 12 },
    errorCopy: { flex: 1 },
    errorTitle: { color: a.text, fontSize: 14, fontWeight: "700" },
    errorBody: { color: a.textMuted, fontSize: 13, lineHeight: 18, marginTop: 2 },
    scopeGrid: { flexDirection: expanded ? "row" : "column", alignItems: "flex-start", gap: 16 },
    scopeColumn: { flex: 1, width: "100%", position: "relative" },
    quietOverlay: { position: "absolute", zIndex: 5, top: 13, right: 13, flexDirection: "row", gap: 6 },
    overlayPill: { paddingHorizontal: 9, paddingVertical: 5, borderRadius: 10, backgroundColor: `${a.bg}D9` },
    overlayLabel: { color: a.textMuted, fontSize: 11, fontWeight: "600" },
    inspector: { width: expanded ? 330 : "100%", backgroundColor: a.shell, borderRadius: 22, overflow: "hidden" },
    weatherCard: { minHeight: 68, flexDirection: "row", alignItems: "center", gap: 12, padding: 13, borderRadius: 19, backgroundColor: a.shell, marginTop: 12 },
    weatherIcon: { width: 42, height: 42, alignItems: "center", justifyContent: "center", borderRadius: 14, backgroundColor: `${a.blue}12` },
    weatherCopy: { flex: 1, minWidth: 0 },
    weatherTitle: { color: a.text, fontSize: 14, fontWeight: "700" },
    weatherMeta: { color: a.textMuted, fontSize: 12, lineHeight: 17, marginTop: 3 },
    weatherTemperature: { color: a.text, fontSize: 21, fontWeight: "700", fontVariant: ["tabular-nums"] },
    trackHeading: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 20, marginBottom: 9 },
    trackTitle: { color: a.text, fontSize: 18, fontWeight: "700" },
    trackHint: { color: a.textMuted, fontSize: 12 },
    trackRow: { minHeight: 76, flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 14, paddingVertical: 11, borderRadius: 17, backgroundColor: a.shell },
    pressed: { opacity: 0.74, transform: [{ scale: 0.995 }] },
    trackDot: { width: 9, height: 9, borderRadius: 5 },
    trackIdentity: { flex: 1.25, minWidth: 0 },
    callsign: { color: a.text, fontSize: 15, fontFamily: BOARD_FONT_FAMILY, fontWeight: "700" },
    route: { color: a.textMuted, fontSize: 12, marginTop: 4 },
    trackMotion: { flex: 0.9, alignItems: "flex-end" },
    motionPrimary: { color: a.text, fontSize: 13, fontFamily: BOARD_FONT_FAMILY },
    motionSecondary: { color: a.textMuted, fontSize: 12, marginTop: 3 },
    trackState: { flex: 0.9, alignItems: "flex-end" },
    phase: { fontSize: 12, fontWeight: "700", textAlign: "right" },
    boardStatus: { color: a.textDim, fontSize: 11, marginTop: 3, textAlign: "right" },
    separator: { height: 7 },
    empty: { alignItems: "center", paddingVertical: 50, paddingHorizontal: 20 },
    emptyTitle: { color: a.text, fontSize: 18, fontWeight: "700", marginTop: 13 },
    emptyBody: { color: a.textMuted, fontSize: 14, lineHeight: 20, textAlign: "center", marginTop: 5, maxWidth: 390 },
    sheetSafe: { flex: 1, backgroundColor: a.bg },
    sheetHeader: { height: 58, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 18, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: a.line },
    sheetHeaderTitle: { color: a.text, fontSize: 17, fontWeight: "700" },
    closeButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: 15, backgroundColor: a.lineSoft },
    detailsBody: { padding: 18 },
    detailsHeading: { color: a.text, fontSize: 20, fontWeight: "700" },
    detailsIntro: { color: a.textMuted, fontSize: 13, lineHeight: 19, marginTop: 5 },
    detailsSectionTitle: { color: a.text, fontSize: 14, fontWeight: "700", marginTop: 21, marginBottom: 8 },
    layerRow: { minHeight: 61, flexDirection: "row", alignItems: "center", gap: 11, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: a.lineSoft },
    layerCheck: { width: 24, height: 24, borderRadius: 8, borderWidth: 1, borderColor: a.line, alignItems: "center", justifyContent: "center" },
    layerCheckSelected: { backgroundColor: a.blue, borderColor: a.blue },
    layerCopy: { flex: 1 },
    layerTitle: { color: a.text, fontSize: 14, fontWeight: "600" },
    layerDetail: { color: a.textMuted, fontSize: 12, lineHeight: 17, marginTop: 2 },
    sourceCard: { backgroundColor: a.bg, borderRadius: 16, padding: 13, gap: 10 },
    sourceRow: { flexDirection: "row", justifyContent: "space-between", gap: 12 },
    sourceLabel: { color: a.textMuted, fontSize: 12 },
    sourceValue: { color: a.text, fontSize: 12, fontWeight: "600", maxWidth: "54%", textAlign: "right" },
    groundNote: { color: a.amber, fontSize: 12, lineHeight: 17, marginTop: 10 },
    informationalNote: { color: a.textDim, fontSize: 11, lineHeight: 16, marginTop: 22 }
  });
}
