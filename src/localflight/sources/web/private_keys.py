from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def _project_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[4]


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.getenv("LOCALFLIGHT_PRIVATE_KEYS_FILE", "").strip()
    if explicit:
        paths.append(Path(explicit).expanduser())
    paths.append(_project_root() / "dev" / "private" / "community_keys.json")
    return paths


def load_private_keys() -> Dict[str, str]:
    for path in _candidate_paths():
        try:
            if not path.exists():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            result: Dict[str, str] = {}
            for key, value in raw.items():
                if isinstance(key, str) and isinstance(value, str) and value.strip():
                    result[key.strip()] = value.strip()
            if result:
                return result
        except Exception:
            continue
    return {}


def get_private_key(name: str) -> Optional[str]:
    value: Any = load_private_keys().get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
