from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import List

from localflight.storage.config import AppConfig, config_path


def _profiles_dir() -> Path:
    d = config_path().with_name("profiles")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"[^A-Za-z0-9_\- ]+", "", name)
    name = name.strip().replace(" ", "_")
    return name[:32] or "default"


def list_profiles() -> List[str]:
    d = _profiles_dir()
    names = []
    for f in d.glob("*.json"):
        names.append(f.stem)
    return sorted(names)


def save_profile(name: str, cfg: AppConfig) -> str:
    name = _safe_name(name)
    p = _profiles_dir() / f"{name}.json"
    p.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
    return name


def load_profile(name: str) -> AppConfig:
    name = _safe_name(name)
    p = _profiles_dir() / f"{name}.json"
    raw = json.loads(p.read_text(encoding="utf-8"))

    # tolerate missing keys, fall back to defaults
    base = AppConfig()
    merged = {**asdict(base), **raw}
    return AppConfig(**merged)


def delete_profile(name: str) -> None:
    name = _safe_name(name)
    p = _profiles_dir() / f"{name}.json"
    if p.exists():
        p.unlink()
