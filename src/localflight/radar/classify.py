from __future__ import annotations

import time
from statistics import median
from threading import RLock
from typing import Any

from .geo import bearing_deg, distance_nm, float_or_none, heading_delta_deg
from .normalize import enrich_blip_display_fields


_PHASE_HISTORY_TTL_S = 5 * 60
_PHASE_HISTORY_MAX = 2048
_phase_history: dict[str, dict[str, Any]] = {}
_phase_lock = RLock()


def _altitude_ft(blip: dict[str, Any]) -> float | None:
    altitude = float_or_none(blip.get("altitude_ft"))
    if altitude is not None:
        return altitude
    altitude_m = float_or_none(blip.get("altitude_m"))
    return None if altitude_m is None else altitude_m * 3.28084


def _speed_kt(blip: dict[str, Any]) -> float | None:
    speed = float_or_none(blip.get("speed_kt"))
    if speed is not None:
        return speed
    speed_ms = float_or_none(blip.get("speed_ms"))
    return None if speed_ms is None else speed_ms * 1.94384


def _airport_elevation_ft(runways: list[dict[str, Any]]) -> float | None:
    elevations: list[float] = []
    for runway in runways:
        endpoints = runway.get("endpoints") if isinstance(runway.get("endpoints"), list) else []
        for endpoint in endpoints:
            value = float_or_none(endpoint.get("elevation_ft")) if isinstance(endpoint, dict) else None
            if value is not None:
                elevations.append(value)
    return float(median(elevations)) if elevations else None


def _altitude_agl_ft(blip: dict[str, Any], runways: list[dict[str, Any]]) -> float | None:
    altitude = _altitude_ft(blip)
    elevation = _airport_elevation_ft(runways)
    if altitude is None or elevation is None:
        return None
    return max(-200.0, altitude - elevation)


def _is_ground(blip: dict[str, Any], runways: list[dict[str, Any]] | None = None) -> bool:
    if blip.get("on_ground") is True:
        return True
    if blip.get("on_ground") is False:
        return False
    altitude = _altitude_ft(blip)
    speed = _speed_kt(blip)
    agl = _altitude_agl_ft(blip, runways or [])
    if agl is not None and speed is not None:
        return agl <= 150 and speed < 50
    # Without airport elevation, only use a deliberately conservative fallback.
    return altitude is not None and altitude < 100 and (speed is None or speed < 35)


def _traffic_role(blip: dict[str, Any], airport_icao: str, runways: list[dict[str, Any]]) -> str:
    airport = (airport_icao or "").strip().upper()
    dep = str(blip.get("departure_icao") or "").strip().upper()
    arr = str(blip.get("arrival_icao") or "").strip().upper()
    if airport and arr == airport:
        return "arrival"
    if airport and dep == airport:
        return "departure"
    if _is_ground(blip, runways):
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
            heading_delta = heading_delta_deg(track, inbound_heading)
            bearing_to_threshold = bearing_deg(lat, lon, rlat, rlon)
            inbound_delta = heading_delta_deg(track, bearing_to_threshold)
            if heading_delta is None or inbound_delta is None:
                continue
            matches.append(
                {
                    "runway": str(endpoint.get("ident") or runway.get("label") or ""),
                    "label": str(runway.get("label") or endpoint.get("ident") or ""),
                    "alignment_deg": round(min(heading_delta, inbound_delta), 1),
                    "distance_to_threshold_nm": round(distance_nm(rlat, rlon, lat, lon), 2),
                    "elevation_ft": float_or_none(endpoint.get("elevation_ft")),
                    "confidence": runway.get("confidence") or "unknown",
                }
            )
    matches.sort(key=lambda item: (float(item["alignment_deg"]), float(item["distance_to_threshold_nm"])))
    return matches


def classify_blip(
    blip: dict[str, Any],
    *,
    airport_icao: str,
    runways: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    runway_rows = runways or []
    item = enrich_blip_display_fields(blip)
    board_status = str(item.get("board_status") or item.get("status") or "").strip().lower()
    item["board_status"] = board_status or None

    role = _traffic_role(item, airport_icao, runway_rows)
    item["traffic_role"] = role
    altitude = _altitude_ft(item)
    agl = _altitude_agl_ft(item, runway_rows)
    speed = _speed_kt(item)
    vertical_fpm = float_or_none(item.get("vertical_rate_fpm"))
    distance = float_or_none(item.get("distance_nm"))
    ground = _is_ground(item, runway_rows)
    stale = (float_or_none(item.get("position_age_s")) or 0.0) > 30.0
    motion_trend, motion_label = _motion_trend(vertical_fpm, speed)
    item["motion_trend"] = motion_trend
    item["motion_label"] = motion_label
    item["altitude_agl_ft"] = round(agl) if agl is not None else None
    item["position_stale"] = stale

    runway_matches = _runway_matches(item, runway_rows)
    best_runway = runway_matches[0] if runway_matches else None
    altitude_for_terminal = agl if agl is not None else altitude

    phase = "enroute"
    label = "En route"
    confidence = "low"
    reason = "Airborne target without a stronger terminal-area phase match."

    if ground:
        if role == "departure" and speed is not None and speed > 45:
            phase, label = "departing", "Departing"
            confidence = "medium"
            reason = "Confirmed departure moving at takeoff-roll speed within the airport area."
        elif speed is not None and 5 <= speed <= 45:
            phase, label = "taxi", "Taxi"
            reason = "Ground target moving at taxi speed."
            confidence = "high" if item.get("on_ground") is True else "medium"
        else:
            phase, label = "on_ground", "On ground"
            reason = "Ground flag or reliable low-AGL, low-speed position."
            confidence = "high" if item.get("on_ground") is True else "medium"
    else:
        aligned = bool(best_runway and float(best_runway["alignment_deg"]) <= 18.0)
        near_threshold = bool(best_runway and float(best_runway["distance_to_threshold_nm"]) <= 8.0)
        plausible_final_alt = altitude_for_terminal is None or altitude_for_terminal <= 4500
        plausible_final_speed = speed is None or 85 <= speed <= 260
        not_climbing = vertical_fpm is None or vertical_fpm <= 200
        if (
            role == "arrival"
            and best_runway
            and aligned
            and near_threshold
            and plausible_final_alt
            and plausible_final_speed
            and not_climbing
            and not stale
        ):
            phase, label = "final", "On final"
            confidence = "high" if vertical_fpm is not None and vertical_fpm < -200 else "medium"
            reason = f"Confirmed arrival aligned with runway {best_runway['runway']} and inbound to its threshold."
            item["matched_runway"] = best_runway["runway"]
        elif (
            role == "arrival"
            and distance is not None
            and distance <= 20.0
            and (altitude_for_terminal is None or altitude_for_terminal <= 9000)
            and (vertical_fpm is None or vertical_fpm <= 300)
        ):
            phase, label = "approach", "On approach"
            confidence = "medium" if not stale else "low"
            reason = "Confirmed arrival in the terminal area, not yet meeting final-approach geometry."
        elif (
            role == "unknown"
            and best_runway
            and aligned
            and near_threshold
            and plausible_final_alt
            and vertical_fpm is not None
            and vertical_fpm <= -200
            and not stale
        ):
            phase, label = "approach", "Possible approach"
            confidence = "low"
            reason = f"Descending and aligned with runway {best_runway['runway']}, but route intent is unavailable."
        elif role == "departure" and distance is not None and distance <= 20.0 and (vertical_fpm is None or vertical_fpm >= -300):
            phase, label = "departing", "Departing"
            confidence = "medium"
            reason = "Confirmed departure airborne within the terminal area."
        elif vertical_fpm is not None and vertical_fpm < -500:
            phase, label = "descending", "Descending"
            confidence = "medium" if not stale else "low"
            reason = f"Sustained descent at {round(vertical_fpm):+d} fpm outside a confirmed approach state."
        else:
            confidence = "medium" if role in {"arrival", "departure"} and not stale else "low"

    item["radar_phase"] = phase
    item["radar_status"] = phase
    item["radar_status_label"] = label
    item["phase_confidence"] = confidence
    item["phase_reason"] = reason
    if best_runway:
        if "matched_runway" not in item:
            item["nearest_runway"] = best_runway["runway"]
        item["runway_alignment_deg"] = best_runway["alignment_deg"]
        item["distance_to_threshold_nm"] = best_runway["distance_to_threshold_nm"]
    return item


def _phase_key(item: dict[str, Any]) -> str:
    return str(item.get("icao24") or item.get("callsign") or item.get("flight_number") or "").strip().upper()


def _stabilize_phase(item: dict[str, Any]) -> dict[str, Any]:
    key = _phase_key(item)
    if not key:
        return item
    now = time.monotonic()
    with _phase_lock:
        if len(_phase_history) > _PHASE_HISTORY_MAX:
            stale_keys = sorted(_phase_history, key=lambda name: float(_phase_history[name].get("seen", 0.0)))
            for stale_key in stale_keys[: len(_phase_history) - _PHASE_HISTORY_MAX]:
                _phase_history.pop(stale_key, None)
        previous = _phase_history.get(key)
        if previous and now - float(previous.get("seen", 0.0)) > _PHASE_HISTORY_TTL_S:
            previous = None
            _phase_history.pop(key, None)

        phase = str(item.get("radar_phase") or "enroute")
        if previous:
            old_phase = str(previous.get("phase") or "")
            age = now - float(previous.get("seen", now))
            hold = (
                old_phase == "final" and phase in {"approach", "descending", "enroute"} and age <= 30
            ) or (
                old_phase == "approach" and phase in {"descending", "enroute"} and age <= 20
            )
            if hold and not item.get("position_stale"):
                item["radar_phase"] = old_phase
                item["radar_status"] = old_phase
                item["radar_status_label"] = "On final" if old_phase == "final" else "On approach"
                item["phase_reason"] = "Short phase hold prevents a single noisy position from changing the displayed state."
                item["phase_hysteresis"] = True
                phase = old_phase
        _phase_history[key] = {"phase": phase, "seen": now}
    return item


def annotate_blips(
    blips: list[dict[str, Any]],
    *,
    airport_icao: str,
    runways: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        _stabilize_phase(classify_blip(blip, airport_icao=airport_icao, runways=runways or []))
        for blip in blips
    ]


def clear_phase_history() -> None:
    with _phase_lock:
        _phase_history.clear()
