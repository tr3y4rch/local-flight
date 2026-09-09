"""SQLite-backed provider pacing, credential pauses and bounded retries."""
from __future__ import annotations

import hashlib
import math
import random
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from fastapi import HTTPException

current_transport: ContextVar[Any] = ContextVar("schedule_transport", default=None)

enrichment: ContextVar[bool] = ContextVar("schedule_enrichment", default=False)


def ensure_schema(conn: Any) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS schedule_provider_transport (
        credential TEXT PRIMARY KEY, next_at REAL NOT NULL DEFAULT 0,
        paused INTEGER NOT NULL DEFAULT 0, blocked_until REAL NOT NULL DEFAULT 0)""")
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    if "blocked_until" not in {row[1] for row in conn.execute("PRAGMA table_info(schedule_provider_transport)")}:
        conn.execute("ALTER TABLE schedule_provider_transport ADD COLUMN blocked_until REAL NOT NULL DEFAULT 0")


def retry_after(value: Any) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        try:
            return max(1, int((parsedate_to_datetime(str(value)) - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return 60


class ProviderTransport:
    def __init__(self, connect: Callable, *, provider: str, credential: str, rps: float = 1) -> None:
        self.connect = connect
        self.key = hashlib.sha256(f"{provider}:{credential}".encode()).hexdigest()
        self.interval = 1 / max(0.01, rps)
        self.retries = 0

    def check_available(self) -> None:
        conn = self.connect()
        try:
            row = conn.execute("SELECT next_at, paused FROM schedule_provider_transport WHERE credential=?", (self.key,)).fetchone()
            if row and (row[1] or row[0] - time.time() > 25):
                raise HTTPException(503, "Schedule provider is temporarily unavailable",
                                    headers={"Retry-After": str(max(60, math.ceil(row[0] - time.time())))})
        finally:
            conn.close()

    def _slot(self) -> None:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO schedule_provider_transport(credential) VALUES (?)", (self.key,))
            row = conn.execute("SELECT next_at, paused FROM schedule_provider_transport WHERE credential=?", (self.key,)).fetchone()
            delay = max(0, row[0] - time.time())
            if row[1] or delay > 25:
                raise HTTPException(503, "Schedule provider is temporarily unavailable", headers={"Retry-After": str(max(60, int(delay)))})
            conn.execute("UPDATE schedule_provider_transport SET next_at=? WHERE credential=?", (time.time() + delay + self.interval, self.key))
            conn.commit()
        finally:
            conn.close()
        if delay:
            time.sleep(delay)
        # Another worker may have received a 429 or credential rejection while
        # this request waited for its reserved pacing slot.
        conn = self.connect()
        try:
            row = conn.execute("SELECT blocked_until, paused FROM schedule_provider_transport WHERE credential=?", (self.key,)).fetchone()
            if row and (row[1] or row[0] > time.time()):
                raise HTTPException(503, "Schedule provider is temporarily unavailable",
                                    headers={"Retry-After": str(max(1, math.ceil(row[0] - time.time())))})
        finally:
            conn.close()

    def _defer(self, seconds: int, *, paused: bool = False) -> None:
        conn = self.connect()
        try:
            conn.execute("UPDATE schedule_provider_transport SET next_at=MAX(next_at, ?), blocked_until=MAX(blocked_until, ?), paused=MAX(paused, ?) WHERE credential=?",
                         (time.time() + seconds, time.time() + seconds, int(paused), self.key))
            conn.commit()
        finally:
            conn.close()

    def get(self, request: Callable, *, reserve_retry: Callable[[], None]) -> Any:
        while True:
            self._slot()
            try:
                response = request()
            except Exception as exc:
                if self.retries >= 2:
                    raise HTTPException(502, "Schedule provider is temporarily unavailable") from exc
                response = None
            if response is not None:
                status = response.status_code
                if status in {401, 403}:
                    self._defer(0, paused=True)
                    raise HTTPException(503, "Schedule provider configuration needs attention", headers={"Retry-After": "900"})
                if status == 429:
                    headers = getattr(response, "headers", {})
                    delay = retry_after(headers.get("Retry-After") if isinstance(headers, dict) or hasattr(headers, "get") else None)
                    self._defer(delay)
                    raise HTTPException(503, "Schedule provider is temporarily rate limited", headers={"Retry-After": str(delay)})
                if status < 500 or self.retries >= 2:
                    return response
            self.retries += 1
            reserve_retry()
            time.sleep(random.uniform(0.5, 1.5) * self.retries)
