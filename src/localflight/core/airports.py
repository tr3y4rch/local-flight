from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


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
