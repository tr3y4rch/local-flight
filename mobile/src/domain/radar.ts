import type { RadarBlip } from "../api/types";
import type { ProjectedBlip } from "./types";

export type ProjectedRadarPoint = {
  x: number;
  y: number;
  distanceNm: number;
};

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
