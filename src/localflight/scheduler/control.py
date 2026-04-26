from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_lock = threading.RLock()
_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event] = None
_started_at: Optional[str] = None
_generation = 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_dotenv_for_scheduler() -> Optional[str]:
    """
    Reload .env into the current process before starting a new scheduler loop.
    Values are intentionally allowed to update so setup/API key edits take effect.
    """
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent.parent.parent / ".env",
        here.parent.parent / ".env",
        Path.home() / ".localflight" / ".env",
    ]

    env_path = next((path for path in candidates if path.exists()), None)
    if env_path is None:
        return None

    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key:
                os.environ[key] = value.strip()
        return str(env_path)
    except Exception as exc:
        log.warning("Scheduler .env reload failed: %s", exc)
        return None


def _run_scheduler(stop_event: threading.Event, generation: int) -> None:
    global _thread, _stop_event

    try:
        from localflight.scheduler.jobs import run_snapshot_job
        from localflight.scheduler.runtime import run_loop
        from localflight.storage.config import load_config

        _load_dotenv_for_scheduler()
        cfg = load_config()
        log.info(
            "Scheduler thread starting | generation=%s source=%s airport=%s",
            generation,
            cfg.source,
            cfg.airport_iata,
        )
        run_loop(
            fetch=run_snapshot_job,
            once=False,
            source_name=cfg.source,
            stop_event=stop_event,
        )
    finally:
        with _lock:
            current = threading.current_thread()
            if _thread is current:
                _thread = None
                _stop_event = None
        log.info("Scheduler thread stopped | generation=%s", generation)


def start_scheduler_thread() -> threading.Thread:
    global _thread, _stop_event, _started_at, _generation

    with _lock:
        if _thread and _thread.is_alive():
            return _thread

        _generation += 1
        _stop_event = threading.Event()
        _started_at = _utc_now()
        _thread = threading.Thread(
            target=_run_scheduler,
            args=(_stop_event, _generation),
            name="scheduler",
            daemon=True,
        )
        _thread.start()
        return _thread


def scheduler_status() -> Dict[str, Any]:
    with _lock:
        running = bool(_thread and _thread.is_alive())
        return {
            "running": running,
            "generation": _generation,
            "started_at": _started_at,
            "thread_name": _thread.name if _thread else None,
        }


def restart_scheduler(timeout: float = 5.0) -> Dict[str, Any]:
    global _thread, _stop_event

    with _lock:
        old_thread = _thread
        old_stop = _stop_event
        was_running = bool(old_thread and old_thread.is_alive())
        if was_running and old_stop:
            old_stop.set()

    if was_running and old_thread:
        old_thread.join(timeout=timeout)
        if old_thread.is_alive():
            log.warning("Scheduler restart requested but previous thread is still busy")
            return {
                **scheduler_status(),
                "ok": False,
                "status": "stopping",
                "message": "Scheduler is finishing its current fetch. Try again in a moment.",
                "was_running": True,
                "started": False,
            }

    thread = start_scheduler_thread()
    log.info("Scheduler restarted manually")
    return {
        **scheduler_status(),
        "ok": True,
        "status": "restarted" if was_running else "started",
        "message": "Scheduler restarted and a fresh fetch cycle has started.",
        "was_running": was_running,
        "started": thread.is_alive(),
    }
