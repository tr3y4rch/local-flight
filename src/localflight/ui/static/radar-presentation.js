(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.LocalFlightRadarPresentation = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const VERSION = 1;
  const REVOLUTION_MS = 15000;
  const FRAME_INTERVAL_MS = 80;
  const TRAIL_DEGREES = 72;
  const FLASH_DEGREES = 6;
  const FOCUSED_MIN_OPACITY = 0.86;
  const INTERACTIVE_MIN_OPACITY = 0.08;
  const PHASE_PRIORITY = {
    final: 700,
    approach: 600,
    departing: 500,
    descending: 400,
    enroute: 300,
    unknown: 250,
    taxi: 200,
    on_ground: 100,
  };

  function normalizeAngle(value) {
    const angle = Number(value) % 360;
    return angle < 0 ? angle + 360 : angle;
  }

  function sweepAngleAfter(startAngle, elapsedMs) {
    return normalizeAngle(Number(startAngle) + Math.max(0, Number(elapsedMs)) * 360 / REVOLUTION_MS);
  }

  function bearingFromOffset(xNm, yNm) {
    return normalizeAngle(Math.atan2(Number(xNm), Number(yNm)) * 180 / Math.PI);
  }

  function angularAge(sweepAngle, targetBearing) {
    return normalizeAngle(Number(sweepAngle) - Number(targetBearing));
  }

  function blipOpacity(targetBearing, sweepAngle, focused) {
    const age = angularAge(sweepAngle, targetBearing);
    let opacity = 0;
    if (age <= FLASH_DEGREES) opacity = 1;
    else if (age < TRAIL_DEGREES) opacity = 1 - ((age - FLASH_DEGREES) / (TRAIL_DEGREES - FLASH_DEGREES));
    if (focused) opacity = Math.max(opacity, FOCUSED_MIN_OPACITY);
    return Math.max(0, Math.min(1, opacity));
  }

  function normalizePhase(blip) {
    let phase = String(blip?.radar_phase || blip?.radar_status || "").trim().toLowerCase().replace(/[ -]/g, "_");
    if (["final", "approach", "departing", "descending", "enroute", "taxi", "on_ground"].includes(phase)) return phase;
    if (["arrival", "arriving", "landing"].includes(phase)) return "approach";
    if (["departure", "climb", "climbing"].includes(phase)) return "departing";
    if (["descent", "descend"].includes(phase)) return "descending";
    if (["airborne", "cruise", "cruising"].includes(phase)) return "enroute";
    if (["ground", "surface", "parked", "gate"].includes(phase) || blip?.on_ground === true) return "on_ground";
    return "unknown";
  }

  function isStale(blip) {
    const quality = [blip?.source_quality, blip?.track_freshness, blip?.freshness, blip?.radar_quality].filter(Boolean).join(" ");
    return /\b(stale|lost|missing|invalid|expired)\b/i.test(quality);
  }

  function toneRole(blip) {
    if (isStale(blip)) return "stale";
    const phase = normalizePhase(blip);
    if (["on_ground", "taxi"].includes(phase)) return "ground";
    if (phase === "departing") return "departure";
    if (["approach", "final"].includes(phase)) return "approach";
    return "accent";
  }

  function targetShape(blip) {
    if (isStale(blip)) return "hollow";
    return ["on_ground", "taxi"].includes(normalizePhase(blip)) ? "diamond" : "dot";
  }

  function phaseLabel(blip) {
    return {
      on_ground: "GROUND",
      taxi: "TAXI",
      departing: "DEP",
      enroute: "EN ROUTE",
      descending: "DESC",
      approach: "APPROACH",
      final: "FINAL",
      unknown: "",
    }[normalizePhase(blip)];
  }

  function labelPriority(blip, focused) {
    const distance = Number.isFinite(Number(blip?.distance_nm)) ? Number(blip.distance_nm) : 10000;
    return [focused ? 10000 : PHASE_PRIORITY[normalizePhase(blip)], isStale(blip) ? 0 : 1, -distance];
  }

  function isInteractive(targetBearing, sweepAngle, focused) {
    return blipOpacity(targetBearing, sweepAngle, focused) >= INTERACTIVE_MIN_OPACITY;
  }

  return {
    VERSION,
    REVOLUTION_MS,
    FRAME_INTERVAL_MS,
    TRAIL_DEGREES,
    FLASH_DEGREES,
    FOCUSED_MIN_OPACITY,
    INTERACTIVE_MIN_OPACITY,
    normalizeAngle,
    sweepAngleAfter,
    bearingFromOffset,
    angularAge,
    blipOpacity,
    normalizePhase,
    isStale,
    toneRole,
    targetShape,
    phaseLabel,
    labelPriority,
    isInteractive,
  };
});
