"""Demand-driven airport snapshots, coordinated across processes by SQLite.

Only this service authorizes refresh work. HTTP handlers authenticate consumers;
provider adapters own provider-specific credentials, budgets and transport.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from localflight.sources.web.schedule_fusion import enrich_schedule_records


def stamp(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def epoch(value: Any) -> float:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.timestamp() if dt.tzinfo else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schedule_refresh_state (
            lane TEXT PRIMARY KEY, airport TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
            lease_until REAL NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
            grace INTEGER NOT NULL DEFAULT 30, horizon INTEGER NOT NULL DEFAULT 12,
            enrichment_at REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
            accesses INTEGER NOT NULL DEFAULT 0, hits INTEGER NOT NULL DEFAULT 0,
            refreshes INTEGER NOT NULL DEFAULT 0, rejected INTEGER NOT NULL DEFAULT 0,
            stale_serves INTEGER NOT NULL DEFAULT 0, coverage_gaps INTEGER NOT NULL DEFAULT 0,
            empty_confirmations INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS schedule_provider_cache (
            lane TEXT NOT NULL, provider TEXT NOT NULL, payload TEXT NOT NULL,
            fetched_at REAL NOT NULL, expires_at REAL NOT NULL,
            PRIMARY KEY(lane, provider));
        CREATE INDEX IF NOT EXISTS schedule_provider_expiry ON schedule_provider_cache(expires_at);
    """)
    conn.execute("BEGIN IMMEDIATE")
    if "empty_confirmations" not in {r[1] for r in conn.execute("PRAGMA table_info(schedule_refresh_state)")}:
        conn.execute("ALTER TABLE schedule_refresh_state ADD COLUMN empty_confirmations INTEGER NOT NULL DEFAULT 0")
    columns = {r[1] for r in conn.execute("PRAGMA table_info(schedule_refresh_state)")}
    for name, declaration in {"enrichment_fetches": "INTEGER NOT NULL DEFAULT 0",
                              "enrichment_fields": "INTEGER NOT NULL DEFAULT 0",
                              "fallbacks": "INTEGER NOT NULL DEFAULT 0",
                              "last_fallback": "TEXT NOT NULL DEFAULT ''"}.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE schedule_refresh_state ADD COLUMN {name} {declaration}")


def suspicious(payload: dict, previous: dict | None) -> bool:
    if not previous:
        return False
    meta = payload.get("meta", {})
    start = max(epoch(meta.get("coverage_from")), epoch(previous.get("meta", {}).get("coverage_from")))
    end = min(epoch(meta.get("coverage_to")), epoch(previous.get("meta", {}).get("coverage_to")))
    if not start or end <= start:
        return False
    def count(p: dict) -> int:
        return sum(start <= epoch(r.get("scheduled") or r.get("estimated") or r.get("actual")) <= end
                   for r in p.get("records", []))
    before, after = count(previous), count(payload)
    # Empty cold/quiet boards are accepted. A busy overlapping board disappearing
    # needs a second independently fetched empty result before replacement.
    return before >= 8 and after < max(3, before // 4)


class ScheduleService:
    def __init__(self, path: Path, backend: Any, *, workers: int = 2, cold_wait: float = 30,
                 lease_seconds: float = 60, interval: int = 900) -> None:
        self.path, self.backend = path, backend
        self.cold_wait, self.lease_seconds, self.interval = cold_wait, lease_seconds, max(900, interval)
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="lf-schedule")
        self.slots = threading.BoundedSemaphore(workers)
        self.enrichment_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lf-schedule-fill")
        self.enrichment_slots = threading.BoundedSemaphore(1)
        self.closed = False
        conn = self.connect()
        try:
            ensure_schema(conn)
            conn.commit()
        finally:
            conn.close()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA secure_delete=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def close(self) -> None:
        self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.enrichment_executor.shutdown(wait=True, cancel_futures=True)

    def lane(self, airport: str) -> str:
        return hashlib.sha256(f"fids-v2:{airport}:{self.backend.policy_key()}".encode()).hexdigest()

    def _load(self, conn: sqlite3.Connection, lane: str, provider: str = "published") -> dict | None:
        row = conn.execute("SELECT payload FROM schedule_provider_cache WHERE lane=? AND provider=? AND expires_at>?",
                           (lane, provider, time.time())).fetchone()
        if not row:
            return None
        payload = json.loads(row[0])
        if not self.backend.allowed(payload.get("provider", "")):
            return None
        return payload

    def _usable(self, payload: dict | None, now: float) -> bool:
        if not payload:
            return False
        meta = payload.get("meta", {})
        return (0 <= now - epoch(meta.get("source_fetched_at")) <= 86400
                and epoch(meta.get("coverage_to")) > now and epoch(meta.get("expires_at")) > now)

    def read(self, *, airport: str, timezone_name: str, grace: int, horizon: int,
             min_interval: int = 900) -> dict:
        lane = self.lane(airport)
        now = time.time()
        conn = self.connect()
        try:
            conn.execute("INSERT OR IGNORE INTO schedule_refresh_state(lane, airport) VALUES (?, ?)", (lane, airport))
            conn.execute("UPDATE schedule_refresh_state SET grace=MAX(grace, ?), horizon=MAX(horizon, ?), accesses=accesses+1 WHERE lane=?",
                         (grace, horizon, lane))
            state = conn.execute("SELECT * FROM schedule_refresh_state WHERE lane=?", (lane,)).fetchone()
            payload = self._load(conn, lane)
            conn.commit()
        finally:
            conn.close()
        # Stricter access policy may slow this consumer's triggering of work;
        # another consumer can still reuse a snapshot already refreshed elsewhere.
        due = state["next_at"] <= now
        if payload:
            due = due and now - epoch(payload["meta"].get("source_fetched_at")) >= max(self.interval, min_interval)
        if due:
            self._schedule(lane, airport, timezone_name)
        if self._usable(payload, now):
            return self._view(lane, payload, grace, horizon)
        deadline = time.monotonic() + self.cold_wait
        while time.monotonic() < deadline:
            conn = self.connect()
            try:
                payload = self._load(conn, lane)
                state = conn.execute("SELECT * FROM schedule_refresh_state WHERE lane=?", (lane,)).fetchone()
            finally:
                conn.close()
            if self._usable(payload, time.time()):
                return self._view(lane, payload, grace, horizon)
            if state["lease_until"] <= time.time() and state["last_error"]:
                break
            if state["lease_until"] <= time.time() and state["next_at"] <= time.time():
                self._schedule(lane, airport, timezone_name)
            time.sleep(0.05)
        delay = max(10, math.ceil(state["next_at"] - time.time()))
        raise HTTPException(503, "Flight information is being prepared or temporarily unavailable",
                            headers={"Retry-After": str(delay)})

    def _schedule(self, lane: str, airport: str, timezone_name: str) -> None:
        if self.closed or not self.slots.acquire(blocking=False):
            return
        claimed = False
        conn = self.connect()
        try:
            now = time.time()
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM schedule_refresh_state WHERE lane=?", (lane,)).fetchone()
            if row["lease_until"] > now or row["next_at"] > now:
                return
            generation = row["generation"] + 1
            conn.execute("UPDATE schedule_refresh_state SET generation=?, lease_until=?, next_at=? WHERE lane=?",
                         (generation, now + self.lease_seconds, now + self.interval, lane))
            conn.commit()
            self.executor.submit(self._refresh, lane, generation, airport, timezone_name, row["grace"], row["horizon"])
            claimed = True
        finally:
            conn.close()
            if not claimed:
                self.slots.release()

    def _renew(self, lane: str, generation: int, stop: threading.Event) -> None:
        while not stop.wait(self.lease_seconds / 3):
            conn = self.connect()
            try:
                conn.execute("UPDATE schedule_refresh_state SET lease_until=? WHERE lane=? AND generation=? AND lease_until>?",
                             (time.time() + self.lease_seconds, lane, generation, time.time()))
                conn.commit()
            finally:
                conn.close()

    def _publish(self, lane: str, generation: int, payload: dict, *, published: bool) -> bool:
        meta = payload.setdefault("meta", {})
        fetched = epoch(meta.get("source_fetched_at") or payload.get("generated_at"))
        if not fetched or not epoch(meta.get("coverage_from")) or not epoch(meta.get("coverage_to")):
            raise ValueError("Missing provider coverage")
        meta["source_fetched_at"] = stamp(fetched)
        meta.setdefault("snapshot_id", uuid.uuid4().hex)
        meta["expires_at"] = stamp(min(epoch(meta.get("expires_at")) or float("inf"), fetched + self.backend.retention_seconds(payload["provider"])))
        meta["provider_fetched_at"] = {payload["provider"]: stamp(fetched)}
        payload["generated_at"] = stamp(fetched)
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT generation, lease_until FROM schedule_refresh_state WHERE lane=?", (lane,)).fetchone()
            if row[0] != generation or (published and row[1] <= time.time()) or not self.backend.allowed(payload["provider"]):
                return False
            previous = self._load(conn, lane, payload["provider"])
            if suspicious(payload, previous):
                empty = bool(meta.get("validated_empty")) and not payload["records"]
                confirmations = conn.execute("SELECT empty_confirmations FROM schedule_refresh_state WHERE lane=?", (lane,)).fetchone()[0]
                if not empty or confirmations < 1:
                    conn.execute("UPDATE schedule_refresh_state SET rejected=rejected+1, empty_confirmations=? WHERE lane=?", (int(empty), lane))
                    conn.commit()
                    raise ValueError("Suspicious overlapping coverage")
            conn.execute("UPDATE schedule_refresh_state SET empty_confirmations=0 WHERE lane=?", (lane,))
            for provider in ([payload["provider"], "published"] if published else [payload["provider"]]):
                conn.execute("INSERT OR REPLACE INTO schedule_provider_cache VALUES (?, ?, ?, ?, ?)",
                             (lane, provider, json.dumps(payload), fetched, epoch(meta["expires_at"])))
            if published:
                conn.execute("UPDATE schedule_refresh_state SET refreshes=refreshes+1, last_error='' WHERE lane=?", (lane,))
                reason = meta.get("fallback_reason")
                if reason in {"primary_budget_exhausted", "primary_fetch_failed", "primary_unavailable"}:
                    conn.execute("UPDATE schedule_refresh_state SET fallbacks=fallbacks+1, last_fallback=? WHERE lane=?", (reason, lane))
            else:
                primary = self._load(conn, lane)
                if primary:
                    _, fill_meta = enrich_schedule_records(primary["records"], payload["records"], fetched_at=meta["source_fetched_at"])
                    conn.execute("UPDATE schedule_refresh_state SET enrichment_fetches=enrichment_fetches+1, enrichment_fields=enrichment_fields+? WHERE lane=?",
                                 (fill_meta["filled_fields"], lane))
            conn.commit()
            return True
        finally:
            conn.close()

    def _refresh(self, lane: str, generation: int, airport: str, timezone_name: str, grace: int, horizon: int) -> None:
        stop = threading.Event()
        renewer = threading.Thread(target=self._renew, args=(lane, generation, stop), daemon=True)
        renewer.start()
        try:
            payload = self.backend.fetch(airport, timezone_name, grace, horizon)
            if not self._publish(lane, generation, payload, published=True):
                return
            # Primary is visible now; enrichment is independent of HTTP latency.
            needs_enrichment = any(not all(row.get(field) for field in ("gate", "terminal", "aircraft_type")) for row in payload["records"])
            if payload["provider"] == "aerodatabox" and needs_enrichment and self.backend.enrichment_enabled():
                self._queue_enrichment(lane, generation, airport, timezone_name, grace, horizon)
        except Exception as exc:
            delay = 0
            reason = "budget_exhausted" if getattr(exc, "reason_code", "") == "budget_exhausted" else "schedule_unavailable"
            if isinstance(exc, HTTPException):
                from relay.schedule_transport import retry_after
                if exc.headers and exc.headers.get("Retry-After"):
                    delay = retry_after(exc.headers["Retry-After"])
            conn = self.connect()
            try:
                conn.execute("UPDATE schedule_refresh_state SET last_error=?, next_at=MAX(next_at, ?) WHERE lane=? AND generation=?",
                             (reason, time.time() + delay, lane, generation))
                conn.commit()
            finally:
                conn.close()
        finally:
            stop.set()
            renewer.join()
            conn = self.connect()
            try:
                conn.execute("UPDATE schedule_refresh_state SET lease_until=0 WHERE lane=? AND generation=?", (lane, generation))
                conn.execute("DELETE FROM schedule_provider_cache WHERE expires_at<=?", (time.time(),))
                conn.commit()
            finally:
                conn.close()
                self.slots.release()

    def _queue_enrichment(self, lane: str, generation: int, airport: str, timezone_name: str, grace: int, horizon: int) -> None:
        if self.closed or not self.enrichment_slots.acquire(blocking=False):
            return
        claimed = False
        conn = self.connect()
        try:
            claim = conn.execute("UPDATE schedule_refresh_state SET enrichment_at=? WHERE lane=? AND enrichment_at<=? AND generation=?",
                                 (time.time(), lane, time.time() - 3600, generation)).rowcount
            conn.commit()
            if claim:
                self.enrichment_executor.submit(self._enrich, lane, generation, airport, timezone_name, grace, horizon)
                claimed = True
        finally:
            conn.close()
            if not claimed:
                self.enrichment_slots.release()

    def _enrich(self, lane: str, generation: int, airport: str, timezone_name: str, grace: int, horizon: int) -> None:
        try:
            fill = self.backend.enrich(airport, timezone_name, grace, horizon)
            # A newer primary generation invalidates this work. Enrichment never
            # replaces the published primary or extends its source timestamp.
            self._publish(lane, generation, fill, published=False)
        except Exception:
            pass
        finally:
            self.enrichment_slots.release()

    def _view(self, lane: str, payload: dict, grace: int, horizon: int) -> dict:
        result = copy.deepcopy(payload)
        meta = result["meta"]
        now = time.time()
        complete = meta.get("coverage_complete", True) and epoch(meta["coverage_from"]) <= now - grace * 60 and epoch(meta["coverage_to"]) >= now + horizon * 3600
        conn = self.connect()
        try:
            state = conn.execute("SELECT * FROM schedule_refresh_state WHERE lane=?", (lane,)).fetchone()
            fill = self._load(conn, lane, "aviationstack") if payload["provider"] == "aerodatabox" else None
            stale = now - epoch(meta["source_fetched_at"]) >= self.interval
            conn.execute("UPDATE schedule_refresh_state SET hits=hits+?, stale_serves=stale_serves+?, coverage_gaps=coverage_gaps+? WHERE lane=?",
                         (int(not stale), int(stale), int(not complete), lane))
            conn.commit()
        finally:
            conn.close()
        if fill:
            result["records"], enrichment_meta = enrich_schedule_records(result["records"], fill["records"],
                fetched_at=fill["meta"]["source_fetched_at"], now=datetime.fromtimestamp(now, timezone.utc))
            meta.update(enrichment_meta)
            if enrichment_meta["filled_fields"]:
                meta["provider_fetched_at"]["aviationstack"] = fill["meta"]["source_fetched_at"]
                meta["expires_at"] = min(meta["expires_at"], fill["meta"]["expires_at"])
                # Aggregate identity changes with enrichment, but source age does not.
                meta["snapshot_id"] = hashlib.sha256((meta["snapshot_id"] + fill["meta"]["snapshot_id"]).encode()).hexdigest()
        result["cache_state"] = "stale" if stale else "fresh"
        meta["coverage_complete"] = complete
        meta["next_refresh_at"] = stamp(state["next_at"])
        meta["refresh_after_s"] = max(10, math.ceil(state["next_at"] - now))
        notices = []
        if stale:
            notices.append({"code": "schedule.stale", "tone": "warning", "message": "Showing previously fetched flight information.", "next_step": "Local Flight will retry shortly."})
        if not complete:
            notices.append({"code": "schedule.partial", "tone": "warning", "message": "Flight information covers part of the requested period."})
        if state["lease_until"] > now:
            notices.append({"code": "schedule.refreshing", "tone": "info", "message": "Flight information is updating."})
        if state["last_error"] == "budget_exhausted" or meta.get("fallback_reason") == "primary_budget_exhausted":
            notices.append({"code": "schedule.budget_exhausted", "tone": "warning", "message": "The flight data allowance has been reached.", "next_step": "Updates resume when the allowance resets."})
        elif state["last_error"]:
            notices.append({"code": "schedule.unavailable", "tone": "warning", "message": "Fresh flight information is temporarily unavailable."})
        result["notices"] = notices
        # Serve only the requested, still-relevant interval, retaining flights
        # whose revised time brings them into view after a long delay.
        result["records"] = [r for r in result["records"] if any(
            now - grace * 60 <= epoch(r.get(k)) <= now + horizon * 3600
            for k in ("scheduled", "estimated", "actual"))]
        for key in ("snapshot_id", "source_fetched_at", "provider_fetched_at", "coverage_from", "coverage_to",
                    "coverage_complete", "next_refresh_at", "refresh_after_s", "expires_at"):
            result[key] = meta[key]
        # Metadata is assembled here, never copied from raw provider errors.
        meta.pop("provider_errors", None)
        return result
