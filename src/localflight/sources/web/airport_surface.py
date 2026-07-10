from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

import requests

AIRPORT_SURFACE_SCHEMA_VERSION = "osm-surface-v1"
AIRPORT_SURFACE_PROVIDER = "openstreetmap"
AIRPORT_SURFACE_ATTRIBUTION = "© OpenStreetMap contributors"
AIRPORT_SURFACE_LICENSE_URL = "https://www.openstreetmap.org/copyright"
AIRPORT_SURFACE_ESTIMATED_PROVIDER = "localflight-estimated"
AIRPORT_SURFACE_ESTIMATED_ATTRIBUTION = "Estimated airport surface"
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
DEFAULT_SURFACE_RADIUS_NM = 5.0
MIN_SURFACE_RADIUS_NM = 1.0
MAX_SURFACE_RADIUS_NM = 5.0
MIN_SURFACE_LOOKUP_RADIUS_M = int(MIN_SURFACE_RADIUS_NM * 1852)
MAX_SURFACE_LOOKUP_RADIUS_M = int(MAX_SURFACE_RADIUS_NM * 1852)

_AEROWAY_KIND = {
    "aerodrome": "boundary",
    "runway": "runway",
    "taxiway": "taxiway",
    "apron": "apron",
    "terminal": "terminal",
    "hangar": "building",
}
_BUILDING_TAGS = {"terminal", "hangar", "transportation", "airport"}
_KIND_ORDER = {"boundary": 0, "apron": 1, "terminal": 2, "building": 3, "taxiway": 4, "runway": 5}
_POLYGON_KINDS = {"boundary", "apron", "terminal", "building"}


def _clean_code(value: str | None) -> str:
    return "".join(ch for ch in (value or "").strip().upper() if ch.isalnum())


def surface_cache_key(airport_iata: str | None, airport_icao: str | None) -> str:
    iata = _clean_code(airport_iata) or "UNK"
    icao = _clean_code(airport_icao) or "UNK"
    return f"{AIRPORT_SURFACE_SCHEMA_VERSION}:{icao}:{iata}"


def clamp_surface_radius_nm(radius_nm: float | int | str | None = None) -> float:
    try:
        value = float(radius_nm if radius_nm is not None else DEFAULT_SURFACE_RADIUS_NM)
    except (TypeError, ValueError):
        value = DEFAULT_SURFACE_RADIUS_NM
    return max(MIN_SURFACE_RADIUS_NM, min(MAX_SURFACE_RADIUS_NM, value))


def clamp_surface_radius_m(radius_nm: float | int | str | None = None) -> int:
    return max(
        MIN_SURFACE_LOOKUP_RADIUS_M,
        min(MAX_SURFACE_LOOKUP_RADIUS_M, int(clamp_surface_radius_nm(radius_nm) * 1852)),
    )


def build_overpass_query(lat: float, lon: float, radius_m: int) -> str:
    radius = max(MIN_SURFACE_LOOKUP_RADIUS_M, min(MAX_SURFACE_LOOKUP_RADIUS_M, int(radius_m)))
    return f"""
[out:json][timeout:25];
(
  way["aeroway"~"^(aerodrome|runway|taxiway|apron|terminal)$"](around:{radius},{lat:.7f},{lon:.7f});
  relation["aeroway"~"^(aerodrome|runway|taxiway|apron|terminal)$"](around:{radius},{lat:.7f},{lon:.7f});
  way["aeroway"="hangar"](around:{radius},{lat:.7f},{lon:.7f});
  relation["aeroway"="hangar"](around:{radius},{lat:.7f},{lon:.7f});
  way["building"~"^(terminal|hangar|transportation|airport)$"](around:{radius},{lat:.7f},{lon:.7f});
  relation["building"~"^(terminal|hangar|transportation|airport)$"](around:{radius},{lat:.7f},{lon:.7f});
);
out body geom;
""".strip()


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


def _downsample_points(points: list[list[float]], max_points: int = 450) -> list[list[float]]:
    if len(points) <= max_points:
        return points
    step = max(1, len(points) // max_points)
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled[:max_points]


def _is_closed(points: list[list[float]], kind: str) -> bool:
    if len(points) < 3:
        return False
    first, last = points[0], points[-1]
    closed = abs(first[0] - last[0]) < 0.00001 and abs(first[1] - last[1]) < 0.00001
    return closed or kind in _POLYGON_KINDS


def _label_for(tags: dict[str, Any], kind: str) -> str:
    if kind == "runway":
        return str(tags.get("ref") or tags.get("name") or "").strip()
    if kind == "taxiway":
        return str(tags.get("ref") or "").strip()
    return str(tags.get("name") or tags.get("ref") or "").strip()


def _feature_from_element(element: dict[str, Any], *, relation_index: int | None = None) -> dict[str, Any] | None:
    tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
    aeroway = str(tags.get("aeroway") or "").strip().lower()
    kind = _AEROWAY_KIND.get(aeroway)
    building = str(tags.get("building") or "").strip().lower()
    if not kind and building in _BUILDING_TAGS:
        kind = "building"
    if not kind:
        return None
    points = _points_from_geometry(element.get("geometry") or [])
    if len(points) < 2:
        return None
    source_id = element.get("id", "unknown")
    if relation_index is None:
        feature_id = f"{element.get('type', 'way')}:{source_id}"
    else:
        feature_id = f"relation:{source_id}:{relation_index}"
    label = _label_for(tags, kind)
    return {
        "kind": kind,
        "id": str(feature_id),
        "label": label,
        "closed": _is_closed(points, kind),
        "points": points,
    }


def normalize_overpass_surface(payload: dict[str, Any]) -> list[dict[str, Any]]:
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
            _KIND_ORDER.get(str(item.get("kind")), 99),
            str(item.get("label") or ""),
            str(item.get("id") or ""),
        )
    )
    return features[:450]


def build_surface_payload(
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
    meta: dict[str, Any] | None = None,
    provider: str = AIRPORT_SURFACE_PROVIDER,
    attribution_text: str | None = None,
    attribution_url: str | None = None,
) -> dict[str, Any]:
    provider_name = str(provider or AIRPORT_SURFACE_PROVIDER)
    payload: dict[str, Any] = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "cache_state": cache_state,
        "provider": provider_name,
        "schema_version": AIRPORT_SURFACE_SCHEMA_VERSION,
        "attribution": {
            "text": attribution_text or AIRPORT_SURFACE_ATTRIBUTION,
            "url": attribution_url if attribution_url is not None else AIRPORT_SURFACE_LICENSE_URL,
        },
        "center": {
            "lat": float(center_lat),
            "lon": float(center_lon),
            "airport_iata": _clean_code(airport_iata),
            "airport_icao": _clean_code(airport_icao),
        },
        "radius_nm": clamp_surface_radius_nm(radius_nm),
        "features": features,
        "meta": meta or {},
    }
    if error:
        payload["error"] = str(error)[:300]
    return payload


def _offset_point(lat: float, lon: float, *, north_nm: float = 0.0, east_nm: float = 0.0) -> list[float]:
    cos_lat = max(0.15, abs(math.cos(math.radians(lat))))
    return [
        round(lat + (north_nm / 60.0), 7),
        round(lon + (east_nm / (60.0 * cos_lat)), 7),
    ]


def _point_on_heading(lat: float, lon: float, heading_deg: float, distance_nm: float) -> list[float]:
    radians = math.radians(heading_deg)
    return _offset_point(
        lat,
        lon,
        north_nm=math.cos(radians) * distance_nm,
        east_nm=math.sin(radians) * distance_nm,
    )


def _rectangle_points(
    lat: float,
    lon: float,
    *,
    north_nm: float,
    east_nm: float,
    height_nm: float,
    width_nm: float,
) -> list[list[float]]:
    half_h = height_nm / 2.0
    half_w = width_nm / 2.0
    points = [
        _offset_point(lat, lon, north_nm=north_nm - half_h, east_nm=east_nm - half_w),
        _offset_point(lat, lon, north_nm=north_nm - half_h, east_nm=east_nm + half_w),
        _offset_point(lat, lon, north_nm=north_nm + half_h, east_nm=east_nm + half_w),
        _offset_point(lat, lon, north_nm=north_nm + half_h, east_nm=east_nm - half_w),
    ]
    points.append(points[0])
    return points


def estimated_surface_features(center_lat: float, center_lon: float, radius_nm: float) -> list[dict[str, Any]]:
    """Small deterministic fallback so first-run radar never looks broken."""
    radius = clamp_surface_radius_nm(radius_nm)
    boundary_radius = min(2.2, max(0.9, radius * 0.52))
    boundary = [
        _point_on_heading(center_lat, center_lon, heading, boundary_radius)
        for heading in range(0, 360, 30)
    ]
    boundary.append(boundary[0])

    main_half = min(1.35, max(0.55, radius * 0.34))
    cross_half = min(0.85, max(0.38, radius * 0.22))
    taxi_half = main_half * 0.82
    taxi_center = _offset_point(center_lat, center_lon, north_nm=-0.13, east_nm=0.18)

    return [
        {
            "kind": "boundary",
            "id": "estimated:boundary",
            "label": "Estimated airport area",
            "closed": True,
            "points": boundary,
        },
        {
            "kind": "apron",
            "id": "estimated:apron",
            "label": "Estimated apron",
            "closed": True,
            "points": _rectangle_points(
                center_lat,
                center_lon,
                north_nm=-0.22,
                east_nm=0.34,
                height_nm=min(0.52, radius * 0.16),
                width_nm=min(0.9, radius * 0.24),
            ),
        },
        {
            "kind": "building",
            "id": "estimated:terminal",
            "label": "Estimated terminal",
            "closed": True,
            "points": _rectangle_points(
                center_lat,
                center_lon,
                north_nm=-0.55,
                east_nm=0.58,
                height_nm=min(0.25, radius * 0.08),
                width_nm=min(0.58, radius * 0.16),
            ),
        },
        {
            "kind": "taxiway",
            "id": "estimated:taxiway-main",
            "label": "Estimated taxiway",
            "closed": False,
            "points": [
                _point_on_heading(taxi_center[0], taxi_center[1], 160, taxi_half),
                _point_on_heading(taxi_center[0], taxi_center[1], 340, taxi_half),
            ],
        },
        {
            "kind": "runway",
            "id": "estimated:runway-main",
            "label": "EST RWY",
            "closed": False,
            "points": [
                _point_on_heading(center_lat, center_lon, 160, main_half),
                _point_on_heading(center_lat, center_lon, 340, main_half),
            ],
        },
        {
            "kind": "runway",
            "id": "estimated:runway-cross",
            "label": "EST",
            "closed": False,
            "points": [
                _point_on_heading(center_lat, center_lon, 70, cross_half),
                _point_on_heading(center_lat, center_lon, 250, cross_half),
            ],
        },
    ]


def build_estimated_surface_payload(
    *,
    airport_iata: str,
    airport_icao: str,
    center_lat: float,
    center_lon: float,
    radius_nm: float,
    error: str | None = None,
) -> dict[str, Any]:
    features = estimated_surface_features(center_lat, center_lon, radius_nm)
    return build_surface_payload(
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_nm=radius_nm,
        features=features,
        cache_state="estimated",
        error=error,
        meta={
            "served_via": "local-estimated-surface",
            "estimated_surface": True,
            "feature_count": len(features),
            "reason": "No relay or local OSM surface cache was available.",
        },
        provider=AIRPORT_SURFACE_ESTIMATED_PROVIDER,
        attribution_text=AIRPORT_SURFACE_ESTIMATED_ATTRIBUTION,
        attribution_url="",
    )


def validate_surface_payload(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("provider") not in {AIRPORT_SURFACE_PROVIDER, AIRPORT_SURFACE_ESTIMATED_PROVIDER}:
        return False
    if payload.get("schema_version") != AIRPORT_SURFACE_SCHEMA_VERSION:
        return False
    if not isinstance(payload.get("center"), dict):
        return False
    if not isinstance(payload.get("features"), list):
        return False
    return True


def fetch_overpass_surface(
    *,
    lat: float,
    lon: float,
    radius_m: int,
    timeout_s: int = 25,
    overpass_url: str | None = None,
) -> dict[str, Any]:
    query = build_overpass_query(lat, lon, radius_m)
    response = requests.post(
        overpass_url or DEFAULT_OVERPASS_URL,
        data={"data": query},
        headers={
            "User-Agent": "localflight-relay/0.5.1 (+https://beacontools.cc/local-flight)",
            "Accept": "application/json",
        },
        timeout=timeout_s,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Overpass response shape invalid")
    return payload
