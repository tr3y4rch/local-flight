from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, List, Optional

from localflight.core.models import Flight
from localflight.storage.config import config_path


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


def snapshot_store_root(*, create: bool = False) -> Path:
    """
    Canonical runtime snapshot storage under ~/.localflight/storage/data.
    This keeps packaged and source-based runs consistent.
    """
    root = config_path().parent / "storage" / "data"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _legacy_store_root() -> Path:
    """
    Legacy snapshot location used by older source-tree builds.
    Reads still fall back here so existing snapshots remain visible.
    """
    return Path(__file__).resolve().parent / "data"


def _all_store_roots() -> List[Path]:
    roots: List[Path] = []
    for root in (snapshot_store_root(), _legacy_store_root()):
        if root not in roots:
            roots.append(root)
    return roots


def _airport_dir(airport_iata: str, *, root: Optional[Path] = None) -> Path:
    return (root or snapshot_store_root()) / airport_iata.upper()


def _snapshots_dir(airport_iata: str, *, root: Optional[Path] = None) -> Path:
    return _airport_dir(airport_iata, root=root) / "snapshots"


def ensure_dirs(airport_iata: str) -> None:
    _snapshots_dir(
        airport_iata,
        root=snapshot_store_root(create=True),
    ).mkdir(parents=True, exist_ok=True)


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
    snapshots: List[Path] = []
    seen: set[Path] = set()

    for root in _all_store_roots():
        d = _snapshots_dir(airport_iata, root=root)
        if not d.exists():
            continue
        for path in d.glob("*.json"):
            try:
                key = path.resolve()
            except Exception:
                key = path
            if key in seen:
                continue
            seen.add(key)
            snapshots.append(path)

    snapshots.sort(key=_snapshot_sort_key)
    return snapshots


def load_latest_snapshot_path(airport_iata: str) -> Optional[Path]:
    snaps = list_snapshots(airport_iata)
    return snaps[-1] if snaps else None


def snapshot_age_seconds(airport_iata: str) -> Optional[float]:
    """
    Age in seconds of the most recent snapshot for this airport.
    Returns None if no snapshot exists (treat as infinitely stale).
    Uses the UTC timestamp embedded in the filename, not the file mtime.
    """
    p = load_latest_snapshot_path(airport_iata)
    if p is None:
        return None
    ts = _snapshot_timestamp(p)
    return (_utcnow() - ts).total_seconds()


def prune_snapshots(airport_iata: str, *, keep_hours: int = 24) -> int:
    """
    Delete snapshot files older than keep_hours.
    Returns number of files deleted.
    """
    cutoff = _utcnow() - timedelta(hours=keep_hours)
    deleted = 0

    for root in _all_store_roots():
        d = _snapshots_dir(airport_iata, root=root)
        if not d.exists():
            continue

        for p in d.glob("*.json"):
            if _snapshot_timestamp(p) < cutoff:
                p.unlink(missing_ok=True)
                deleted += 1

    return deleted


def _snapshot_timestamp(path: Path) -> datetime:
    try:
        return datetime.strptime(path.stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _snapshot_sort_key(path: Path) -> tuple[datetime, str, str]:
    canonical = _snapshots_dir(path.parent.parent.name, root=snapshot_store_root())
    return (
        _snapshot_timestamp(path),
        "1" if path.parent == canonical else "0",
        path.name,
    )
