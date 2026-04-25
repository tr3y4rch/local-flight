from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("config.json")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {
            "app_name": "Local Flight",
            "airport": "LSZH",
            "mode": "cycle",
            "refresh_minutes": 60,
            "timezone": "local",
            "theme": "dark",
        }
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict[str, Any]) -> None:
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
