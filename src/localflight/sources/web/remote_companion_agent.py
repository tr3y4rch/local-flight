from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests

from localflight.remote_companion_crypto import decrypt_envelope, encrypt_envelope, remote_aad
from localflight.sources.web.relay_defaults import default_public_relay_url
from localflight.storage.config import config_path, load_config
from localflight.storage.install import get_activation_token, get_install_id
from localflight.storage.remote_companion import (
    get_remote_grant,
    list_remote_grants,
    mark_remote_grant_used,
    public_remote_grant,
)
from localflight.version import app_version as _app_version

log = logging.getLogger(__name__)

_AGENT_TASK: asyncio.Task[None] | None = None
_AGENT_LOOP: asyncio.AbstractEventLoop | None = None
_AGENT_WAKE: asyncio.Event | None = None
_REPLAY_CACHE: dict[str, dict[str, float]] = {}
_REPLAY_TTL_SECONDS = 10 * 60
_LOCAL_BASE_URL = "http://127.0.0.1:8000"

_ALLOWED_GET_EXACT = {
    "/api/health",
    "/api/config",
    "/api/mobile/summary",
    "/api/mobile/remote/probe",
    "/api/admin/system",
    "/api/admin/connections",
    "/api/admin/updates",
    "/api/admin/budget",
    "/api/admin/scheduler",
    "/api/metar",
    "/api/fids",
    "/api/fids/detail",
    "/api/history",
    "/api/history/summary",
    "/api/history/stats",
    "/api/history/flight",
    "/api/radar",
    "/api/radar/map",
    "/api/radar/surface",
    "/api/matrix/config",
    "/api/airports/search",
    "/api/airports/resolve",
}
_ALLOWED_GET_PREFIXES = ("/api/docs/",)
_ALLOWED_POST_EXACT = {
    "/api/admin/scheduler/restart",
    "/api/admin/companion/checkin",
    "/api/feedback",
    "/api/feedback/crash",
    "/api/matrix/config",
}
_ALLOWED_PATCH_EXACT = {"/api/config"}


def _setup_complete() -> bool:
    return (config_path().parent / "setup_complete").exists()


def _active_remote_grants() -> list[dict[str, Any]]:
    return [
        grant
        for grant in list_remote_grants(include_revoked=False)
        if grant.get("relay_url") and grant.get("grant_ref") and grant.get("remote_key")
    ]


def _relay_ws_url(relay_url: str, *, install_id: str, activation_token: str) -> str:
    base = (relay_url or default_public_relay_url()).rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    query = urlencode(
        {
            "install_id": install_id,
            "activation_token": activation_token,
            "app_version": _app_version(),
        }
    )
    return f"{base}/v1/remote-companion/host/ws?{query}"


def register_remote_grant_with_relay(grant: dict[str, Any], *, revoke: bool = False) -> dict[str, Any]:
    install_id = get_install_id()
    activation_token = get_activation_token()
    if not activation_token:
        raise RuntimeError("Remote Companion requires a relay activation token")
    relay_url = str(grant.get("relay_url") or default_public_relay_url()).rstrip("/")
    payload = {
        "install_id": install_id,
        "activation_token": activation_token,
        "install_ref": str(grant.get("install_ref") or ""),
        "grant_ref": str(grant.get("grant_ref") or ""),
        "companion_ref": str(grant.get("companion_id") or ""),
        "action": "revoke" if revoke else "register",
        "client_name": str(grant.get("client_name") or ""),
        "device_type": str(grant.get("device_type") or ""),
        "app_version": str(grant.get("app_version") or ""),
    }
    response = requests.post(
        f"{relay_url}/v1/remote-companion/grants",
        json=payload,
        timeout=10,
    )
    if not response.ok:
        detail = response.text[:240]
        try:
            detail = response.json().get("detail") or detail
        except Exception:
            pass
        raise RuntimeError(detail or f"Relay returned HTTP {response.status_code}")
    data = response.json()
    return data if isinstance(data, dict) else {"ok": True}


def ensure_remote_companion_agent_started() -> None:
    global _AGENT_LOOP, _AGENT_TASK, _AGENT_WAKE
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _AGENT_TASK and not _AGENT_TASK.done():
        return
    _AGENT_LOOP = loop
    _AGENT_WAKE = asyncio.Event()
    _AGENT_TASK = loop.create_task(_agent_loop(), name="remote-companion-agent")


def wake_remote_companion_agent() -> None:
    """Wake the host relay loop after a phone grant is created."""
    if _AGENT_LOOP is None or _AGENT_WAKE is None or _AGENT_LOOP.is_closed():
        return
    _AGENT_LOOP.call_soon_threadsafe(_AGENT_WAKE.set)


async def _agent_sleep(seconds: float) -> None:
    if _AGENT_WAKE is None:
        await asyncio.sleep(seconds)
        return
    try:
        await asyncio.wait_for(_AGENT_WAKE.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        _AGENT_WAKE.clear()


async def _agent_loop() -> None:
    while True:
        try:
            cfg = load_config()
            grants = _active_remote_grants()
            token = get_activation_token()
            if not cfg.remote_companion_enabled or not _setup_complete() or not token or not grants:
                await _agent_sleep(30)
                continue
            relay_url = str(grants[0].get("relay_url") or default_public_relay_url())
            await asyncio.to_thread(_sync_active_grants, grants)
            await _agent_session(relay_url=relay_url, activation_token=token)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.info("Remote Companion agent idle after relay error: %s", exc)
            await _agent_sleep(15)


async def _agent_session(*, relay_url: str, activation_token: str) -> None:
    try:
        import websockets
    except Exception as exc:
        log.info("Remote Companion agent unavailable; websockets package missing: %s", exc)
        await asyncio.sleep(60)
        return

    install_id = get_install_id()
    ws_url = _relay_ws_url(relay_url, install_id=install_id, activation_token=activation_token)
    async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
        log.info("Remote Companion agent connected to relay")
        async for raw in ws:
            try:
                message = json.loads(raw)
            except Exception:
                continue
            if not isinstance(message, dict) or message.get("type") != "request":
                continue
            response = await _handle_remote_request(message)
            await ws.send(json.dumps(response, separators=(",", ":")))


def _sync_active_grants(grants: list[dict[str, Any]]) -> None:
    for grant in grants:
        try:
            register_remote_grant_with_relay(grant)
        except Exception as exc:
            log.info(
                "Remote Companion grant sync failed for %s: %s",
                public_remote_grant(grant).get("grant_ref") or "unknown",
                exc,
            )


def _remember_message(*, grant_ref: str, request_id: str, nonce: str) -> None:
    now = time.monotonic()
    cache = _REPLAY_CACHE.setdefault(grant_ref, {})
    for key, seen_at in list(cache.items()):
        if now - seen_at > _REPLAY_TTL_SECONDS:
            cache.pop(key, None)
    request_key = f"request:{request_id}"
    nonce_key = f"nonce:{nonce}"
    if request_key in cache or nonce_key in cache:
        raise ValueError("Remote Companion replayed request rejected")
    cache[request_key] = now
    cache[nonce_key] = now


async def _handle_remote_request(message: dict[str, Any]) -> dict[str, Any]:
    request_id = str(message.get("request_id") or "")
    grant_ref = str(message.get("grant_ref") or "")
    install_ref = str(message.get("install_ref") or "")
    grant = get_remote_grant(grant_ref)
    if not grant or grant.get("revoked_at"):
        return {"type": "response", "request_id": request_id, "ok": False, "error": "remote_grant_revoked"}
    remote_key = str(grant.get("remote_key") or "")
    envelope = message.get("envelope") if isinstance(message.get("envelope"), dict) else {}
    response_aad = remote_aad(
        install_ref=install_ref,
        grant_ref=grant_ref,
        request_id=request_id,
        direction="response",
    )
    try:
        _remember_message(grant_ref=grant_ref, request_id=request_id, nonce=str(envelope.get("nonce") or ""))
        request_payload = decrypt_envelope(
            envelope,
            remote_key=remote_key,
            aad=remote_aad(
                install_ref=install_ref,
                grant_ref=grant_ref,
                request_id=request_id,
                direction="request",
            ),
        )
        result = await _dispatch_remote_payload(request_payload, grant=grant)
        mark_remote_grant_used(grant_ref)
    except Exception as exc:
        result = {"ok": False, "status": 502, "detail": str(exc)}
    encrypted = encrypt_envelope(result, remote_key=remote_key, aad=response_aad)
    return {
        "type": "response",
        "request_id": request_id,
        "install_ref": install_ref,
        "grant_ref": grant_ref,
        "ok": True,
        "envelope": encrypted,
    }


def _allowed_remote_path(method: str, raw_path: str) -> str:
    method = method.upper().strip()
    if "://" in raw_path or raw_path.startswith("//"):
        raise ValueError("Remote Companion path must be local")
    parsed = urlsplit(raw_path)
    path = parsed.path or "/"
    if method == "GET" and (path in _ALLOWED_GET_EXACT or any(path.startswith(prefix) for prefix in _ALLOWED_GET_PREFIXES)):
        return path + (f"?{parsed.query}" if parsed.query else "")
    if method == "POST" and path in _ALLOWED_POST_EXACT:
        return path + (f"?{parsed.query}" if parsed.query else "")
    if method == "PATCH" and path in _ALLOWED_PATCH_EXACT:
        return path + (f"?{parsed.query}" if parsed.query else "")
    raise ValueError(f"Remote Companion does not allow {method} {path}")


async def _dispatch_remote_payload(payload: dict[str, Any], *, grant: dict[str, Any]) -> dict[str, Any]:
    method = str(payload.get("method") or "GET").upper().strip()
    path = _allowed_remote_path(method, str(payload.get("path") or ""))
    body = payload.get("body") if isinstance(payload.get("body"), dict) else None
    headers = {
        "Accept": "application/json",
        "X-LocalFlight-Client-Type": "mobile-companion",
        "X-LocalFlight-Companion-Id": str(grant.get("companion_id") or "remote-companion"),
        "X-LocalFlight-Client-Name": str(grant.get("client_name") or "Local Flight Companion"),
        "X-LocalFlight-Client-Platform": str(grant.get("mobile_os") or "remote"),
        "X-LocalFlight-Device-Type": str(grant.get("device_type") or "phone"),
        "X-LocalFlight-App-Version": str(grant.get("app_version") or ""),
    }
    if method in {"POST", "PATCH"}:
        headers["Content-Type"] = "application/json"

    def _call() -> dict[str, Any]:
        response = requests.request(
            method,
            f"{_LOCAL_BASE_URL}{path}",
            headers=headers,
            json=body if method in {"POST", "PATCH"} else None,
            timeout=20,
        )
        try:
            data: Any = response.json()
        except Exception:
            data = {"text": response.text[:4096]}
        return {
            "ok": bool(response.ok),
            "status": int(response.status_code),
            "body": data,
        }

    return await asyncio.to_thread(_call)


__all__ = [
    "ensure_remote_companion_agent_started",
    "register_remote_grant_with_relay",
    "wake_remote_companion_agent",
]
