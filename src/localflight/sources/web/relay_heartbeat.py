"""Privacy-preserving relay heartbeat metadata."""
from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any, Dict

from localflight.version import app_version as _app_version


def relay_client_metadata() -> Dict[str, Any]:
    """Return coarse install metadata safe to send to the hosted relay."""
    metadata: Dict[str, Any] = {
        "app_version": _app_version(),
        "os_family": platform.system() or "unknown",
        "os_version": platform.release() or "",
        "arch": platform.machine() or "",
        "requested_gui": "",
        "effective_gui": "",
        "source_mode": "",
        "diagnostics_mode": "",
        "companion_count": 0,
        "matrix_count": 0,
        "matrix_online_count": 0,
    }
    try:
        from localflight.platform.detect import detect
        from localflight.platform.gui_launcher import decide_gui_launch

        decision = decide_gui_launch(detect())
        metadata["requested_gui"] = str(decision.requested_mode or "")
        metadata["effective_gui"] = str(decision.effective_mode or "")
    except Exception:
        pass
    try:
        from localflight.storage.config import config_path, load_config

        cfg = load_config()
        metadata["source_mode"] = str(cfg.source or "")
        metadata["diagnostics_mode"] = str(cfg.diagnostics_mode or "")
        base = config_path().parent
        metadata.update(_device_counts(base))
    except Exception:
        pass
    return metadata


def _device_counts(base: Path) -> Dict[str, int]:
    companions = _load_json(base / "companion_clients.json", {})
    pings = _load_json(base / "device_pings.json", {})
    companion_count = sum(1 for value in companions.values() if isinstance(value, dict)) if isinstance(companions, dict) else 0
    matrix_count = len(pings) if isinstance(pings, dict) else 0
    return {
        "companion_count": companion_count,
        "matrix_count": matrix_count,
        "matrix_online_count": matrix_count,
    }


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        if not path.exists():
            return fallback
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
