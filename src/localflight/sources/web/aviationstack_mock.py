from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from localflight.sources.web.aviationstack_files import (
    PayloadKind,
    load_latest_local_payload,
)

log = logging.getLogger(__name__)

# This file lives at:
#   src/localflight/sources/web/aviationstack_mock.py
# parents[0] = web
# parents[1] = sources
# parents[2] = localflight
_LF_ROOT = Path(__file__).resolve().parents[2]

# 1) manually dropped "real" sample
_SAMPLE_REAL = _LF_ROOT / "storage" / "samples" / "aviationstack_real.json"

# 2) original bundled sample
_SAMPLE_DEFAULT = _LF_ROOT / "storage" / "samples" / "aviationstack_flights.json"


def _read_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def load_sample_payload(path: Path | None = None) -> Dict[str, Any]:
    """
    Load an aviationstack response from disk.

    Resolution order:
      - explicit `path` argument (if provided)
      - latest local RAW payload from cache / local files (if present)
      - src/localflight/storage/samples/aviationstack_real.json (if present)
      - src/localflight/storage/samples/aviationstack_flights.json (fallback)
    """
    if path is not None:
        payload = _read_json(path)
        log.info("aviationstack_mock: using explicit path: %s", path)
        return payload

    try:
        payload, payload_path = load_latest_local_payload(
            airport_iata="ZRH",
            kind=PayloadKind.RAW,
        )
        log.info("aviationstack_mock: using local RAW payload: %s", payload_path)
        return payload
    except FileNotFoundError:
        pass

    for candidate in (_SAMPLE_REAL, _SAMPLE_DEFAULT):
        if candidate.exists():
            payload = _read_json(candidate)
            log.info("aviationstack_mock: using sample payload: %s", candidate)
            return payload

    raise FileNotFoundError(
        "No aviationstack payload found. Tried: "
        f"latest local RAW payload, {_SAMPLE_REAL}, {_SAMPLE_DEFAULT}"
    )
