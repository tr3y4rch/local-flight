"""
localflight/sources/web/opensky_radar.py

Fetches live aircraft position data from OpenSky Network for a
bounding box around a given airport. Used for the radar display.

Endpoint (no auth — anonymous, 100 req/day limit):
  https://opensky-network.org/api/states/all?lamin=&lomin=&lamax=&lomax=

With credentials (registered user, 1000 req/day):
  Same endpoint with HTTP Basic Auth.

State vector fields (index):
  0  icao24       - ICAO 24-bit address (hex)
  1  callsign     - callsign (may be None)
  2  origin_country
  3  time_position - unix timestamp of last position update
  4  last_contact  - unix timestamp of last signal
  5  longitude
  6  latitude
  7  baro_altitude - meters
  8  on_ground
  9  velocity      - m/s
  10 true_track    - degrees (0=N, clockwise)
  11 vertical_rate - m/s
  12 sensors
  13 geo_altitude  - meters
  14 squawk
  15 spi
  16 position_source
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

OPENSKY_BASE_URL = "https://opensky-network.org/api/states/all"
_TIMEOUT_S = 20
_NM_TO_DEG_LAT = 1 / 60.0  # 1 nautical mile = 1 arcminute of latitude


class OpenSkyError(RuntimeError):
    """Raised for OpenSky client errors."""


def _nm_to_deg_lon(lat_deg: float) -> float:
    """Convert nautical miles to degrees longitude at a given latitude."""
    return _NM_TO_DEG_LAT / math.cos(math.radians(lat_deg))


def bounding_box(
    lat: float,
    lon: float,
    radius_nm: float = 50.0,
) -> tuple[float, float, float, float]:
    """
    Returns (lamin, lomin, lamax, lomax) for a circle approximated
    as a bounding box around (lat, lon) with given radius in nautical miles.
    """
    d_lat = radius_nm * _NM_TO_DEG_LAT
    d_lon = radius_nm * _nm_to_deg_lon(lat)
    return (
        lat - d_lat,
        lon - d_lon,
        lat + d_lat,
        lon + d_lon,
    )


def _get_auth() -> Optional[tuple[str, str]]:
    """Returns (username, password) from env vars, or None for anonymous."""
    user   = os.getenv("OPENSKY_CLIENT_ID", "").strip()
    secret = os.getenv("OPENSKY_CLIENT_SECRET", "").strip()
    if user and secret:
        return (user, secret)
    return None


def fetch_radar_blips(
    *,
    lat: float,
    lon: float,
    radius_nm: float = 50.0,
    timeout_s: int = _TIMEOUT_S,
) -> List[Dict[str, Any]]:
    """
    Fetch live aircraft positions within radius_nm of (lat, lon).

    Returns a list of blip dicts:
      {
        icao24:    str,
        callsign:  str,
        lat:       float,
        lon:       float,
        altitude_m: float | None,   # barometric altitude in metres
        heading:   float | None,    # true track degrees (0=N)
        speed_ms:  float | None,    # ground speed m/s
        on_ground: bool,
      }

    Filters out:
      - Aircraft with no position (lat/lon None)
      - Aircraft on ground (on_ground=True) — optional, kept for now
    """
    lamin, lomin, lamax, lomax = bounding_box(lat, lon, radius_nm)

    params = {
        "lamin": round(lamin, 6),
        "lomin": round(lomin, 6),
        "lamax": round(lamax, 6),
        "lomax": round(lomax, 6),
    }

    auth = _get_auth()

    try:
        r = requests.get(
            OPENSKY_BASE_URL,
            params=params,
            auth=auth,
            timeout=timeout_s,
            headers={"User-Agent": "local-flight/1.0 (+https://localflight.invalid)"},
        )
    except requests.RequestException as exc:
        raise OpenSkyError(f"OpenSky request failed: {exc}") from exc

    if r.status_code == 429:
        raise OpenSkyError("OpenSky rate limit exceeded (100 req/day anonymous, 1000 with account)")
    if r.status_code >= 400:
        raise OpenSkyError(f"OpenSky HTTP {r.status_code}")

    try:
        data = r.json()
    except Exception as exc:
        raise OpenSkyError(f"OpenSky response not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise OpenSkyError("Unexpected OpenSky payload shape")

    states = data.get("states") or []
    blips: List[Dict[str, Any]] = []

    for sv in states:
        if not isinstance(sv, list) or len(sv) < 17:
            continue

        lat_pos = sv[6]
        lon_pos = sv[5]

        if lat_pos is None or lon_pos is None:
            continue

        callsign = (sv[1] or "").strip().upper() or (sv[0] or "").upper()

        blips.append({
            "icao24":     (sv[0] or "").upper(),
            "callsign":   callsign,
            "lat":        float(lat_pos),
            "lon":        float(lon_pos),
            "altitude_m": float(sv[7]) if sv[7] is not None else None,
            "heading":    float(sv[10]) if sv[10] is not None else None,
            "speed_ms":   float(sv[9])  if sv[9]  is not None else None,
            "vertical_rate": float(sv[11]) if sv[11] is not None else None,
            "on_ground":  bool(sv[8]),
        })

    log.info(
        "OpenSky radar: %d blips within %.0fnm of (%.4f, %.4f)",
        len(blips), radius_nm, lat, lon,
    )
    return blips
