from __future__ import annotations

import time
import threading
import random
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Optional

from localflight.storage.logging_setup import setup_logging
from localflight.storage.config import AppConfig, load_config
from localflight.storage.state import AppState, load_state, save_state

FetchFn   = Callable[[AppConfig], Any]
ProcessFn = Callable[[Any, AppConfig], Any]
RenderFn  = Callable[[Any, AppConfig], Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _retry_delay_seconds(exc: Exception, failure_count: int, *, jitter: bool = True) -> int:
    status_code = getattr(exc, "status_code", None)
    retry_after = getattr(exc, "retry_after_s", None)
    if status_code == 429 and retry_after:
        return max(1, int(retry_after))
    if status_code in {401, 403}:
        return 60
    if retry_after and status_code == 503:
        return max(10, int(retry_after))
    steps = (10, 60, 300, 900)
    base = steps[min(max(1, failure_count), len(steps)) - 1]
    return max(1, int(round(base * random.uniform(0.9, 1.1)))) if jitter else base


def _notice_code_for_exception(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return "scheduler.rate_limited"
    if status_code in {401, 403}:
        return "scheduler.relay_link_required"
    return "scheduler.update_interrupted"


def _repair_relay_link_if_needed(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    message = str(exc).casefold()
    if status_code not in {401, 403} and "activation token" not in message and "device credential" not in message and "relay link" not in message:
        return False
    try:
        from localflight.sources.web.relay_activation import ensure_relay_link, legacy_relay_compat_enabled
        from localflight.storage.config import load_config
        from localflight.storage.install import get_stored_activation_token

        if load_config().data_route != "relay":
            return False
        if get_stored_activation_token().startswith("lfr_") or not legacy_relay_compat_enabled():
            return False

        result = ensure_relay_link(force=False)
        return bool(result.get("linked"))
    except Exception:
        return False


def run_loop(
    fetch: FetchFn,
    process: Optional[ProcessFn] = None,
    render: Optional[RenderFn] = None,
    *,
    once: bool = False,
    source_name: str = "unknown",
    stop_event: Optional[threading.Event] = None,
) -> None:
    logger = setup_logging()
    logger.info("Session started | component=runtime | source=%s", source_name)
    last_cfg: Optional[dict] = None
    failure_count = 0

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Scheduler stop requested before next cycle | source=%s", source_name)
            return

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
        previous_state = load_state()

        sleep_override_s: Optional[int] = None
        try:
            data = fetch(cfg)

            if process:
                data = process(data, cfg)
            if render:
                render(data, cfg)

            # NOTE: history write is handled inside jobs.run_snapshot_job()
            # Do NOT write history here to avoid double writes.

            latency_ms = int((time.time() - t0) * 1000)

            failure_count = 0
            cache_state = "cached" if isinstance(data, list) and not data else "live"
            next_refresh = datetime.now(timezone.utc) + timedelta(seconds=max(1, int(cfg.refresh_seconds)))
            save_state(AppState(
                ok=True,
                last_attempt_utc=attempt_ts,
                last_success_utc=attempt_ts,
                last_error=None,
                source_name=source_name,
                last_latency_ms=latency_ms,
                next_refresh_utc=next_refresh.isoformat().replace("+00:00", "Z"),
                next_retry_utc=None,
                retry_after_s=None,
                retry_count=0,
                cache_state=cache_state,
                notice_code=None,
            ))

        except Exception as e:
            failure_count += 1
            latency_ms = int((time.time() - t0) * 1000)
            error_msg  = f"{type(e).__name__}: {e}"
            repaired = _repair_relay_link_if_needed(e)
            retry_after_s = 10 if repaired else _retry_delay_seconds(e, failure_count)
            next_retry = datetime.now(timezone.utc) + timedelta(seconds=retry_after_s)
            sleep_override_s = retry_after_s

            save_state(AppState(
                ok=False,
                last_attempt_utc=attempt_ts,
                last_success_utc=previous_state.last_success_utc,
                last_error=error_msg,
                source_name=source_name,
                last_latency_ms=latency_ms,
                next_refresh_utc=next_retry.isoformat().replace("+00:00", "Z"),
                next_retry_utc=next_retry.isoformat().replace("+00:00", "Z"),
                retry_after_s=retry_after_s,
                retry_count=failure_count,
                cache_state="stale" if previous_state.last_success_utc else "empty",
                notice_code=_notice_code_for_exception(e),
            ))
            logger.exception("Cycle error | source=%s", source_name)

            # File to operator's Linear (optional, needs env vars, deduped per 6h)
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

            # Auto crash report to developer's Linear (always-on, deduped per 6h)
            try:
                import traceback as _tb
                from localflight.sources.web.bug_reporter import submit_crash
                submit_crash(
                    error_msg,
                    traceback_str=_tb.format_exc(),
                    context=f"scheduler/{source_name}",
                )
            except Exception:
                pass

        if once:
            return

        elapsed = time.time() - t0
        sleep_s = sleep_override_s if sleep_override_s is not None else max(1, cfg.refresh_seconds - int(elapsed))
        if stop_event:
            if stop_event.wait(sleep_s):
                logger.info("Scheduler stop requested during sleep | source=%s", source_name)
                return
        else:
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
            data_route=base_cfg.data_route,
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
                    fetch(cfg)
                except Exception as exc:
                    logger.exception(
                        "Multi-airport cycle error | %s: %s",
                        cfg.airport_iata, exc,
                    )
                    error_msg = f"{type(exc).__name__}: {exc}"
                    try:
                        import traceback as _tb
                        from localflight.sources.web.bug_reporter import submit_crash
                        submit_crash(
                            error_msg,
                            traceback_str=_tb.format_exc(),
                            context=f"scheduler/multi/{cfg.airport_iata}",
                        )
                    except Exception:
                        pass
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
