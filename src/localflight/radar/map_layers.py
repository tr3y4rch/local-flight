from __future__ import annotations

from typing import Any

from .runways import merge_runways


_DRAWABLE_SURFACE_KINDS = {"boundary", "apron", "terminal", "building", "taxiway"}
_DRAWABLE_MAP_KINDS = {"water", "coastline", "park", "landuse", "road", "rail"}


def _surface_features(surface_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(surface_payload, dict):
        return []
    features = surface_payload.get("features")
    if not isinstance(features, list):
        return []
    return [dict(feature) for feature in features if isinstance(feature, dict)]


def _features_from_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    features = payload.get("features")
    if not isinstance(features, list):
        return []
    return [dict(feature) for feature in features if isinstance(feature, dict)]


def _runway_merge_features(surface_payload: dict[str, Any] | None, features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only pass provider-truth runway geometry into the runway merge.

    The local estimated surface keeps first-run radar from looking empty, but
    its sketch runways are visual placeholders. Letting those placeholders
    masquerade as OSM geometry can hide or distort the better OurAirports
    runway layer.
    """
    provider = str(surface_payload.get("provider") if isinstance(surface_payload, dict) else "").strip().lower()
    if provider == "localflight-estimated":
        return [feature for feature in features if str(feature.get("kind") or "").strip().lower() != "runway"]
    return features


def _has_non_estimated_runway(runways: list[dict[str, Any]]) -> bool:
    return any(str(runway.get("confidence") or "").strip().lower() != "estimated" for runway in runways)


def _runway_source_summary(runways: list[dict[str, Any]]) -> dict[str, Any]:
    confidences = sorted({str(item.get("confidence") or "unknown") for item in runways})
    precisions = sorted({str(item.get("geometry_precision") or "unknown") for item in runways})
    exact_count = sum(
        1
        for item in runways
        if str(item.get("confidence") or "").strip().lower() in {"ourairports", "ourairports+osm", "osm"}
    )
    endpoint_count = sum(
        1
        for item in runways
        if str(item.get("geometry_precision") or "").strip().lower() == "endpoint"
    )
    return {
        "runways": confidences,
        "runway_geometry_precision": precisions,
        "runway_exact_count": exact_count,
        "runway_endpoint_count": endpoint_count,
        "has_provider_runways": bool(exact_count),
    }


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


def _map_context_features(features: list[dict[str, Any]], *, radius_nm: float) -> list[dict[str, Any]]:
    """Very quiet geographic context. No labels, no POI-style detail."""
    if radius_nm <= 5:
        max_features = 90
        per_kind_caps = {"water": 20, "coastline": 12, "park": 18, "landuse": 20, "road": 28, "rail": 10}
    elif radius_nm <= 20:
        max_features = 70
        per_kind_caps = {"water": 14, "coastline": 8, "park": 10, "landuse": 14, "road": 20, "rail": 8}
    else:
        max_features = 16
        per_kind_caps = {"water": 8, "coastline": 5, "landuse": 3}
    counts: dict[str, int] = {}
    mapped: list[dict[str, Any]] = []
    for feature in features:
        kind = str(feature.get("kind") or "").strip().lower()
        if kind not in _DRAWABLE_MAP_KINDS:
            continue
        if radius_nm > 20 and kind not in {"water", "coastline", "landuse"}:
            continue
        if radius_nm > 40 and kind not in {"water", "coastline"}:
            continue
        count = counts.get(kind, 0)
        if count >= per_kind_caps.get(kind, 0):
            continue
        item = dict(feature)
        item["label"] = ""
        mapped.append(item)
        counts[kind] = count + 1
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
    map_payload: dict[str, Any] | None = None,
    terrain_payload: dict[str, Any] | None = None,
    terrain_enabled: bool = False,
    refresh_runways: bool = False,
) -> dict[str, Any]:
    source_features = _surface_features(surface_payload)
    map_source_features = _features_from_payload(map_payload)
    runway_features = _runway_merge_features(surface_payload, source_features)
    runways = merge_runways(
        airport_icao=airport_icao,
        center_lat=center_lat,
        center_lon=center_lon,
        surface_features=runway_features,
        auto_refresh=refresh_runways,
    )
    if not refresh_runways and not _has_non_estimated_runway(runways):
        refreshed = merge_runways(
            airport_icao=airport_icao,
            center_lat=center_lat,
            center_lon=center_lon,
            surface_features=runway_features,
            auto_refresh=True,
        )
        if _has_non_estimated_runway(refreshed):
            runways = refreshed
    surface_provider = ""
    surface_cache_state = ""
    attribution = []
    if isinstance(surface_payload, dict):
        surface_provider = str(surface_payload.get("provider") or "")
        surface_cache_state = str(surface_payload.get("cache_state") or "")
        attr = surface_payload.get("attribution") if isinstance(surface_payload.get("attribution"), dict) else {}
        if attr.get("text"):
            attribution.append(attr)
    map_provider = ""
    map_cache_state = ""
    if isinstance(map_payload, dict):
        map_provider = str(map_payload.get("provider") or "")
        map_cache_state = str(map_payload.get("cache_state") or "")
        attr = map_payload.get("attribution") if isinstance(map_payload.get("attribution"), dict) else {}
        if attr.get("text") and attr not in attribution:
            attribution.append(attr)

    terrain_features = _features_from_payload(terrain_payload)
    terrain_attr = terrain_payload.get("attribution") if isinstance(terrain_payload, dict) and isinstance(terrain_payload.get("attribution"), dict) else {}
    if terrain_attr.get("text") and terrain_attr not in attribution:
        attribution.append(terrain_attr)
    terrain_provider = str(terrain_payload.get("provider") or "") if isinstance(terrain_payload, dict) else ""
    terrain_cache_state = str(terrain_payload.get("cache_state") or "") if isinstance(terrain_payload, dict) else ""
    terrain = {
        "available": bool(terrain_enabled),
        "enabled": bool(terrain_enabled),
        "provider": terrain_provider or ("aws-terrain-tiles" if terrain_enabled else ""),
        "label": "Minimal cached relief" if terrain_enabled else "Terrain off",
        "features": terrain_features if terrain_enabled else [],
        "cache_state": terrain_cache_state or ("none" if terrain_enabled else "off"),
        "note": "Terrain is visual context only and is not for navigation.",
    }

    runway_sources = _runway_source_summary(runways)
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
        "map_features": _map_context_features(map_source_features, radius_nm=radius_nm),
        "surface_features": _map_surface_features(source_features, radius_nm=radius_nm),
        "terrain": terrain,
        "attribution": attribution,
        "sources": {
            "runways": runway_sources["runways"],
            "runway_geometry_precision": runway_sources["runway_geometry_precision"],
            "surface": surface_provider or "none",
            "surface_cache_state": surface_cache_state or "none",
            "map": map_provider or "none",
            "map_cache_state": map_cache_state or "none",
            "terrain": terrain["provider"] or "none",
            "terrain_cache_state": terrain["cache_state"],
        },
        "confidence": {
            "runway_count": len(runways),
            "runway_exact_count": runway_sources["runway_exact_count"],
            "runway_endpoint_count": runway_sources["runway_endpoint_count"],
            "has_provider_runways": runway_sources["has_provider_runways"],
            "surface_feature_count": len(source_features),
            "map_feature_count": len(map_source_features),
            "terrain_feature_count": len(terrain_features),
            "note": "Runways prefer OurAirports metadata plus OSM geometry when available.",
        },
    }
