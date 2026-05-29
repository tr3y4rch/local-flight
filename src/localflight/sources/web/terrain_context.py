from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import math
from typing import Any

import requests
from PIL import Image

from localflight.sources.web.airport_surface import clamp_surface_radius_nm


TERRAIN_SCHEMA_VERSION = "terrain-context-v1"
TERRAIN_PROVIDER = "aws-terrain-tiles"
TERRAIN_ATTRIBUTION = "Terrain Tiles on AWS"
TERRAIN_LICENSE_URL = "https://registry.opendata.aws/terrain-tiles/"
TERRARIUM_TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEFAULT_TERRAIN_ZOOM = 10
DEFAULT_TERRAIN_TIMEOUT_S = 3.0
EARTH_RADIUS_M = 6378137.0


def latlon_to_tile(lat: float, lon: float, zoom: int = DEFAULT_TERRAIN_ZOOM) -> tuple[int, int]:
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    lon = ((float(lon) + 180.0) % 360.0) - 180.0
    n = 2**int(zoom)
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def latlon_to_global_pixel(lat: float, lon: float, zoom: int = DEFAULT_TERRAIN_ZOOM) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    lon = ((float(lon) + 180.0) % 360.0) - 180.0
    scale = 256 * (2**int(zoom))
    x = (lon + 180.0) / 360.0 * scale
    lat_rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * scale
    return x, y


def global_pixel_to_latlon(x: float, y: float, zoom: int = DEFAULT_TERRAIN_ZOOM) -> list[float]:
    scale = 256 * (2**int(zoom))
    lon = (float(x) / scale) * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * float(y) / scale
    lat = math.degrees(math.atan(math.sinh(n)))
    return [round(lat, 7), round(lon, 7)]


def decode_terrarium_rgb(rgb: tuple[int, int, int] | tuple[int, int, int, int]) -> float:
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    return (r * 256.0 + g + b / 256.0) - 32768.0


def _tile_url(z: int, x: int, y: int) -> str:
    return TERRARIUM_TILE_URL.format(z=int(z), x=int(x), y=int(y))


def fetch_terrain_tile(*, z: int, x: int, y: int, timeout_s: float = DEFAULT_TERRAIN_TIMEOUT_S) -> Image.Image:
    response = requests.get(
        _tile_url(z, x, y),
        timeout=timeout_s,
        headers={"User-Agent": "local-flight/0.2.8 (+https://beacontools.cc/local-flight)"},
    )
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def terrain_features_from_tile(
    image: Image.Image,
    *,
    tile_x: int,
    tile_y: int,
    zoom: int,
    center_lat: float,
    center_lon: float,
    radius_nm: float,
) -> list[dict[str, Any]]:
    """Convert a single Terrarium tile into very quiet radar relief lines."""
    center_px, center_py = latlon_to_global_pixel(center_lat, center_lon, zoom)
    tile_origin_x = int(tile_x) * 256
    tile_origin_y = int(tile_y) * 256
    local_cx = center_px - tile_origin_x
    local_cy = center_py - tile_origin_y
    meters_per_pixel = 156543.03392 * math.cos(math.radians(float(center_lat))) / (2**int(zoom))
    radius_m = clamp_surface_radius_nm(radius_nm) * 1852.0
    span_px = int(max(18, min(112, radius_m / max(1.0, meters_per_pixel))))
    offsets = [-1.0, -0.66, -0.33, 0.0, 0.33, 0.66, 1.0]

    rows: list[tuple[float, list[tuple[float, float, float]]]] = []
    all_elevations: list[float] = []
    for row_idx, row_frac in enumerate(offsets):
        samples: list[tuple[float, float, float]] = []
        for col_frac in offsets:
            px = int(round(local_cx + col_frac * span_px))
            py = int(round(local_cy + row_frac * span_px))
            if px < 0 or py < 0 or px >= image.width or py >= image.height:
                continue
            elevation_m = decode_terrarium_rgb(image.getpixel((px, py)))
            global_x = tile_origin_x + px
            global_y = tile_origin_y + py
            lat, lon = global_pixel_to_latlon(global_x, global_y, zoom)
            samples.append((lat, lon, elevation_m))
            all_elevations.append(elevation_m)
        if len(samples) >= 2:
            rows.append((row_idx + 1, samples))

    if len(all_elevations) < 4:
        return []
    min_elev = min(all_elevations)
    max_elev = max(all_elevations)
    if (max_elev - min_elev) < 35.0:
        return []

    features: list[dict[str, Any]] = []
    for row_idx, samples in rows:
        avg_m = sum(sample[2] for sample in samples) / len(samples)
        if abs(avg_m - min_elev) < 12.0 and abs(avg_m - max_elev) < 12.0:
            continue
        features.append(
            {
                "kind": "relief",
                "id": f"terrain:{zoom}:{tile_x}:{tile_y}:{int(row_idx)}",
                "label": "",
                "elevation_ft": int(round(avg_m * 3.28084)),
                "points": [[lat, lon] for lat, lon, _elevation in samples],
            }
        )
        if len(features) >= 7:
            break
    return features


def build_terrain_payload(
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
        "provider": TERRAIN_PROVIDER,
        "schema_version": TERRAIN_SCHEMA_VERSION,
        "attribution": {"text": TERRAIN_ATTRIBUTION, "url": TERRAIN_LICENSE_URL},
        "center": {
            "lat": float(center_lat),
            "lon": float(center_lon),
            "airport_iata": str(airport_iata or "").upper(),
            "airport_icao": str(airport_icao or "").upper(),
        },
        "radius_nm": clamp_surface_radius_nm(radius_nm),
        "features": features,
    }
    if error:
        payload["error"] = str(error)[:300]
    return payload


def validate_terrain_payload(payload: dict[str, Any]) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("provider") == TERRAIN_PROVIDER
        and payload.get("schema_version") == TERRAIN_SCHEMA_VERSION
        and isinstance(payload.get("center"), dict)
        and isinstance(payload.get("features"), list)
    )


def fetch_terrain_context(
    *,
    airport_iata: str,
    airport_icao: str,
    center_lat: float,
    center_lon: float,
    radius_nm: float,
    zoom: int = DEFAULT_TERRAIN_ZOOM,
    timeout_s: float = DEFAULT_TERRAIN_TIMEOUT_S,
) -> dict[str, Any]:
    x, y = latlon_to_tile(center_lat, center_lon, zoom)
    image = fetch_terrain_tile(z=zoom, x=x, y=y, timeout_s=timeout_s)
    features = terrain_features_from_tile(
        image,
        tile_x=x,
        tile_y=y,
        zoom=zoom,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_nm=radius_nm,
    )
    return build_terrain_payload(
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_nm=radius_nm,
        features=features,
        cache_state="fresh",
    )
