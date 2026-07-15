from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from localflight.storage.config import config_path


@dataclass(frozen=True)
class AppState:
    ok: bool = False
    last_attempt_utc: Optional[str] = None
    last_success_utc: Optional[str] = None
    last_error: Optional[str] = None
    source_name: str = "unknown"
    last_latency_ms: Optional[int] = None
    next_refresh_utc: Optional[str] = None
    next_retry_utc: Optional[str] = None
    retry_after_s: Optional[int] = None
    retry_count: int = 0
    cache_state: str = "unknown"
    notice_code: Optional[str] = None


def state_path() -> Path:
    # keep it next to config.json in ~/.localflight/
    return config_path().with_name("state.json")


def load_state() -> AppState:
    p = state_path()
    if not p.exists():
        return AppState()

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return AppState()

    return AppState(
        ok=bool(raw.get("ok", False)),
        last_attempt_utc=raw.get("last_attempt_utc"),
        last_success_utc=raw.get("last_success_utc"),
        last_error=raw.get("last_error"),
        source_name=str(raw.get("source_name", "unknown") or "unknown"),
        last_latency_ms=raw.get("last_latency_ms"),
        next_refresh_utc=raw.get("next_refresh_utc"),
        next_retry_utc=raw.get("next_retry_utc"),
        retry_after_s=raw.get("retry_after_s"),
        retry_count=int(raw.get("retry_count", 0) or 0),
        cache_state=str(raw.get("cache_state", "unknown") or "unknown"),
        notice_code=raw.get("notice_code"),
    )


def save_state(state: AppState) -> None:
    p = state_path()
    p.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
