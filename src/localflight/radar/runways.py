from __future__ import annotations

import csv
import gzip
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from .geo import bearing_deg, distance_nm, float_or_none, heading_delta_deg, point_on_heading

OURAIRPORTS_RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"
_RUNWAY_CACHE_MAX_AGE_DAYS = 30
_RUNWAY_DOWNLOAD_TIMEOUT_S = 2.5


def _runway_data_path() -> Path:
    return Path(__file__).resolve().parents[1] / "decode" / "mappings" / "runways.csv.gz"


def _plain_runway_data_path() -> Path:
    return Path(__file__).resolve().parents[1] / "decode" / "mappings" / "runways.csv"


def _runway_cache_dir() -> Path:
    from localflight.storage.config import config_path

    path = config_path().parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runway_cache_path() -> Path:
    return _runway_cache_dir() / "runways.csv.gz"


def _runway_cache_meta_path() -> Path:
    return _runway_cache_dir() / "runways.meta.json"


def _clean(value: Any) -> str:
    return str(value or "").strip().upper()


def _boolish(value: Any) -> bool:
    clean = str(value or "").strip().lower()
    return clean in {"1", "true", "yes", "y"}


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def _load_ourairports_runways_cached() -> dict[str, list[dict[str, Any]]]:
    """Load optional OurAirports runways.csv(.gz), indexed by airport ICAO/ident."""
    rows = _read_rows(_runway_cache_path()) or _read_rows(_runway_data_path()) or _read_rows(_plain_runway_data_path())
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ident = _clean(row.get("airport_ident"))
        if not ident:
            continue
        low_ident = _clean(row.get("le_ident"))
        high_ident = _clean(row.get("he_ident"))
        endpoints = []
        for prefix, label in (("le", low_ident), ("he", high_ident)):
            lat = float_or_none(row.get(f"{prefix}_latitude_deg"))
            lon = float_or_none(row.get(f"{prefix}_longitude_deg"))
            heading = float_or_none(row.get(f"{prefix}_heading_degT"))
            elevation = float_or_none(row.get(f"{prefix}_elevation_ft"))
            if lat is not None and lon is not None:
                endpoints.append(
                    {
                        "ident": label,
                        "lat": lat,
                        "lon": lon,
                        "heading_deg": heading,
                        "elevation_ft": elevation,
                    }
                )
        if len(endpoints) < 2:
            continue
        item = {
            "kind": "runway",
            "id": f"ourairports:{ident}:{low_ident}-{high_ident}",
            "label": "/".join(part for part in (low_ident, high_ident) if part) or _clean(row.get("id")) or "RWY",
            "airport_ident": ident,
            "closed": _boolish(row.get("closed")),
            "lighted": _boolish(row.get("lighted")),
            "length_ft": float_or_none(row.get("length_ft")),
            "width_ft": float_or_none(row.get("width_ft")),
            "surface": row.get("surface"),
            "endpoints": endpoints,
            "points": [[round(endpoints[0]["lat"], 7), round(endpoints[0]["lon"], 7)], [round(endpoints[1]["lat"], 7), round(endpoints[1]["lon"], 7)]],
            "confidence": "ourairports",
            "data_source": "ourairports",
            "source_url": OURAIRPORTS_RUNWAYS_URL,
            "geometry_precision": "endpoint",
        }
        index.setdefault(ident, []).append(item)
    return index


def _cache_is_fresh(path: Path, *, max_age_days: int = _RUNWAY_CACHE_MAX_AGE_DAYS) -> bool:
    if not path.exists():
        return False
    try:
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return False
    return age <= timedelta(days=max(1, int(max_age_days)))


def refresh_ourairports_runway_cache(*, force: bool = False, timeout_s: float = _RUNWAY_DOWNLOAD_TIMEOUT_S) -> dict[str, Any]:
    """Download the public-domain OurAirports runway CSV into the user cache.

    The native radar can use this opportunistically, but a failed refresh should
    never break the radar screen. Callers may show the returned status in
    diagnostics if needed.
    """
    cache_path = _runway_cache_path()
    if not force and _cache_is_fresh(cache_path):
        return {"ok": True, "cache_state": "fresh", "path": str(cache_path)}

    response = requests.get(
        OURAIRPORTS_RUNWAYS_URL,
        timeout=timeout_s,
        headers={"Accept": "text/csv", "User-Agent": "local-flight/1.0 (+https://localflight.invalid)"},
    )
    response.raise_for_status()
    text = response.text
    if "airport_ident" not in text or "le_ident" not in text:
        raise ValueError("OurAirports runway CSV did not contain expected columns")

    with gzip.open(cache_path, "wt", encoding="utf-8", newline="") as handle:
        handle.write(text)
    meta = {
        "source": OURAIRPORTS_RUNWAYS_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "bytes": len(text.encode("utf-8")),
    }
    _runway_cache_meta_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _load_ourairports_runways_cached.cache_clear()
    return {"ok": True, "cache_state": "refreshed", "path": str(cache_path), **meta}


def load_ourairports_runways(*, auto_refresh: bool = False) -> dict[str, list[dict[str, Any]]]:
    if auto_refresh and not (_runway_cache_path().exists() or _runway_data_path().exists() or _plain_runway_data_path().exists()):
        try:
            refresh_ourairports_runway_cache()
        except Exception:
            pass
    return _load_ourairports_runways_cached()


def ourairports_runways_for(airport_icao: str | None, *, auto_refresh: bool = False) -> list[dict[str, Any]]:
    if not airport_icao:
        return []
    return [dict(item) for item in load_ourairports_runways(auto_refresh=auto_refresh).get(_clean(airport_icao), [])]


def runway_heading_from_points(points: list[Any]) -> float | None:
    if len(points) < 2:
        return None
    first = points[0]
    last = points[-1]
    if not isinstance(first, (list, tuple)) or not isinstance(last, (list, tuple)) or len(first) < 2 or len(last) < 2:
        return None
    lat1 = float_or_none(first[0])
    lon1 = float_or_none(first[1])
    lat2 = float_or_none(last[0])
    lon2 = float_or_none(last[1])
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    return round(bearing_deg(lat1, lon1, lat2, lon2), 1)


def _midpoint(points: list[Any]) -> tuple[float, float] | None:
    coords: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        lat = float_or_none(point[0])
        lon = float_or_none(point[1])
        if lat is not None and lon is not None:
            coords.append((lat, lon))
    if not coords:
        return None
    return sum(lat for lat, _lon in coords) / len(coords), sum(lon for _lat, lon in coords) / len(coords)


def _ourairports_heading_match(heading: float | None, candidate: dict[str, Any]) -> float | None:
    endpoints = candidate.get("endpoints") if isinstance(candidate.get("endpoints"), list) else []
    deltas = [
        heading_delta_deg(heading, endpoint.get("heading_deg"))
        for endpoint in endpoints
        if heading_delta_deg(heading, endpoint.get("heading_deg")) is not None
    ]
    return min(deltas) if deltas else None


def _ourairports_midpoint(candidate: dict[str, Any]) -> tuple[float, float] | None:
    return _midpoint(candidate.get("points") if isinstance(candidate.get("points"), list) else [])


def _match_ourairports_runway(
    *,
    osm_label: str,
    osm_points: list[Any],
    osm_heading: float | None,
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    osm_mid = _midpoint(osm_points)
    best: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    for candidate in candidates:
        cand_label = _clean(candidate.get("label"))
        label_match = bool(osm_label and cand_label and (osm_label == cand_label or osm_label in cand_label or cand_label in osm_label))
        heading_delta = _ourairports_heading_match(osm_heading, candidate)
        cand_mid = _ourairports_midpoint(candidate)
        midpoint_distance = None
        if osm_mid and cand_mid:
            midpoint_distance = distance_nm(osm_mid[0], osm_mid[1], cand_mid[0], cand_mid[1])
        if label_match:
            score = 0.0 + (heading_delta or 0.0) / 100.0
        elif heading_delta is not None and heading_delta <= 22.0 and midpoint_distance is not None and midpoint_distance <= 1.2:
            score = 10.0 + heading_delta + midpoint_distance
        else:
            continue
        validation = {
            "label_match": label_match,
            "heading_delta_deg": round(heading_delta, 1) if heading_delta is not None else None,
            "midpoint_distance_nm": round(midpoint_distance, 2) if midpoint_distance is not None else None,
        }
        if best is None or score < best[0]:
            best = (score, candidate, validation)
    if best:
        return best[1], best[2]
    return None, {}


def estimated_runway_from_center(
    *,
    center_lat: float,
    center_lon: float,
    label: str,
    heading_deg: float,
    length_nm: float,
) -> dict[str, Any]:
    start = point_on_heading(center_lat, center_lon, (heading_deg + 180.0) % 360.0, length_nm / 2.0)
    end = point_on_heading(center_lat, center_lon, heading_deg, length_nm / 2.0)
    return {
        "kind": "runway",
        "id": f"estimated:{label}",
        "label": label,
        "closed": False,
        "points": [start, end],
        "heading_deg": round(heading_deg % 360.0, 1),
        "confidence": "estimated",
    }


def merge_runways(
    *,
    airport_icao: str,
    center_lat: float,
    center_lon: float,
    surface_features: list[dict[str, Any]],
    auto_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Merge OSM drawable runways with optional OurAirports metadata."""
    osm_runways = [dict(f) for f in surface_features if str(f.get("kind") or "").lower() == "runway"]
    oa_runways = ourairports_runways_for(airport_icao, auto_refresh=auto_refresh)
    merged: list[dict[str, Any]] = []
    used_oa: set[str] = set()

    for osm in osm_runways:
        label = _clean(osm.get("label"))
        osm_points = osm.get("points") if isinstance(osm.get("points"), list) else []
        heading = runway_heading_from_points(osm_points)
        match, validation = _match_ourairports_runway(
            osm_label=label,
            osm_points=osm_points,
            osm_heading=heading,
            candidates=oa_runways,
        )
        item = dict(osm)
        item["heading_deg"] = heading
        if match:
            used_oa.add(str(match.get("id")))
            endpoints = match.get("endpoints") if isinstance(match.get("endpoints"), list) else []
            item.update(
                {
                    "confidence": "ourairports+osm",
                    "length_ft": match.get("length_ft"),
                    "width_ft": match.get("width_ft"),
                    "surface": match.get("surface"),
                    "lighted": match.get("lighted"),
                    "closed": bool(item.get("closed")) or bool(match.get("closed")),
                    "endpoints": endpoints,
                    "data_source": "openstreetmap+ourairports",
                    "source_url": OURAIRPORTS_RUNWAYS_URL,
                    "geometry_precision": "osm-polyline",
                }
            )
            if heading is not None and endpoints:
                endpoint_heading = endpoints[0].get("heading_deg")
                item["heading_delta_deg"] = heading_delta_deg(heading, endpoint_heading)
            item["validation"] = {
                "validated_by": ["openstreetmap", "ourairports-runways"],
                **validation,
            }
        else:
            item["confidence"] = "osm"
            item["data_source"] = "openstreetmap"
            item["geometry_precision"] = "osm-polyline"
            item["validation"] = {"validated_by": ["openstreetmap"], "label_match": False}
        merged.append(item)

    for oa in oa_runways:
        if str(oa.get("id")) not in used_oa:
            item = dict(oa)
            item.setdefault("data_source", "ourairports")
            item.setdefault("source_url", OURAIRPORTS_RUNWAYS_URL)
            item.setdefault("geometry_precision", "endpoint")
            item["validation"] = {"validated_by": ["ourairports-runways"], "label_match": True}
            merged.append(item)

    if not merged:
        merged.append(
            estimated_runway_from_center(
                center_lat=center_lat,
                center_lon=center_lon,
                label="EST RWY",
                heading_deg=45.0,
                length_nm=1.5,
            )
        )

    priority = {"ourairports+osm": 0, "ourairports": 1, "osm": 2, "estimated": 3}
    merged.sort(
        key=lambda item: (
            priority.get(str(item.get("confidence") or "").lower(), 9),
            bool(item.get("closed")),
            str(item.get("label") or ""),
            str(item.get("id") or ""),
        )
    )
    return merged[:24]
