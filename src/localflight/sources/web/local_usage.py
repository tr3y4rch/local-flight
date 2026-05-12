from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class LocalBudgetExceeded(RuntimeError):
    def __init__(
        self,
        *,
        service: str,
        current: int,
        limit: int,
        requested: int,
        period: str,
    ) -> None:
        self.service = service
        self.current = int(current)
        self.limit = int(limit)
        self.requested = int(requested)
        self.period = period
        super().__init__(
            f"{service} {period} budget exceeded: "
            f"{current}/{limit} used, {requested} requested."
        )


def _db_path() -> Path:
    from localflight.storage.config import config_path

    return config_path().parent / "api_usage.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage (
            service   TEXT NOT NULL,
            period    TEXT NOT NULL,
            calls     INTEGER DEFAULT 0,
            last_seen TEXT NOT NULL,
            PRIMARY KEY (service, period)
        )
        """
    )
    return conn


def month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_counter(service: str, period: Optional[str] = None) -> int:
    period = period or month_key()
    if not _db_path().exists():
        return 0
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT calls FROM usage WHERE service=? AND period=?",
            (service, period),
        ).fetchone()
        return int(row["calls"] or 0) if row else 0
    finally:
        conn.close()


def ensure_counter_at_least(service: str, period: str, minimum: int) -> None:
    minimum = max(0, int(minimum or 0))
    if minimum <= 0:
        return
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT calls FROM usage WHERE service=? AND period=?",
            (service, period),
        ).fetchone()
        current = int(row["calls"] or 0) if row else 0
        if current < minimum:
            conn.execute(
                """
                INSERT INTO usage (service, period, calls, last_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(service, period) DO UPDATE SET
                    calls = excluded.calls,
                    last_seen = excluded.last_seen
                """,
                (service, period, minimum, _now()),
            )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def check_and_increment_many(counters: list[Dict[str, Any]]) -> Dict[str, int]:
    normalized: list[Dict[str, Any]] = []
    for counter in counters:
        monthly_limit = counter.get("monthly_limit")
        daily_limit = counter.get("daily_limit")
        normalized.append(
            {
                "service": str(counter.get("service") or ""),
                "amount": max(1, int(counter.get("amount", 1) or 1)),
                "month": str(counter.get("month") or month_key()),
                "day": str(counter.get("day") or day_key()),
                "monthly_limit": None if monthly_limit is None else max(0, int(monthly_limit)),
                "daily_limit": None if daily_limit is None else max(0, int(daily_limit)),
            }
        )
    if not normalized:
        return {}

    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current: dict[tuple[str, str], int] = {}
        for counter in normalized:
            for period, limit, label in (
                (counter["month"], counter["monthly_limit"], "monthly"),
                (counter["day"], counter["daily_limit"], "daily"),
            ):
                if limit is None:
                    continue
                key = (counter["service"], period)
                if key not in current:
                    row = conn.execute(
                        "SELECT calls FROM usage WHERE service=? AND period=?",
                        key,
                    ).fetchone()
                    current[key] = int(row["calls"] or 0) if row else 0
                if current[key] + counter["amount"] > limit:
                    conn.rollback()
                    raise LocalBudgetExceeded(
                        service=counter["service"],
                        current=current[key],
                        limit=limit,
                        requested=counter["amount"],
                        period=label,
                    )
        now = _now()
        result: Dict[str, int] = {}
        for counter in normalized:
            for period in (counter["month"], counter["day"]):
                key = (counter["service"], period)
                if key not in current:
                    row = conn.execute(
                        "SELECT calls FROM usage WHERE service=? AND period=?",
                        key,
                    ).fetchone()
                    current[key] = int(row["calls"] or 0) if row else 0
                conn.execute(
                    """
                    INSERT INTO usage (service, period, calls, last_seen)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(service, period) DO UPDATE SET
                        calls = calls + excluded.calls,
                        last_seen = excluded.last_seen
                    """,
                    (counter["service"], period, counter["amount"], now),
                )
                current[key] = current[key] + counter["amount"]
                if period == counter["month"]:
                    result[counter["service"]] = current[key]
        conn.commit()
        return result
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def check_and_increment(
    service: str,
    amount: int,
    *,
    monthly_limit: Optional[int],
    daily_limit: Optional[int] = None,
) -> int:
    return check_and_increment_many(
        [
            {
                "service": service,
                "amount": amount,
                "monthly_limit": monthly_limit,
                "daily_limit": daily_limit,
            }
        ]
    ).get(service, amount)
