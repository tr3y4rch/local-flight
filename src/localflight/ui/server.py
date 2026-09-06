from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import time as _time
import ipaddress
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from localflight.companion_pairing import pairing_gateway_payload, pairing_qr_png_bytes
from localflight.ui.api import router as api_router
from localflight.ui.matrix_guidance import matrix_guidance_payload
from localflight.core.airports import best_label, city_country_label
from localflight.core.notices import attach_notices, make_notice
from localflight.core.settings_options import settings_options_context
from localflight.core.timezones import resolve_airport_timezone, resolve_config_timezone
from localflight.sources.web.relay_defaults import default_public_relay_url, relay_endpoint_url, validate_public_relay_url
from localflight.storage.config import (
    AppConfig, load_config, save_config,
    ALLOWED_DATA_ROUTES,
    ALLOWED_DIAGNOSTICS_MODES, DEFAULT_DIAGNOSTICS_MODE,
    ALLOWED_OUTPUTS, ALLOWED_SOURCES, ALLOWED_SKINS,
    ALLOWED_RADAR_SURFACE_MODES, DEFAULT_RADAR_SURFACE_MODE,
    DEFAULT_DISPLAY_GRACE_MINUTES, DEFAULT_DISPLAY_HORIZON_HOURS,
    DEFAULT_OUTPUTS, DEFAULT_SOURCE, DEFAULT_SKIN,
    DEFAULT_WEB_ROTATION_SECONDS, DEFAULT_WEB_ROW_LIMIT,
)
from localflight.storage.provider_keys import (
    AERODATABOX_DEFAULT_FIDS_UNITS,
    AERODATABOX_DEFAULT_MONTHLY_UNITS,
    SECRET_KEYS,
    apply_byok_values,
    apply_relay_values,
    apply_virtual_values,
    clear_provider_keys,
    env_path as provider_env_path,
    normalize_aerodatabox_marketplace,
    provider_env_values,
    provider_status,
    read_env as read_provider_env,
    reload_provider_env,
    save_provider_keys,
    show_provider_key_settings,
    write_env as write_provider_env,
)
from localflight.storage.logging_setup import (
    logs_dir, setup_logging,
    MAX_LOG_FILES, MAX_LOG_DAYS, MAX_LOG_BYTES,
)
from localflight.storage.profiles import delete_profile, list_profiles, load_profile, save_profile
from localflight.storage.state import load_state
from localflight.version import app_version, user_agent

logger = setup_logging()

ALLOWED_REFRESH_SECONDS = {900, 1800, 2700, 3600, 7200, 14400, 28800, 43200, 86400}
DEFAULT_REFRESH_SECONDS = 3600
FETCH_COOLDOWN_SECONDS = 900
SCHEDULER_SYNC_FIELDS = (
    "airport_iata",
    "airport_icao",
    "refresh_seconds",
    "source",
    "data_route",
    "timezone",
    "display_grace_minutes",
    "display_horizon_hours",
)


def _schedule_policy_for_source(source: Optional[str], data_route: Optional[str] = None) -> Dict[str, Any]:
    try:
        from localflight.sources.web.aviationstack_client import schedule_policy

        cfg = load_config()
        return schedule_policy(source or cfg.source, data_route=data_route or cfg.data_route)
    except Exception:
        allowed = sorted(ALLOWED_REFRESH_SECONDS)
        return {
            "shared_relay": False,
            "active_mode": "unknown",
            "community_shared": False,
            "min_refresh_seconds": min(allowed) if allowed else DEFAULT_REFRESH_SECONDS,
            "allowed_refresh_seconds": allowed,
            "reason": "",
            "cooldown_remaining_seconds": 0,
        }


def _coerce_refresh_for_policy(refresh_seconds: int, source: Optional[str]) -> int:
    policy = _schedule_policy_for_source(source)
    allowed = [int(value) for value in (policy.get("allowed_refresh_seconds") or []) if int(value) in ALLOWED_REFRESH_SECONDS]
    if not allowed:
        allowed = sorted(ALLOWED_REFRESH_SECONDS)
    refresh = int(refresh_seconds)
    if refresh in allowed:
        return refresh
    minimum = int(policy.get("min_refresh_seconds") or min(allowed))
    for value in sorted(allowed):
        if value >= max(refresh, minimum):
            return value
    return max(allowed)


def _settings_options_for_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    options = settings_options_context()
    allowed = {int(value) for value in (policy.get("allowed_refresh_seconds") or [])}
    if allowed:
        options["refresh"] = [option for option in options["refresh"] if int(option.get("value", 0)) in allowed]
    return options


def _scheduler_config_changed(before: AppConfig, after: AppConfig) -> bool:
    return any(getattr(before, field) != getattr(after, field) for field in SCHEDULER_SYNC_FIELDS)


def _data_route_label(route: str) -> str:
    return {
        "relay": "Beacon Relay",
        "byok": "Bring Your Own Keys",
        "vatsim": "VATSIM",
    }.get(str(route or "").strip().lower(), "Beacon Relay")


def _network_tools_enabled() -> bool:
    return os.getenv("LOCALFLIGHT_ENABLE_NETWORK_TOOLS", "").strip().lower() in {"1", "true", "yes", "on"}


# â”€â”€ Setup gate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Paths always accessible even before setup completes
_SETUP_FREE_PATHS = {
    "/splash",
    "/setup",
    "/api/setup/complete",
    "/api/setup/reset",
    "/api/setup/client-info",
    "/api/setup/access/catalog",
    "/api/setup/access/deactivate",
    "/api/setup/activate",
    "/api/setup/client-status",
    "/api/setup/request-activation",
    "/api/setup/request-activation/status",
    "/api/setup/test-activation",
    "/api/setup/test-aerodatabox",
    "/api/setup/test-aviationstack",
    "/api/setup/test-opensky",
    "/api/setup/test-rapidapi",
    "/api/airports/search",
    "/static",
    "/health",
    "/ws",
}
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _normalized_request_host(value: str) -> str:
    host = (value or "").strip().lower()
    if not host:
        return ""
    if host.startswith("[") and "]" in host:
        return host[1 : host.index("]")]
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def _origin_host(value: str) -> str:
    try:
        parsed = urlparse(value or "")
    except Exception:
        return ""
    return _normalized_request_host(parsed.netloc or "")


def _is_cross_origin_mutation(request: Request) -> bool:
    if request.method.upper() not in _UNSAFE_METHODS:
        return False

    fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if fetch_site == "cross-site":
        return True

    request_host = _normalized_request_host(request.headers.get("host", ""))
    for header_name in ("origin", "referer"):
        raw = request.headers.get(header_name, "")
        if not raw:
            continue
        source_host = _origin_host(raw)
        if source_host and request_host and source_host != request_host:
            return True
    return False


def _setup_complete() -> bool:
    from localflight.storage.config import config_path
    return (config_path().parent / "setup_complete").exists()


def _mark_setup_complete() -> None:
    from localflight.storage.config import config_path
    marker = config_path().parent / "setup_complete"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


class SetupGateMiddleware(BaseHTTPMiddleware):
    """Redirects all requests to /setup until setup_complete marker exists."""

    async def dispatch(self, request: Request, call_next):
        if _setup_complete():
            return await call_next(request)

        path = request.url.path
        for free in _SETUP_FREE_PATHS:
            if path == free or path.startswith(free + "/"):
                return await call_next(request)

        return RedirectResponse(url="/setup", status_code=302)


class LocalMutationGuardMiddleware(BaseHTTPMiddleware):
    """Blocks browser drive-by POSTs from unrelated origins."""

    async def dispatch(self, request: Request, call_next):
        if _is_cross_origin_mutation(request):
            return JSONResponse({"detail": "Cross-origin mutation blocked"}, status_code=403)
        return await call_next(request)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request to the local traffic DB (non-fatal)."""

    async def dispatch(self, request: Request, call_next):
        start = _time.monotonic()
        response = await call_next(request)
        latency_ms = int((_time.monotonic() - start) * 1000)
        try:
            from localflight.storage.request_log import log_request
            ip = request.headers.get("fly-client-ip", "").strip() or (
                request.client.host if request.client else "unknown"
            )
            log_request(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                latency_ms=latency_ms,
                ip=ip,
                user_agent=request.headers.get("user-agent", ""),
                client_id=request.headers.get("x-localflight-companion-id", ""),
                platform=request.headers.get("x-localflight-client-platform", ""),
                client_type_override=request.headers.get("x-localflight-client-type", ""),
            )
        except Exception:
            pass
        return response


# â”€â”€ App setup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def _static_asset_version() -> str:
    """Fingerprint bundled assets so updated clients never reuse stale CSS."""
    digest = hashlib.sha256()
    static_dir = _static_dir()
    for asset in sorted(path for path in static_dir.rglob("*") if path.is_file()):
        digest.update(asset.relative_to(static_dir).as_posix().encode("utf-8"))
        digest.update(asset.read_bytes())
    return digest.hexdigest()[:12]


_RELAY_RELEASE_RETRY_STARTUP_S = 60
_RELAY_RELEASE_RETRY_INTERVAL_S = 5 * 60


def _recover_data_route_transition() -> None:
    """Finish the safe part of a setup transition interrupted by shutdown."""
    from localflight.storage.install import get_stored_activation_token, update_relay_access_summary
    from localflight.storage.route_transition import complete_route_transition, load_route_transition

    transition = load_route_transition()
    if not transition:
        return
    cfg = load_config()
    target = str(transition.get("target_route") or "")
    stage = str(transition.get("stage") or "")
    if stage == "started" and cfg.data_route != target:
        complete_route_transition()
        return
    if cfg.data_route != target and stage in {"provider_saved", "route_saved"}:
        values = asdict(cfg)
        values.update(data_route=target, source="virtual" if target == "vatsim" else "real")
        save_config(AppConfig(**values))
    if target != "relay" and get_stored_activation_token():
        update_relay_access_summary(
            relay_state="release_pending",
            reason_code="route_transition_interrupted",
            release_retry_after_s=0,
            release_retry_not_before="",
        )
    complete_route_transition()


async def _retry_pending_relay_release_once() -> bool:
    """Retry one deferred main-device release while a free route is active."""
    from localflight.storage.install import get_relay_access_summary

    access = get_relay_access_summary()
    if access.get("relay_state") != "release_pending":
        return False
    retry_not_before = str(access.get("release_retry_not_before") or "")
    if retry_not_before:
        try:
            if datetime.fromisoformat(retry_not_before) > datetime.now(timezone.utc):
                return False
        except ValueError:
            pass
    if load_config().data_route == "relay":
        # Returning to Relay is resolved by an explicit status check; never
        # release a credential behind that choice.
        return False
    await asyncio.to_thread(_deactivate_local_relay, _relay_url_default())
    return True


async def _relay_release_retry_loop() -> None:
    await asyncio.sleep(_RELAY_RELEASE_RETRY_STARTUP_S)
    while True:
        try:
            await _retry_pending_relay_release_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Deferred Relay Access release retry skipped: %s", exc)
        await asyncio.sleep(_RELAY_RELEASE_RETRY_INTERVAL_S)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    logger.info("Session started | component=ui")
    try:
        _recover_data_route_transition()
    except Exception as exc:
        logger.warning("Data route transition recovery deferred: %s", exc)
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)
    asyncio.create_task(manager.broadcast_loop())
    from localflight.sources.web.relay_beat import _heartbeat_loop
    asyncio.create_task(_heartbeat_loop())
    asyncio.create_task(_relay_release_retry_loop())
    try:
        from localflight.sources.web.remote_companion_agent import ensure_remote_companion_agent_started

        ensure_remote_companion_agent_started()
    except Exception as exc:
        logger.info("Remote Companion agent not started: %s", exc)

    import localflight.ui.server as _self
    _self._ws_manager = manager

    try:
        _ = best_label(iata="ZRH", icao="LSZH")
        logger.info("Airport DB loaded | component=ui")
    except Exception as e:
        logger.warning("Airport DB not available: %s", e)

    yield


app = FastAPI(title="Local Flight UI", lifespan=_lifespan, docs_url=None, redoc_url=None)

# Middleware order: RequestLog (outer, optional) -> MutationGuard -> SetupGate -> route.
# add_middleware is LIFO, so SetupGate must be added first.
app.add_middleware(SetupGateMiddleware)
app.add_middleware(LocalMutationGuardMiddleware)
if _network_tools_enabled():
    app.add_middleware(RequestLogMiddleware)

app.mount("/static", StaticFiles(directory=str(_static_dir())), name="static")
app.include_router(api_router)
templates = Jinja2Templates(directory=str(_templates_dir()))

_APP_VERSION = app_version()

templates.env.globals["app_version"] = _APP_VERSION
templates.env.globals["airport_timezone"] = resolve_config_timezone
templates.env.globals["static_version"] = _static_asset_version()


def _safe_local_path(path: str, *, fallback: str = "/display") -> str:
    """Accept only local absolute paths for splash redirects."""
    path = (path or "").strip()
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        return fallback
    return path


def _relay_url_default() -> str:
    return default_public_relay_url()


def _validated_setup_relay_url(relay_url: str) -> str:
    return validate_public_relay_url(relay_url or _relay_url_default(), trusted_default=_relay_url_default())


def _managed_status_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/managed/config")


def _client_status_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/client/status")


def _client_checkin_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/client/checkin")


def _access_activate_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/access/activate")


def _access_activate_commit_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/access/activate/commit")


def _access_status_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/access/status")


def _access_catalog_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/access/catalog")


def _access_deactivate_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/access/deactivate")


def _activate_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/activate")


def _activation_request_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/activation-request")


def _activation_request_status_url(relay_url: str) -> str:
    return _activation_request_url(relay_url).rstrip("/") + "/status"


BEACON_TOOLS_URL = "https://beacontools.cc"
LOCAL_FLIGHT_WEB_URL = f"{BEACON_TOOLS_URL}/local-flight"
PRIVACY_WEB_URL = f"{BEACON_TOOLS_URL}/privacy"

_DOC_PAGES: Dict[str, Dict[str, str]] = {
    "readme": {
        "title": "Project README",
        "filename": "README.md",
        "summary": "Friendly overview, quick path chooser, previews, and links to deeper docs.",
        "external_url": LOCAL_FLIGHT_WEB_URL,
        "external_label": "Open online",
    },
    "install": {
        "title": "Install Guide",
        "filename": "install.md",
        "summary": "Platform install steps for Windows, macOS, Raspberry Pi, source checkout, and mobile apps.",
        "external_url": f"{LOCAL_FLIGHT_WEB_URL}#install",
        "external_label": "Open online",
    },
    "display-modes": {
        "title": "Display Modes",
        "filename": "display-modes.md",
        "summary": "How native desktop, LAN browser, Pi kiosk, mobile, and Matrix clients fit together.",
        "external_url": f"{LOCAL_FLIGHT_WEB_URL}#display-modes",
        "external_label": "Open online",
    },
    "client-notes": {
        "title": "0.6.0 Public Release Notes",
        "filename": "release-notes-0.6.0.md",
        "summary": "0.6.0 release notes for desktop, server, Pi, Beacon Relay Access, Matrix, and mobile testing.",
        "external_url": f"{LOCAL_FLIGHT_WEB_URL}#release-notes",
        "external_label": "Open online",
    },
    "privacy": {
        "title": "Privacy & Diagnostics",
        "filename": "PRIVACY.md",
        "summary": "What stays local, what reporting can send, and how diagnostics modes work.",
        "external_url": PRIVACY_WEB_URL,
        "external_label": "Open privacy policy",
    },
    "changelog": {
        "title": "Release Notes",
        "filename": "CHANGELOG.md",
        "summary": "Version history and recent release changes.",
        "external_url": f"{LOCAL_FLIGHT_WEB_URL}#release-notes",
        "external_label": "Open online",
    },
    "third-party": {
        "title": "Third-Party Notices",
        "filename": "THIRD_PARTY_NOTICES.md",
        "summary": "Bundled font licenses and source attribution for local app assets.",
        "external_url": f"{LOCAL_FLIGHT_WEB_URL}#third-party",
        "external_label": "Open online",
    },
}


def _resolve_doc_path(filename: str) -> Optional[Path]:
    here = Path(__file__).resolve()
    candidates = [
        here.parent / "docs" / filename,
        here.parents[3] / "docs" / filename,
        here.parents[3] / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _doc_payload(slug: str) -> Dict[str, Any]:
    doc_slug = (slug or "").strip().lower()
    page = _DOC_PAGES.get(doc_slug)
    if not page:
        raise HTTPException(status_code=404, detail="Document not found")

    path = _resolve_doc_path(page["filename"])
    bundled = path is not None
    content = (
        path.read_text(encoding="utf-8", errors="replace")
        if path is not None
        else f"{page['filename']} is not bundled with this build."
    )

    external_url = page.get("external_url") or page.get("github_url") or LOCAL_FLIGHT_WEB_URL
    external_label = page.get("external_label") or "Open online"
    return {
        "slug": doc_slug,
        "title": page["title"],
        "summary": page["summary"],
        "filename": page["filename"],
        "external_url": external_url,
        "external_label": external_label,
        # Deprecated compatibility alias for older mobile clients.
        "github_url": external_url,
        "content": content,
        "bundled": bundled,
    }


# â”€â”€ WebSocket connection manager â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.debug("WS connect â€” %d active", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.debug("WS disconnect â€” %d active", len(self._connections))

    async def _broadcast(self, message: str) -> None:
        dead: Set[WebSocket] = set()
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._connections.discard(ws)

    async def broadcast_loop(self) -> None:
        while True:
            message = await self._queue.get()
            await self._broadcast(message)

    def notify(self, event_type: str, payload: Optional[dict] = None) -> None:
        if self._loop is None or not self._connections:
            return
        msg = json.dumps({"type": event_type, **(payload or {})})
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, msg)
        except Exception as exc:
            logger.debug("WS notify failed: %s", exc)


manager = ConnectionManager()
_ws_manager: Optional[ConnectionManager] = None


# â”€â”€ Background fetch helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _should_fetch() -> bool:
    state = load_state()
    if not state.last_attempt_utc:
        return True
    try:
        last = datetime.fromisoformat(state.last_attempt_utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last > timedelta(seconds=FETCH_COOLDOWN_SECONDS)
    except Exception:
        return True


def _background_fetch(cfg: AppConfig) -> None:
    from localflight.scheduler.jobs import run_snapshot_job
    try:
        flights = run_snapshot_job(cfg)
        logger.info(
            "Background fetch complete: %d flights for %s (source=%s)",
            len(flights), cfg.airport_iata, cfg.source,
        )
    except Exception as exc:
        logger.error("Background fetch failed: %s", exc)


# â”€â”€ WebSocket endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


# â”€â”€ Setup wizard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _request_is_loopback(request: Request | None) -> bool:
    if request is None:
        # Direct/native callers are local. HTTP routes always receive Request.
        return True
    host = str(request.client.host if request.client else "").strip().split("%", 1)[0]
    if host in {"localhost", "testclient"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request) -> HTMLResponse:
    from localflight.ui.setup_guidance import guidance_context

    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={
            "relay_url_default": _relay_url_default(),
            "setup_guidance": guidance_context(),
            "allow_license_key": _request_is_loopback(request),
        },
    )


@app.get("/api/setup/client-info")
def setup_client_info(request: Request = None) -> Dict[str, Any]:
    from localflight.storage.install import get_install_fingerprint, get_relay_access_summary, get_stored_activation_token

    cfg = load_config()
    # Reading setup state is the migration boundary for the former .env copy.
    # The returned payload below remains summary-only.
    get_stored_activation_token()
    access = get_relay_access_summary()
    provider_values = provider_env_values()
    fingerprint = get_install_fingerprint()
    return {
        # Compatibility alias: client-facing install_id has always been used as
        # a display/support value. Keep the field while returning no raw UUID.
        "install_id": fingerprint,
        "install_fingerprint": fingerprint,
        "relay_url": _relay_url_default(),
        "activation_token_present": bool(access["credential_present"]),
        "activation_token_prefix": access["credential_reference"],
        "relay_state": access["relay_state"],
        "access_state": access["access_state"],
        "reason_code": access["reason_code"],
        "license_reference": access["license_reference"],
        "masked_key_reference": access["masked_key_reference"],
        "purchase_source": access["purchase_source"],
        "current_main_device_description": access["current_main_device_description"],
        "last_successful_check_time": access["last_successful_check_time"],
        "master_key_allowed": _request_is_loopback(request),
        "provider_keys": {
            "aerodatabox_configured": bool(str(provider_values.get("AERODATABOX_API_KEY") or "").strip()),
            "aviationstack_configured": bool(str(provider_values.get("AVIATIONSTACK_API_KEY") or "").strip()),
            "adsbexchange_configured": bool(str(provider_values.get("RAPIDAPI_KEY") or "").strip()),
            "opensky_configured": bool(
                str(provider_values.get("OPENSKY_CLIENT_ID") or "").strip()
                or str(provider_values.get("OPENSKY_CLIENT_SECRET") or "").strip()
            ),
        },
        "config": {
            "airport_iata": cfg.airport_iata,
            "airport_icao": cfg.airport_icao,
            "timezone": cfg.timezone,
            "display_name": cfg.display_name,
            "diagnostics_mode": cfg.diagnostics_mode,
            "source": cfg.source,
            "data_route": cfg.data_route,
        },
    }


class ApiKeyTestIn(BaseModel):
    key: str = Field(..., min_length=1, max_length=256)


class AeroDataBoxKeyTestIn(BaseModel):
    key: str = Field(..., min_length=1, max_length=256)
    marketplace: str = Field("apimarket", max_length=32)
    airport_iata: str = Field("ZRH", max_length=4)
    monthly_units_limit: int = Field(AERODATABOX_DEFAULT_MONTHLY_UNITS, ge=0, le=250_000)


class OpenSkyKeyTestIn(BaseModel):
    opensky_id: str = Field(..., min_length=1, max_length=256)
    opensky_secret: str = Field(..., min_length=1, max_length=256)


class ProviderKeysSaveIn(BaseModel):
    aerodatabox_key: str = Field("", max_length=256)
    aerodatabox_marketplace: str = Field("apimarket", max_length=32)
    aerodatabox_monthly_units_limit: int = Field(AERODATABOX_DEFAULT_MONTHLY_UNITS, ge=0, le=250_000)
    aerodatabox_daily_units_limit: str = Field("", max_length=16)
    aviationstack_key: str = Field("", max_length=256)
    rapidapi_key: str = Field("", max_length=256)
    opensky_id: str = Field("", max_length=256)
    opensky_secret: str = Field("", max_length=256)


class ActivationSetupIn(BaseModel):
    relay_url: str = Field("", max_length=300)
    airport_iata: str = Field("", max_length=4)
    airport_icao: str = Field("", max_length=4)
    display_name: str = Field("", max_length=80)
    requested_mode: str = Field("relay", max_length=20)
    license_key: str = Field("", max_length=200)
    activation_grant: str = Field("", max_length=200)
    confirm_move_token: str = Field("", max_length=200)


class ClientStatusSetupIn(BaseModel):
    relay_url: str = Field("", max_length=300)
    activation_token: str = Field("", max_length=256)


class ActivationTokenTestIn(BaseModel):
    relay_url: str = Field("", max_length=300)
    activation_token: str = Field("", max_length=256)


class RelayAccessLocalIn(BaseModel):
    relay_url: str = Field("", max_length=300)


def _relay_detail(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error") or payload.get("message") or payload.get("decision_note")
        if isinstance(detail, dict):
            detail = detail.get("detail") or detail.get("error") or detail.get("message")
        if detail:
            return str(detail)
    return fallback


def _relay_status_code(payload: Any, http_status: int = 0) -> str:
    """Use the relay's stable code; never derive client state from prose."""
    detail = payload.get("detail") if isinstance(payload, dict) else None
    code = ""
    if isinstance(detail, dict):
        code = str(detail.get("code") or "").strip().lower()
    if not code and isinstance(payload, dict):
        code = str(payload.get("code") or payload.get("reason_code") or "").strip().lower()
    aliases = {
        "access_rate_limited": "rate_limited",
        "invalid_license_key": "invalid_license_key",
        "license_not_found": "credential_not_found",
        "license_inactive": "license_inactive",
        "invalid_challenge": "stale_move_token",
        "access_not_configured": "relay_unavailable",
        "relay_credential_required": "credential_not_found",
        "seat_in_use": "seat_in_use",
    }
    if code:
        return aliases.get(code, code[:80])
    if http_status == 429:
        return "rate_limited"
    if http_status in {401, 403}:
        return "inactive"
    if http_status >= 500:
        return "relay_unreachable"
    return "relay_error"


def _friendly_relay_error(detail: str, code: str, fallback: str) -> str:
    if code == "invalid_license_key":
        return "That Relay Access key or activation code was not accepted. Check it and try again."
    if code == "credential_not_found":
        return "This desktop's saved Relay Access credential is no longer recognized. Activate access again."
    if code == "license_inactive":
        return "Relay Access is not active. Open Relay Access details for the current status."
    if code == "stale_move_token":
        return "That move confirmation expired because the activation details changed. Start the move again."
    if code == "rate_limited":
        return "The relay is cooling down activation/status checks. Try again shortly."
    if code in {"relay_unavailable", "relay_unreachable"}:
        return "The relay could not be reached right now. Your local setup is unchanged."
    return fallback


def _retry_after_seconds(response: Any) -> int | None:
    try:
        raw = response.headers.get("Retry-After")
    except Exception:
        raw = None
    try:
        value = int(str(raw or "").strip())
    except Exception:
        return None
    return max(1, value)


def _relay_failure_payload(payload: Any, *, http_status: int = 0, fallback: str = "Relay request failed.", response: Any = None) -> Dict[str, Any]:
    detail = _relay_detail(payload, fallback)
    code = _relay_status_code(payload, http_status)
    result: Dict[str, Any] = {
        "ok": False,
        "status": code,
        "error": _friendly_relay_error(detail, code, fallback),
    }
    if http_status:
        result["relay_http_status"] = int(http_status)
    retry_after = _retry_after_seconds(response)
    if retry_after is not None:
        result["retry_after_s"] = retry_after
    if isinstance(payload, dict):
        for key in ("request_id", "install_fingerprint", "known_install", "can_reissue", "token_prefix"):
            if key in payload:
                result[key] = payload[key]
    if isinstance(payload, dict):
        source = payload.get("detail") if isinstance(payload.get("detail"), dict) else payload
        for key in ("access_state", "reason_code"):
            if isinstance(source, dict) and source.get(key):
                result[key] = source[key]
    tone = "warning" if code in {"rate_limited", "relay_unavailable", "relay_unreachable"} else "error"
    return attach_notices(
        result,
        [make_notice(
            f"relay.{code}",
            tone,
            result["error"],
            next_step="Your local setup is unchanged. Try again shortly or continue with a local setup option.",
            action={"kind": "settings", "label": "Open Settings", "target": "/settings"},
        )],
        route_family="setup",
        source_category="relay",
    )


def _relay_json_response(response: Any) -> Dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        payload = {"detail": f"Relay returned HTTP {response.status_code}"}
    return payload if isinstance(payload, dict) else {"detail": "Relay response was invalid"}


def _cache_access_payload(payload: Dict[str, Any], *, relay_state: str) -> None:
    from localflight.storage.install import update_relay_access_summary

    license_summary = payload.get("license") if isinstance(payload.get("license"), dict) else payload
    receiver = payload.get("receiver") if isinstance(payload.get("receiver"), dict) else payload
    device_name = str(receiver.get("device_name") or "").strip()
    device_kind = str(receiver.get("device_kind") or "").strip()
    description = device_name or device_kind
    update_relay_access_summary(
        relay_state=relay_state,
        access_state=license_summary.get("access_state") or payload.get("access_state") or "",
        reason_code=license_summary.get("reason_code") or payload.get("reason_code") or "",
        license_reference=license_summary.get("license_ref") or payload.get("license_ref") or "",
        masked_key_reference=license_summary.get("key_ref") or payload.get("key_ref") or "",
        purchase_source=license_summary.get("purchase_source") or payload.get("purchase_source") or "",
        current_main_device_description=description,
        last_successful_check_time=datetime.now(timezone.utc).isoformat() if relay_state in {"active", "inactive"} else "",
    )


def _mark_access_failure(payload: Dict[str, Any], *, http_status: int = 0) -> None:
    from localflight.storage.install import get_relay_access_summary, update_relay_access_summary

    code = _relay_status_code(payload, http_status)
    current = get_relay_access_summary()
    if code in {"relay_unavailable", "relay_unreachable", "rate_limited"}:
        state = "release_pending" if current.get("relay_state") == "release_pending" else "unreachable"
    else:
        state = "inactive"
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else payload
    reported_access_state = (detail.get("access_state") if isinstance(detail, dict) else "")
    # A failed or malformed status response must never leave a cached "active"
    # state authoritative. Terminal states are retained for actionable UI copy.
    access_state = str(reported_access_state or "").strip().lower()
    if access_state not in {"suspended", "refunded", "revoked"}:
        access_state = ""
    update_relay_access_summary(
        relay_state=state,
        access_state=access_state,
        reason_code=(detail.get("reason_code") if isinstance(detail, dict) else "") or code,
    )


def _deactivate_local_relay(relay_url: str) -> Dict[str, Any]:
    import requests as _req
    from localflight.storage.install import (
        clear_activation_token,
        get_install_id,
        get_stored_activation_token,
        update_relay_access_summary,
    )

    credential = get_stored_activation_token().strip()
    if not credential:
        update_relay_access_summary(relay_state="none", current_main_device_description="")
        return {"ok": True, "status": "inactive", "released": False}
    try:
        root = _validated_setup_relay_url(relay_url)
        response = _req.post(
            _access_deactivate_url(root),
            json={"install_id": get_install_id()},
            headers={"Accept": "application/json", "Authorization": f"Bearer {credential}"},
            timeout=12,
        )
    except Exception:
        retry_after = _RELAY_RELEASE_RETRY_INTERVAL_S
        update_relay_access_summary(
            relay_state="release_pending",
            reason_code="relay_unreachable",
            release_retry_after_s=retry_after,
            release_retry_not_before=(datetime.now(timezone.utc) + timedelta(seconds=retry_after)).isoformat(),
        )
        return {
            "ok": False,
            "status": "release_pending",
            "error": "Relay Access will be released when this desktop can reach Beacon Relay again.",
        }
    payload = _relay_json_response(response)
    code = _relay_status_code(payload, response.status_code)
    if response.status_code < 400 or code in {"credential_not_found", "license_inactive", "refunded", "revoked"}:
        clear_activation_token()
        update_relay_access_summary(
            relay_state="inactive",
            access_state=str(payload.get("access_state") or "active"),
            reason_code=str(payload.get("reason_code") or "main_device_released"),
            current_main_device_description="",
            last_successful_check_time=datetime.now(timezone.utc).isoformat(),
            release_retry_after_s=0,
            release_retry_not_before="",
        )
        return {"ok": True, "status": "inactive", "released": True, **payload}
    retry_after = _retry_after_seconds(response) or _RELAY_RELEASE_RETRY_INTERVAL_S
    update_relay_access_summary(
        relay_state="release_pending",
        reason_code=code,
        release_retry_after_s=retry_after,
        release_retry_not_before=(datetime.now(timezone.utc) + timedelta(seconds=retry_after)).isoformat(),
    )
    failure = _relay_failure_payload(payload, http_status=response.status_code, response=response)
    failure["status"] = "release_pending"
    failure["release_error_code"] = code
    return failure


@app.get("/api/setup/access/catalog")
async def setup_access_catalog(relay_url: str = Query("", max_length=300)) -> Dict[str, Any]:
    import requests as _req

    try:
        root = _validated_setup_relay_url(relay_url)
        response = await asyncio.to_thread(
            _req.get,
            _access_catalog_url(root),
            headers={"Accept": "application/json"},
            timeout=10,
        )
    except Exception:
        return {
            "ok": False,
            "status": "catalog_unavailable",
            "sales_available": False,
            "error": "New purchases are temporarily unavailable. Existing keys and activation codes can still be used.",
        }
    payload = _relay_json_response(response)
    if response.status_code >= 400:
        return {
            **_relay_failure_payload(payload, http_status=response.status_code, response=response),
            "status": "catalog_unavailable",
            "sales_available": False,
        }
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    sources = product.get("purchase_sources") if isinstance(product.get("purchase_sources"), dict) else {}
    stripe = sources.get("stripe") if isinstance(sources.get("stripe"), dict) else {}
    return {
        **payload,
        "ok": True,
        "sales_available": bool(product.get("sales_available") or stripe.get("available")),
    }


@app.post("/api/setup/access/deactivate")
async def setup_access_deactivate(body: RelayAccessLocalIn) -> Dict[str, Any]:
    return await asyncio.to_thread(_deactivate_local_relay, body.relay_url)


def _provider_error_text(payload: Any, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    error = payload.get("error")
    if not isinstance(error, dict):
        return fallback
    code = str(error.get("code") or "").strip()
    message = str(error.get("message") or error.get("info") or "").strip()
    combined = f"{code} {message}".casefold()
    if any(word in combined for word in ("quota", "rate limit", "too many")):
        return "This connection has reached its current usage allowance."
    if any(word in combined for word in ("invalid", "unauthorized", "forbidden", "access key")):
        return "This connection key was rejected. Check it and try again."
    return fallback


def _provider_test_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    notices = []
    if not result.get("ok"):
        message = str(result.get("error") or "This connection key could not be verified.")
        notices.append(make_notice(
            "provider.connection_check_failed",
            "warning",
            message,
            next_step="Check the connection details and try again. Nothing has been saved.",
        ))
    return attach_notices(
        result,
        notices,
        route_family="setup",
        source_category="provider",
    )


async def _test_aviationstack_key(key: str) -> Dict[str, Any]:
    """Test an AviationStack API key without saving it."""
    import requests as _req
    try:
        r = _req.get(
            "https://api.aviationstack.com/v1/flights",
            params={"access_key": key, "limit": 1},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if "error" in data:
                return {"ok": False, "error": _provider_error_text(data, "This connection key could not be verified.")}
            return {"ok": True}
        try:
            data = r.json()
        except Exception:
            data = {}
        return {"ok": False, "error": _provider_error_text(data, "This connection key could not be verified.")}
    except Exception:
        return {"ok": False, "error": "This connection could not be checked right now. Try again shortly."}


async def _test_aerodatabox_key(
    key: str,
    *,
    marketplace: str = "apimarket",
    airport_iata: str = "ZRH",
    monthly_units_limit: int = AERODATABOX_DEFAULT_MONTHLY_UNITS,
) -> Dict[str, Any]:
    """Test an AeroDataBox key without saving it."""
    import requests as _req

    from localflight.sources.web.aerodatabox_client import (
        AERODATABOX_APIMARKET_BASE_URL,
        AERODATABOX_RAPIDAPI_BASE_URL,
    )

    market = normalize_aerodatabox_marketplace(marketplace)
    airport = (airport_iata or "ZRH").strip().upper()[:3] or "ZRH"
    base = AERODATABOX_RAPIDAPI_BASE_URL if market == "rapidapi" else AERODATABOX_APIMARKET_BASE_URL
    headers = (
        {
            "X-RapidAPI-Key": key,
            "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com",
            "Accept": "application/json",
        }
        if market == "rapidapi"
        else {
            "x-magicapi-key": key,
            "Accept": "application/json",
        }
    )
    try:
        from localflight.sources.web import local_usage

        monthly_limit = max(0, int(monthly_units_limit or AERODATABOX_DEFAULT_MONTHLY_UNITS))
        local_usage.check_and_increment_many(
            [
                {
                    "service": "aerodatabox_units",
                    "amount": AERODATABOX_DEFAULT_FIDS_UNITS,
                    "monthly_limit": monthly_limit,
                    "daily_limit": max(1, (monthly_limit + 29) // 30),
                },
                {
                    "service": "aerodatabox_requests",
                    "amount": 1,
                    "monthly_limit": None,
                    "daily_limit": None,
                },
            ]
        )
    except Exception as exc:
        if exc.__class__.__name__ == "LocalBudgetExceeded":
            return {"ok": False, "error": "This connection has reached its current usage allowance."}
        logger.debug("AeroDataBox test budget guard unavailable; continuing with provider probe: %s", exc)
    try:
        r = _req.get(
            f"{base}/flights/airports/iata/{airport}",
            params={
                "offsetMinutes": 0,
                "durationMinutes": 60,
                "direction": "Both",
                "withLeg": "true",
                "withCancelled": "true",
                "withCodeshared": "true",
                "withCargo": "false",
                "withPrivate": "false",
                "withLocation": "false",
            },
            headers=headers,
            timeout=12,
        )
        if r.status_code in {200, 204}:
            return {"ok": True}
        if r.status_code in {401, 403}:
            return {"ok": False, "error": "AeroDataBox key invalid or not subscribed for this marketplace"}
        if r.status_code == 429:
            return {"ok": False, "error": "AeroDataBox provider quota or rate limit reached"}
        return {"ok": False, "error": "This connection key could not be verified."}
    except Exception:
        return {"ok": False, "error": "This connection could not be checked right now. Try again shortly."}


@app.post("/api/setup/test-aerodatabox")
async def setup_test_aerodatabox_post(body: AeroDataBoxKeyTestIn) -> Dict[str, Any]:
    return _provider_test_payload(await _test_aerodatabox_key(
        body.key,
        marketplace=body.marketplace,
        airport_iata=body.airport_iata,
        monthly_units_limit=body.monthly_units_limit,
    ))


@app.get("/api/setup/test-aerodatabox")
async def setup_test_aerodatabox_get(
    key: str = Query(...),
    marketplace: str = Query("apimarket"),
    airport_iata: str = Query("ZRH"),
    monthly_units_limit: int = Query(AERODATABOX_DEFAULT_MONTHLY_UNITS),
) -> Dict[str, Any]:
    return _provider_test_payload(await _test_aerodatabox_key(
        key,
        marketplace=marketplace,
        airport_iata=airport_iata,
        monthly_units_limit=monthly_units_limit,
    ))


@app.post("/api/setup/test-aviationstack")
async def setup_test_aviationstack_post(body: ApiKeyTestIn) -> Dict[str, Any]:
    return _provider_test_payload(await _test_aviationstack_key(body.key))


@app.get("/api/setup/test-aviationstack")
async def setup_test_aviationstack_get(key: str = Query(...)) -> Dict[str, Any]:
    return _provider_test_payload(await _test_aviationstack_key(key))


async def _test_rapidapi_key(key: str) -> Dict[str, Any]:
    """Test a RapidAPI key for ADS-B Exchange without saving it."""
    import requests as _req
    try:
        r = _req.get(
            "https://adsbexchange-com1.p.rapidapi.com/v2/lat/47.45/lon/8.55/dist/5/",
            headers={
                "X-RapidAPI-Key":  key,
                "X-RapidAPI-Host": "adsbexchange-com1.p.rapidapi.com",
            },
            timeout=10,
        )
        if r.status_code == 403:
            return {"ok": False, "error": "API key invalid or not subscribed to ADS-B Exchange on RapidAPI"}
        if r.status_code == 429:
            return {"ok": False, "error": "Rate limit hit â€” try again shortly"}
        if r.status_code >= 400:
            return {"ok": False, "error": "This connection key could not be verified."}
        return {"ok": True}
    except Exception:
        return {"ok": False, "error": "This connection could not be checked right now. Try again shortly."}


async def _test_opensky_key(opensky_id: str, opensky_secret: str) -> Dict[str, Any]:
    """Test OpenSky credentials with a tiny bounded state-vector probe."""
    import requests as _req

    user = (opensky_id or "").strip()
    secret = (opensky_secret or "").strip()
    if not user or not secret:
        return {"ok": False, "error": "OpenSky needs both client ID and secret"}
    try:
        from localflight.sources.web.opensky_radar import OPENSKY_BASE_URL, bounding_box

        lamin, lomin, lamax, lomax = bounding_box(47.45, 8.55, 1.0)
        r = _req.get(
            OPENSKY_BASE_URL,
            params={
                "lamin": round(lamin, 6),
                "lomin": round(lomin, 6),
                "lamax": round(lamax, 6),
                "lomax": round(lomax, 6),
            },
            auth=(user, secret),
            timeout=10,
            headers={"User-Agent": user_agent()},
        )
        if r.status_code in {401, 403}:
            return {"ok": False, "error": "OpenSky credentials were rejected"}
        if r.status_code == 429:
            return {"ok": False, "error": "OpenSky rate limit reached"}
        if r.status_code >= 400:
            return {"ok": False, "error": "This connection key could not be verified."}
        try:
            payload = r.json()
        except Exception:
            return {"ok": False, "error": "OpenSky response was not valid JSON"}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "OpenSky response shape was unexpected"}
        return {"ok": True}
    except Exception:
        return {"ok": False, "error": "This connection could not be checked right now. Try again shortly."}


@app.post("/api/setup/test-rapidapi")
async def setup_test_rapidapi_post(body: ApiKeyTestIn) -> Dict[str, Any]:
    return _provider_test_payload(await _test_rapidapi_key(body.key))


@app.get("/api/setup/test-rapidapi")
async def setup_test_rapidapi_get(key: str = Query(...)) -> Dict[str, Any]:
    return _provider_test_payload(await _test_rapidapi_key(key))


@app.post("/api/setup/test-opensky")
async def setup_test_opensky_post(body: OpenSkyKeyTestIn) -> Dict[str, Any]:
    return _provider_test_payload(await _test_opensky_key(body.opensky_id, body.opensky_secret))


@app.get("/api/setup/test-opensky")
async def setup_test_opensky_get(
    opensky_id: str = Query(...),
    opensky_secret: str = Query(...),
) -> Dict[str, Any]:
    return _provider_test_payload(await _test_opensky_key(opensky_id, opensky_secret))


@app.post("/api/setup/activate")
async def setup_activate(body: ActivationSetupIn, request: Request = None) -> Dict[str, Any]:
    if body.requested_mode.strip().lower() == "relay":
        import requests as _req
        from localflight.storage.install import (
            activation_storage_ready,
            clear_activation_token,
            get_install_id,
            get_stored_activation_token,
            set_activation_token,
            set_relay_access_mode,
        )

        try:
            relay_url = _validated_setup_relay_url(body.relay_url)
        except ValueError:
            return _relay_failure_payload({"detail": "connection failed"}, fallback="The Beacon Relay address could not be used.")
        if not body.license_key.strip() and not body.activation_grant.strip():
            return {
                "ok": False,
                "status": "license_key_required",
                "error": "Enter the Relay Access license key from your Beacon Tools purchase email.",
            }
        if body.license_key.strip() and not _request_is_loopback(request):
            return {
                "ok": False,
                "status": "license_key_local_only",
                "error": "For safety, enter a one-time activation code when setup is open from another device.",
            }
        if not activation_storage_ready():
            return {
                "ok": False,
                "status": "credential_storage_unavailable",
                "error": "Secure local credential storage is unavailable. Fix its permissions and try again.",
            }
        entered_value = body.license_key.strip()
        activation_grant = body.activation_grant.strip() or (entered_value if entered_value.startswith("lfrag_") else "")
        license_key = "" if activation_grant else entered_value
        try:
            response = await asyncio.to_thread(
                _req.post,
                _access_activate_url(relay_url),
                json={
                    "install_id": get_install_id(),
                    "device_kind": "desktop",
                    "device_name": body.display_name.strip() or "Local Flight Desktop",
                    "license_key": license_key,
                    "activation_grant": activation_grant,
                    "confirm_move_token": body.confirm_move_token.strip(),
                },
                headers={"Accept": "application/json"},
                timeout=12,
            )
        except Exception:
            return _relay_failure_payload(
                {"detail": "Relay activation could not be completed. Check the relay address and try again."},
                fallback="Beacon Relay activation failed.",
            )
        payload = _relay_json_response(response)
        if response.status_code == 409 and isinstance(payload, dict):
            receiver = payload.get("current_receiver") if isinstance(payload.get("current_receiver"), dict) else {}
            return {
                "ok": False,
                "status": "seat_in_use",
                "error": "Relay Access is currently used by another main device.",
                "move_token": str(payload.get("move_token") or ""),
                "current_receiver": receiver,
                "current_main_device_description": str(receiver.get("device_name") or receiver.get("device_kind") or "another main device"),
            }
        if response.status_code >= 400:
            _mark_access_failure(payload, http_status=response.status_code)
            return _relay_failure_payload(payload, http_status=response.status_code, fallback="Beacon Relay activation failed.", response=response)
        credential = str(payload.get("credential") or "") if isinstance(payload, dict) else ""
        if not credential.startswith("lfr_"):
            return {"ok": False, "status": "relay_error", "error": "Beacon Relay did not return a device credential."}
        if payload.get("ok") is not True or str(payload.get("activation_state") or "") != "pending_commit":
            try:
                await asyncio.to_thread(
                    _req.post,
                    _access_deactivate_url(relay_url),
                    json={"install_id": get_install_id()},
                    headers={"Accept": "application/json", "Authorization": f"Bearer {credential}"},
                    timeout=12,
                )
            except Exception:
                pass
            return {
                "ok": False,
                "status": "invalid_activation_response",
                "error": "Beacon Relay did not return a safely prepared activation.",
            }
        try:
            set_activation_token(credential)
            if get_stored_activation_token() != credential:
                raise OSError("credential verification failed")
        except Exception:
            try:
                clear_activation_token()
            except Exception:
                pass
            # Activation is server-authoritative. Compensate immediately when
            # local durable storage fails so a moved license is not orphaned.
            try:
                await asyncio.to_thread(
                    _req.post,
                    _access_deactivate_url(relay_url),
                    json={"install_id": get_install_id()},
                    headers={"Accept": "application/json", "Authorization": f"Bearer {credential}"},
                    timeout=12,
                )
            except Exception:
                pass
            return {
                "ok": False,
                "status": "credential_storage_failed",
                "error": "Relay Access was not kept on this desktop because its credential could not be saved.",
            }
        try:
            commit_response = await asyncio.to_thread(
                _req.post,
                _access_activate_commit_url(relay_url),
                json={"install_id": get_install_id()},
                headers={"Accept": "application/json", "Authorization": f"Bearer {credential}"},
                timeout=12,
            )
            commit_payload = _relay_json_response(commit_response)
        except Exception:
            commit_response = None
            commit_payload = {"code": "relay_unreachable"}
        committed = bool(
            commit_response is not None
            and commit_response.status_code < 400
            and commit_payload.get("ok") is True
            and commit_payload.get("activated") is True
            and str(commit_payload.get("activation_state") or "") == "active"
            and str((commit_payload.get("license") or {}).get("access_state") or "") == "active"
        )
        if not committed:
            try:
                await asyncio.to_thread(
                    _req.post,
                    _access_deactivate_url(relay_url),
                    json={"install_id": get_install_id()},
                    headers={"Accept": "application/json", "Authorization": f"Bearer {credential}"},
                    timeout=12,
                )
            except Exception:
                pass
            try:
                clear_activation_token()
            except Exception:
                pass
            _mark_access_failure(commit_payload, http_status=int(getattr(commit_response, "status_code", 503) or 503))
            failure = _relay_failure_payload(
                commit_payload,
                http_status=int(getattr(commit_response, "status_code", 503) or 503),
                fallback="Relay Access could not finish activation safely.",
                response=commit_response,
            )
            failure["status"] = "activation_commit_failed"
            return failure
        payload = commit_payload
        try:
            set_relay_access_mode("managed")
        except Exception:
            pass
        _cache_access_payload(payload, relay_state="active")
        return {
            "ok": True,
            "status": "active",
            "activation_token_present": True,
            "activation_token_prefix": str(payload.get("credential_prefix") or credential[:12]),
            "license": payload.get("license") if isinstance(payload.get("license"), dict) else {},
            "receiver": payload.get("receiver") if isinstance(payload.get("receiver"), dict) else {},
            "access_state": str((payload.get("license") or {}).get("access_state") or "active") if isinstance(payload.get("license"), dict) else "active",
        }

    return {
        "ok": False,
        "status": "activation_mode_unsupported",
        "error": "Relay activation is only used for the Beacon Relay data route.",
    }


@app.post("/api/setup/client-status")
async def setup_client_status(body: ClientStatusSetupIn) -> Dict[str, Any]:
    import requests as _req
    from localflight.sources.web.relay_heartbeat import relay_client_metadata
    from localflight.storage.config import load_config
    from localflight.storage.install import get_install_id, get_stored_activation_token

    try:
        relay_url = _validated_setup_relay_url(body.relay_url)
    except ValueError:
        return _relay_failure_payload({"detail": "connection failed"}, fallback="The relay address could not be used.")
    activation_token = (body.activation_token or "").strip() or get_stored_activation_token().strip()
    if activation_token and not activation_token.startswith(("lfr_", "lfm_")):
        return {
            "ok": False,
            "status": "token_invalid",
            "error": "Activate the Relay Access key first; only a device credential can be checked.",
        }
    if activation_token.startswith("lfr_"):
        try:
            response = await asyncio.to_thread(
                _req.get,
                _access_status_url(relay_url),
                params={"install_id": get_install_id()},
                headers={"Accept": "application/json", "Authorization": f"Bearer {activation_token}"},
                timeout=12,
            )
        except Exception:
            _mark_access_failure({"code": "relay_unreachable"}, http_status=503)
            return _relay_failure_payload({"detail": "Relay status could not be checked."}, fallback="Relay status check failed.")
        payload = _relay_json_response(response)
        if response.status_code >= 400:
            _mark_access_failure(payload, http_status=response.status_code)
            return _relay_failure_payload(payload, http_status=response.status_code, fallback="Relay status check failed.", response=response)
        access_state = str(payload.get("access_state") or "").strip().lower()
        active = payload.get("ok") is True and payload.get("active") is True and access_state == "active"
        inactive_status = access_state if access_state in {"suspended", "refunded", "revoked"} else "invalid_status_response"
        if active:
            _cache_access_payload(payload, relay_state="active")
        elif inactive_status in {"suspended", "refunded", "revoked"}:
            _cache_access_payload(payload, relay_state="inactive")
            _mark_access_failure({**payload, "code": inactive_status})
        else:
            _mark_access_failure({**payload, "code": inactive_status})
        return {
            **payload,
            "ok": active,
            "status": "active" if active else inactive_status,
            "error": "" if active else {
                "suspended": "Relay Access is suspended.",
                "refunded": "Relay Access was refunded.",
                "revoked": "Relay Access was revoked.",
            }.get(inactive_status, "Beacon Relay returned an invalid access status."),
            "activation_token_present": True,
            "activation_token_prefix": activation_token[:12],
        }
    from localflight.sources.web.relay_activation import legacy_relay_compat_enabled

    if not legacy_relay_compat_enabled():
        _mark_access_failure({"code": "credential_not_found"}, http_status=401)
        return {
            "ok": False,
            "status": "credential_not_found",
            "error": "This desktop needs a current Relay Access device credential.",
        }

    metadata = relay_client_metadata()
    try:
        cfg = load_config()
        metadata.update(
            {
                "airport_iata": cfg.airport_iata,
                "timezone": cfg.timezone,
                "display_grace_minutes": int(cfg.display_grace_minutes),
                "display_horizon_hours": int(cfg.display_horizon_hours),
                "refresh_seconds": int(cfg.refresh_seconds),
            }
        )
    except Exception:
        pass
    try:
        response = await asyncio.to_thread(
            _req.post,
            _client_checkin_url(relay_url),
            json={
                "install_id": get_install_id(),
                "activation_token": activation_token,
                **metadata,
            },
            headers={"Accept": "application/json"},
            timeout=12,
        )
    except Exception:
        return _relay_failure_payload({"detail": "Relay status could not be checked."}, fallback="Relay status check failed.")

    payload = _relay_json_response(response)
    if response.status_code >= 400:
        return _relay_failure_payload(payload, http_status=response.status_code, fallback="Relay status check failed.", response=response)
    if not isinstance(payload, dict):
        return {"ok": False, "status": "relay_error", "error": "Relay status response was invalid"}
    payload.setdefault("ok", True)
    payload.setdefault("status", "ok")
    return payload


@app.post("/api/setup/request-activation")
async def setup_request_activation_compat(body: ActivationSetupIn, request: Request) -> Dict[str, Any]:
    return await setup_activate(body, request)


@app.post("/api/setup/request-activation/status")
async def setup_request_activation_status_compat(body: ClientStatusSetupIn) -> Dict[str, Any]:
    return await setup_client_status(body)


@app.post("/api/setup/test-activation")
async def setup_test_activation(body: ActivationTokenTestIn) -> Dict[str, Any]:
    import requests as _req
    from localflight.sources.web.relay_heartbeat import relay_client_metadata
    from localflight.storage.install import get_install_id, get_stored_activation_token

    try:
        relay_url = _validated_setup_relay_url(body.relay_url)
    except ValueError:
        return _relay_failure_payload({"detail": "connection failed"}, fallback="The relay address could not be used.")
    token = get_stored_activation_token().strip()
    if not token:
        return {"ok": False, "status": "token_invalid", "error": "A Relay Access device credential is not loaded on this machine yet."}
    if token.startswith("lfr_"):
        try:
            response = await asyncio.to_thread(
                _req.get,
                _access_status_url(relay_url),
                params={"install_id": get_install_id()},
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                timeout=12,
            )
        except Exception:
            _mark_access_failure({"code": "relay_unreachable"}, http_status=503)
            return _relay_failure_payload({"detail": "Relay verification could not be completed."}, fallback="Relay verification failed.")
        payload = _relay_json_response(response)
        if response.status_code >= 400:
            _mark_access_failure(payload, http_status=response.status_code)
            return _relay_failure_payload(payload, http_status=response.status_code, fallback="Relay verification failed.", response=response)
        access_state = str(payload.get("access_state") or "").strip().lower()
        active = payload.get("ok") is True and payload.get("active") is True and access_state == "active"
        inactive_status = access_state if access_state in {"suspended", "refunded", "revoked"} else "invalid_status_response"
        if active:
            _cache_access_payload(payload, relay_state="active")
        elif inactive_status in {"suspended", "refunded", "revoked"}:
            _cache_access_payload(payload, relay_state="inactive")
            _mark_access_failure({**payload, "code": inactive_status})
        else:
            _mark_access_failure({**payload, "code": inactive_status})
        return {
            **payload,
            "ok": active,
            "status": "active" if active else inactive_status,
            "error": "" if active else {
                "suspended": "Relay Access is suspended.",
                "refunded": "Relay Access was refunded.",
                "revoked": "Relay Access was revoked.",
            }.get(inactive_status, "Beacon Relay returned an invalid access status."),
            "activation_token_prefix": token[:12],
        }
    if not token.startswith("lfm_"):
        return {"ok": False, "status": "token_invalid", "error": "The saved Relay Access credential is not valid."}
    from localflight.sources.web.relay_activation import legacy_relay_compat_enabled

    if not legacy_relay_compat_enabled():
        return {"ok": False, "status": "credential_not_found", "error": "This desktop needs a current Relay Access device credential."}
    try:
        response = _req.get(
            _client_status_url(relay_url),
            params={"install_id": get_install_id(), "activation_token": token, **relay_client_metadata()},
            headers={"Accept": "application/json"},
            timeout=12,
        )
    except Exception:
        return _relay_failure_payload({"detail": "Relay verification could not be completed."}, fallback="Relay verification failed.")

    payload = _relay_json_response(response)

    if response.status_code >= 400:
        return _relay_failure_payload(payload, http_status=response.status_code, fallback="Relay verification failed.", response=response)
    payload.setdefault("ok", True)
    payload.setdefault("status", "ok")
    return payload


@app.post("/api/setup/complete")
async def setup_complete(request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Save setup wizard results â€” write .env, save config, mark setup complete."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    airport_iata = (data.get("airport_iata") or "ZRH").upper().strip()
    airport_icao = (data.get("airport_icao") or "LSZH").upper().strip()
    timezone_str = resolve_airport_timezone(
        str(data.get("timezone") or ""),
        airport_iata=airport_iata,
        airport_icao=airport_icao,
    )
    old_cfg = load_config()
    setup_mode = str(data.get("data_route") or data.get("setup_mode") or old_cfg.data_route).strip().lower()
    setup_mode = {"virtual": "vatsim", "community": "relay", "managed": "relay"}.get(setup_mode, setup_mode)
    if setup_mode not in ALLOWED_DATA_ROUTES:
        return JSONResponse(
            {"ok": False, "status": "data_route_invalid", "error": "Choose Beacon Relay, Bring Your Own Keys, or VATSIM."},
            status_code=422,
        )
    source = "virtual" if setup_mode == "vatsim" else "real"
    diagnostics_mode = str(data.get("diagnostics_mode") or DEFAULT_DIAGNOSTICS_MODE).strip().lower()
    if diagnostics_mode not in ALLOWED_DIAGNOSTICS_MODES:
        diagnostics_mode = DEFAULT_DIAGNOSTICS_MODE

    env_path = provider_env_path()
    existing = read_provider_env(env_path)
    original_env = dict(existing)
    adb_key = data.get("aerodatabox_key", "").strip()
    adb_marketplace = normalize_aerodatabox_marketplace(data.get("aerodatabox_marketplace", "apimarket"))
    adb_monthly_limit = data.get("aerodatabox_monthly_units_limit", AERODATABOX_DEFAULT_MONTHLY_UNITS)
    adb_daily_limit = data.get("aerodatabox_daily_units_limit", "")
    as_key = data.get("aviationstack_key", "").strip()
    rp_key = data.get("rapidapi_key", "").strip()
    relay_url = data.get("relay_url", "").strip()
    if setup_mode == "relay":
        try:
            relay_url = _validated_setup_relay_url(relay_url)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    os_id = data.get("opensky_id", "").strip()
    os_sec = data.get("opensky_secret", "").strip()

    from localflight.storage.install import get_relay_access_summary, get_stored_activation_token

    activation_token = get_stored_activation_token().strip()
    release_result: Dict[str, Any] | None = None

    removed_keys: set[str] = set()
    if setup_mode == "relay":
        if not activation_token.startswith("lfr_"):
            return JSONResponse(
                {"ok": False, "status": "relay_license_required", "error": "Activate this desktop with a Relay Access license before finishing."},
                status_code=403,
            )
        status = await setup_test_activation(
            ActivationTokenTestIn(relay_url=relay_url, activation_token=activation_token)
        )
        if not status.get("ok"):
            return JSONResponse(status, status_code=403)
        removed_keys |= apply_relay_values(existing, activation_token=activation_token, relay_url=relay_url, community=False)
    elif setup_mode == "byok":
        existing_adb = str(existing.get("AERODATABOX_API_KEY") or "").strip()
        existing_as = str(existing.get("AVIATIONSTACK_API_KEY") or "").strip()
        replacing_schedule_keys = bool(adb_key or as_key)
        effective_adb = adb_key if replacing_schedule_keys else existing_adb
        effective_as = as_key if replacing_schedule_keys else existing_as
        if not (effective_adb or effective_as):
            return JSONResponse(
                {"ok": False, "error": "Bring Your Own Keys needs an AeroDataBox or AviationStack schedule key."},
                status_code=400,
            )
        removed_keys |= apply_byok_values(
            existing,
            aerodatabox_key=effective_adb,
            aerodatabox_marketplace=adb_marketplace or existing.get("LOCALFLIGHT_AERODATABOX_MARKETPLACE", "apimarket"),
            aerodatabox_monthly_units_limit=adb_monthly_limit or existing.get("LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT", AERODATABOX_DEFAULT_MONTHLY_UNITS),
            aerodatabox_daily_units_limit=adb_daily_limit,
            aviationstack_key=effective_as,
            rapidapi_key=rp_key or ("" if replacing_schedule_keys else existing.get("RAPIDAPI_KEY", "")),
            opensky_id=os_id or ("" if replacing_schedule_keys else existing.get("OPENSKY_CLIENT_ID", "")),
            opensky_secret=os_sec or ("" if replacing_schedule_keys else existing.get("OPENSKY_CLIENT_SECRET", "")),
        )
    else:
        removed_keys |= apply_virtual_values(existing)

    from localflight.storage.route_transition import (
        begin_route_transition,
        complete_route_transition,
        update_route_transition,
    )

    transition_started = setup_mode != old_cfg.data_route or bool(activation_token and setup_mode != "relay")
    if transition_started:
        try:
            begin_route_transition(old_cfg.data_route, setup_mode)
        except Exception as exc:
            logger.error("Setup: could not start route transition: %s", exc)
            return JSONResponse(
                {"ok": False, "status": "route_transition_failed", "error": "The data route change could not be started safely."},
                status_code=500,
            )

    try:
        write_provider_env(existing, removed=removed_keys, path=env_path)
        reload_provider_env(env_path)
        logger.info("Setup provider env saved: mode=%s path=%s", setup_mode or source, env_path)
    except Exception as exc:
        logger.error("Setup: could not write .env: %s", exc)
        try:
            write_provider_env(original_env, removed=set(existing).difference(original_env), path=env_path)
            reload_provider_env(env_path)
            if transition_started:
                complete_route_transition()
        except Exception:
            pass
        return JSONResponse({"ok": False, "error": f"Could not save config: {exc}"}, status_code=500)
    if transition_started:
        update_route_transition("provider_saved")

    initial_refresh_seconds = 1800 if setup_mode == "relay" else (28800 if setup_mode == "byok" else 900)
    cfg_values = asdict(old_cfg)
    cfg_values.update(
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        timezone=timezone_str,
        source=source,
        data_route=setup_mode,
        display_name=str(data.get("display_name") or old_cfg.display_name or "Local Flight").strip()[:40] or "Local Flight",
        refresh_seconds=_coerce_refresh_for_policy(initial_refresh_seconds, source),
        diagnostics_mode=diagnostics_mode,
    )
    cfg = AppConfig(**cfg_values)
    try:
        save_config(cfg)
    except Exception as exc:
        logger.error("Setup: could not save route config: %s", exc)
        try:
            write_provider_env(
                original_env,
                removed=set(existing).difference(original_env),
                path=env_path,
            )
            reload_provider_env(env_path)
            complete_route_transition()
        except Exception:
            # Keep the journal in place. For a transition away from Relay its
            # target route continues to block credential use until recovery.
            pass
        return JSONResponse(
            {"ok": False, "status": "route_transition_failed", "error": "The data route change could not be saved safely."},
            status_code=500,
        )
    if transition_started:
        update_route_transition("route_saved")

    if setup_mode != "relay" and activation_token:
        release_result = await asyncio.to_thread(_deactivate_local_relay, relay_url or _relay_url_default())
    if transition_started:
        complete_route_transition()
    logger.info("Setup complete: %s/%s data_route=%s source=%s", airport_iata, airport_icao, setup_mode, source)

    _mark_setup_complete()
    from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

    notify_config_updated(cfg, reason="setup_complete")
    background_tasks.add_task(restart_scheduler_and_notify, "setup_complete")
    try:
        from localflight.sources.web.relay_beat import fire_heartbeat
        fire_heartbeat()
    except Exception:
        pass

    access = get_relay_access_summary()
    return {
        "ok": True,
        "status": "preparing",
        "message": "Setup saved. Preparing your first board.",
        "data_route": setup_mode,
        "relay_state": access["relay_state"],
        "release_pending": bool(release_result and release_result.get("status") == "release_pending"),
    }


# â”€â”€ Pages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/splash", response_class=HTMLResponse)
def splash_page(
    request: Request,
    next_path: str = Query("/display", alias="next"),
    duration_ms: int = Query(6200, ge=5000, le=8000),
) -> HTMLResponse:
    target = _safe_local_path(next_path)
    if not _setup_complete() and target != "/setup":
        target = "/setup"

    cfg = load_config()
    return templates.TemplateResponse(
        request=request,
        name="splash.html",
        context={
            "cfg": cfg,
            "next_url": target,
            "duration_ms": duration_ms,
        },
    )


@app.get("/", response_class=HTMLResponse)
def settings_page(
    request: Request,
    saved: Optional[str] = None,
    profile_msg: Optional[str] = None,
) -> HTMLResponse:
    cfg = load_config()
    state = load_state()
    profiles = list_profiles()
    schedule_policy = _schedule_policy_for_source(cfg.source)
    companion_pairing = pairing_gateway_payload(base_url=str(request.base_url).rstrip("/"))
    qr_bytes = pairing_qr_png_bytes(str(companion_pairing.get("deep_link") or ""), size=190)
    companion_pairing["qr_data_uri"] = (
        f"data:image/png;base64,{base64.b64encode(qr_bytes).decode('ascii')}" if qr_bytes else ""
    )
    provider_key_status = provider_status()
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "cfg": cfg,
            "state": state,
            "profiles": profiles,
            "companion_pairing": companion_pairing,
            "provider_status": provider_key_status,
            "show_provider_key_settings": show_provider_key_settings(provider_key_status),
            "settings_options": _settings_options_for_policy(schedule_policy),
            "schedule_policy": schedule_policy,
            "data_route_label": _data_route_label(cfg.data_route),
            "saved": (saved == "1"),
            "profile_msg": profile_msg,
        },
    )


# â”€â”€ Log helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _list_log_files() -> list[str]:
    d = logs_dir()
    return [p.name for p in sorted(d.glob("localflight_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)]


def _secret_values_for_redaction() -> list[str]:
    try:
        values = provider_env_values()
    except Exception:
        values = {}
    process_values = dict(os.environ)
    secrets = []
    for key in {*SECRET_KEYS, "LOCALFLIGHT_ACTIVATION_TOKEN"}:
        for source in (values, process_values):
            value = str(source.get(key, "") or "").strip()
            if len(value) >= 6:
                secrets.append(value)
    return sorted(set(secrets), key=len, reverse=True)


def _redact_sensitive_log_text(text: str) -> str:
    redacted = text
    for secret in _secret_values_for_redaction():
        redacted = redacted.replace(secret, "[redacted]")
    return redacted


def _tail_lines(path: Path, n: int = 500) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ["(log file not found)"]
    lines = _redact_sensitive_log_text(text).splitlines()
    return lines[-n:] if len(lines) > n else lines


@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, file: Optional[str] = Query(None)) -> HTMLResponse:
    files = _list_log_files()
    base = {
        "cfg": load_config(),
        "max_files": MAX_LOG_FILES,
        "max_days": MAX_LOG_DAYS,
        "max_mb": MAX_LOG_BYTES // 1_048_576,
        "live_mode": True,
        "auto_scroll": True,
    }

    if not files:
        return templates.TemplateResponse(
            request=request,
            name="logs.html",
            context={
                "files": [],
                "selected": None,
                "lines": ["(no logs yet)"],
                **base,
            },
        )

    selected = file if (file in files) else files[0]
    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={
            "files": files,
            "selected": selected,
            "lines": _tail_lines(logs_dir() / selected),
            **base,
        },
    )


@app.get("/logs/tail")
def logs_tail(file: Optional[str] = Query(None), after: int = Query(0, ge=0)) -> JSONResponse:
    files = _list_log_files()
    if not files:
        return JSONResponse({"lines": [], "total": 0})

    selected = file if (file in files) else files[0]
    try:
        text = (logs_dir() / selected).read_text(encoding="utf-8", errors="replace")
        all_lines = _redact_sensitive_log_text(text).splitlines()
    except FileNotFoundError:
        return JSONResponse({"lines": [], "total": 0})

    return JSONResponse({"lines": all_lines[after:] if after < len(all_lines) else [], "total": len(all_lines)})


@app.get("/api/provider-keys/status")
def api_provider_keys_status() -> Dict[str, Any]:
    return provider_status()


@app.post("/api/provider-keys/test-aerodatabox")
async def api_provider_keys_test_aerodatabox(body: AeroDataBoxKeyTestIn) -> Dict[str, Any]:
    return await _test_aerodatabox_key(
        body.key,
        marketplace=body.marketplace,
        airport_iata=body.airport_iata,
        monthly_units_limit=body.monthly_units_limit,
    )


@app.post("/api/provider-keys/test-aviationstack")
async def api_provider_keys_test_aviationstack(body: ApiKeyTestIn) -> Dict[str, Any]:
    return await _test_aviationstack_key(body.key)


@app.post("/api/provider-keys/test-rapidapi")
async def api_provider_keys_test_rapidapi(body: ApiKeyTestIn) -> Dict[str, Any]:
    return await _test_rapidapi_key(body.key)


@app.post("/api/provider-keys/test-opensky")
async def api_provider_keys_test_opensky(body: OpenSkyKeyTestIn) -> Dict[str, Any]:
    return await _test_opensky_key(body.opensky_id, body.opensky_secret)


@app.post("/api/provider-keys/save")
def api_provider_keys_save(body: ProviderKeysSaveIn) -> Dict[str, Any]:
    try:
        save_provider_keys(
            aerodatabox_key=body.aerodatabox_key,
            aerodatabox_marketplace=body.aerodatabox_marketplace,
            aerodatabox_monthly_units_limit=body.aerodatabox_monthly_units_limit,
            aerodatabox_daily_units_limit=body.aerodatabox_daily_units_limit,
            aviationstack_key=body.aviationstack_key,
            rapidapi_key=body.rapidapi_key,
            opensky_id=body.opensky_id,
            opensky_secret=body.opensky_secret,
        )
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Provider keys could not be saved: {exc}"}, status_code=500)
    try:
        from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

        notify_config_updated(load_config(), reason="provider_keys")
        restart_scheduler_and_notify("provider_keys")
    except Exception:
        pass
    return provider_status()


@app.post("/api/provider-keys/clear")
def api_provider_keys_clear() -> Dict[str, Any]:
    try:
        clear_provider_keys()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"Provider keys could not be cleared: {exc}"}, status_code=500)
    try:
        from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

        notify_config_updated(load_config(), reason="provider_keys_cleared")
        restart_scheduler_and_notify("provider_keys_cleared")
    except Exception:
        pass
    return provider_status()


@app.get("/api/logs")
def api_logs(file: Optional[str] = Query(None)) -> JSONResponse:
    """Native/client-friendly log metadata without scraping the HTML logs page."""
    files = _list_log_files()
    selected = file if (file in files) else (files[0] if files else None)
    total = 0
    if selected:
        try:
            total = len((logs_dir() / selected).read_text(encoding="utf-8", errors="replace").splitlines())
        except FileNotFoundError:
            total = 0
    return JSONResponse(
        {
            "files": files,
            "selected": selected,
            "total": total,
            "max_files": MAX_LOG_FILES,
            "max_days": MAX_LOG_DAYS,
            "max_mb": MAX_LOG_BYTES // 1_048_576,
            "live_mode": True,
            "auto_scroll": True,
        }
    )


# â”€â”€ Settings save â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/save")
async def save_settings(
    background_tasks: BackgroundTasks,
    request: Request,
    airport_icao: str = Form(...),
    airport_iata: str = Form(...),
    refresh_seconds: int = Form(...),
    display_name: str = Form(...),
    theme: Optional[str] = Form("dark"),
    source: Optional[str] = Form(DEFAULT_SOURCE),
    timezone: str = Form("UTC"),
    skin: Optional[str] = Form(DEFAULT_SKIN),
    diagnostics_mode: Optional[str] = Form(DEFAULT_DIAGNOSTICS_MODE),
    web_row_limit: int = Form(DEFAULT_WEB_ROW_LIMIT),
    web_rotation_seconds: int = Form(DEFAULT_WEB_ROTATION_SECONDS),
    display_grace_minutes: int = Form(DEFAULT_DISPLAY_GRACE_MINUTES),
    display_horizon_hours: int = Form(DEFAULT_DISPLAY_HORIZON_HOURS),
    radar_surface_enabled: Optional[str] = Form(None),
    radar_surface_mode: Optional[str] = Form(DEFAULT_RADAR_SURFACE_MODE),
    remote_companion_enabled: Optional[str] = Form(None),
) -> RedirectResponse:
    old_cfg = load_config()
    data_route = old_cfg.data_route
    src = "virtual" if data_route == "vatsim" else "real"
    rs = int(refresh_seconds) if int(refresh_seconds) in ALLOWED_REFRESH_SECONDS else DEFAULT_REFRESH_SECONDS
    rs = _coerce_refresh_for_policy(rs, src)

    sk = (skin or DEFAULT_SKIN).strip().lower()
    if sk not in ALLOWED_SKINS:
        sk = DEFAULT_SKIN

    diag_mode = (diagnostics_mode or DEFAULT_DIAGNOSTICS_MODE).strip().lower()
    if diag_mode not in ALLOWED_DIAGNOSTICS_MODES:
        diag_mode = DEFAULT_DIAGNOSTICS_MODE
    web_rows = max(5, min(40, int(web_row_limit)))
    web_rotate = max(3, min(60, int(web_rotation_seconds)))
    grace_minutes = max(0, min(180, int(display_grace_minutes)))
    horizon_hours = max(1, min(24, int(display_horizon_hours)))
    raw_surface_mode = str(radar_surface_mode or "").strip().lower()
    if raw_surface_mode not in ALLOWED_RADAR_SURFACE_MODES:
        raw_surface_mode = "relay" if str(radar_surface_enabled or "").strip().lower() in {"1", "true", "yes", "on"} else DEFAULT_RADAR_SURFACE_MODE
    surface_enabled = raw_surface_mode != "off"
    remote_enabled = str(remote_companion_enabled or "").strip().lower() in {"1", "true", "yes", "on"}

    form_data = await request.form()
    raw_outputs = form_data.getlist("display_outputs")
    display_outputs = [o for o in raw_outputs if o in ALLOWED_OUTPUTS] or list(DEFAULT_OUTPUTS)
    cfg = AppConfig(
        airport_icao=airport_icao.upper().strip(),
        airport_iata=airport_iata.upper().strip(),
        refresh_seconds=rs,
        display_name=display_name.strip()[:40] or "Local Flight",
        theme=(theme or "dark").strip() or "dark",
        source=src,
        data_route=data_route,
        timezone=resolve_airport_timezone(
            timezone,
            airport_iata=airport_iata,
            airport_icao=airport_icao,
        ),
        skin=sk,
        display_outputs=display_outputs,
        diagnostics_mode=diag_mode,
        web_row_limit=web_rows,
        web_rotation_seconds=web_rotate,
        display_grace_minutes=grace_minutes,
        display_horizon_hours=horizon_hours,
        radar_surface_enabled=surface_enabled,
        radar_surface_mode=raw_surface_mode,
        remote_companion_enabled=remote_enabled,
    )
    config_changed = asdict(old_cfg) != asdict(cfg)
    if config_changed:
        save_config(cfg)

    logger.info(
        "UI save: %s/%s refresh=%ss source=%s skin=%s outputs=%s diagnostics=%s web_rows=%s web_rotate=%ss grace=%sm horizon=%sh surface=%s",
        cfg.airport_iata,
        cfg.airport_icao,
        cfg.refresh_seconds,
        cfg.source,
        cfg.skin,
        cfg.display_outputs,
        cfg.diagnostics_mode,
        cfg.web_row_limit,
        cfg.web_rotation_seconds,
        cfg.display_grace_minutes,
        cfg.display_horizon_hours,
        cfg.radar_surface_mode,
    )

    from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

    if config_changed:
        notify_config_updated(cfg, reason="desktop_settings")
    if config_changed and _scheduler_config_changed(old_cfg, cfg):
        logger.info("Triggering scheduler restart after settings save")
        background_tasks.add_task(restart_scheduler_and_notify, "desktop_settings")
    else:
        logger.info("Settings save did not change scheduler fields")
    try:
        from localflight.sources.web.relay_beat import fire_heartbeat
        if config_changed:
            fire_heartbeat()
    except Exception:
        pass

    return RedirectResponse(url="/?saved=1", status_code=303)


# â”€â”€ Legacy JSON endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/api/status")
def api_status() -> JSONResponse:
    return JSONResponse(asdict(load_state()))


# â”€â”€ Profiles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/profiles/save")
def profiles_save(profile_name: str = Form(...)) -> RedirectResponse:
    name = save_profile(profile_name, load_config())
    logger.info("UI profile saved: %s", name)
    return RedirectResponse(url=f"/?profile_msg=saved:{name}", status_code=303)


@app.post("/profiles/load")
def profiles_load(background_tasks: BackgroundTasks, profile_name: str = Form(...)) -> RedirectResponse:
    old_cfg = load_config()
    loaded_cfg = load_profile(profile_name)
    # Profiles customize a board; they are not a licensing or data-route
    # transition mechanism. Preserve the current authoritative route.
    loaded_values = asdict(loaded_cfg)
    loaded_values.update(data_route=old_cfg.data_route, source=old_cfg.source)
    cfg = AppConfig(**loaded_values)
    save_config(cfg)
    logger.info("UI profile loaded: %s", profile_name)

    from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

    notify_config_updated(cfg, reason="profile_load")
    if _scheduler_config_changed(old_cfg, cfg):
        logger.info("Triggering scheduler restart after profile load: %s", profile_name)
        background_tasks.add_task(restart_scheduler_and_notify, "profile_load")
    else:
        logger.info("Profile load did not change scheduler fields")

    return RedirectResponse(url=f"/?profile_msg=loaded:{profile_name}", status_code=303)


@app.post("/profiles/delete")
def profiles_delete(profile_name: str = Form(...)) -> RedirectResponse:
    delete_profile(profile_name)
    logger.info("UI profile deleted: %s", profile_name)
    return RedirectResponse(url=f"/?profile_msg=deleted:{profile_name}", status_code=303)


# â”€â”€ Health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


# â”€â”€ FIDS display â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/fids", response_class=HTMLResponse)
def fids(request: Request, view: str = "arrivals", embedded: bool = Query(False)) -> HTMLResponse:
    import json as _json
    from localflight.core.models import FlightDirection
    from localflight.storage.flights_store import load_latest_snapshot_path
    from localflight.ui.api import _dict_to_flight
    from localflight.render.fids import build_fids_context as _build

    view = "departures" if view == "departures" else "arrivals"
    cfg = load_config()
    state = load_state()
    airport_label = city_country_label(iata=cfg.airport_iata, icao=cfg.airport_icao) or cfg.airport_iata

    snap_path = load_latest_snapshot_path(cfg.airport_iata)
    if snap_path:
        raw = _json.loads(snap_path.read_text(encoding="utf-8"))
        source_label = f"real:file:{snap_path.name}"
    else:
        raw = {"flights": []}
        source_label = "real:NO SNAPSHOT"

    direction = FlightDirection.DEPARTURE if view == "departures" else FlightDirection.ARRIVAL
    all_flights = [_dict_to_flight(f) for f in (raw.get("flights") or [])]
    flights = [f for f in all_flights if f.direction == direction]

    ctx = _build(
        cfg=cfg,
        view=view,
        refresh_seconds=cfg.refresh_seconds,
        flights=flights,
        source_status=f"{source_label} payload={len(all_flights)} visible={min(len(flights), cfg.web_row_limit)}",
    )
    ctx["rows"] = list(ctx["rows"])[: cfg.web_row_limit]
    ctx.update({
        "state": state,
        "cfg": cfg,
        "airport_label": airport_label,
        "embedded": embedded,
    })

    return templates.TemplateResponse(
        request=request,
        name="fids.html",
        context=ctx,
    )


# â”€â”€ Radar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/radar", response_class=HTMLResponse)
def radar(
    request:   Request,
    embedded:  bool  = Query(False),
    radius_nm: int   = Query(20, ge=1, le=200),
) -> HTMLResponse:
    from localflight.core.airports import lookup_airport

    cfg = load_config()
    airport = lookup_airport(iata=cfg.airport_iata, icao=cfg.airport_icao)

    return templates.TemplateResponse(
        request=request,
        name="radar.html",
        context={
            "cfg": cfg,
            "state": load_state(),
            "airport_label": best_label(iata=cfg.airport_iata, icao=cfg.airport_icao) or cfg.airport_iata,
            "center_lat": airport.lat if airport and airport.lat else 47.458056,
            "center_lon": airport.lon if airport and airport.lon else 8.548056,
            "radius_nm": radius_nm,
            "embedded": embedded,
        },
    )


# â”€â”€ Display â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/display", response_class=HTMLResponse)
def display(request: Request) -> HTMLResponse:
    cfg = load_config()
    return templates.TemplateResponse(
        request=request,
        name="display.html",
        context={
            "cfg": cfg,
            "state": load_state(),
        },
    )


# â”€â”€ Matrix preview â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/matrix-preview", response_class=HTMLResponse)
def matrix_preview(
    request: Request,
    panel_w: int = Query(256, ge=32, le=512),
    panel_h: int = Query(64, ge=16, le=128),
    pixel_size: int = Query(6, ge=2, le=20),
    view: str = Query("departures"),
    rows: int = Query(4, ge=1, le=8),
) -> HTMLResponse:
    cfg = load_config()
    view = "departures" if view == "departures" else "arrivals"

    return templates.TemplateResponse(
        request=request,
        name="matrix_preview.html",
        context={
            "cfg": cfg,
            "state": load_state(),
            "airport_label": best_label(iata=cfg.airport_iata, icao=cfg.airport_icao) or cfg.airport_iata,
            "panel_w": panel_w,
            "panel_h": panel_h,
            "pixel_size": pixel_size,
            "view": view,
            "rows": rows,
            "matrix_guidance": matrix_guidance_payload(),
        },
    )


# â”€â”€ Admin hub â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/admin", response_class=HTMLResponse)
def admin_hub(request: Request) -> HTMLResponse:
    cfg = load_config()
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "cfg": cfg,
            "state": load_state(),
        },
    )


# â”€â”€ Feedback / bug report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/feedback", response_class=HTMLResponse)
def feedback_page(request: Request) -> HTMLResponse:
    cfg = load_config()
    return templates.TemplateResponse(
        request=request,
        name="feedback.html",
        context={"cfg": cfg, "state": load_state()},
    )


@app.get("/docs/{slug}", response_class=HTMLResponse)
def docs_page(request: Request, slug: str) -> HTMLResponse:
    payload = _doc_payload(slug)

    cfg = load_config()
    return templates.TemplateResponse(
        request=request,
        name="doc_view.html",
        context={
            "cfg": cfg,
            "state": load_state(),
            "doc_slug": payload["slug"],
            "doc_title": payload["title"],
            "doc_summary": payload["summary"],
            "doc_filename": payload["filename"],
            "doc_text": payload["content"],
            "doc_github_url": payload["github_url"],
            "doc_external_url": payload["external_url"],
            "doc_external_label": payload["external_label"],
            "doc_pages": _DOC_PAGES,
        },
    )


@app.get("/api/docs/{slug}")
def api_docs_page(slug: str) -> Dict[str, Any]:
    return _doc_payload(slug)


# â”€â”€ History browser â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request) -> HTMLResponse:
    cfg = load_config()
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "cfg": cfg,
            "state": load_state(),
        },
    )

# â”€â”€ Traffic hub â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/admin/requests", response_class=HTMLResponse)
def traffic_page(request: Request) -> HTMLResponse:
    if not _network_tools_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    cfg = load_config()
    return templates.TemplateResponse(
        request=request,
        name="requests.html",
        context={
            "cfg": cfg,
            "state": load_state(),
        },
    )


# â”€â”€ Quit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.post("/api/setup/reset")
def api_setup_reset() -> dict:
    """Delete the setup_complete marker so clients can open the setup wizard immediately."""
    from localflight.storage.config import config_path
    marker = config_path().parent / "setup_complete"
    try:
        marker.unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    logger.info("Setup reset via UI â€” setup_complete marker removed")
    return {"ok": True}


@app.post("/api/quit")
def api_quit() -> dict:
    import threading

    def _shutdown():
        import time
        # Kill the browser process first, then end the integrated backend/UI
        # process. This also releases Windows log handles before hard exit.
        try:
            import localflight.__main__ as _main
            proc = getattr(_main, "_browser_proc", None)
            if proc:
                proc.terminate()
        except Exception:
            pass
        time.sleep(0.5)  # brief pause then kill everything
        logger.info("Quit requested via UI")
        try:
            import localflight.__main__ as _main
            _main._hard_exit(0)
        except Exception:
            import os
            os._exit(0)

    threading.Thread(target=_shutdown, daemon=True).start()
    return {"ok": True}
