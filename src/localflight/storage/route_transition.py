from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localflight.storage.private_files import write_private_text


TRANSITION_VERSION = 1


def _path() -> Path:
    from localflight.storage.config import config_path

    return config_path().parent / "data_route_transition.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_route_transition() -> dict[str, Any]:
    path = _path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict) or payload.get("version") != TRANSITION_VERSION:
        return {}
    if payload.get("target_route") not in {"relay", "byok", "vatsim"}:
        return {}
    return payload


def begin_route_transition(previous_route: str, target_route: str) -> dict[str, Any]:
    payload = {
        "version": TRANSITION_VERSION,
        "previous_route": str(previous_route or ""),
        "target_route": str(target_route or ""),
        "stage": "started",
        "updated_at": _now(),
    }
    write_private_text(_path(), json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def update_route_transition(stage: str) -> dict[str, Any]:
    payload = load_route_transition()
    if not payload:
        return {}
    payload["stage"] = str(stage or "")[:40]
    payload["updated_at"] = _now()
    write_private_text(_path(), json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def complete_route_transition() -> None:
    try:
        _path().unlink(missing_ok=True)
    except Exception:
        pass


def runtime_route() -> str:
    """Return the route runtime must obey, including an interrupted switch.

    Once a transition away from Relay begins, the target free route wins even
    before all cleanup work completes. This prevents a retained credential from
    being used during an offline release.
    """
    transition = load_route_transition()
    target = str(transition.get("target_route") or "")
    stage = str(transition.get("stage") or "")
    if target in {"byok", "vatsim"}:
        return target
    if target == "relay" and stage == "route_saved":
        return target
    try:
        from localflight.storage.config import load_config

        return load_config().data_route
    except Exception:
        return "relay"
