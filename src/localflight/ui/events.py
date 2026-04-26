from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict

from localflight.storage.config import AppConfig

log = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def notify_clients(event_type: str, payload: Dict[str, Any] | None = None) -> None:
    """
    Non-fatal WebSocket event helper.

    Importing server lazily avoids a circular import while still letting scheduler,
    desktop form handlers, and JSON APIs publish through one channel.
    """
    try:
        import localflight.ui.server as server_module

        manager = getattr(server_module, "_ws_manager", None)
        if manager is None:
            manager = getattr(server_module, "manager", None)
        if manager is None:
            return
        manager.notify(event_type, payload or {})
    except Exception as exc:
        log.debug("WS notify %s failed (non-fatal): %s", event_type, exc)


def notify_config_updated(cfg: AppConfig, *, reason: str) -> None:
    notify_clients(
        "config_updated",
        {
            "reason": reason,
            "updated_at": _utc_now(),
            "config": asdict(cfg),
            "airport_iata": cfg.airport_iata,
            "airport_icao": cfg.airport_icao,
            "source": cfg.source,
            "refresh_seconds": cfg.refresh_seconds,
            "timezone": cfg.timezone,
            "skin": cfg.skin,
            "display_outputs": cfg.display_outputs,
        },
    )


def notify_scheduler_restarted(result: Dict[str, Any], *, reason: str) -> None:
    notify_clients(
        "scheduler_restarted",
        {
            "reason": reason,
            "updated_at": _utc_now(),
            **result,
        },
    )


def restart_scheduler_and_notify(reason: str) -> Dict[str, Any]:
    from localflight.scheduler.control import restart_scheduler

    result = restart_scheduler()
    notify_scheduler_restarted(result, reason=reason)
    return result
