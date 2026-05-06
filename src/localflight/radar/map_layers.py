from __future__ import annotations

from typing import Any

from .runways import merge_runways


_DRAWABLE_SURFACE_KINDS = {"boundary", "apron", "terminal", "building", "taxiway"}


def _surface_features(surface_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(surface_payload, dict):
        return []
    features = surface_payload.get("features")
    if not isinstance(features, list):
        return []
    return [dict(feature) for feature in features if isinstance(feature, dict)]


def _map_surface_features(features: list[dict[str, Any]], *, radius_nm: float) -> list[dict[str, Any]]:
    """Keep the map intentionally calm: runways handled separately, clutter fades by range."""
    max_features = 80 if radius_nm <= 5 else 30 if radius_nm <= 20 else 12
    mapped: list[dict[str, Any]] = []
    for feature in features:
        kind = str(feature.get("kind") or "").strip().lower()
        if kind == "runway" or kind not in _DRAWABLE_SURFACE_KINDS:
            continue
        if radius_nm > 20 and kind not in {"boundary", "terminal", "building"}:
            continue
        if radius_nm > 40 and kind != "boundary":
            continue
        mapped.append(feature)
        if len(mapped) >= max_features:
            break
    return mapped


def build_radar_map(
    *,
    airport_iata: str,
    airport_icao: str,
    center_lat: float,
    center_lon: float,
    radius_nm: float,
    surface_payload: dict[str, Any] | None,
    terrain_enabled: bool = False,
    refresh_runways: bool = False,
) -> dict[str, Any]:
    source_features = _surface_features(surface_payload)
    runways = merge_runways(
        airport_icao=airport_icao,
        center_lat=center_lat,
        center_lon=center_lon,
        surface_features=source_features,
        auto_refresh=refresh_runways,
    )
    surface_provider = ""
    surface_cache_state = ""
    attribution = []
    if isinstance(surface_payload, dict):
        surface_provider = str(surface_payload.get("provider") or "")
        surface_cache_state = str(surface_payload.get("cache_state") or "")
        attr = surface_payload.get("attribution") if isinstance(surface_payload.get("attribution"), dict) else {}
        if attr.get("text"):
            attribution.append(attr)

    terrain = {
        "available": bool(terrain_enabled),
        "enabled": bool(terrain_enabled),
        "provider": "aws-terrain-tiles" if terrain_enabled else "",
        "label": "Minimal cached relief" if terrain_enabled else "Terrain off",
        "features": [],
        "note": "Terrain is visual context only and is not for navigation.",
    }

    runway_confidences = {str(item.get("confidence") or "unknown") for item in runways}
    return {
        "center": {
            "lat": float(center_lat),
            "lon": float(center_lon),
            "airport_iata": airport_iata,
            "airport_icao": airport_icao,
        },
        "radius_nm": float(radius_nm),
        "schema_version": "radar-map-v1",
        "runways": runways,
        "surface_features": _map_surface_features(source_features, radius_nm=radius_nm),
        "terrain": terrain,
        "attribution": attribution,
        "sources": {
            "runways": sorted(runway_confidences),
            "surface": surface_provider or "none",
            "surface_cache_state": surface_cache_state or "none",
            "terrain": terrain["provider"] or "none",
        },
        "confidence": {
            "runway_count": len(runways),
            "surface_feature_count": len(source_features),
            "note": "Runways prefer OurAirports metadata plus OSM geometry when available.",
        },
    }
