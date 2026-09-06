from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_lock = threading.RLock()
_thread: Optional[threading.Thread] = None
_stop_event: Optional[threading.Event] = None
_started_at: Optional[str] = None
_generation = 0
_last_restart_request_monotonic: Optional[float] = None
_RESTART_COALESCE_S = 60.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_dotenv_for_scheduler() -> Optional[str]:
    """
    Reload .env into the current process before starting a new scheduler loop.
    Local Flight-owned provider/relay values are authoritative so setup/API key
    edits take effect and stale keys are cleared.
    """
    from localflight.storage.provider_keys import env_path as provider_env_path

    here = Path(__file__).resolve().parent
    candidates = [
        provider_env_path(),
        here.parent.parent.parent / ".env",
        here.parent.parent / ".env",
        Path.home() / ".localflight" / ".env",
    ]

    env_path = next((path for path in candidates if path.exists()), None)
    if env_path is None:
        return None

    try:
        from localflight.storage.provider_keys import reload_provider_env

        reload_provider_env(env_path)
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
        _ensure_community_relay_link(cfg)
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


def _ensure_community_relay_link(cfg: Any) -> None:
    """Repair legacy relay installs once without blocking board fallback."""
    if str(getattr(cfg, "data_route", "") or "").strip().lower() != "relay":
        return
    try:
        from localflight.sources.web.relay_activation import legacy_relay_compat_enabled

        if not legacy_relay_compat_enabled():
            return
        from localflight.sources.web.aviationstack_client import schedule_policy

        policy = schedule_policy("real", data_route="relay")
        if not bool(policy.get("community_shared")):
            return
        from localflight.sources.web.relay_activation import ensure_relay_link

        result = ensure_relay_link(
            airport_iata=str(getattr(cfg, "airport_iata", "") or ""),
            airport_icao=str(getattr(cfg, "airport_icao", "") or ""),
            requested_mode="community",
            force=False,
        )
        if result.get("linked"):
            log.info("Beacon Relay link verified at scheduler startup")
        else:
            log.info("Beacon Relay link needs attention | status=%s", result.get("status") or "relay_link_required")
    except Exception as exc:
        log.debug("Beacon Relay startup link check deferred: %s", type(exc).__name__)


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
        status: Dict[str, Any] = {
            "running": running,
            "generation": _generation,
            "started_at": _started_at,
            "thread_name": _thread.name if _thread else None,
        }
    try:
        from localflight.storage.state import load_state

        state = load_state()
        status.update(
            {
                "last_success_at": state.last_success_utc,
                "next_refresh_at": state.next_refresh_utc or state.next_retry_utc,
                "retry_after_s": state.retry_after_s,
                "retry_count": state.retry_count,
                "cache_state": state.cache_state,
                "notice_code": state.notice_code,
            }
        )
    except Exception:
        pass
    return status


def restart_scheduler(timeout: float = 5.0, *, coalesce_seconds: float = _RESTART_COALESCE_S) -> Dict[str, Any]:
    global _thread, _stop_event, _last_restart_request_monotonic

    with _lock:
        now = time.monotonic()
        if _last_restart_request_monotonic is not None and coalesce_seconds > 0:
            age_s = now - _last_restart_request_monotonic
            if age_s < coalesce_seconds:
                retry_after = max(1, int(coalesce_seconds - age_s))
                log.info("Scheduler restart coalesced; retry_after=%ss", retry_after)
                return {
                    **scheduler_status(),
                    "ok": False,
                    "status": "rate_limited",
                    "message": f"Scheduler restart was requested recently. Try again in {retry_after}s.",
                    "was_running": bool(_thread and _thread.is_alive()),
                    "started": False,
                    "retry_after_s": retry_after,
                }
        _last_restart_request_monotonic = now
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
