from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional


_INDEX_FILE = Path(__file__).with_name("airports_index.json.gz")


@lru_cache(maxsize=1)
def _load_index() -> Dict[str, Any]:
    if not _INDEX_FILE.exists():
        raise FileNotFoundError(
            f"Airport index not found: {_INDEX_FILE}. "
            f"Generate it with: python scripts/build_airports_index.py"
        )

    with gzip.open(_INDEX_FILE, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def lookup_airport(code: str) -> Optional[Dict[str, Any]]:
    """
    Lookup by IATA (3) or ICAO (4) or whatever is present in OurAirports 'ident'.
    Returns the stored record dict or None.
    """
    c = (code or "").strip().upper()
    if not c:
        return None

    idx = _load_index()
    by_iata = idx.get("by_iata", {})
    by_icao = idx.get("by_icao", {})

    # Prefer IATA if present, but fall back to ICAO.
    return by_iata.get(c) or by_icao.get(c)


def format_airport(code: str, *, prefer: str = "city") -> str:
    """
    prefer:
      - "city" -> municipality if possible, else name, else code
      - "name" -> airport name if possible, else city, else code
      - "city_name" -> "City (Airport Name)" when both exist
    """
    rec = lookup_airport(code)
    c = (code or "").strip().upper()

    if not rec:
        return c or ""

    city = (rec.get("city") or "").strip()
    name = (rec.get("name") or "").strip()

    if prefer == "name":
        return name or city or c
    if prefer == "city_name":
        if city and name and city.lower() not in name.lower():
            return f"{city} ({name})"
        return city or name or c

    # default "city"
    return city or name or c
