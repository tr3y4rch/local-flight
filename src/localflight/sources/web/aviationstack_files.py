from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


class PayloadKind(str, Enum):
    RAW = "raw"          # aviationstack shape: {"data": [...]}
    SNAPSHOT = "snapshot"  # our snapshot shape: {"flights": [...]}
    EITHER = "either"


def _repo_root() -> Path:
    """
    Robust-ish repo root detection.

    This file lives at:
      src/localflight/sources/web/aviationstack_files.py

    We walk upwards until we find a folder that looks like the repo root.
    """
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        # Your repo root clearly has /src and /data
        if (p / "src" / "localflight").is_dir() and (p / "data").is_dir():
            return p
        # fallback: some repos only have /src but still fine for us
        if (p / "src" / "localflight").is_dir() and (p / ".github").is_dir():
            return p

    # last resort: original assumption (parents[4]) so we don't explode
    return here.parents[4]


def _localflight_root() -> Path:
    # src/localflight
    return Path(__file__).resolve().parents[2]


def _cache_file() -> Path:
    # repo-root/data/cache/aviationstack_last.json
    return _repo_root() / "data" / "cache" / "aviationstack_last.json"


def _snapshots_dir(airport_iata: str) -> Path:
    # src/localflight/storage/data/<IATA>/snapshots
    return (
        _localflight_root()
        / "storage"
        / "data"
        / airport_iata.upper().strip()
        / "snapshots"
    )


def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _looks_like_raw_aviationstack(obj: Any) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("data"), list)


def _looks_like_snapshot(obj: Any) -> bool:
    # Your flights_store.py writes: airport_iata, generated_at, count, flights:[...]
    return isinstance(obj, dict) and isinstance(obj.get("flights"), list)


def find_latest_local_payload_path(
    *,
    airport_iata: str,
    kind: PayloadKind = PayloadKind.EITHER,
) -> Optional[Path]:
    """
    Pick the newest payload we can find from local files only.

    Candidates:
      - repo-root/data/cache/aviationstack_last.json  (raw aviationstack typically)
      - newest JSON under src/localflight/storage/data/<IATA>/snapshots/*.json (your snapshots)

    kind:
      - RAW: only accept {"data":[...]}
      - SNAPSHOT: only accept {"flights":[...]}
      - EITHER: accept either, newest wins

    Returns:
      Path | None
    """
    candidates: list[Path] = []

    cache = _cache_file()
    if cache.exists():
        candidates.append(cache)

    snap_dir = _snapshots_dir(airport_iata)
    if snap_dir.exists():
        candidates.extend(
            sorted(
                snap_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        )

    checked: list[Tuple[float, Path]] = []

    for p in candidates:
        try:
            obj = _read_json(p)

            is_raw = _looks_like_raw_aviationstack(obj)
            is_snap = _looks_like_snapshot(obj)

            if kind == PayloadKind.RAW and not is_raw:
                continue
            if kind == PayloadKind.SNAPSHOT and not is_snap:
                continue
            if kind == PayloadKind.EITHER and not (is_raw or is_snap):
                continue

            checked.append((p.stat().st_mtime, p))
        except Exception:
            continue

    if not checked:
        return None

    checked.sort(key=lambda t: t[0], reverse=True)
    return checked[0][1]


def load_latest_local_payload(
    *,
    airport_iata: str,
    kind: PayloadKind = PayloadKind.EITHER,
) -> tuple[Dict[str, Any], Path]:
    """
    Load the latest payload from local files.

    Raises FileNotFoundError if nothing exists.
    """
    p = find_latest_local_payload_path(airport_iata=airport_iata, kind=kind)
    if p is None:
        raise FileNotFoundError(
            f"No local payload found (kind={kind}) in cache/snapshots for airport {airport_iata}."
        )
    return _read_json(p), p
