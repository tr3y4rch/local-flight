"""Periodic relay heartbeat — asyncio background task, silent-failure, jitter-safe."""
from __future__ import annotations

import asyncio
import logging
import os
import random
import threading
import time

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL_S = 30 * 60  # 30 minutes nominal
_HEARTBEAT_JITTER_S = 5 * 60  # ±5 minutes uniform
_STARTUP_DELAY_S = 45  # wait after startup before first beat
_STARTUP_JITTER_S = 30  # ±30s startup spread
_HTTP_TIMEOUT_S = 8
_LOCAL_MIN_INTERVAL_S = 5 * 60  # sender-side backstop matching the relay cooldown
_last_send_at = 0.0
_send_guard = threading.Lock()


def _jitter(base: int, spread: int) -> float:
    return base + random.uniform(-spread, spread)


def _is_byok() -> bool:
    """True if the user supplied their own AviationStack key (bypasses relay)."""
    key = os.getenv("AVIATIONSTACK_API_KEY", "").strip()
    if not key:
        return False
    enabled = os.getenv("LOCALFLIGHT_AVIATIONSTACK_ENABLED", "").strip().lower()
    return not enabled or enabled in {"1", "true", "yes", "on"}


def _should_send() -> bool:
    """Gate: only real-flight relay installs after setup is complete."""
    try:
        from localflight.storage.config import config_path, load_config

        if not (config_path().parent / "setup_complete").exists():
            return False
        cfg = load_config()
        if (cfg.source or "").strip().lower() != "real":
            return False
        return not _is_byok()
    except Exception:
        return False


def _claim_send_slot() -> bool:
    """Return True when the local sender may emit one heartbeat now."""
    global _last_send_at
    now = time.monotonic()
    with _send_guard:
        if _last_send_at and (now - _last_send_at) < _LOCAL_MIN_INTERVAL_S:
            return False
        _last_send_at = now
        return True


def _send_now() -> None:
    """Send one heartbeat synchronously. Never raises."""
    import requests as _req

    from localflight.sources.web.relay_defaults import default_public_relay_url, relay_heartbeat_url
    from localflight.sources.web.relay_heartbeat import relay_client_metadata
    from localflight.storage.install import get_install_id

    try:
        url = relay_heartbeat_url(default_public_relay_url())
        payload = {"install_id": get_install_id(), **relay_client_metadata()}
        resp = _req.post(
            url,
            json=payload,
            headers={
                "User-Agent": "local-flight/1.0 (+https://beacontools.cc/local-flight)",
                "Accept": "application/json",
            },
            timeout=_HTTP_TIMEOUT_S,
        )
        logger.debug("Relay heartbeat | status=%s", resp.status_code)
    except Exception as exc:
        logger.debug("Relay heartbeat skipped (non-fatal): %s", exc)


async def _heartbeat_loop() -> None:
    """Asyncio task: startup beat after jitter delay, then every ~30 min forever."""
    await asyncio.sleep(_jitter(_STARTUP_DELAY_S, _STARTUP_JITTER_S))
    while True:
        if _should_send() and _claim_send_slot():
            await asyncio.get_event_loop().run_in_executor(None, _send_now)
        await asyncio.sleep(_jitter(_HEARTBEAT_INTERVAL_S, _HEARTBEAT_JITTER_S))


def fire_heartbeat() -> None:
    """Fire one immediate heartbeat (on config change or setup complete). Non-blocking."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running() and _should_send() and _claim_send_slot():
            asyncio.ensure_future(loop.run_in_executor(None, _send_now))
    except Exception:
        pass
