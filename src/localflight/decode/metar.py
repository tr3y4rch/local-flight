"""
Local Flight semantic METAR decoration.

This module does not fetch weather. It turns an already fetched METAR into a
small app-owned "weather mood" that the UI can render with friendly icons while
keeping METAR/flight category as the aviation source of truth.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

_WX_RE = re.compile(
    r"^(?:[-+]|VC)?"
    r"(?:(?:MI|PR|BC|DR|BL|SH|TS|FZ){0,2})"
    r"(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)+$"
)


def decorate_metar(decoded: Dict[str, Any]) -> Dict[str, Any]:
    """Return Local Flight weather UX fields derived from decoded/raw METAR."""
    raw_text = str(decoded.get("raw_text") or "").upper().replace("=", " ")
    tokens = [t.strip() for t in raw_text.split() if t.strip()]
    wx_tokens = _weather_tokens(tokens, str(decoded.get("wx_string") or ""))
    cloud_codes = _cloud_codes(tokens, decoded.get("clouds") or [])
    flight_cat = str(decoded.get("flight_cat") or "").upper()
    visibility_m = _to_float(decoded.get("visibility_m"))
    ceiling_ft = _to_float(decoded.get("ceiling_ft"))
    wind_speed = _to_float(decoded.get("wind_speed_kt"))
    wind_gust = _to_float(decoded.get("wind_gust_kt"))

    condition = _base_sky_condition(tokens, cloud_codes)
    icon = {
        "clear": "sun",
        "partly_cloudy": "partly",
        "cloudy": "cloud",
    }.get(condition, "unknown")
    label = {
        "clear": "Clear",
        "partly_cloudy": "Partly cloudy",
        "cloudy": "Cloudy",
    }.get(condition, "Weather observed")
    hazards: List[str] = []

    precip_intensity = _precip_intensity(wx_tokens)
    if _has_any(wx_tokens, ("TS", "VCTS")):
        condition, icon, label = "thunderstorm", "storm", "Thunderstorm"
        hazards.append("Thunderstorm near the field")
    elif _has_any(wx_tokens, ("FC",)):
        condition, icon, label = "thunderstorm", "storm", "Funnel cloud reported"
        hazards.append("Convective weather")
    elif _has_any(wx_tokens, ("FZRA", "FZDZ", "FZFG", "PL", "GR", "GS")):
        condition, icon, label = "ice", "ice", "Freezing precipitation"
        hazards.append("Icing risk")
    elif _has_any(wx_tokens, ("SN", "SG", "IC")):
        condition, icon = "snow", "snow"
        label = _intensity_label(precip_intensity, "snow")
    elif _has_any(wx_tokens, ("RA", "DZ", "SHRA")):
        condition, icon = "rain", "rain"
        label = _intensity_label(precip_intensity, "rain")
    elif _has_any(wx_tokens, ("FG", "BR", "HZ", "FU", "DU", "SA", "VA", "PY")):
        condition, icon, label = "fog", "fog", "Fog / haze"
    elif _has_any(wx_tokens, ("SQ",)):
        condition, icon, label = "windy", "wind", "Squalls"
        hazards.append("Squalls")

    if visibility_m is not None:
        if visibility_m < 1000:
            hazards.append("Very low visibility")
            if condition not in ("thunderstorm", "ice", "snow", "rain"):
                condition, icon, label = "fog", "fog", "Low visibility"
        elif visibility_m < 5000:
            hazards.append("Reduced visibility")

    if ceiling_ft is not None:
        if ceiling_ft < 500:
            hazards.append("Very low ceiling")
        elif ceiling_ft < 1500:
            hazards.append("Low ceiling")

    strong_wind = False
    if wind_gust is not None and wind_gust >= 30:
        strong_wind = True
        hazards.append("Strong gusts")
    elif wind_speed is not None and wind_speed >= 25:
        strong_wind = True
        hazards.append("Strong wind")
    elif wind_gust is not None and wind_gust >= 20:
        hazards.append("Gusty wind")

    if strong_wind and condition in ("clear", "partly_cloudy", "cloudy", "unknown"):
        condition, icon, label = "windy", "wind", "Windy"

    tone = _tone(flight_cat, condition, hazards, wx_tokens)
    summary = _weather_summary(label, flight_cat, decoded, hazards)
    chips = _weather_chips(label, flight_cat, decoded)

    payload = {
        "condition": condition,
        "icon": icon,
        "label": label,
        "tone": tone,
        "summary": summary,
        "hazards": _dedupe(hazards),
        "chips": chips,
        "source": "metar",
    }
    return {
        "weather": payload,
        "weather_condition": condition,
        "weather_icon": icon,
        "weather_label": label,
        "weather_tone": tone,
        "weather_summary": summary,
        "weather_hazards": payload["hazards"],
        "weather_chips": chips,
    }


def _weather_tokens(tokens: List[str], wx_string: str) -> List[str]:
    out: List[str] = []
    for source in [*tokens, *wx_string.upper().split()]:
        token = source.strip()
        if token in {"TS", "VCTS", "VCSH"}:
            out.append(token)
        elif token and _WX_RE.match(token):
            out.append(token)
    return _dedupe(out)


def _cloud_codes(tokens: List[str], clouds: List[Dict[str, Any]]) -> List[str]:
    codes: List[str] = []
    for token in tokens:
        if token in ("CAVOK", "CLR", "SKC", "NSC", "NCD"):
            codes.append(token)
        elif re.match(r"^(FEW|SCT|BKN|OVC|VV)\d{3}", token):
            codes.append(token[:3])
    for layer in clouds:
        cover = str(layer.get("cover") or "").upper()
        if cover:
            codes.append(cover)
    return _dedupe(codes)


def _base_sky_condition(tokens: List[str], cloud_codes: List[str]) -> str:
    if "CAVOK" in tokens or any(code in ("CLR", "SKC", "NSC", "NCD") for code in cloud_codes):
        return "clear"
    if any(code in ("BKN", "OVC", "VV") for code in cloud_codes):
        return "cloudy"
    if any(code in ("FEW", "SCT") for code in cloud_codes):
        return "partly_cloudy"
    return "unknown"


def _has_any(tokens: List[str], needles: tuple[str, ...]) -> bool:
    return any(any(needle in token for needle in needles) for token in tokens)


def _precip_intensity(tokens: List[str]) -> str:
    if any(token.startswith("+") for token in tokens):
        return "heavy"
    if any(token.startswith("-") for token in tokens):
        return "light"
    return "moderate"


def _intensity_label(intensity: str, noun: str) -> str:
    if intensity == "heavy":
        return f"Heavy {noun}"
    if intensity == "light":
        return f"Light {noun}"
    return noun.capitalize()


def _tone(flight_cat: str, condition: str, hazards: List[str], wx_tokens: List[str]) -> str:
    if condition in ("thunderstorm", "ice") or _has_any(wx_tokens, ("+TS", "+RA", "+SN", "FC")):
        return "bad"
    if flight_cat in ("IFR", "LIFR"):
        return "bad"
    if condition in ("fog", "snow") or any(
        h in hazards for h in ("Very low visibility", "Very low ceiling", "Strong gusts", "Strong wind")
    ):
        return "caution"
    if flight_cat == "MVFR" or hazards:
        return "caution"
    if flight_cat == "VFR" and condition in ("clear", "partly_cloudy"):
        return "good"
    return "neutral"


def _weather_summary(
    label: str,
    flight_cat: str,
    decoded: Dict[str, Any],
    hazards: List[str],
) -> str:
    parts = [label]
    if flight_cat:
        parts.append(flight_cat)
    wind = _wind_text(decoded)
    if wind:
        parts.append(wind)
    if hazards:
        parts.append(_dedupe(hazards)[0])
    return " · ".join(parts)


def _weather_chips(label: str, flight_cat: str, decoded: Dict[str, Any]) -> List[Dict[str, str]]:
    chips: List[Dict[str, str]] = [{"label": "WX", "value": label}]
    if flight_cat:
        chips.append({"label": "CAT", "value": flight_cat})
    wind = _wind_text(decoded)
    if wind:
        chips.append({"label": "WND", "value": wind})
    visibility = _visibility_text(_to_float(decoded.get("visibility_m")))
    if visibility:
        chips.append({"label": "VIS", "value": visibility})
    ceiling = _ceiling_text(_to_float(decoded.get("ceiling_ft")))
    if ceiling:
        chips.append({"label": "CLD", "value": ceiling})
    return chips


def _wind_text(decoded: Dict[str, Any]) -> str:
    speed = _to_float(decoded.get("wind_speed_kt"))
    gust = _to_float(decoded.get("wind_gust_kt"))
    direction = decoded.get("wind_dir_deg")
    if speed is None:
        return ""
    if speed == 0:
        return "Calm"
    try:
        direction_text = "VRB" if direction in (None, "VRB") else f"{int(float(direction)):03d}"
    except (TypeError, ValueError):
        direction_text = "VRB"
    gust_text = f"G{int(gust)}" if gust else ""
    return f"{direction_text} {int(speed)}{gust_text}kt"


def _visibility_text(value_m: float | None) -> str:
    if value_m is None:
        return ""
    if value_m >= 9999:
        return "10km+"
    if value_m >= 1000:
        return f"{value_m / 1000:.0f}km"
    return f"{int(value_m)}m"


def _ceiling_text(value_ft: float | None) -> str:
    if value_ft is None:
        return "CLR"
    return f"{int(value_ft)}ft"


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
