from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

# ── Timezone tables ────────────────────────────────────────────────────────────
# Region-level table handles multi-tz countries (US, CA, AU, RU, etc.).
# iso_region from OurAirports is "CC-XX" e.g. "US-CA", "AU-NSW".
_REGION_TZ: dict[str, str] = {
    # United States
    "US-AK": "America/Anchorage", "US-HI": "Pacific/Honolulu",
    "US-WA": "America/Los_Angeles", "US-OR": "America/Los_Angeles",
    "US-CA": "America/Los_Angeles", "US-NV": "America/Los_Angeles",
    "US-ID": "America/Boise",       "US-MT": "America/Denver",
    "US-WY": "America/Denver",      "US-CO": "America/Denver",
    "US-UT": "America/Denver",      "US-AZ": "America/Phoenix",
    "US-NM": "America/Denver",      "US-ND": "America/Chicago",
    "US-SD": "America/Chicago",     "US-NE": "America/Chicago",
    "US-KS": "America/Chicago",     "US-OK": "America/Chicago",
    "US-TX": "America/Chicago",     "US-MN": "America/Chicago",
    "US-IA": "America/Chicago",     "US-MO": "America/Chicago",
    "US-WI": "America/Chicago",     "US-IL": "America/Chicago",
    "US-MI": "America/Detroit",     "US-IN": "America/Indiana/Indianapolis",
    "US-OH": "America/New_York",    "US-KY": "America/New_York",
    "US-TN": "America/Chicago",     "US-AL": "America/Chicago",
    "US-MS": "America/Chicago",     "US-LA": "America/Chicago",
    "US-AR": "America/Chicago",     "US-GA": "America/New_York",
    "US-FL": "America/New_York",    "US-SC": "America/New_York",
    "US-NC": "America/New_York",    "US-VA": "America/New_York",
    "US-WV": "America/New_York",    "US-MD": "America/New_York",
    "US-DE": "America/New_York",    "US-PA": "America/New_York",
    "US-NJ": "America/New_York",    "US-NY": "America/New_York",
    "US-CT": "America/New_York",    "US-RI": "America/New_York",
    "US-MA": "America/New_York",    "US-VT": "America/New_York",
    "US-NH": "America/New_York",    "US-ME": "America/New_York",
    "US-DC": "America/New_York",
    # Canada
    "CA-BC": "America/Vancouver",  "CA-AB": "America/Edmonton",
    "CA-SK": "America/Regina",     "CA-MB": "America/Winnipeg",
    "CA-ON": "America/Toronto",    "CA-QC": "America/Toronto",
    "CA-NB": "America/Halifax",    "CA-NS": "America/Halifax",
    "CA-PE": "America/Halifax",    "CA-NL": "America/St_Johns",
    "CA-NT": "America/Yellowknife","CA-NU": "America/Rankin_Inlet",
    "CA-YT": "America/Whitehorse",
    # Australia
    "AU-WA": "Australia/Perth",    "AU-SA": "Australia/Adelaide",
    "AU-NT": "Australia/Darwin",   "AU-QLD": "Australia/Brisbane",
    "AU-NSW": "Australia/Sydney",  "AU-VIC": "Australia/Melbourne",
    "AU-TAS": "Australia/Hobart",  "AU-ACT": "Australia/Sydney",
    # Russia
    "RU-MOW": "Europe/Moscow",     "RU-SPE": "Europe/Moscow",
    "RU-KGD": "Europe/Kaliningrad","RU-SAM": "Europe/Samara",
    "RU-YEK": "Asia/Yekaterinburg","RU-OMS": "Asia/Omsk",
    "RU-KRS": "Asia/Krasnoyarsk",  "RU-IRK": "Asia/Irkutsk",
    "RU-YAK": "Asia/Yakutsk",      "RU-VVO": "Asia/Vladivostok",
    "RU-MAG": "Asia/Magadan",      "RU-CHUK": "Asia/Anadyr",
    # Brazil
    "BR-AM": "America/Manaus",     "BR-PA": "America/Belem",
    "BR-AC": "America/Rio_Branco", "BR-RR": "America/Boa_Vista",
    "BR-AP": "America/Belem",
    # Indonesia
    "ID-JK": "Asia/Jakarta",       "ID-BA": "Asia/Makassar",
    "ID-PA": "Asia/Jayapura",
    # Mexico
    "MX-BCN": "America/Tijuana",   "MX-SON": "America/Hermosillo",
    "MX-CHH": "America/Chihuahua", "MX-COA": "America/Monterrey",
}

_COUNTRY_TZ: dict[str, str] = {
    "AD": "Europe/Andorra",       "AE": "Asia/Dubai",
    "AF": "Asia/Kabul",           "AG": "America/Antigua",
    "AL": "Europe/Tirane",        "AM": "Asia/Yerevan",
    "AO": "Africa/Luanda",        "AR": "America/Argentina/Buenos_Aires",
    "AT": "Europe/Vienna",        "AU": "Australia/Sydney",
    "AZ": "Asia/Baku",            "BA": "Europe/Sarajevo",
    "BB": "America/Barbados",     "BD": "Asia/Dhaka",
    "BE": "Europe/Brussels",      "BF": "Africa/Ouagadougou",
    "BG": "Europe/Sofia",         "BH": "Asia/Bahrain",
    "BJ": "Africa/Porto-Novo",    "BN": "Asia/Brunei",
    "BO": "America/La_Paz",       "BR": "America/Sao_Paulo",
    "BS": "America/Nassau",       "BT": "Asia/Thimphu",
    "BW": "Africa/Gaborone",      "BY": "Europe/Minsk",
    "BZ": "America/Belize",       "CA": "America/Toronto",
    "CD": "Africa/Kinshasa",      "CF": "Africa/Bangui",
    "CG": "Africa/Brazzaville",   "CH": "Europe/Zurich",
    "CI": "Africa/Abidjan",       "CL": "America/Santiago",
    "CM": "Africa/Douala",        "CN": "Asia/Shanghai",
    "CO": "America/Bogota",       "CR": "America/Costa_Rica",
    "CU": "America/Havana",       "CV": "Atlantic/Cape_Verde",
    "CY": "Asia/Nicosia",         "CZ": "Europe/Prague",
    "DE": "Europe/Berlin",        "DJ": "Africa/Djibouti",
    "DK": "Europe/Copenhagen",    "DM": "America/Dominica",
    "DO": "America/Santo_Domingo","DZ": "Africa/Algiers",
    "EC": "America/Guayaquil",    "EE": "Europe/Tallinn",
    "EG": "Africa/Cairo",         "ER": "Africa/Asmara",
    "ES": "Europe/Madrid",        "ET": "Africa/Addis_Ababa",
    "FI": "Europe/Helsinki",      "FJ": "Pacific/Fiji",
    "FR": "Europe/Paris",         "GA": "Africa/Libreville",
    "GB": "Europe/London",        "GD": "America/Grenada",
    "GE": "Asia/Tbilisi",         "GH": "Africa/Accra",
    "GM": "Africa/Banjul",        "GN": "Africa/Conakry",
    "GQ": "Africa/Malabo",        "GR": "Europe/Athens",
    "GT": "America/Guatemala",    "GW": "Africa/Bissau",
    "GY": "America/Guyana",       "HK": "Asia/Hong_Kong",
    "HN": "America/Tegucigalpa",  "HR": "Europe/Zagreb",
    "HT": "America/Port-au-Prince","HU": "Europe/Budapest",
    "ID": "Asia/Jakarta",         "IE": "Europe/Dublin",
    "IL": "Asia/Jerusalem",       "IN": "Asia/Kolkata",
    "IQ": "Asia/Baghdad",         "IR": "Asia/Tehran",
    "IS": "Atlantic/Reykjavik",   "IT": "Europe/Rome",
    "JM": "America/Jamaica",      "JO": "Asia/Amman",
    "JP": "Asia/Tokyo",           "KE": "Africa/Nairobi",
    "KG": "Asia/Bishkek",         "KH": "Asia/Phnom_Penh",
    "KI": "Pacific/Tarawa",       "KM": "Indian/Comoro",
    "KN": "America/St_Kitts",     "KP": "Asia/Pyongyang",
    "KR": "Asia/Seoul",           "KW": "Asia/Kuwait",
    "KZ": "Asia/Almaty",          "LA": "Asia/Vientiane",
    "LB": "Asia/Beirut",          "LC": "America/St_Lucia",
    "LI": "Europe/Vaduz",         "LK": "Asia/Colombo",
    "LR": "Africa/Monrovia",      "LS": "Africa/Maseru",
    "LT": "Europe/Vilnius",       "LU": "Europe/Luxembourg",
    "LV": "Europe/Riga",          "LY": "Africa/Tripoli",
    "MA": "Africa/Casablanca",    "MC": "Europe/Monaco",
    "MD": "Europe/Chisinau",      "ME": "Europe/Podgorica",
    "MG": "Indian/Antananarivo",  "MK": "Europe/Skopje",
    "ML": "Africa/Bamako",        "MM": "Asia/Rangoon",
    "MN": "Asia/Ulaanbaatar",     "MO": "Asia/Macau",
    "MR": "Africa/Nouakchott",    "MT": "Europe/Malta",
    "MU": "Indian/Mauritius",     "MV": "Indian/Maldives",
    "MW": "Africa/Blantyre",      "MX": "America/Mexico_City",
    "MY": "Asia/Kuala_Lumpur",    "MZ": "Africa/Maputo",
    "NA": "Africa/Windhoek",      "NE": "Africa/Niamey",
    "NG": "Africa/Lagos",         "NI": "America/Managua",
    "NL": "Europe/Amsterdam",     "NO": "Europe/Oslo",
    "NP": "Asia/Kathmandu",       "NR": "Pacific/Nauru",
    "NZ": "Pacific/Auckland",     "OM": "Asia/Muscat",
    "PA": "America/Panama",       "PE": "America/Lima",
    "PG": "Pacific/Port_Moresby", "PH": "Asia/Manila",
    "PK": "Asia/Karachi",         "PL": "Europe/Warsaw",
    "PT": "Europe/Lisbon",        "PW": "Pacific/Palau",
    "PY": "America/Asuncion",     "QA": "Asia/Qatar",
    "RO": "Europe/Bucharest",     "RS": "Europe/Belgrade",
    "RU": "Europe/Moscow",        "RW": "Africa/Kigali",
    "SA": "Asia/Riyadh",          "SB": "Pacific/Guadalcanal",
    "SC": "Indian/Mahe",          "SD": "Africa/Khartoum",
    "SE": "Europe/Stockholm",     "SG": "Asia/Singapore",
    "SI": "Europe/Ljubljana",     "SK": "Europe/Bratislava",
    "SL": "Africa/Freetown",      "SM": "Europe/San_Marino",
    "SN": "Africa/Dakar",         "SO": "Africa/Mogadishu",
    "SR": "America/Paramaribo",   "SS": "Africa/Juba",
    "ST": "Africa/Sao_Tome",      "SV": "America/El_Salvador",
    "SY": "Asia/Damascus",        "SZ": "Africa/Mbabane",
    "TD": "Africa/Ndjamena",      "TG": "Africa/Lome",
    "TH": "Asia/Bangkok",         "TJ": "Asia/Dushanbe",
    "TL": "Asia/Dili",            "TM": "Asia/Ashgabat",
    "TN": "Africa/Tunis",         "TO": "Pacific/Tongatapu",
    "TR": "Europe/Istanbul",      "TT": "America/Port_of_Spain",
    "TV": "Pacific/Funafuti",     "TZ": "Africa/Dar_es_Salaam",
    "UA": "Europe/Kiev",          "UG": "Africa/Kampala",
    "US": "America/New_York",     "UY": "America/Montevideo",
    "UZ": "Asia/Tashkent",        "VA": "Europe/Vatican",
    "VC": "America/St_Vincent",   "VE": "America/Caracas",
    "VN": "Asia/Ho_Chi_Minh",     "VU": "Pacific/Efate",
    "WS": "Pacific/Apia",         "YE": "Asia/Aden",
    "ZA": "Africa/Johannesburg",  "ZM": "Africa/Lusaka",
    "ZW": "Africa/Harare",
}

_COUNTRY_DISPLAY_NAMES: dict[str, str] = {
    "AE": "United Arab Emirates",
    "AR": "Argentina",
    "AT": "Austria",
    "AU": "Australia",
    "BE": "Belgium",
    "BR": "Brazil",
    "CA": "Canada",
    "CH": "Switzerland",
    "CL": "Chile",
    "CN": "China",
    "CO": "Colombia",
    "DE": "Germany",
    "DK": "Denmark",
    "EG": "Egypt",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "GR": "Greece",
    "HK": "Hong Kong",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IN": "India",
    "IT": "Italy",
    "JP": "Japan",
    "KR": "South Korea",
    "MX": "Mexico",
    "MY": "Malaysia",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "PH": "Philippines",
    "PL": "Poland",
    "PT": "Portugal",
    "QA": "Qatar",
    "SA": "Saudi Arabia",
    "SE": "Sweden",
    "SG": "Singapore",
    "TH": "Thailand",
    "TR": "Turkey",
    "TW": "Taiwan",
    "US": "United States",
    "VN": "Vietnam",
    "ZA": "South Africa",
}


def get_airport_timezone(country: str, region: str) -> str:
    """Return IANA timezone for a given OurAirports country + region pair."""
    tz = _REGION_TZ.get(region.upper()) or _COUNTRY_TZ.get(country.upper())
    return tz or "UTC"


def country_display_name(country: str | None) -> str:
    code = _norm(country)
    return _COUNTRY_DISPLAY_NAMES.get(code, code)


@dataclass(frozen=True, slots=True)
class AirportRec:
    name: str
    city: str
    country: str
    region: str
    type: str
    lat: float | None
    lon: float | None
    iata: str | None
    icao: str | None


def _index_path() -> Path:
    """
    Offline airport index built by your script:
      src/localflight/decode/mappings/airports_index.json.gz
    """
    return (
        Path(__file__).resolve().parents[1]  # src/localflight
        / "decode"
        / "mappings"
        / "airports_index.json.gz"
    )


def _norm(s: str | None) -> str:
    return (s or "").strip().upper()


@lru_cache(maxsize=1)
def _load_index() -> dict[str, Any]:
    """
    Load once per process (cached).
    Structure from your script:
      { meta: {...}, by_iata: {...}, by_icao: {...} }
    """
    p = _index_path()
    if not p.exists():
        # No hard crash: UI can still run, it'll just show codes.
        return {"meta": {}, "by_iata": {}, "by_icao": {}}

    with gzip.open(p, "rb") as f:
        obj = json.loads(f.read().decode("utf-8"))

    if not isinstance(obj, dict):
        raise ValueError(f"Airport index must be a dict, got {type(obj)} in {p}")
    obj.setdefault("by_iata", {})
    obj.setdefault("by_icao", {})
    return obj


def lookup_airport(*, iata: str | None = None, icao: str | None = None) -> Optional[AirportRec]:
    idx = _load_index()
    by_iata = idx.get("by_iata") or {}
    by_icao = idx.get("by_icao") or {}

    rec: Any = None
    if iata:
        rec = by_iata.get(_norm(iata))
    if rec is None and icao:
        rec = by_icao.get(_norm(icao))

    if not isinstance(rec, dict):
        return None

    return AirportRec(
        name=str(rec.get("name") or "").strip(),
        city=str(rec.get("city") or "").strip(),
        country=str(rec.get("country") or "").strip(),
        region=str(rec.get("region") or "").strip(),
        type=str(rec.get("type") or "").strip(),
        lat=rec.get("lat") if isinstance(rec.get("lat"), (int, float)) else None,
        lon=rec.get("lon") if isinstance(rec.get("lon"), (int, float)) else None,
        iata=rec.get("iata"),
        icao=rec.get("icao"),
    )


def best_label(
    *,
    iata: str | None = None,
    icao: str | None = None,
    prefer: str = "city",
    include_code: bool = False,
) -> str:
    """
    Human-friendly airport label.

    prefer:
      - "city"   -> Zurich
      - "name"   -> Zurich Airport
      - "auto"   -> city if present else name else code

    include_code:
      - True  -> "Zurich (ZRH)"
      - False -> "Zurich"
    """
    code = _norm(iata or icao) or "???"
    ap = lookup_airport(iata=iata, icao=icao)

    if ap is None:
        return code

    pref = (prefer or "auto").strip().lower()

    if pref == "name":
        base = ap.name or ap.city or code
    elif pref == "city":
        base = ap.city or ap.name or code
    else:  # auto
        base = ap.city or ap.name or code

    if include_code:
        c = ap.iata or code
        return f"{base} ({c})"

    return base


def city_country_label(
    *,
    iata: str | None = None,
    icao: str | None = None,
    city: str | None = None,
    country: str | None = None,
) -> str:
    """Return a passenger-facing airport display label: City, Country."""
    ap = lookup_airport(iata=iata, icao=icao)
    city_text = str(city or (ap.city if ap else "") or "").strip()
    country_text = country_display_name(country or (ap.country if ap else ""))
    if city_text and country_text:
        return f"{city_text}, {country_text}"
    if city_text:
        return city_text
    if country_text:
        return country_text
    return _norm(iata or icao) or "LOCAL"
