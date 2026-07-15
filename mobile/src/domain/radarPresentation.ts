import type { RadarBlip } from "../api/types";
import type { MobileAppearance } from "../theme/tokens";

export const RADAR_PRESENTATION_VERSION = 1;
export const RADAR_REVOLUTION_MS = 15_000;
export const RADAR_FRAME_INTERVAL_MS = 80;
export const RADAR_TRAIL_DEGREES = 72;
export const RADAR_FLASH_DEGREES = 6;
export const RADAR_FOCUSED_MIN_OPACITY = 0.86;
export const RADAR_INTERACTIVE_MIN_OPACITY = 0.08;

const PHASE_PRIORITY: Record<RadarPresentationPhase, number> = {
  final: 700,
  approach: 600,
  departing: 500,
  descending: 400,
  enroute: 300,
  unknown: 250,
  taxi: 200,
  on_ground: 100
};

export type RadarPresentationPhase = "final" | "approach" | "departing" | "descending" | "enroute" | "taxi" | "on_ground" | "unknown";
export type RadarTargetShape = "dot" | "diamond" | "hollow";

export function normalizeRadarAngle(value: number): number {
  const angle = value % 360;
  return angle < 0 ? angle + 360 : angle;
}

export function radarSweepAngleAfter(startAngle: number, elapsedMs: number): number {
  return normalizeRadarAngle(startAngle + Math.max(0, elapsedMs) * 360 / RADAR_REVOLUTION_MS);
}

export function radarBearingFromOffset(x: number, yNorth: number): number {
  return normalizeRadarAngle(Math.atan2(x, yNorth) * 180 / Math.PI);
}

export function radarAngularAge(sweepAngle: number, targetBearing: number): number {
  return normalizeRadarAngle(sweepAngle - targetBearing);
}

export function radarSweepOpacity(targetBearing: number, sweepAngle: number, focused = false): number {
  const age = radarAngularAge(sweepAngle, targetBearing);
  let opacity = 0;
  if (age <= RADAR_FLASH_DEGREES) {
    opacity = 1;
  } else if (age < RADAR_TRAIL_DEGREES) {
    opacity = 1 - ((age - RADAR_FLASH_DEGREES) / (RADAR_TRAIL_DEGREES - RADAR_FLASH_DEGREES));
  }
  return Math.max(0, Math.min(1, focused ? Math.max(opacity, RADAR_FOCUSED_MIN_OPACITY) : opacity));
}

export function normalizeRadarPhase(blip: RadarBlip): RadarPresentationPhase {
  const raw = String(blip.radar_phase || blip.radar_status || "").trim().toLowerCase().replace(/[ -]/g, "_");
  if (["final", "approach", "departing", "descending", "enroute", "taxi", "on_ground"].includes(raw)) {
    return raw as RadarPresentationPhase;
  }
  if (["arrival", "arriving", "landing"].includes(raw)) return "approach";
  if (["departure", "climb", "climbing"].includes(raw)) return "departing";
  if (["descent", "descend"].includes(raw)) return "descending";
  if (["airborne", "cruise", "cruising"].includes(raw)) return "enroute";
  if (["ground", "surface", "parked", "gate"].includes(raw) || blip.on_ground === true) return "on_ground";
  return "unknown";
}

export function radarTargetIsStale(blip: RadarBlip): boolean {
  const quality = String(blip.source_quality || "");
  return blip.position_stale === true || /\b(stale|lost|missing|invalid|expired)\b/i.test(quality);
}

export function radarTargetTone(blip: RadarBlip, palette: MobileAppearance): string {
  if (radarTargetIsStale(blip)) return palette.textMuted;
  const phase = normalizeRadarPhase(blip);
  if (phase === "on_ground" || phase === "taxi") return palette.amber;
  if (phase === "departing") return palette.blue;
  if (phase === "approach" || phase === "final") return palette.green;
  return palette.blue2;
}

export function radarTargetShape(blip: RadarBlip): RadarTargetShape {
  if (radarTargetIsStale(blip)) return "hollow";
  const phase = normalizeRadarPhase(blip);
  return phase === "on_ground" || phase === "taxi" ? "diamond" : "dot";
}

export function radarPhaseLabel(blip: RadarBlip): string {
  return {
    on_ground: "GROUND",
    taxi: "TAXI",
    departing: "DEP",
    enroute: "EN ROUTE",
    descending: "DESC",
    approach: "APPROACH",
    final: "FINAL",
    unknown: ""
  }[normalizeRadarPhase(blip)];
}

export function radarLabelPriority(blip: RadarBlip, focused = false): [number, number, number] {
  const distance = Number.isFinite(Number(blip.distance_nm)) ? Number(blip.distance_nm) : 10_000;
  return [focused ? 10_000 : PHASE_PRIORITY[normalizeRadarPhase(blip)], radarTargetIsStale(blip) ? 0 : 1, -distance];
}

export function compareRadarPriority(left: [number, number, number], right: [number, number, number]): number {
  for (let index = 0; index < left.length; index += 1) {
    const delta = left[index]! - right[index]!;
    if (delta) return delta;
  }
  return 0;
}
