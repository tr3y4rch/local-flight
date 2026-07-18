from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import math
from typing import Any

import requests
from PIL import Image

from localflight.version import user_agent


TERRAIN_SCHEMA_VERSION = "terrain-context-v2"
TERRAIN_PROVIDER = "aws-terrain-tiles"
TERRAIN_ATTRIBUTION = "Terrain Tiles on AWS"
TERRAIN_LICENSE_URL = "https://registry.opendata.aws/terrain-tiles/"
TERRARIUM_TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEFAULT_TERRAIN_ZOOM = 10
DEFAULT_TERRAIN_TIMEOUT_S = 3.0
MAX_TERRAIN_RADIUS_NM = 20.0
MAX_TERRAIN_TILES = 9
TERRAIN_GRID_SIZE = 17


def clamp_terrain_radius_nm(value: float) -> float:
    return max(1.0, min(MAX_TERRAIN_RADIUS_NM, float(value)))


def latlon_to_tile(lat: float, lon: float, zoom: int = DEFAULT_TERRAIN_ZOOM) -> tuple[int, int]:
    px, py = latlon_to_global_pixel(lat, lon, zoom)
    n = 2**int(zoom)
    return max(0, min(n - 1, int(px // 256))), max(0, min(n - 1, int(py // 256)))


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
        headers={"User-Agent": user_agent()},
    )
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def _meters_per_pixel(lat: float, zoom: int) -> float:
    return max(0.1, 156543.03392 * math.cos(math.radians(float(lat))) / (2**int(zoom)))


def _pixel_bounds(center_lat: float, center_lon: float, radius_nm: float, zoom: int) -> tuple[float, float, float, float]:
    center_x, center_y = latlon_to_global_pixel(center_lat, center_lon, zoom)
    span = clamp_terrain_radius_nm(radius_nm) * 1852.0 / _meters_per_pixel(center_lat, zoom)
    return center_x - span, center_y - span, center_x + span, center_y + span


def _tile_keys_for_bounds(bounds: tuple[float, float, float, float], zoom: int) -> list[tuple[int, int]]:
    min_x, min_y, max_x, max_y = bounds
    n = 2**int(zoom)
    keys: list[tuple[int, int]] = []
    for tile_y in range(max(0, int(min_y // 256)), min(n - 1, int(max_y // 256)) + 1):
        for tile_x in range(int(min_x // 256), int(max_x // 256) + 1):
            keys.append((tile_x % n, tile_y))
    return keys


def _adaptive_zoom(center_lat: float, center_lon: float, radius_nm: float, preferred: int) -> tuple[int, tuple[float, float, float, float], list[tuple[int, int]]]:
    zoom = max(7, min(12, int(preferred)))
    while True:
        bounds = _pixel_bounds(center_lat, center_lon, radius_nm, zoom)
        keys = _tile_keys_for_bounds(bounds, zoom)
        if len(keys) <= MAX_TERRAIN_TILES or zoom <= 7:
            return zoom, bounds, keys[:MAX_TERRAIN_TILES]
        zoom -= 1


def _sample_grid(
    tiles: dict[tuple[int, int], Image.Image],
    *,
    bounds: tuple[float, float, float, float],
    zoom: int,
    size: int = TERRAIN_GRID_SIZE,
) -> tuple[list[list[float]], list[list[list[float]]]]:
    min_x, min_y, max_x, max_y = bounds
    values: list[list[float]] = []
    points: list[list[list[float]]] = []
    for row in range(size):
        y = min_y + (max_y - min_y) * row / (size - 1)
        value_row: list[float] = []
        point_row: list[list[float]] = []
        for col in range(size):
            x = min_x + (max_x - min_x) * col / (size - 1)
            tile_x = int(x // 256) % (2**int(zoom))
            tile_y = int(y // 256)
            image = tiles.get((tile_x, tile_y))
            if image is None:
                raise RuntimeError("Terrain mosaic did not cover the requested area")
            px = max(0, min(image.width - 1, int(x - math.floor(x / 256) * 256)))
            py = max(0, min(image.height - 1, int(y - math.floor(y / 256) * 256)))
            value_row.append(decode_terrarium_rgb(image.getpixel((px, py))))
            point_row.append(global_pixel_to_latlon(x, y, zoom))
        values.append(value_row)
        points.append(point_row)
    return values, points


def _contour_interval_ft(relief_ft: float) -> int:
    if relief_ft <= 500:
        return 100
    if relief_ft <= 1500:
        return 250
    if relief_ft <= 4000:
        return 500
    return 1000


def _edge_point(
    level_m: float,
    value_a: float,
    value_b: float,
    point_a: list[float],
    point_b: list[float],
) -> list[float] | None:
    if (value_a < level_m and value_b < level_m) or (value_a > level_m and value_b > level_m):
        return None
    if value_a == value_b:
        return None
    fraction = max(0.0, min(1.0, (level_m - value_a) / (value_b - value_a)))
    return [
        round(point_a[0] + (point_b[0] - point_a[0]) * fraction, 7),
        round(point_a[1] + (point_b[1] - point_a[1]) * fraction, 7),
    ]


def terrain_features_from_grid(
    values: list[list[float]],
    points: list[list[list[float]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    flattened = [value for row in values for value in row]
    if not flattened:
        return [], [], {}
    min_m, max_m = min(flattened), max(flattened)
    min_ft, max_ft = min_m * 3.28084, max_m * 3.28084
    relief_ft = max_ft - min_ft
    interval_ft = _contour_interval_ft(relief_ft)

    bands: list[dict[str, Any]] = []
    rows = min(len(values), len(points))
    cols = min(len(values[0]), len(points[0])) if rows else 0
    for row in range(rows - 1):
        for col in range(cols - 1):
            average_m = (
                values[row][col]
                + values[row][col + 1]
                + values[row + 1][col + 1]
                + values[row + 1][col]
            ) / 4.0
            ratio = 0.0 if max_m == min_m else (average_m - min_m) / (max_m - min_m)
            bands.append(
                {
                    "kind": "terrain_band",
                    "id": f"terrain-band:{row}:{col}",
                    "label": "",
                    "band_index": min(4, int(ratio * 5)),
                    "elevation_ft": round(average_m * 3.28084),
                    "closed": True,
                    "points": [
                        points[row][col],
                        points[row][col + 1],
                        points[row + 1][col + 1],
                        points[row + 1][col],
                    ],
                }
            )

    start_ft = math.ceil(min_ft / interval_ft) * interval_ft
    levels_ft = list(range(int(start_ft), int(max_ft) + 1, interval_ft))
    if len(levels_ft) > 8:
        stride = math.ceil(len(levels_ft) / 8)
        levels_ft = levels_ft[::stride]
    contours: list[dict[str, Any]] = []
    for level_ft in levels_ft:
        level_m = level_ft / 3.28084
        for row in range(rows - 1):
            for col in range(cols - 1):
                corners = [
                    (values[row][col], points[row][col]),
                    (values[row][col + 1], points[row][col + 1]),
                    (values[row + 1][col + 1], points[row + 1][col + 1]),
                    (values[row + 1][col], points[row + 1][col]),
                ]
                intersections: list[list[float]] = []
                for index in range(4):
                    value_a, point_a = corners[index]
                    value_b, point_b = corners[(index + 1) % 4]
                    point = _edge_point(level_m, value_a, value_b, point_a, point_b)
                    if point is not None and point not in intersections:
                        intersections.append(point)
                if len(intersections) == 2:
                    pairs = [(intersections[0], intersections[1])]
                elif len(intersections) == 4:
                    pairs = [(intersections[0], intersections[1]), (intersections[2], intersections[3])]
                else:
                    pairs = []
                for first, second in pairs:
                    contours.append(
                        {
                            "kind": "contour",
                            "id": f"terrain-contour:{level_ft}:{row}:{col}:{len(contours)}",
                            "label": "",
                            "elevation_ft": level_ft,
                            "points": [first, second],
                        }
                    )
                    if len(contours) >= 360:
                        break
                if len(contours) >= 360:
                    break
            if len(contours) >= 360:
                break
        if len(contours) >= 360:
            break
    return bands, contours, {
        "min_elevation_ft": round(min_ft),
        "max_elevation_ft": round(max_ft),
        "contour_interval_ft": interval_ft,
    }


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
    bounds = _pixel_bounds(center_lat, center_lon, radius_nm, zoom)
    # Compatibility helper: callers provide one synthetic tile. Repeat that
    # sample over any adjacent keys touched by the requested test window.
    tiles = {key: image for key in _tile_keys_for_bounds(bounds, zoom)}
    tiles.setdefault((tile_x, tile_y), image)
    values, points = _sample_grid(tiles, bounds=bounds, zoom=zoom)
    bands, contours, _metadata = terrain_features_from_grid(values, points)
    return [*bands, *contours]


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
    bands: list[dict[str, Any]] | None = None,
    contours: list[dict[str, Any]] | None = None,
    elevation_meta: dict[str, Any] | None = None,
    zoom: int | None = None,
    tile_count: int | None = None,
) -> dict[str, Any]:
    band_rows = list(bands) if bands is not None else [item for item in features if item.get("kind") == "terrain_band"]
    contour_rows = list(contours) if contours is not None else [item for item in features if item.get("kind") == "contour"]
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
        "radius_nm": clamp_terrain_radius_nm(radius_nm),
        "coverage_radius_nm": clamp_terrain_radius_nm(radius_nm),
        "features": features,
        "bands": band_rows,
        "contours": contour_rows,
        **(elevation_meta or {}),
    }
    if zoom is not None:
        payload["zoom"] = int(zoom)
    if tile_count is not None:
        payload["tile_count"] = int(tile_count)
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
        and isinstance(payload.get("bands"), list)
        and isinstance(payload.get("contours"), list)
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
    radius = clamp_terrain_radius_nm(radius_nm)
    preferred_zoom = 11 if radius <= 5 else 10 if radius <= 10 else 9
    selected_zoom, bounds, tile_keys = _adaptive_zoom(center_lat, center_lon, radius, min(zoom, preferred_zoom))
    tiles = {
        key: fetch_terrain_tile(z=selected_zoom, x=key[0], y=key[1], timeout_s=timeout_s)
        for key in tile_keys
    }
    values, points = _sample_grid(tiles, bounds=bounds, zoom=selected_zoom)
    bands, contours, elevation_meta = terrain_features_from_grid(values, points)
    features = [*bands, *contours]
    return build_terrain_payload(
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_nm=radius,
        features=features,
        bands=bands,
        contours=contours,
        elevation_meta=elevation_meta,
        cache_state="fresh",
        zoom=selected_zoom,
        tile_count=len(tiles),
    )
