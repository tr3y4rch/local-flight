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
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from localflight.decode.metar import decorate_metar
from localflight.version import user_agent

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
            headers={"User-Agent": user_agent()},
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

    icao = str(_first(raw, "station_id", "stationId", "icaoId", "icao") or "").upper()
    raw_text = str(_first(raw, "raw_ob", "rawOb", "raw_text", "rawText") or "").strip()
    # AviationWeather has changed its JSON aliases over time. The raw report is
    # the compatibility floor and fills any structured field the active schema
    # omits; valid structured values still take precedence below.
    raw_fallback = decode_raw_metar(icao, raw_text) if raw_text else {}

    # Clouds
    clouds: List[Dict[str, Any]] = []
    for layer in (_first(raw, "clouds", "cloudLayers") or []):
        cover = str(_first(layer, "cover", "coverage") or "").upper()
        base_ft = _first(layer, "base", "base_ft", "baseFt")
        clouds.append({"cover": cover, "base_ft": base_ft})
    if not clouds:
        clouds = list(raw_fallback.get("clouds") or [])

    # Ceiling = lowest BKN or OVC layer
    ceiling_ft: Optional[int] = None
    for layer in clouds:
        if layer["cover"] in ("BKN", "OVC") and layer["base_ft"] is not None:
            if ceiling_ft is None or layer["base_ft"] < ceiling_ft:
                ceiling_ft = layer["base_ft"]

    # Flight category — use API value if present, else derive
    flight_cat = str(_first(raw, "flight_cat", "flightCat", "fltCat") or raw_fallback.get("flight_cat") or "").upper().strip()
    if not flight_cat:
        flight_cat = _derive_flight_cat(
            vis_m=raw_fallback.get("visibility_m"),
            ceiling_ft=ceiling_ft,
        )

    # Wind
    wind_dir = _first(raw, "wind_dir", "windDir", "wdir")
    wind_spd = _first(raw, "wind_speed", "windSpeed", "wspd")
    wind_gust = _first(raw, "wind_gust", "windGust", "wgst")
    if wind_dir is None:
        wind_dir = raw_fallback.get("wind_dir_deg")
    if wind_spd is None:
        wind_spd = raw_fallback.get("wind_speed_kt")
    if wind_gust is None:
        wind_gust = raw_fallback.get("wind_gust_kt")

    # Visibility — API returns statute miles, convert to metres
    vis_sm = _parse_visibility_sm(_first(raw, "visibility", "visibility_sm", "visibilitySm", "visib"))
    if vis_sm is None:
        vis_sm = raw_fallback.get("visibility_sm")
    vis_m: Optional[float] = None
    if vis_sm is not None:
        try:
            vis_m = float(vis_sm) * 1609.34
        except (ValueError, TypeError):
            vis_m = None

    # Altimeter
    altim_hg = _first(raw, "altim_in_hg", "altimInHg")
    altim_hpa: Optional[float] = None
    if altim_hg is not None:
        try:
            altim_hpa = round(float(altim_hg) * 33.8639, 1)
        except (ValueError, TypeError):
            pass
    if altim_hpa is None:
        current_altim = _first(raw, "altim", "altimeter", "altimeter_hpa", "altimeterHpa")
        try:
            numeric_altim = float(current_altim)
            altim_hpa = round(numeric_altim * 33.8639, 1) if numeric_altim < 40 else round(numeric_altim, 1)
        except (ValueError, TypeError):
            altim_hpa = raw_fallback.get("altimeter_hpa")

    temp_c = _first(raw, "temp", "temp_c", "tempC")
    dewpoint_c = _first(raw, "dewp", "dewpoint", "dewpoint_c", "dewpC")
    if temp_c is None:
        temp_c = raw_fallback.get("temp_c")
    if dewpoint_c is None:
        dewpoint_c = raw_fallback.get("dewpoint_c")
    wx_string = str(_first(raw, "wx_string", "wxString", "weather") or raw_fallback.get("wx_string") or "")

    decoded = {
        "icao":           icao,
        "raw_text":       raw_text,
        "obs_time":       _first(raw, "obs_time", "obsTime", "reportTime") or raw_fallback.get("obs_time", ""),
        "flight_cat":     flight_cat,
        "temp_c":         temp_c,
        "dewpoint_c":     dewpoint_c,
        "wind_dir_deg":   wind_dir,
        "wind_speed_kt":  wind_spd,
        "wind_gust_kt":   wind_gust,
        "visibility_m":   vis_m,
        "visibility_sm":  vis_sm,
        "ceiling_ft":     ceiling_ft,
        "clouds":         clouds,
        "wx_string":      wx_string,
        "altimeter_hpa":  altim_hpa,
        "flight_cat_color": _flight_cat_color(flight_cat),
        "decoded_summary": _summary({"temp": temp_c, "dewp": dewpoint_c, "wx_string": wx_string}, flight_cat, wind_dir, wind_spd,
                                     wind_gust, vis_m, ceiling_ft, altim_hpa),
    }
    decoded.update(decorate_metar(decoded))
    return decoded


def _first(values: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = values.get(key)
        if value is not None and value != "":
            return value
    return None


def _parse_visibility_sm(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).upper().strip().replace("SM", "")
    text = text.lstrip("P><").rstrip("+")
    less_than = text.startswith("M")
    if less_than:
        text = text[1:]
    try:
        if " " in text:
            whole, fraction = text.split(None, 1)
            numerator, denominator = fraction.split("/", 1)
            result = float(whole) + float(numerator) / float(denominator)
        elif "/" in text:
            numerator, denominator = text.split("/", 1)
            result = float(numerator) / float(denominator)
        else:
            result = float(text)
    except (ValueError, TypeError, ZeroDivisionError):
        return None
    # A less-than report still needs a useful conservative numeric boundary.
    return result if not less_than else max(0.0, result)


def decode_raw_metar(
    icao: str,
    raw_text: str,
    *,
    source: str = "metar",
) -> Dict[str, Any]:
    """Decode a raw METAR string from non-aviationweather sources."""
    icao = icao.upper().strip()
    raw_text = str(raw_text or "").strip().replace("\n", " ").replace("\r", " ")
    raw_text = re.sub(r"\s+", " ", raw_text).strip()
    tokens = raw_text.upper().replace("=", " ").split()

    wind_dir: Any = None
    wind_spd: Any = None
    wind_gust: Any = None
    for token in tokens:
        match = re.match(r"^(VRB|\d{3})(\d{2,3})(?:G(\d{2,3}))?KT$", token)
        if match:
            wind_dir = None if match.group(1) == "VRB" else int(match.group(1))
            wind_spd = int(match.group(2))
            wind_gust = int(match.group(3)) if match.group(3) else None
            break

    vis_m: Optional[float] = None
    vis_sm: Optional[float] = None
    if "CAVOK" in tokens:
        vis_m = 10000.0
        vis_sm = round(vis_m / 1609.34, 1)
    else:
        for index, token in enumerate(tokens):
            if token == "9999":
                vis_m = 10000.0
                vis_sm = round(vis_m / 1609.34, 1)
                break
            if re.match(r"^\d{4}$", token):
                vis_m = float(token)
                vis_sm = round(vis_m / 1609.34, 1)
                break
            if token.endswith("SM"):
                visibility_token = token[:-2]
                if "/" in visibility_token and index > 0 and tokens[index - 1].isdigit():
                    visibility_token = f"{tokens[index - 1]} {visibility_token}"
                vis_sm = _parse_visibility_sm(visibility_token)
            if vis_sm is not None:
                vis_m = vis_sm * 1609.34
                break

    clouds: List[Dict[str, Any]] = []
    for token in tokens:
        match = re.match(r"^(FEW|SCT|BKN|OVC|VV)(\d{3})(?:CB|TCU)?$", token)
        if match:
            clouds.append({"cover": match.group(1), "base_ft": int(match.group(2)) * 100})
        elif token in {"CLR", "SKC", "NSC", "NCD"}:
            clouds.append({"cover": token, "base_ft": None})

    ceiling_ft: Optional[int] = None
    for layer in clouds:
        if layer["cover"] in ("BKN", "OVC", "VV") and layer["base_ft"] is not None:
            if ceiling_ft is None or layer["base_ft"] < ceiling_ft:
                ceiling_ft = layer["base_ft"]

    temp_c: Optional[int] = None
    dewp_c: Optional[int] = None
    for token in tokens:
        match = re.match(r"^(M?\d{2}|//)/(M?\d{2}|//)$", token)
        if match:
            temp_c = _parse_signed_metar_temp(match.group(1))
            dewp_c = _parse_signed_metar_temp(match.group(2))
            break

    altim_hpa: Optional[float] = None
    for token in tokens:
        if re.match(r"^Q\d{4}$", token):
            altim_hpa = float(token[1:])
            break
        if re.match(r"^A\d{4}$", token):
            inches = float(token[1:]) / 100.0
            altim_hpa = round(inches * 33.8639, 1)
            break

    wx_tokens = [
        token for token in tokens
        if re.match(r"^(?:[-+]|VC)?(?:(?:MI|PR|BC|DR|BL|SH|TS|FZ){0,2})(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+$", token)
    ]
    flight_cat = _derive_flight_cat(vis_m=vis_m, ceiling_ft=ceiling_ft)
    raw = {"temp": temp_c, "dewp": dewp_c, "wx_string": " ".join(wx_tokens)}

    decoded = {
        "icao": icao,
        "raw_text": raw_text,
        "obs_time": datetime.now(timezone.utc).isoformat(),
        "flight_cat": flight_cat,
        "temp_c": temp_c,
        "dewpoint_c": dewp_c,
        "wind_dir_deg": wind_dir,
        "wind_speed_kt": wind_spd,
        "wind_gust_kt": wind_gust,
        "visibility_m": vis_m,
        "visibility_sm": vis_sm,
        "ceiling_ft": ceiling_ft,
        "clouds": clouds,
        "wx_string": " ".join(wx_tokens),
        "altimeter_hpa": altim_hpa,
        "flight_cat_color": _flight_cat_color(flight_cat),
        "decoded_summary": _summary(raw, flight_cat, wind_dir, wind_spd, wind_gust, vis_m, ceiling_ft, altim_hpa),
        "source": source,
    }
    decoded.update(decorate_metar(decoded))
    return decoded


def _parse_signed_metar_temp(value: str) -> Optional[int]:
    if not value or value == "//":
        return None
    if value.startswith("M"):
        return -int(value[1:])
    return int(value)


def _derive_flight_cat(
    vis_m: Optional[float],
    ceiling_ft: Optional[int],
) -> str:
    """Derive flight category from visibility and ceiling."""
    vis_sm = (vis_m / 1609.34) if vis_m is not None else None
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
