import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, Pressable, StyleSheet, View } from "react-native";
import Svg, { Circle, ClipPath, Defs, G, Line, Path, Polygon, Polyline } from "react-native-svg";

import { accessibleButton, tapTargetHitSlop, useReducedMotionPreference } from "../accessibility/mobileA11y";
import type { RadarBlip, RadarMapFeature, RadarMapResponse, RadarResponse } from "../api/types";
import { V2Text as Text } from "../components/V2Text";
import {
  RADAR_FRAME_INTERVAL_MS,
  RADAR_INTERACTIVE_MIN_OPACITY,
  RADAR_TRAIL_DEGREES,
  radarPhaseLabel,
  radarSweepAngleAfter,
  radarSweepOpacity,
  radarTargetShape,
  radarTargetTone
} from "../domain/radarPresentation";
import { projectBlip, projectLatLonToScope, type ProjectedRadarPoint } from "../domain/radar";
import type { RadarRadius } from "../domain/types";
import type { MobileRadarDrawingLayers } from "../storage/settings";
import { useMobileTheme } from "../theme/runtime";
import { BOARD_BOLD_FONT_FAMILY, BOARD_FONT_FAMILY, type MobileAppearance } from "../theme/tokens";

type FeatureLayer = "terrain" | "map" | "surface" | "runway";

export type RadarScopeV2Props = {
  data: RadarResponse | null;
  groundData: RadarMapResponse | null;
  groundError: string | null;
  radiusNm: RadarRadius;
  radiusOptions: RadarRadius[];
  drawingLayers: MobileRadarDrawingLayers;
  onRadiusChange: (value: RadarRadius) => void;
  onOpenDetail: (callsign: string, blip?: RadarBlip) => void;
};

function featurePoints(
  feature: RadarMapFeature,
  center: RadarMapResponse["center"],
  radiusNm: number,
  scopeSize: number
): ProjectedRadarPoint[] {
  return (feature.points || [])
    .map((point) => {
      const lat = Number(point[0]);
      const lon = Number(point[1]);
      return Number.isFinite(lat) && Number.isFinite(lon)
        ? projectLatLonToScope(lat, lon, center, radiusNm, scopeSize)
        : null;
    })
    .filter((point): point is ProjectedRadarPoint => Boolean(point));
}

function drawable(features: RadarMapFeature[] | undefined): RadarMapFeature[] {
  return (features || []).filter((feature) => Array.isArray(feature.points) && feature.points.length >= 2);
}

function visibleFeatures(
  features: RadarMapFeature[] | undefined,
  center: RadarMapResponse["center"],
  radiusNm: number,
  scopeSize: number
): Array<{ feature: RadarMapFeature; points: ProjectedRadarPoint[] }> {
  return drawable(features)
    .map((feature) => ({ feature, points: featurePoints(feature, center, radiusNm, scopeSize) }))
    .filter(({ points }) => points.length >= 2 && points.some((point) => point.distanceNm <= radiusNm * 1.08));
}

function groundStatus(
  groundData: RadarMapResponse | null,
  groundError: string | null,
  visibleSurfaceCount: number,
  visibleContextCount: number,
  radiusNm: number
): "Airport surface ready" | "Surface loading" | "Geographic context only" {
  const state = String(groundData?.sources?.surface_cache_state || "").toLowerCase();
  const source = String(groundData?.sources?.surface || "").toLowerCase();
  const coverage = Number(groundData?.coverage_radius_nm || groundData?.radius_nm || 0);
  const surfaceCoverageReady = coverage <= 0 || coverage + 0.05 >= Math.min(radiusNm, 5);
  if (visibleSurfaceCount > 0 && surfaceCoverageReady && !["miss", "preparing", "queued", "error"].includes(state)) {
    return "Airport surface ready";
  }
  if (visibleContextCount > 0 || state === "disabled" || source === "none" || Boolean(groundError && groundData)) {
    return "Geographic context only";
  }
  return "Surface loading";
}

function paint(a: MobileAppearance, feature: RadarMapFeature, layer: FeatureLayer, radiusNm: number) {
  const kind = String(feature.kind || "").toLowerCase();
  if (layer === "terrain") return { fill: kind.includes("band") ? `${a.green}0D` : "none", stroke: `${a.green}24`, width: 0.7 };
  if (layer === "map") return { fill: kind === "water" ? `${a.blue}12` : "none", stroke: `${a.textDim}30`, width: radiusNm <= 5 ? 0.9 : 0.55 };
  if (layer === "runway") return { fill: "none", stroke: `${a.text}B8`, width: radiusNm <= 5 ? 3.2 : 1.8 };
  if (["apron", "terminal", "building"].includes(kind)) return { fill: `${a.blue2}14`, stroke: `${a.blue2}4D`, width: 1.1 };
  return { fill: "none", stroke: `${a.green}59`, width: radiusNm <= 5 ? 1.45 : 0.9 };
}

function GroundFeature({
  item,
  layer,
  appearance,
  radiusNm
}: {
  item: { feature: RadarMapFeature; points: ProjectedRadarPoint[] };
  layer: FeatureLayer;
  appearance: MobileAppearance;
  radiusNm: number;
}) {
  const points = item.points.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
  const colors = paint(appearance, item.feature, layer, radiusNm);
  const polygon = Boolean(item.feature.closed && item.points.length >= 3 && layer !== "runway");
  return polygon
    ? <Polygon points={points} fill={colors.fill} stroke={colors.stroke} strokeWidth={colors.width} strokeLinejoin="round" />
    : <Polyline points={points} fill="none" stroke={colors.stroke} strokeWidth={colors.width} strokeLinecap="round" strokeLinejoin="round" />;
}

function sweepSectorPath(size: number, startDeg: number, endDeg: number): string {
  const center = size / 2;
  const radius = size * 0.44;
  const point = (degrees: number) => {
    const radians = (degrees - 90) * Math.PI / 180;
    return { x: center + radius * Math.cos(radians), y: center + radius * Math.sin(radians) };
  };
  const start = point(startDeg);
  const end = point(endDeg);
  return `M ${center} ${center} L ${start.x} ${start.y} A ${radius} ${radius} 0 0 1 ${end.x} ${end.y} Z`;
}

export function RadarScopeV2(props: RadarScopeV2Props) {
  const { appearance } = useMobileTheme();
  const styles = useMemo(() => makeStyles(appearance), [appearance]);
  const reduceMotion = useReducedMotionPreference();
  const [scopeSize, setScopeSize] = useState(320);
  const [sweepDeg, setSweepDeg] = useState(0);
  const [selectedKey, setSelectedKey] = useState("");
  const pinchRef = useRef<{ distance: number; index: number } | null>(null);

  useEffect(() => {
    if (reduceMotion) {
      setSweepDeg(0);
      return;
    }
    let active = AppState.currentState === "active";
    let previous = Date.now();
    const timer = setInterval(() => {
      const now = Date.now();
      if (active) setSweepDeg((value) => radarSweepAngleAfter(value, now - previous));
      previous = now;
    }, RADAR_FRAME_INTERVAL_MS);
    const subscription = AppState.addEventListener("change", (state) => {
      active = state === "active";
      previous = Date.now();
    });
    return () => {
      clearInterval(timer);
      subscription.remove();
    };
  }, [reduceMotion]);

  const groundCenter = props.groundData?.center || null;
  const runways = groundCenter && props.drawingLayers.runways
    ? visibleFeatures(props.groundData?.runways, groundCenter, props.radiusNm, scopeSize)
    : [];
  const surface = groundCenter && props.drawingLayers.surface
    ? visibleFeatures(props.groundData?.surface_features, groundCenter, props.radiusNm, scopeSize)
    : [];
  const map = groundCenter && props.drawingLayers.surface
    ? visibleFeatures(props.groundData?.map_features, groundCenter, props.radiusNm, scopeSize)
    : [];
  const terrain = groundCenter && props.drawingLayers.terrain
    ? visibleFeatures(props.groundData?.terrain?.features, groundCenter, props.radiusNm, scopeSize)
    : [];
  const status = groundStatus(props.groundData, props.groundError, runways.length + surface.length, map.length + terrain.length, props.radiusNm);

  const projected = (props.data?.blips || [])
    .map((blip, index) => {
      const item = props.data ? projectBlip(blip, props.data.center, props.radiusNm, scopeSize) : null;
      if (!item) return null;
      const key = `${blip.icao24 || blip.callsign}-${index}`;
      const focused = key === selectedKey;
      const opacity = reduceMotion ? 1 : radarSweepOpacity(item.angleDeg, sweepDeg, focused);
      return { item, key, focused, opacity };
    })
    .filter((item): item is NonNullable<typeof item> => Boolean(item));
  const visibleLabelKeys = new Set<string>();
  const occupiedLabels: Array<{ x: number; y: number; width: number; height: number }> = [];
  for (const candidate of [...projected].sort((left, right) => left.item.distanceNm - right.item.distanceNm)) {
    if (!candidate.focused && candidate.opacity <= 0.72) continue;
    const callsign = String(candidate.item.blip.callsign || "").trim();
    if (!callsign) continue;
    const rect = {
      x: candidate.item.left + 14,
      y: candidate.item.top - 4,
      width: Math.min(90, Math.max(48, callsign.length * 7)),
      height: 17
    };
    const outside = rect.x + rect.width > scopeSize - 5 || rect.y < 4 || rect.y + rect.height > scopeSize - 5;
    const collides = occupiedLabels.some((other) => (
      rect.x < other.x + other.width
      && rect.x + rect.width > other.x
      && rect.y < other.y + other.height
      && rect.y + rect.height > other.y
    ));
    if ((outside || collides) && !candidate.focused) continue;
    occupiedLabels.push(rect);
    visibleLabelKeys.add(candidate.key);
    if (visibleLabelKeys.size >= 10) break;
  }

  useEffect(() => {
    if (selectedKey && !projected.some((item) => item.key === selectedKey)) setSelectedKey("");
  }, [projected, selectedKey]);

  const measure = useCallback((width: number) => {
    const next = Math.max(240, Math.min(720, width - 20));
    setScopeSize((current) => Math.abs(current - next) > 1 ? next : current);
  }, []);

  const pinchStart = (touches: Array<{ pageX: number; pageY: number }>) => {
    if (touches.length < 2 || !touches[0] || !touches[1]) {
      pinchRef.current = null;
      return;
    }
    pinchRef.current = {
      distance: Math.hypot(touches[1].pageX - touches[0].pageX, touches[1].pageY - touches[0].pageY),
      index: props.radiusOptions.indexOf(props.radiusNm)
    };
  };
  const pinchMove = (touches: Array<{ pageX: number; pageY: number }>) => {
    if (touches.length < 2 || !touches[0] || !touches[1] || !pinchRef.current) return;
    const distance = Math.hypot(touches[1].pageX - touches[0].pageX, touches[1].pageY - touches[0].pageY);
    const ratio = distance / Math.max(1, pinchRef.current.distance);
    const delta = ratio > 1.14 ? 1 : ratio < 0.88 ? -1 : 0;
    const nextIndex = Math.max(0, Math.min(props.radiusOptions.length - 1, pinchRef.current.index + delta));
    if (delta && nextIndex !== pinchRef.current.index) {
      props.onRadiusChange(props.radiusOptions[nextIndex]!);
      pinchRef.current = { distance, index: nextIndex };
    }
  };

  return (
    <View style={styles.card} onLayout={(event) => measure(event.nativeEvent.layout.width)}>
      <Text style={styles.scopeTitle}>Radar scope</Text>
      <View
        style={[styles.frame, { width: scopeSize, height: scopeSize }]}
        accessibilityLabel={`Radar scope, ${props.radiusNm} nautical mile range, ${projected.length} aircraft in range.`}
        onTouchStart={(event) => pinchStart(event.nativeEvent.touches as Array<{ pageX: number; pageY: number }>)}
        onTouchMove={(event) => pinchMove(event.nativeEvent.touches as Array<{ pageX: number; pageY: number }>)}
        onTouchEnd={() => { pinchRef.current = null; }}
        onTouchCancel={() => { pinchRef.current = null; }}
      >
        <Svg width={scopeSize} height={scopeSize} viewBox={`0 0 ${scopeSize} ${scopeSize}`} style={StyleSheet.absoluteFill}>
          <Defs><ClipPath id="v2-radar-clip"><Circle cx={scopeSize / 2} cy={scopeSize / 2} r={scopeSize * 0.44} /></ClipPath></Defs>
          <G clipPath="url(#v2-radar-clip)">
            {terrain.map((item, index) => <GroundFeature key={`terrain-${index}`} item={item} layer="terrain" appearance={appearance} radiusNm={props.radiusNm} />)}
            {map.map((item, index) => <GroundFeature key={`map-${index}`} item={item} layer="map" appearance={appearance} radiusNm={props.radiusNm} />)}
            {surface.map((item, index) => <GroundFeature key={`surface-${index}`} item={item} layer="surface" appearance={appearance} radiusNm={props.radiusNm} />)}
            {runways.map((item, index) => <GroundFeature key={`runway-${index}`} item={item} layer="runway" appearance={appearance} radiusNm={props.radiusNm} />)}
            {!reduceMotion ? (
              <G transform={`rotate(${sweepDeg} ${scopeSize / 2} ${scopeSize / 2})`}>
                <Path d={sweepSectorPath(scopeSize, -RADAR_TRAIL_DEGREES, 0)} fill={`${appearance.blue2}18`} />
                <Line x1={scopeSize / 2} y1={scopeSize / 2} x2={scopeSize / 2} y2={scopeSize * 0.06} stroke={`${appearance.blue2}C0`} strokeWidth={1.5} />
              </G>
            ) : null}
          </G>
          <Circle cx={scopeSize / 2} cy={scopeSize / 2} r={scopeSize * 0.44} fill="none" stroke={appearance.line} strokeWidth={1.5} />
          <Circle cx={scopeSize / 2} cy={scopeSize / 2} r={scopeSize * 0.29} fill="none" stroke={appearance.lineSoft} strokeWidth={1} />
          <Circle cx={scopeSize / 2} cy={scopeSize / 2} r={scopeSize * 0.145} fill="none" stroke={appearance.lineSoft} strokeWidth={1} />
          <Line x1={scopeSize / 2} y1={scopeSize * 0.06} x2={scopeSize / 2} y2={scopeSize * 0.94} stroke={appearance.lineSoft} strokeWidth={1} />
          <Line x1={scopeSize * 0.06} y1={scopeSize / 2} x2={scopeSize * 0.94} y2={scopeSize / 2} stroke={appearance.lineSoft} strokeWidth={1} />
        </Svg>

        {projected.map(({ item, key, focused, opacity }) => {
          const tone = radarTargetTone(item.blip, appearance);
          const shape = radarTargetShape(item.blip);
          const interactive = opacity >= RADAR_INTERACTIVE_MIN_OPACITY;
          return (
            <Pressable
              key={key}
              pointerEvents={interactive ? "auto" : "none"}
              style={[styles.targetWrap, { left: item.left, top: item.top, opacity }]}
              onPress={() => {
                setSelectedKey(key);
                props.onOpenDetail(item.blip.callsign, item.blip);
              }}
              {...accessibleButton({ label: `${item.blip.callsign}, ${radarPhaseLabel(item.blip) || "tracked aircraft"}. Opens aircraft details.` })}
            >
              <View style={[
                styles.target,
                { backgroundColor: shape === "hollow" ? "transparent" : tone, borderColor: tone },
                shape === "diamond" && styles.targetDiamond,
                shape === "hollow" && styles.targetHollow,
                focused && styles.targetFocused
              ]} />
              {visibleLabelKeys.has(key) ? <Text style={styles.targetLabel} numberOfLines={1}>{item.blip.callsign}</Text> : null}
            </Pressable>
          );
        })}
        <View style={styles.centerDot} />
      </View>

      <View style={styles.footer}>
        <Text style={styles.hint}>Pinch to zoom or choose a range below.</Text>
        <Text style={[styles.groundStatus, status === "Surface loading" && styles.groundLoading]}>{status}</Text>
        <View style={styles.chips}>
          {props.radiusOptions.map((radius) => (
            <Pressable
              key={radius}
              style={[styles.chip, radius === props.radiusNm && styles.chipActive]}
              hitSlop={tapTargetHitSlop}
              onPress={() => props.onRadiusChange(radius)}
              {...accessibleButton({ label: `Set radar range to ${radius} nautical miles`, selected: radius === props.radiusNm })}
            >
              <Text style={[styles.chipText, radius === props.radiusNm && styles.chipTextActive]}>{radius} NM</Text>
            </Pressable>
          ))}
        </View>
      </View>
    </View>
  );
}

function makeStyles(a: MobileAppearance) {
  return StyleSheet.create({
    card: { width: "100%", alignItems: "center", borderRadius: 22, backgroundColor: a.row, paddingHorizontal: 10, paddingTop: 14, paddingBottom: 16, overflow: "hidden" },
    scopeTitle: { width: "100%", color: a.blue2, fontSize: 12, lineHeight: 17, fontWeight: "700", paddingHorizontal: 4, marginBottom: 8 },
    frame: { position: "relative", borderRadius: 999, backgroundColor: `${a.bg}B8`, overflow: "hidden" },
    targetWrap: { position: "absolute", width: 12, height: 12, zIndex: 3 },
    target: { width: 10, height: 10, borderRadius: 6, borderWidth: 1 },
    targetDiamond: { borderRadius: 2, transform: [{ rotate: "45deg" }] },
    targetHollow: { borderWidth: 2 },
    targetFocused: { borderWidth: 2.5, transform: [{ scale: 1.35 }] },
    targetLabel: { position: "absolute", left: 14, top: -4, minWidth: 74, color: a.text, fontFamily: BOARD_FONT_FAMILY, fontSize: 10, lineHeight: 14 },
    centerDot: { position: "absolute", left: "50%", top: "50%", width: 8, height: 8, marginLeft: -4, marginTop: -4, borderRadius: 5, backgroundColor: a.blue2, zIndex: 4 },
    footer: { width: "100%", paddingHorizontal: 4, paddingTop: 12 },
    hint: { color: a.textMuted, fontSize: 13, lineHeight: 18 },
    groundStatus: { color: a.green, fontSize: 12, lineHeight: 17, fontWeight: "700", marginTop: 5 },
    groundLoading: { color: a.amber },
    chips: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 },
    chip: { minWidth: 60, minHeight: 44, alignItems: "center", justifyContent: "center", borderRadius: 15, backgroundColor: a.lineSoft, paddingHorizontal: 12 },
    chipActive: { borderWidth: 1.5, borderColor: a.blue2, backgroundColor: `${a.blue2}10` },
    chipText: { color: a.textMuted, fontFamily: BOARD_FONT_FAMILY, fontSize: 12 },
    chipTextActive: { color: a.blue2, fontFamily: BOARD_BOLD_FONT_FAMILY }
  });
}
