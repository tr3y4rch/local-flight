from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

log = logging.getLogger(__name__)

# This file lives at:
#   src/localflight/sources/web/aviationstack_mock.py
# parents[0] = web
# parents[1] = sources
# parents[2] = localflight
_LF_ROOT = Path(__file__).resolve().parents[2]

# 1) last live fetch cache (preferred)
_CACHE_LAST = _LF_ROOT.parents[1] / "data" / "cache" / "aviationstack_last.json"

# 2) newest snapshot from storage/ (preferred over bundled samples)
# Your tree shows: src/localflight/storage/data/ZRH/snapshots/
_SNAPSHOTS_ROOT = _LF_ROOT / "storage" / "data"

# 3) manually dropped "real" sample
_SAMPLE_REAL = _LF_ROOT / "storage" / "samples" / "aviationstack_real.json"

# 4) original bundled sample
_SAMPLE_DEFAULT = _LF_ROOT / "storage" / "samples" / "aviationstack_flights.json"


def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _iter_snapshot_candidates() -> Iterable[Path]:
    """
    Yield candidate snapshot JSON files ordered newest-first.
    We keep it flexible: any *.json in any */snapshots/ folder under storage/data.
    """
    if not _SNAPSHOTS_ROOT.exists():
        return []

    files = list(_SNAPSHOTS_ROOT.glob("*/snapshots/*.json"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _find_latest_snapshot() -> Optional[Path]:
    for p in _iter_snapshot_candidates():
        # light sanity check: if it parses and has data, it's probably an aviationstack payload
        try:
            obj = _read_json(p)
            if isinstance(obj, dict) and isinstance(obj.get("data"), list) and len(obj["data"]) > 0:
                return p
        except Exception:
            continue
    return None


def load_sample_payload(path: Path | None = None) -> Dict[str, Any]:
    """
    Load an aviationstack response from disk.

    Resolution order:
      - explicit `path` argument (if provided)
      - data/cache/aviationstack_last.json (if present)
      - newest JSON under src/localflight/storage/data/*/snapshots/ (if present)
      - src/localflight/storage/samples/aviationstack_real.json (if present)
      - src/localflight/storage/samples/aviationstack_flights.json (fallback)
    """
    if path is not None:
        payload = _read_json(path)
        log.info("aviationstack_mock: using explicit path: %s", path)
        return payload

    if _CACHE_LAST.exists():
        payload = _read_json(_CACHE_LAST)
        log.info("aviationstack_mock: using cache payload: %s", _CACHE_LAST)
        return payload

    latest = _find_latest_snapshot()
    if latest is not None:
        payload = _read_json(latest)
        log.info("aviationstack_mock: using latest snapshot payload: %s", latest)
        return payload

    for candidate in (_SAMPLE_REAL, _SAMPLE_DEFAULT):
        if candidate.exists():
            payload = _read_json(candidate)
            log.info("aviationstack_mock: using sample payload: %s", candidate)
            return payload

    raise FileNotFoundError(
        "No aviationstack payload found. Tried: "
        f"{_CACHE_LAST}, snapshots under {_SNAPSHOTS_ROOT}, {_SAMPLE_REAL}, {_SAMPLE_DEFAULT}"
    )
