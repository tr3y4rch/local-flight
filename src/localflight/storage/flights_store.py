from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, List, Optional

from localflight.core.models import Flight

def _json_safe(obj: Any) -> Any:
    """
    Recursively convert objects into JSON-serializable forms.
    - datetime -> ISO string
    - Enum -> value
    - dict/list/tuple -> recurse
    """
    if obj is None:
        return None
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _store_root() -> Path:
    """
    Storage root inside the repo package tree.
    src/localflight/storage/data/...
    """
    return Path(__file__).resolve().parent / "data"


def _airport_dir(airport_iata: str) -> Path:
    return _store_root() / airport_iata.upper()


def _snapshots_dir(airport_iata: str) -> Path:
    return _airport_dir(airport_iata) / "snapshots"


def ensure_dirs(airport_iata: str) -> None:
    _snapshots_dir(airport_iata).mkdir(parents=True, exist_ok=True)


def save_snapshot(
    airport_iata: str,
    flights: Iterable[Flight],
    *,
    at: Optional[datetime] = None,
) -> Path:
    """
    Write one snapshot as JSON.
    Returns the file path written.
    """
    ensure_dirs(airport_iata)

    ts = at or _utcnow()
    # Filename: 20260102T064812Z.json
    fname = ts.strftime("%Y%m%dT%H%M%SZ") + ".json"
    path = _snapshots_dir(airport_iata) / fname

    payload = {
        "airport_iata": airport_iata.upper(),
        "generated_at": ts.isoformat(),
        "count": 0,
        "flights": [],
    }

    flights_list = list(flights)
    payload["count"] = len(flights_list)

    # dataclasses.asdict handles nested dataclasses nicely
    payload["flights"] = [_json_safe(asdict(f)) for f in flights_list]


    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def list_snapshots(airport_iata: str) -> List[Path]:
    d = _snapshots_dir(airport_iata)
    if not d.exists():
        return []
    return sorted(d.glob("*.json"))


def load_latest_snapshot_path(airport_iata: str) -> Optional[Path]:
    snaps = list_snapshots(airport_iata)
    return snaps[-1] if snaps else None


def prune_snapshots(airport_iata: str, *, keep_hours: int = 24) -> int:
    """
    Delete snapshot files older than keep_hours.
    Returns number of files deleted.
    """
    d = _snapshots_dir(airport_iata)
    if not d.exists():
        return 0

    cutoff = _utcnow() - timedelta(hours=keep_hours)
    deleted = 0

    for p in d.glob("*.json"):
        # filename is UTC timestamp; use mtime fallback if parsing fails
        try:
            ts = datetime.strptime(p.stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)

        if ts < cutoff:
            p.unlink(missing_ok=True)
            deleted += 1

    return deleted
