import type { RadarBlip } from "../api/types";
import type { ProjectedBlip } from "./types";

export type ProjectedRadarPoint = {
  x: number;
  y: number;
  distanceNm: number;
};

export function normalizeRadarCoordinatePair(
  point: number[],
  center: { lat: number; lon: number }
): { lat: number; lon: number } | null {
  if (point.length < 2) return null;
  const first = Number(point[0]);
  const second = Number(point[1]);
  if (!Number.isFinite(first) || !Number.isFinite(second)) return null;
  const candidates = [
    { lat: first, lon: second },
    { lat: second, lon: first }
  ].filter(({ lat, lon }) => Math.abs(lat) <= 90 && Math.abs(lon) <= 180);
  if (!candidates.length) return null;
  return candidates.sort((left, right) => {
    const leftDistance = (left.lat - center.lat) ** 2 + ((left.lon - center.lon) * Math.cos(center.lat * Math.PI / 180)) ** 2;
    const rightDistance = (right.lat - center.lat) ** 2 + ((right.lon - center.lon) * Math.cos(center.lat * Math.PI / 180)) ** 2;
    return leftDistance - rightDistance;
  })[0] || null;
}

export function projectLatLonToScope(
  lat: number,
  lon: number,
  center: { lat: number; lon: number },
  radiusNm: number,
  scopeSize: number
): ProjectedRadarPoint | null {
  const latDeltaNm = (lat - center.lat) * 60;
  const lonDeltaNm =
    (lon - center.lon) * 60 * Math.cos((center.lat * Math.PI) / 180);
  const distanceNm = Math.sqrt(latDeltaNm ** 2 + lonDeltaNm ** 2);

  if (!Number.isFinite(distanceNm) || !Number.isFinite(radiusNm) || radiusNm <= 0) {
    return null;
  }

  const usableRadiusPx = scopeSize * 0.42;
  const x = scopeSize / 2 + (lonDeltaNm / radiusNm) * usableRadiusPx;
  const y = scopeSize / 2 - (latDeltaNm / radiusNm) * usableRadiusPx;

  return { x, y, distanceNm };
}

export function projectBlip(
  blip: RadarBlip,
  center: { lat: number; lon: number },
  radiusNm: number,
  scopeSize: number
): ProjectedBlip | null {
  const projected = projectLatLonToScope(blip.lat, blip.lon, center, radiusNm, scopeSize);

  if (!projected || projected.distanceNm > radiusNm) {
    return null;
  }

  const dotOffset = 5;
  const angleDeg = (Math.atan2(
    projected.x - scopeSize / 2,
    scopeSize / 2 - projected.y
  ) * 180 / Math.PI + 360) % 360;

  return {
    blip,
    left: projected.x - dotOffset,
    top: projected.y - dotOffset,
    distanceNm: projected.distanceNm,
    angleDeg
  };
}
