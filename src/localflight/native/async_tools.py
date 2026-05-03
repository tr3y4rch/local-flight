"""Shared async helpers for native Qt pages."""
from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

API_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lf-native-api")
LOG = logging.getLogger("localflight.native")


class AsyncFetchMixin:
    """Run slow local API calls away from the Qt UI thread.

    The mixin uses Qt signals rather than a fixed polling timer, so the UI wakes
    only when a background request finishes. Repeated refresh requests coalesce
    into one active fetch plus one queued follow-up.
    """

    def _init_async(self, QtCore: Any, owner: Any) -> None:
        self._pending_fetch: Future[Any] | None = None
        self._fetch_active = False
        self._pending_apply: Callable[[Any], None] | None = None
        self._pending_error: Callable[[Exception], None] | None = None
        self._pending_label = self.__class__.__name__
        self._pending_started_at = 0.0
        self._pending_cache_start: dict[str, int] = {"hits": 0, "misses": 0}
        self._queued_fetch: tuple[
            Callable[[], Any],
            Callable[[Any], None],
            Callable[[Exception], None],
            str,
            int,
        ] | None = None

        class _AsyncBridge(QtCore.QObject):
            completed = QtCore.Signal(object)
            failed = QtCore.Signal(object)

        self._async_qt = QtCore
        self._async_bridge = _AsyncBridge(owner)
        self._async_bridge.completed.connect(self._async_completed)
        self._async_bridge.failed.connect(self._async_failed)
        self._debounce_timer = QtCore.QTimer(owner)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._start_queued_fetch)

    def _run_async(
        self,
        work: Callable[[], Any],
        apply: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        *,
        label: str = "",
        debounce_ms: int = 80,
    ) -> bool:
        if self._fetch_active:
            self._queued_fetch = (work, apply, on_error, label or self.__class__.__name__, debounce_ms)
            return False
        self._queued_fetch = (work, apply, on_error, label or self.__class__.__name__, debounce_ms)
        if debounce_ms > 0:
            self._debounce_timer.start(debounce_ms)
            return True
        self._start_queued_fetch()
        return True

    def _start_queued_fetch(self) -> None:
        if self._fetch_active:
            return
        queued = self._queued_fetch
        if queued is None:
            return
        work, apply, on_error, label, _debounce_ms = queued
        self._queued_fetch = None
        self._pending_apply = apply
        self._pending_error = on_error
        self._pending_label = label
        self._pending_started_at = time.perf_counter()
        self._pending_cache_start = self._cache_counters()
        self._fetch_active = True

        def _worker() -> None:
            try:
                self._async_bridge.completed.emit(work())
            except Exception as exc:  # pragma: no cover - exercised by Qt runtime
                self._async_bridge.failed.emit(exc)

        self._pending_fetch = API_EXECUTOR.submit(_worker)

    def _cache_counters(self) -> dict[str, int]:
        client = getattr(self, "client", None)
        if client is not None and hasattr(client, "cache_counters"):
            try:
                return client.cache_counters()
            except Exception:
                return {"hits": 0, "misses": 0}
        return {"hits": 0, "misses": 0}

    def _log_refresh_elapsed(self) -> None:
        elapsed_ms = int((time.perf_counter() - self._pending_started_at) * 1000) if self._pending_started_at else 0
        if elapsed_ms < 650:
            return
        counters = self._cache_counters()
        hits = max(0, counters.get("hits", 0) - self._pending_cache_start.get("hits", 0))
        misses = max(0, counters.get("misses", 0) - self._pending_cache_start.get("misses", 0))
        LOG.info(
            "Native refresh slow | screen=%s elapsed_ms=%s cache_hits=%s cache_misses=%s",
            self._pending_label,
            elapsed_ms,
            hits,
            misses,
        )

    def _async_completed(self, result: Any) -> None:
        self._pending_fetch = None
        self._fetch_active = False
        apply = self._pending_apply
        self._pending_apply = None
        self._pending_error = None
        self._log_refresh_elapsed()
        if apply:
            apply(result)
        self._start_followup_fetch()

    def _async_failed(self, exc: Exception) -> None:
        self._pending_fetch = None
        self._fetch_active = False
        on_error = self._pending_error
        self._pending_apply = None
        self._pending_error = None
        self._log_refresh_elapsed()
        if on_error:
            on_error(exc)
        self._start_followup_fetch()

    def _start_followup_fetch(self) -> None:
        if self._queued_fetch is not None:
            self._async_qt.QTimer.singleShot(0, self._start_queued_fetch)


_AsyncFetchMixin = AsyncFetchMixin
