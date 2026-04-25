from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Public domain, nightly updated dataset. :contentReference[oaicite:2]{index=2}
OURAIRPORTS_AIRPORTS_CSV = "https://davidmegginson.github.io/ourairports-data/airports.csv"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _download_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8")


def _norm(s: Optional[str]) -> str:
    return (s or "").strip()


def build_index(csv_text: str) -> Dict[str, Any]:
    """
    Build a compact index usable offline.

    We keep only what we need for display and lookup.
    """
    by_iata: Dict[str, Dict[str, Any]] = {}
    by_icao: Dict[str, Dict[str, Any]] = {}

    reader = csv.DictReader(csv_text.splitlines())
    for row in reader:
        iata = _norm(row.get("iata_code"))
        icao = _norm(row.get("ident"))  # ICAO-ish (also includes local codes sometimes)
        name = _norm(row.get("name"))
        city = _norm(row.get("municipality"))
        country = _norm(row.get("iso_country"))
        region = _norm(row.get("iso_region"))
        typ = _norm(row.get("type"))

        # Keep some coords for future features (map pins, distance, whatever).
        lat = _norm(row.get("latitude_deg"))
        lon = _norm(row.get("longitude_deg"))

        rec: Dict[str, Any] = {
            "name": name,
            "city": city,
            "country": country,
            "region": region,
            "type": typ,
            "lat": float(lat) if lat else None,
            "lon": float(lon) if lon else None,
            "iata": iata or None,
            "icao": icao or None,
        }

        # Add entries if codes exist.
        if iata:
            by_iata[iata.upper()] = rec
        if icao:
            by_icao[icao.upper()] = rec

    return {
        "meta": {
            "source": OURAIRPORTS_AIRPORTS_CSV,
            "generated_at": _utcnow_iso(),
        },
        "by_iata": by_iata,
        "by_icao": by_icao,
    }


def write_gz_json(obj: Dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(out_path, "wb") as f:
        f.write(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default="src/localflight/decode/mappings/airports_index.json.gz",
        help="Output path for the compressed airport index.",
    )
    args = ap.parse_args()

    out_path = Path(args.out).resolve()

    print(f"Downloading: {OURAIRPORTS_AIRPORTS_CSV}")
    csv_text = _download_text(OURAIRPORTS_AIRPORTS_CSV)

    print("Building index...")
    idx = build_index(csv_text)

    print(f"Writing: {out_path}")
    write_gz_json(idx, out_path)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
