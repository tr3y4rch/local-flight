from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from localflight.storage.config import config_path

# One log file per process launch (session)
_SESSION_LOG_FILE: Path | None = None

# ── Retention policy ───────────────────────────────────────────────────────────
MAX_LOG_FILES   = 10      # keep at most this many session log files
MAX_LOG_DAYS    = 30      # delete files older than this many days
MAX_LOG_BYTES   = 1_000_000  # 1MB per file before rotation
LOG_BACKUP_COUNT = 3      # rotations within a session


def logs_dir() -> Path:
    d = config_path().with_name("logs")
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_path() -> Path:
    """
    Returns the current session's log file path.
    File is NOT created until the first log event (delay=True).
    """
    global _SESSION_LOG_FILE
    if _SESSION_LOG_FILE is None:
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        pid = os.getpid()
        _SESSION_LOG_FILE = logs_dir() / f"localflight_{ts}_{pid}.log"
    return _SESSION_LOG_FILE


def prune_old_logs() -> None:
    """
    Enforce log retention policy:
      1. Delete files older than MAX_LOG_DAYS days
      2. If more than MAX_LOG_FILES remain, delete oldest by mtime
    Called once on startup before any logging begins.
    """
    d = logs_dir()
    files = sorted(d.glob("localflight_*.log"), key=lambda p: p.stat().st_mtime)

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_LOG_DAYS)

    for f in files[:]:
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                files.remove(f)
        except Exception:
            pass

    # Also prune .log.1, .log.2 rotation files
    for f in d.glob("localflight_*.log.*"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
        except Exception:
            pass

    # Keep only the newest MAX_LOG_FILES files
    files = sorted(d.glob("localflight_*.log"), key=lambda p: p.stat().st_mtime)
    while len(files) > MAX_LOG_FILES:
        try:
            files[0].unlink()
            files.pop(0)
        except Exception:
            break


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Safe to call multiple times. Creates a per-launch log file path,
    but does NOT create the file unless something is actually logged.
    Runs log pruning on first call.
    """
    logger = logging.getLogger("localflight")
    logger.setLevel(level)

    # Avoid duplicate handlers
    if any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return logger

    # Prune old logs before setting up the new session handler
    try:
        prune_old_logs()
    except Exception:
        pass  # never let pruning crash the app

    handler = RotatingFileHandler(
        filename=str(log_path()),
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
        delay=True,  # don't create file until first emit
    )

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(fmt)

    logger.addHandler(handler)
    logger.propagate = False

    # IMPORTANT: do NOT log here — would create the file immediately
    return logger