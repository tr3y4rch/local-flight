"""
localflight/scheduler/run_scheduler.py

Entry point for the background scheduler.
Reads all settings from ~/.localflight/config.json via load_config().
Runs the fetch → normalize → dedupe → snapshot pipeline on a timer.

Usage:
    python -m localflight.scheduler.run_scheduler

    # or via entry point if configured in pyproject.toml:
    localflight-scheduler
"""
from __future__ import annotations

from localflight.scheduler.jobs import run_snapshot_job
from localflight.scheduler.runtime import run_loop
from localflight.storage.config import load_config
from localflight.storage.flights_store import prune_snapshots


def _make_process(keep_hours: int = 24):
    """
    Returns a process function that prunes old snapshots after each run.
    Plugs into runtime.run_loop() as the optional process step.
    """
    def process(flights, cfg):
        deleted = prune_snapshots(cfg.airport_iata, keep_hours=keep_hours)
        if deleted:
            pass  # runtime logger handles the cycle; keep this quiet
        return flights
    return process


def main() -> None:
    # Read config once at startup to log the initial state.
    # runtime.run_loop() re-reads config on every cycle so changes take effect
    # without restarting the process.
    cfg = load_config()

    print(f"Local Flight scheduler starting")
    print(f"Airport : {cfg.airport_iata} / {cfg.airport_icao}")
    print(f"Source  : {cfg.source}")
    print(f"Refresh : every {cfg.refresh_seconds}s")
    print(f"Config  : ~/.localflight/config.json")
    print(f"Stop with Ctrl+C.\n")

    run_loop(
        fetch=run_snapshot_job,
        process=_make_process(keep_hours=24),
        render=None,
        once=False,
        source_name=cfg.source,
    )


if __name__ == "__main__":
    main()
