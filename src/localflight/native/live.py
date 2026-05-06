"""Native live-update bus for the PySide6 shell."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse


def native_ws_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    host = parsed.netloc or parsed.path
    return f"{scheme}://{host}/ws"


@dataclass(frozen=True)
class LiveStatus:
    text: str
    connected: bool


class NativeLiveBus:  # pragma: no cover - Qt runtime exercised in integration tests
    """Own the native WebSocket lifecycle and dispatch decoded event payloads."""

    def __init__(
        self,
        QtCore: Any,
        QtWebSockets: Any,
        owner: Any,
        *,
        base_url: str,
        on_event: Callable[[dict[str, Any]], None],
        on_status: Callable[[LiveStatus], None],
    ) -> None:
        self.QtCore = QtCore
        self.owner = owner
        self.url = native_ws_url(base_url)
        self.on_event = on_event
        self.on_status = on_status
        self.retry_ms = 1000
        self.closed = False
        self.socket = QtWebSockets.QWebSocket()
        self.retry_timer = QtCore.QTimer(owner)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.timeout.connect(self.connect)
        self.socket.connected.connect(self._connected)
        self.socket.disconnected.connect(self._disconnected)
        self.socket.textMessageReceived.connect(self._message)
        if hasattr(self.socket, "errorOccurred"):
            self.socket.errorOccurred.connect(lambda _err: self._failed())
        owner.destroyed.connect(self.close)

    def start(self) -> None:
        self.connect()

    def connect(self) -> None:
        if self.closed:
            return
        self.on_status(LiveStatus("live push connecting", False))
        self.socket.open(self.QtCore.QUrl(self.url))

    def close(self) -> None:
        self.closed = True
        self.retry_timer.stop()
        try:
            self.socket.close()
        except RuntimeError:
            pass

    def _connected(self) -> None:
        self.retry_ms = 1000
        self.on_status(LiveStatus("live push connected", True))

    def _failed(self) -> None:
        if not self.closed:
            self.on_status(LiveStatus("live push reconnecting", False))

    def _disconnected(self) -> None:
        if self.closed:
            return
        self.on_status(LiveStatus("live push offline", False))
        self.retry_timer.start(min(self.retry_ms, 30000))
        self.retry_ms = min(self.retry_ms * 2, 30000)

    def _message(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            self.on_event(payload)


def event_refresh_targets(event_type: str, fallback_keys: set[str], current_key: str) -> set[str]:
    if event_type == "config_updated":
        return set(fallback_keys)
    if event_type in {"snapshot_updated", "scheduler_restarted"}:
        return {key for key in fallback_keys if key != current_key}
    return set()
