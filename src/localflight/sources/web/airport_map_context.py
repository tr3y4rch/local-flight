from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import requests

from localflight.version import user_agent

from localflight.sources.web.airport_surface import (
    DEFAULT_OVERPASS_URL,
    OverpassPayloadTooLarge,
    decode_overpass_json_response,
)


AIRPORT_MAP_SCHEMA_VERSION = "osm-map-context-v2"
AIRPORT_MAP_PROVIDER = "openstreetmap"
AIRPORT_MAP_ATTRIBUTION = "© OpenStreetMap contributors"
AIRPORT_MAP_LICENSE_URL = "https://www.openstreetmap.org/copyright"
DEFAULT_MAP_CONTEXT_TIMEOUT_S = 5.0
OVERPASS_MAP_CONTEXT_URLS = (DEFAULT_OVERPASS_URL,)

_MAP_KIND_ORDER = {"water": 0, "coastline": 1, "park": 2, "landuse": 3, "road": 4, "rail": 5}
_POLYGON_KINDS = {"water", "park", "landuse"}
MAX_MAP_CONTEXT_RADIUS_NM = 20.0
MAX_MAP_CONTEXT_FEATURES = 240
MAX_MAP_FEATURE_POINTS = 180


def clamp_map_context_radius_nm(value: float | int | str | None = None) -> float:
    try:
        radius = float(value if value is not None else 5.0)
    except (TypeError, ValueError):
        radius = 5.0
    return max(1.0, min(MAX_MAP_CONTEXT_RADIUS_NM, radius))


def clamp_map_context_radius_m(value: float | int | str | None = None) -> int:
    return int(clamp_map_context_radius_nm(value) * 1852)


def _bbox(lat: float, lon: float, radius_m: int) -> str:
    radius = max(1852, min(int(radius_m), int(MAX_MAP_CONTEXT_RADIUS_NM * 1852)))
    lat_delta = radius / 111320.0
    lon_delta = radius / (111320.0 * max(0.2, math.cos(math.radians(float(lat)))))
    return (
        f"{float(lat) - lat_delta:.7f},{float(lon) - lon_delta:.7f},"
        f"{float(lat) + lat_delta:.7f},{float(lon) + lon_delta:.7f}"
    )


def build_overpass_map_context_query(lat: float, lon: float, radius_m: int) -> str:
    outer_bbox = _bbox(lat, lon, radius_m)
    inner_bbox = _bbox(lat, lon, min(int(radius_m), int(10.0 * 1852)))
    return f"""
[out:json][timeout:45][maxsize:16777216];
(
  way["natural"="water"]({outer_bbox});
  way["natural"="coastline"]({outer_bbox});
  way["natural"="wood"]({outer_bbox});
  way["waterway"="riverbank"]({outer_bbox});
  way["landuse"="forest"]({outer_bbox});
  way["leisure"="park"]({outer_bbox});
  way["highway"="motorway"]({outer_bbox});
  way["highway"="trunk"]({outer_bbox});
  way["highway"="primary"]({outer_bbox});
  way["highway"="secondary"]({inner_bbox});
  way["railway"="rail"]({inner_bbox});
);
out body geom;
""".strip()


def _clean_code(value: str | None) -> str:
    return "".join(ch for ch in (value or "").strip().upper() if ch.isalnum())


def _downsample_points(points: list[list[float]], max_points: int = MAX_MAP_FEATURE_POINTS) -> list[list[float]]:
    if len(points) <= max_points:
        return points
    step = max(1, len(points) // max_points)
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled[:max_points]


def _points_from_geometry(geometry: Iterable[Any]) -> list[list[float]]:
    points: list[list[float]] = []
    for pt in geometry:
        if not isinstance(pt, dict):
            continue
        try:
            lat = float(pt["lat"])
            lon = float(pt["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if points and abs(points[-1][0] - lat) < 0.0000001 and abs(points[-1][1] - lon) < 0.0000001:
            continue
        points.append([round(lat, 7), round(lon, 7)])
    return _downsample_points(points)


def _feature_span_score(feature: dict[str, Any]) -> float:
    points = feature.get("points")
    if not isinstance(points, list) or len(points) < 2:
        return 0.0
    parsed: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        try:
            parsed.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    if len(parsed) < 2:
        return 0.0
    min_lat = min(point[0] for point in parsed)
    max_lat = max(point[0] for point in parsed)
    min_lon = min(point[1] for point in parsed)
    max_lon = max(point[1] for point in parsed)
    span = (max_lat - min_lat) + (max_lon - min_lon)
    step_length = 0.0
    for idx in range(1, len(parsed)):
        step_length += abs(parsed[idx][0] - parsed[idx - 1][0]) + abs(parsed[idx][1] - parsed[idx - 1][1])
    return span * 3.0 + step_length


def _kind_for(tags: dict[str, Any]) -> str:
    natural = str(tags.get("natural") or "").strip().lower()
    if natural == "water":
        return "water"
    if natural == "coastline":
        return "coastline"
    if str(tags.get("waterway") or "").strip().lower() == "riverbank":
        return "water"
    leisure = str(tags.get("leisure") or "").strip().lower()
    if leisure in {"park", "golf_course"}:
        return "park"
    if natural == "wood":
        return "landuse"
    landuse = str(tags.get("landuse") or "").strip().lower()
    if landuse == "forest":
        return "landuse"
    if tags.get("highway"):
        return "road"
    railway = str(tags.get("railway") or "").strip().lower()
    if railway == "rail":
        return "rail"
    return ""


def _feature_from_element(element: dict[str, Any], *, relation_index: int | None = None) -> dict[str, Any] | None:
    tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
    kind = _kind_for(tags)
    if not kind:
        return None
    points = _points_from_geometry(element.get("geometry") or [])
    if len(points) < 2:
        return None
    source_id = element.get("id", "unknown")
    feature_id = f"{element.get('type', 'way')}:{source_id}" if relation_index is None else f"relation:{source_id}:{relation_index}"
    label = str(tags.get("ref") or tags.get("name") or "").strip()
    closed = kind in _POLYGON_KINDS or (
        len(points) >= 3
        and abs(points[0][0] - points[-1][0]) < 0.00001
        and abs(points[0][1] - points[-1][1]) < 0.00001
    )
    feature = {"kind": kind, "id": str(feature_id), "label": label, "closed": closed, "points": points}
    if kind == "road":
        feature["road_class"] = str(tags.get("highway") or "").strip().lower()
    return feature


def _distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_nm = 3440.065
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return earth_nm * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))


def _boundary_point(
    inside: list[float], outside: list[float], *, center_lat: float, center_lon: float, radius_nm: float
) -> list[float]:
    low = list(inside)
    high = list(outside)
    for _ in range(18):
        mid = [(low[0] + high[0]) / 2.0, (low[1] + high[1]) / 2.0]
        if _distance_nm(center_lat, center_lon, mid[0], mid[1]) <= radius_nm:
            low = mid
        else:
            high = mid
    return [round(low[0], 7), round(low[1], 7)]


def clip_map_features(
    features: list[dict[str, Any]], *, center_lat: float, center_lon: float, radius_nm: float
) -> list[dict[str, Any]]:
    radius = clamp_map_context_radius_nm(radius_nm)
    clipped: list[dict[str, Any]] = []
    for feature in features:
        points = [list(point[:2]) for point in feature.get("points") or [] if isinstance(point, list | tuple) and len(point) >= 2]
        if len(points) < 2:
            continue
        output: list[list[float]] = []
        previous = points[0]
        previous_inside = _distance_nm(center_lat, center_lon, previous[0], previous[1]) <= radius
        if previous_inside:
            output.append(previous)
        for point in points[1:]:
            inside = _distance_nm(center_lat, center_lon, point[0], point[1]) <= radius
            if inside != previous_inside:
                output.append(
                    _boundary_point(
                        previous if previous_inside else point,
                        point if previous_inside else previous,
                        center_lat=center_lat,
                        center_lon=center_lon,
                        radius_nm=radius,
                    )
                )
            if inside:
                output.append(point)
            previous, previous_inside = point, inside
        output = _downsample_points(output)
        if len(output) < 2:
            continue
        item = dict(feature)
        item["points"] = output
        if item.get("closed") and output[0] != output[-1]:
            item["points"] = _downsample_points([*output, output[0]])
        clipped.append(item)
    return clipped[:MAX_MAP_CONTEXT_FEATURES]


def normalize_overpass_map_context(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return []
    features: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        direct = _feature_from_element(element)
        if direct and direct["id"] not in seen:
            features.append(direct)
            seen.add(direct["id"])
        members = element.get("members")
        if not isinstance(members, list):
            continue
        for index, member in enumerate(members):
            if not isinstance(member, dict):
                continue
            merged = dict(member)
            merged.setdefault("type", "relation_member")
            merged.setdefault("id", element.get("id", "unknown"))
            merged.setdefault("tags", element.get("tags") or {})
            relation_feature = _feature_from_element(merged, relation_index=index)
            if relation_feature and relation_feature["id"] not in seen:
                features.append(relation_feature)
                seen.add(relation_feature["id"])
    features.sort(
        key=lambda item: (
            _MAP_KIND_ORDER.get(str(item.get("kind")), 99),
            -_feature_span_score(item),
            str(item.get("label") or ""),
            str(item.get("id") or ""),
        )
    )
    per_kind_caps = {"water": 40, "coastline": 20, "park": 25, "landuse": 30, "road": 45, "rail": 15}
    counts: dict[str, int] = {}
    balanced: list[dict[str, Any]] = []
    for feature in features:
        kind = str(feature.get("kind") or "")
        count = counts.get(kind, 0)
        if count >= per_kind_caps.get(kind, 10):
            continue
        balanced.append(feature)
        counts[kind] = count + 1
    return balanced[:MAX_MAP_CONTEXT_FEATURES]


def build_map_context_payload(
    *,
    airport_iata: str,
    airport_icao: str,
    center_lat: float,
    center_lon: float,
    radius_nm: float,
    features: list[dict[str, Any]],
    cache_state: str,
    generated_at: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "cache_state": cache_state,
        "provider": AIRPORT_MAP_PROVIDER,
        "schema_version": AIRPORT_MAP_SCHEMA_VERSION,
        "attribution": {"text": "OpenStreetMap contributors", "url": AIRPORT_MAP_LICENSE_URL},
        "center": {
            "lat": float(center_lat),
            "lon": float(center_lon),
            "airport_iata": _clean_code(airport_iata),
            "airport_icao": _clean_code(airport_icao),
        },
        "radius_nm": clamp_map_context_radius_nm(radius_nm),
        "coverage_radius_nm": clamp_map_context_radius_nm(radius_nm),
        "features": features,
    }
    if error:
        payload["error"] = str(error)[:300]
    return payload


def validate_map_context_payload(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("provider") == AIRPORT_MAP_PROVIDER
        and payload.get("schema_version") == AIRPORT_MAP_SCHEMA_VERSION
        and isinstance(payload.get("center"), dict)
        and isinstance(payload.get("features"), list)
    )


def fetch_overpass_map_context(
    *,
    lat: float,
    lon: float,
    radius_nm: float,
    timeout_s: float = DEFAULT_MAP_CONTEXT_TIMEOUT_S,
    overpass_url: str | None = None,
) -> dict[str, Any]:
    query = build_overpass_map_context_query(lat, lon, clamp_map_context_radius_m(radius_nm))
    url = overpass_url or OVERPASS_MAP_CONTEXT_URLS[0]
    headers = {
        "User-Agent": user_agent(),
    }
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            kwargs = {"data": {"data": query}, "headers": headers, "timeout": timeout_s, "stream": True}
            response = requests.post(url, **kwargs)
            if getattr(response, "status_code", 200) == 429 and attempt == 0:
                try:
                    retry_after = min(120.0, max(1.0, float(response.headers.get("Retry-After") or 20)))
                except (TypeError, ValueError):
                    retry_after = 20.0
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return decode_overpass_json_response(response)
        except OverpassPayloadTooLarge:
            raise
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(20.0)
    if last_error:
        raise last_error
    raise ValueError("No Overpass map context endpoint configured")
