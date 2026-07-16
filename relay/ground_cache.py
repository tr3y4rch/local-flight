from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


GROUND_SCHEMA_VERSION = "airport-ground-v1"
GROUND_RADIUS_BUCKETS = (5, 10, 20)
GROUND_MAX_CONTEXT_FEATURES = 240
GROUND_MAX_FEATURE_POINTS = 180

GROUND_SEED_AIRPORTS = (
    "ATL", "LAX", "JFK", "DFW", "ORD", "LHR", "FRA", "AMS", "CDG", "MAD",
    "DXB", "DOH", "IST", "HND", "SIN", "ICN", "DEL", "PVG", "SYD", "GRU",
)
GROUND_PINNED_AIRPORTS = (
    "ATL", "LAX", "LHR", "FRA", "DXB", "IST", "HND", "SIN", "ICN", "DEL", "SYD", "GRU",
)


def clean_airport_code(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().upper() if ch.isalnum())[:4]


def normalize_max_radius(value: Any, *, default: int = 20) -> int:
    try:
        radius = float(value)
    except (TypeError, ValueError):
        radius = float(default)
    for bucket in GROUND_RADIUS_BUCKETS:
        if radius <= bucket:
            return bucket
    return 20


def radius_bucket(requested_radius_nm: Any, *, max_radius_nm: Any = 20) -> int:
    maximum = normalize_max_radius(max_radius_nm)
    try:
        requested = max(1.0, float(requested_radius_nm))
    except (TypeError, ValueError):
        requested = 5.0
    requested = min(requested, float(maximum))
    return normalize_max_radius(requested, default=5)


def layer_cache_key(layer: str, airport_iata: str, airport_icao: str, radius_nm: int) -> str:
    basis = ":".join(
        [
            GROUND_SCHEMA_VERSION,
            str(layer or "").strip().lower(),
            clean_airport_code(airport_icao) or "UNK",
            clean_airport_code(airport_iata) or "UNK",
            str(int(radius_nm)),
        ]
    )
    return f"grd_{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:24]}"


def _bounded_points(points: Any) -> list[list[float]]:
    parsed: list[list[float]] = []
    for point in points if isinstance(points, list) else []:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        try:
            row = [round(float(point[0]), 7), round(float(point[1]), 7)]
        except (TypeError, ValueError):
            continue
        if not parsed or parsed[-1] != row:
            parsed.append(row)
    if len(parsed) <= GROUND_MAX_FEATURE_POINTS:
        return parsed
    step = max(1, len(parsed) // GROUND_MAX_FEATURE_POINTS)
    sampled = parsed[::step]
    if sampled[-1] != parsed[-1]:
        sampled.append(parsed[-1])
    return sampled[:GROUND_MAX_FEATURE_POINTS]


def bounded_features(features: Any, *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in features if isinstance(features, list) else []:
        if not isinstance(raw, dict):
            continue
        points = _bounded_points(raw.get("points"))
        if len(points) < 2:
            continue
        item = dict(raw)
        item["points"] = points
        rows.append(item)
        if len(rows) >= max(0, int(limit)):
            break
    return rows


def combine_ground_payload(
    *,
    airport_iata: str,
    airport_icao: str,
    center_lat: float,
    center_lon: float,
    requested_radius_nm: float,
    coverage_radius_nm: int,
    surface: dict[str, Any],
    map_context: dict[str, Any],
    terrain: dict[str, Any],
) -> dict[str, Any]:
    surface_rows = bounded_features(surface.get("features"), limit=450)
    runways = [row for row in surface_rows if str(row.get("kind") or "").lower() == "runway"]
    surface_features = [row for row in surface_rows if str(row.get("kind") or "").lower() != "runway"]
    map_features = bounded_features(map_context.get("features"), limit=140)
    terrain_features = bounded_features(terrain.get("features"), limit=GROUND_MAX_CONTEXT_FEATURES - len(map_features))
    terrain_payload = dict(terrain)
    terrain_payload["features"] = terrain_features
    terrain_payload["bands"] = [row for row in terrain_features if row.get("kind") == "terrain_band"]
    terrain_payload["contours"] = [row for row in terrain_features if row.get("kind") == "contour"]
    terrain_payload["available"] = bool(terrain_features)
    terrain_payload["enabled"] = True

    attributions: list[dict[str, str]] = []
    for payload in (surface, map_context, terrain):
        item = payload.get("attribution") if isinstance(payload, dict) else None
        if isinstance(item, dict) and item.get("text") and item not in attributions:
            attributions.append({"text": str(item.get("text") or ""), "url": str(item.get("url") or "")})

    states = {
        "surface": str(surface.get("cache_state") or "miss"),
        "map": str(map_context.get("cache_state") or "miss"),
        "terrain": str(terrain.get("cache_state") or "miss"),
    }
    overall = "fresh" if all(value == "fresh" for value in states.values()) else "stale" if any(value == "stale" for value in states.values()) else "partial"
    return {
        "center": {
            "lat": float(center_lat),
            "lon": float(center_lon),
            "airport_iata": clean_airport_code(airport_iata),
            "airport_icao": clean_airport_code(airport_icao),
        },
        "radius_nm": float(requested_radius_nm),
        "coverage_radius_nm": int(coverage_radius_nm),
        "schema_version": GROUND_SCHEMA_VERSION,
        "cache_state": overall,
        "runways": runways,
        "surface_features": surface_features,
        "map_features": map_features,
        "terrain": terrain_payload,
        "attribution": attributions,
        "sources": {
            "runways": str(surface.get("provider") or "none") if runways else "none",
            "surface": str(surface.get("provider") or "none"),
            "surface_cache_state": states["surface"],
            "map": str(map_context.get("provider") or "none"),
            "map_cache_state": states["map"],
            "terrain": str(terrain.get("provider") or "none"),
            "terrain_cache_state": states["terrain"],
        },
        "confidence": {
            "runway_count": len(runways),
            "surface_feature_count": len(surface_features),
            "map_feature_count": len(map_features),
            "terrain_feature_count": len(terrain_features),
        },
    }


def select_hybrid_airports(
    interest_rows: Iterable[tuple[str, int]],
    overrides: dict[str, dict[str, Any]] | None = None,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    overrides = overrides or {}
    selected: list[str] = []

    def enabled(code: str) -> bool:
        return overrides.get(code, {}).get("enabled", True) is not False

    pinned = list(GROUND_PINNED_AIRPORTS)
    pinned.extend(code for code, row in overrides.items() if row.get("pinned") is True and code not in pinned)
    for code in pinned:
        code = clean_airport_code(code)
        if code and enabled(code) and code not in selected:
            selected.append(code)

    demand_slots = max(0, min(8, limit - len(selected)))
    demanded = sorted(
        ((clean_airport_code(code), int(count)) for code, count in interest_rows if clean_airport_code(code)),
        key=lambda row: (-row[1], row[0]),
    )
    for code, _count in demanded:
        if demand_slots <= 0:
            break
        if enabled(code) and code not in selected:
            selected.append(code)
            demand_slots -= 1

    for code in GROUND_SEED_AIRPORTS:
        if len(selected) >= limit:
            break
        if enabled(code) and code not in selected:
            selected.append(code)

    return [
        {
            "airport": code,
            "pinned": code in pinned,
            "max_radius_nm": normalize_max_radius(overrides.get(code, {}).get("max_radius_nm", 20)),
        }
        for code in selected[:limit]
    ]


def payload_etag(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return '"' + hashlib.sha256(raw).hexdigest()[:32] + '"'
