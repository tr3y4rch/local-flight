from __future__ import annotations

from typing import Any

from .geo import distance_nm, float_or_none, heading_delta_deg, bearing_deg
from .normalize import enrich_blip_display_fields


def _is_ground(blip: dict[str, Any]) -> bool:
    if blip.get("on_ground") is True:
        return True
    altitude_ft = float_or_none(blip.get("altitude_ft"))
    if altitude_ft is None:
        altitude_m = float_or_none(blip.get("altitude_m"))
        altitude_ft = None if altitude_m is None else altitude_m * 3.28084
    speed_kt = float_or_none(blip.get("speed_kt"))
    if speed_kt is None:
        speed_ms = float_or_none(blip.get("speed_ms"))
        speed_kt = None if speed_ms is None else speed_ms * 1.94384
    if altitude_ft is not None and speed_kt is not None:
        return altitude_ft < 250 and speed_kt < 50
    return altitude_ft is not None and altitude_ft < 100


def _traffic_role(blip: dict[str, Any], airport_icao: str) -> str:
    airport = (airport_icao or "").strip().upper()
    dep = str(blip.get("departure_icao") or "").strip().upper()
    arr = str(blip.get("arrival_icao") or "").strip().upper()
    if airport and arr == airport:
        return "arrival"
    if airport and dep == airport:
        return "departure"
    if _is_ground(blip):
        return "ground"
    return "unknown"


def _motion_trend(vertical_fpm: float | None, speed_kt: float | None) -> tuple[str, str]:
    if vertical_fpm is None:
        return "unknown", "Motion unknown"
    if vertical_fpm > 500:
        return "climbing", "Climbing"
    if vertical_fpm < -500:
        return "descending", "Descending"
    if speed_kt is not None and speed_kt > 35:
        return "level", "Level"
    return "unknown", "Motion unknown"


def _runway_matches(blip: dict[str, Any], runways: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lat = float_or_none(blip.get("lat"))
    lon = float_or_none(blip.get("lon"))
    track = float_or_none(blip.get("track_deg", blip.get("heading")))
    if lat is None or lon is None or track is None:
        return []
    matches: list[dict[str, Any]] = []
    for runway in runways:
        endpoints = runway.get("endpoints") if isinstance(runway.get("endpoints"), list) else []
        if not endpoints:
            points = runway.get("points") if isinstance(runway.get("points"), list) else []
            if len(points) >= 2:
                endpoints = [
                    {"ident": str(runway.get("label") or "RWY"), "lat": points[0][0], "lon": points[0][1], "heading_deg": runway.get("heading_deg")},
                    {"ident": str(runway.get("label") or "RWY"), "lat": points[-1][0], "lon": points[-1][1], "heading_deg": runway.get("heading_deg")},
                ]
        for endpoint in endpoints:
            rlat = float_or_none(endpoint.get("lat"))
            rlon = float_or_none(endpoint.get("lon"))
            if rlat is None or rlon is None:
                continue
            inbound_heading = float_or_none(endpoint.get("heading_deg"))
            if inbound_heading is None:
                inbound_heading = bearing_deg(lat, lon, rlat, rlon)
            delta = heading_delta_deg(track, inbound_heading)
            threshold_distance = distance_nm(rlat, rlon, lat, lon)
            bearing_to_threshold = bearing_deg(lat, lon, rlat, rlon)
            inbound_delta = heading_delta_deg(track, bearing_to_threshold)
            if delta is None or inbound_delta is None:
                continue
            matches.append(
                {
                    "runway": str(endpoint.get("ident") or runway.get("label") or ""),
                    "label": str(runway.get("label") or endpoint.get("ident") or ""),
                    "alignment_deg": round(min(delta, inbound_delta), 1),
                    "distance_to_threshold_nm": round(threshold_distance, 2),
                    "confidence": runway.get("confidence") or "unknown",
                }
            )
    matches.sort(key=lambda item: (float(item["alignment_deg"]), float(item["distance_to_threshold_nm"])))
    return matches


def classify_blip(blip: dict[str, Any], *, airport_icao: str, runways: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    item = enrich_blip_display_fields(blip)
    role = _traffic_role(item, airport_icao)
    item["traffic_role"] = role

    altitude_ft = float_or_none(item.get("altitude_ft"))
    speed_kt = float_or_none(item.get("speed_kt"))
    vertical_fpm = float_or_none(item.get("vertical_rate_fpm"))
    distance = float_or_none(item.get("distance_nm"))
    ground = _is_ground(item)
    motion_trend, motion_label = _motion_trend(vertical_fpm, speed_kt)
    item["motion_trend"] = motion_trend
    item["motion_label"] = motion_label
    runway_matches = _runway_matches(item, runways or [])
    best_runway = runway_matches[0] if runway_matches else None

    phase = "unknown"
    label = "Unknown"
    confidence = "low"
    reason = "Not enough live data to classify this target."

    if ground:
        phase = "ground"
        label = "On ground"
        confidence = "high" if item.get("on_ground") is True else "medium"
        reason = "Ground flag or very low altitude/speed near the airport."
    elif role == "arrival" and best_runway and distance is not None:
        aligned = float(best_runway["alignment_deg"]) <= 18.0
        near_threshold = float(best_runway["distance_to_threshold_nm"]) <= 8.0
        plausible_alt = altitude_ft is None or altitude_ft <= 4500
        plausible_speed = speed_kt is None or 85 <= speed_kt <= 260
        descending = vertical_fpm is None or vertical_fpm <= 500
        if aligned and near_threshold and plausible_alt and plausible_speed and descending:
            phase = "final"
            label = "On final"
            confidence = "high" if vertical_fpm is not None and vertical_fpm < -200 else "medium"
            reason = f"Aligned with runway {best_runway['runway']} and inbound to threshold."
            item["matched_runway"] = best_runway["runway"]
            item["runway_alignment_deg"] = best_runway["alignment_deg"]
            item["distance_to_threshold_nm"] = best_runway["distance_to_threshold_nm"]
        elif distance <= 20.0 and (altitude_ft is None or altitude_ft <= 9000):
            phase = "approach"
            label = "On approach"
            confidence = "medium"
            reason = "Arrival traffic near the airport but not aligned enough for final."
    elif role == "arrival" and distance is not None and distance <= 20.0 and (altitude_ft is None or altitude_ft <= 9000):
        phase = "approach"
        label = "On approach"
        confidence = "low"
        reason = "Arrival traffic near the airport; runway match unavailable."
    elif role == "unknown" and best_runway and distance is not None:
        aligned = float(best_runway["alignment_deg"]) <= 18.0
        near_threshold = float(best_runway["distance_to_threshold_nm"]) <= 8.0
        plausible_alt = altitude_ft is None or altitude_ft <= 4500
        descending = vertical_fpm is not None and vertical_fpm <= -200
        if aligned and near_threshold and plausible_alt and descending:
            phase = "approach"
            label = "Approach"
            confidence = "low"
            reason = f"Aligned with runway {best_runway['runway']}, but route intent is unavailable."
            item["nearest_runway"] = best_runway["runway"]
            item["runway_alignment_deg"] = best_runway["alignment_deg"]
            item["distance_to_threshold_nm"] = best_runway["distance_to_threshold_nm"]
    elif role == "departure" and distance is not None and distance <= 20.0:
        phase = "departure"
        label = "Departing"
        confidence = "medium" if vertical_fpm is None or vertical_fpm > -200 else "low"
        reason = "Departure traffic moving within the terminal area."
    elif vertical_fpm is not None and vertical_fpm > 500:
        phase = "climb"
        label = "Climb"
        confidence = "medium"
        reason = f"Vertical rate {round(vertical_fpm):+d} fpm."
    elif vertical_fpm is not None and vertical_fpm < -500:
        phase = "descent"
        label = "Descent"
        confidence = "medium"
        reason = f"Vertical rate {round(vertical_fpm):+d} fpm."
    elif altitude_ft is not None and altitude_ft >= 10000 and (vertical_fpm is None or abs(vertical_fpm) <= 500):
        phase = "cruise"
        label = "Cruise"
        confidence = "medium"
        reason = "High altitude with no strong climb/descent trend."

    item["radar_phase"] = phase
    item["radar_status"] = phase
    item["radar_status_label"] = label
    item["phase_confidence"] = confidence
    item["phase_reason"] = reason
    if best_runway and "matched_runway" not in item:
        item["nearest_runway"] = best_runway["runway"]
        item["runway_alignment_deg"] = best_runway["alignment_deg"]
        item["distance_to_threshold_nm"] = best_runway["distance_to_threshold_nm"]
    return item


def annotate_blips(
    blips: list[dict[str, Any]],
    *,
    airport_icao: str,
    runways: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [classify_blip(blip, airport_icao=airport_icao, runways=runways or []) for blip in blips]
