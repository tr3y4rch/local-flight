import type { RadarBlip } from "../api/types";
import type { ProjectedBlip } from "./types";

export function projectBlip(
  blip: RadarBlip,
  center: { lat: number; lon: number },
  radiusNm: number,
  scopeSize: number
): ProjectedBlip | null {
  const latDeltaNm = (blip.lat - center.lat) * 60;
  const lonDeltaNm =
    (blip.lon - center.lon) * 60 * Math.cos((center.lat * Math.PI) / 180);
  const distanceNm = Math.sqrt(latDeltaNm ** 2 + lonDeltaNm ** 2);

  if (!Number.isFinite(distanceNm) || distanceNm > radiusNm) {
    return null;
  }

  const usableRadiusPx = scopeSize * 0.42;
  const dotOffset = 5;
  const x = scopeSize / 2 + (lonDeltaNm / radiusNm) * usableRadiusPx - dotOffset;
  const y = scopeSize / 2 - (latDeltaNm / radiusNm) * usableRadiusPx - dotOffset;

  return { blip, left: x, top: y, distanceNm };
}
