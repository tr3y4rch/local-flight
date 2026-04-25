from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional

from localflight.storage.logging_setup import setup_logging
from localflight.storage.config import AppConfig, load_config
from localflight.storage.state import AppState, save_state

FetchFn   = Callable[[AppConfig], Any]
ProcessFn = Callable[[Any, AppConfig], Any]
RenderFn  = Callable[[Any, AppConfig], Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_loop(
    fetch: FetchFn,
    process: Optional[ProcessFn] = None,
    render: Optional[RenderFn] = None,
    *,
    once: bool = False,
    source_name: str = "unknown",
) -> None:
    logger = setup_logging()
    logger.info("Session started | component=runtime | source=%s", source_name)
    last_cfg: Optional[dict] = None

    while True:
        cfg      = load_config()
        cfg_dict = asdict(cfg)

        # First read: set baseline silently (no log file created yet)
        if last_cfg is None:
            last_cfg = cfg_dict
        elif cfg_dict != last_cfg:
            logger.info(
                "Config changed: %s/%s refresh=%ss name='%s'",
                getattr(cfg, "airport_iata", "???"),
                cfg.airport_icao,
                cfg.refresh_seconds,
                cfg.display_name,
            )
            last_cfg = cfg_dict

        attempt_ts = _utc_now()
        t0         = time.time()

        try:
            data = fetch(cfg)

            if process:
                data = process(data, cfg)
            if render:
                render(data, cfg)

            # NOTE: history write is handled inside jobs.run_snapshot_job()
            # Do NOT write history here to avoid double writes.

            latency_ms = int((time.time() - t0) * 1000)

            save_state(AppState(
                ok=True,
                last_attempt_utc=attempt_ts,
                last_success_utc=attempt_ts,
                last_error=None,
                source_name=source_name,
                last_latency_ms=latency_ms,
            ))

        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            error_msg  = f"{type(e).__name__}: {e}"

            save_state(AppState(
                ok=False,
                last_attempt_utc=attempt_ts,
                last_success_utc=None,
                last_error=error_msg,
                source_name=source_name,
                last_latency_ms=latency_ms,
            ))
            logger.exception("Cycle error | source=%s", source_name)

            # File a Linear issue (non-fatal, deduped per 6h)
            try:
                from localflight.sources.web.linear_client import file_error
                cfg_for_linear = load_config()
                file_error(
                    error_msg,
                    source_name=source_name,
                    airport_iata=getattr(cfg_for_linear, "airport_iata", ""),
                )
            except Exception:
                pass

        if once:
            return

        elapsed = time.time() - t0
        sleep_s = max(1, cfg.refresh_seconds - int(elapsed))
        time.sleep(sleep_s)


def run_multi_airport(
    airports: List[dict],
    fetch: FetchFn,
    *,
    source_name: str = "unknown",
) -> None:
    """
    Run the scheduler for multiple airports simultaneously.
    Each airport runs in its own thread with its own AppConfig.

    airports: list of dicts with keys: airport_iata, airport_icao, refresh_seconds
    Example:
        run_multi_airport([
            {"airport_iata": "ZRH", "airport_icao": "LSZH", "refresh_seconds": 3600},
            {"airport_iata": "LHR", "airport_icao": "EGLL", "refresh_seconds": 3600},
        ], fetch=run_snapshot_job)
    """
    import threading

    logger  = setup_logging()
    threads = []

    for ap in airports:
        base_cfg = load_config()
        ap_cfg   = AppConfig(
            airport_iata=ap.get("airport_iata", base_cfg.airport_iata),
            airport_icao=ap.get("airport_icao", base_cfg.airport_icao),
            refresh_seconds=ap.get("refresh_seconds", base_cfg.refresh_seconds),
            display_name=ap.get("display_name", base_cfg.display_name),
            theme=base_cfg.theme,
            source=base_cfg.source,
            timezone=ap.get("timezone", base_cfg.timezone),
            skin=base_cfg.skin,
            display_outputs=base_cfg.display_outputs,
        )

        logger.info(
            "Starting multi-airport scheduler: %s/%s",
            ap_cfg.airport_iata, ap_cfg.airport_icao,
        )

        def _run(cfg=ap_cfg):
            while True:
                t0 = time.time()
                try:
                    # jobs.run_snapshot_job handles history write internally
                    fetch(cfg)
                except Exception as exc:
                    logger.exception(
                        "Multi-airport cycle error | %s: %s",
                        cfg.airport_iata, exc,
                    )
                elapsed = time.time() - t0
                time.sleep(max(1, cfg.refresh_seconds - int(elapsed)))

        t = threading.Thread(
            target=_run,
            name=f"scheduler-{ap_cfg.airport_iata}",
            daemon=True,
        )
        t.start()
        threads.append(t)
        logger.info("Scheduler thread started: %s", ap_cfg.airport_iata)

    for t in threads:
        t.join()