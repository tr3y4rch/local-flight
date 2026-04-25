"""
localflight/sources/web/metar_client.py

Fetches and decodes METAR data from aviationweather.gov.
Completely free, no API key, no rate limit.

Endpoints:
  JSON: https://aviationweather.gov/api/data/metar?ids=LSZH&format=json
  Raw:  https://aviationweather.gov/api/data/metar?ids=LSZH&format=raw

Decoded fields:
  raw_text     - original METAR string
  flight_cat   - VFR / MVFR / IFR / LIFR
  temp_c       - temperature °C
  dewpoint_c   - dewpoint °C
  wind_dir_deg - wind direction degrees (None if variable)
  wind_speed_kt- wind speed knots
  wind_gust_kt - wind gust knots (None if none)
  visibility_m - visibility metres
  ceiling_ft   - lowest broken/overcast layer feet (None if clear)
  wx_string    - weather phenomena (e.g. "-RA", "TSRA", "FG")
  clouds       - list of {cover, base_ft}
  altimeter_hpa- QNH in hPa
  obs_time     - observation time ISO string
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

METAR_URL = "https://aviationweather.gov/api/data/metar"
_TIMEOUT_S = 10
_CACHE: Dict[str, Any] = {}  # simple in-memory cache keyed by ICAO
_CACHE_TTL_S = 1800          # 30 minutes — METAR updates hourly


class METARError(RuntimeError):
    pass


def _cache_valid(icao: str) -> bool:
    entry = _CACHE.get(icao)
    if not entry:
        return False
    age = (datetime.now(timezone.utc) - entry["fetched_at"]).total_seconds()
    return age < _CACHE_TTL_S


def fetch_metar(icao: str, timeout_s: int = _TIMEOUT_S) -> Optional[Dict[str, Any]]:
    """
    Fetch and decode METAR for an airport ICAO code.
    Returns decoded dict or None if unavailable.
    Uses in-memory cache with 30-minute TTL.
    """
    icao = icao.upper().strip()

    if _cache_valid(icao):
        log.debug("METAR cache hit: %s", icao)
        return _CACHE[icao]["data"]

    try:
        r = requests.get(
            METAR_URL,
            params={"ids": icao, "format": "json"},
            timeout=timeout_s,
            headers={"User-Agent": "local-flight/1.0 (+https://localflight.invalid)"},
        )
    except requests.RequestException as exc:
        log.warning("METAR fetch failed for %s: %s", icao, exc)
        return None

    if r.status_code >= 400:
        log.warning("METAR HTTP %s for %s", r.status_code, icao)
        return None

    try:
        data = r.json()
    except Exception as exc:
        log.warning("METAR JSON parse failed: %s", exc)
        return None

    if not data or not isinstance(data, list):
        log.warning("METAR no data for %s", icao)
        return None

    raw = data[0]
    decoded = _decode(raw)

    _CACHE[icao] = {
        "data":       decoded,
        "fetched_at": datetime.now(timezone.utc),
    }

    log.info("METAR fetched: %s — %s", icao, decoded.get("raw_text", "")[:60])
    return decoded


def _decode(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Parse aviationweather.gov JSON METAR into clean dict."""

    # Clouds
    clouds: List[Dict[str, Any]] = []
    for layer in (raw.get("clouds") or []):
        cover   = layer.get("cover", "")
        base_ft = layer.get("base")
        clouds.append({"cover": cover, "base_ft": base_ft})

    # Ceiling = lowest BKN or OVC layer
    ceiling_ft: Optional[int] = None
    for layer in clouds:
        if layer["cover"] in ("BKN", "OVC") and layer["base_ft"] is not None:
            if ceiling_ft is None or layer["base_ft"] < ceiling_ft:
                ceiling_ft = layer["base_ft"]

    # Flight category — use API value if present, else derive
    flight_cat = (raw.get("flight_cat") or "").upper().strip()
    if not flight_cat:
        flight_cat = _derive_flight_cat(
            vis_m=raw.get("visibility"),
            ceiling_ft=ceiling_ft,
        )

    # Wind
    wind_dir  = raw.get("wind_dir")
    wind_spd  = raw.get("wind_speed")
    wind_gust = raw.get("wind_gust")

    # Visibility — API returns statute miles, convert to metres
    vis_sm = raw.get("visibility")
    vis_m: Optional[float] = None
    if vis_sm is not None:
        try:
            vis_m = float(vis_sm) * 1609.34
        except (ValueError, TypeError):
            vis_m = None

    # Altimeter
    altim_hg = raw.get("altim_in_hg")
    altim_hpa: Optional[float] = None
    if altim_hg is not None:
        try:
            altim_hpa = round(float(altim_hg) * 33.8639, 1)
        except (ValueError, TypeError):
            pass

    return {
        "icao":           raw.get("station_id", ""),
        "raw_text":       raw.get("raw_ob", raw.get("rawOb", "")),
        "obs_time":       raw.get("obs_time", raw.get("obsTime", "")),
        "flight_cat":     flight_cat,
        "temp_c":         raw.get("temp"),
        "dewpoint_c":     raw.get("dewp"),
        "wind_dir_deg":   wind_dir,
        "wind_speed_kt":  wind_spd,
        "wind_gust_kt":   wind_gust,
        "visibility_m":   vis_m,
        "visibility_sm":  vis_sm,
        "ceiling_ft":     ceiling_ft,
        "clouds":         clouds,
        "wx_string":      raw.get("wx_string", ""),
        "altimeter_hpa":  altim_hpa,
        "flight_cat_color": _flight_cat_color(flight_cat),
        "decoded_summary": _summary(raw, flight_cat, wind_dir, wind_spd,
                                     wind_gust, vis_m, ceiling_ft, altim_hpa),
    }


def _derive_flight_cat(
    vis_m: Optional[float],
    ceiling_ft: Optional[int],
) -> str:
    """Derive flight category from visibility and ceiling."""
    vis_sm = (vis_m / 1609.34) if vis_m else None
    c = ceiling_ft

    if (vis_sm is not None and vis_sm < 1) or (c is not None and c < 500):
        return "LIFR"
    if (vis_sm is not None and vis_sm < 3) or (c is not None and c < 1000):
        return "IFR"
    if (vis_sm is not None and vis_sm < 5) or (c is not None and c < 3000):
        return "MVFR"
    return "VFR"


def _flight_cat_color(cat: str) -> str:
    return {
        "VFR":  "#00c040",
        "MVFR": "#4080ff",
        "IFR":  "#ff4040",
        "LIFR": "#ff40ff",
    }.get(cat, "#888888")


def _summary(
    raw: Dict,
    flight_cat: str,
    wind_dir: Any,
    wind_spd: Any,
    wind_gust: Any,
    vis_m: Optional[float],
    ceiling_ft: Optional[int],
    altim_hpa: Optional[float],
) -> str:
    """Build a compact decoded summary string for the FIDS display."""
    parts: List[str] = []

    # Wind
    if wind_dir is not None and wind_spd is not None:
        try:
            gust = f"G{int(wind_gust)}kt" if wind_gust else ""
            parts.append(f"↑{int(wind_dir):03d}° {int(wind_spd)}{gust}kt")
        except (ValueError, TypeError):
            pass
    elif wind_spd == 0 or wind_dir == 0:
        parts.append("CALM")

    # Visibility
    if vis_m is not None:
        try:
            if vis_m >= 9999:
                parts.append("10km+")
            elif vis_m >= 1000:
                parts.append(f"{vis_m/1000:.0f}km")
            else:
                parts.append(f"{int(vis_m)}m")
        except (ValueError, TypeError):
            pass

    # Weather phenomena
    wx = (raw.get("wx_string") or "").strip()
    if wx:
        parts.append(wx)

    # Ceiling
    if ceiling_ft is not None:
        parts.append(f"CEIL {ceiling_ft}ft")
    else:
        parts.append("CLR")

    # Temp/dew
    temp = raw.get("temp")
    dewp = raw.get("dewp")
    if temp is not None:
        try:
            td = f"/{int(dewp)}" if dewp is not None else ""
            parts.append(f"{int(temp)}{td}°C")
        except (ValueError, TypeError):
            pass

    # QNH
    if altim_hpa is not None:
        parts.append(f"Q{int(altim_hpa)}")

    # Flight category
    parts.append(flight_cat)

    return " · ".join(parts)