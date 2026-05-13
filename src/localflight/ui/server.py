from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
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

from localflight.ui.api import router as api_router
from localflight.ui.matrix_guidance import matrix_guidance_payload
from localflight.core.airports import best_label, city_country_label
from localflight.core.settings_options import settings_options_context
from localflight.sources.web.relay_defaults import default_public_relay_url, relay_endpoint_url, validate_public_relay_url
from localflight.storage.config import (
    AppConfig, load_config, save_config,
    ALLOWED_DIAGNOSTICS_MODES, DEFAULT_DIAGNOSTICS_MODE,
    ALLOWED_OUTPUTS, ALLOWED_SOURCES, ALLOWED_SKINS,
    DEFAULT_DISPLAY_GRACE_MINUTES, DEFAULT_DISPLAY_HORIZON_HOURS,
    DEFAULT_OUTPUTS, DEFAULT_SOURCE, DEFAULT_SKIN,
    DEFAULT_WEB_ROTATION_SECONDS, DEFAULT_WEB_ROW_LIMIT,
)
from localflight.storage.logging_setup import (
    logs_dir, setup_logging,
    MAX_LOG_FILES, MAX_LOG_DAYS, MAX_LOG_BYTES,
)
from localflight.storage.profiles import delete_profile, list_profiles, load_profile, save_profile
from localflight.storage.state import load_state

logger = setup_logging()

ALLOWED_REFRESH_SECONDS = {900, 1800, 2700, 3600, 7200, 14400, 28800, 43200, 86400}
DEFAULT_REFRESH_SECONDS = 3600
FETCH_COOLDOWN_SECONDS = 900
SCHEDULER_SYNC_FIELDS = (
    "airport_iata",
    "airport_icao",
    "refresh_seconds",
    "source",
    "timezone",
    "display_grace_minutes",
    "display_horizon_hours",
)


def _schedule_policy_for_source(source: Optional[str]) -> Dict[str, Any]:
    try:
        from localflight.sources.web.aviationstack_client import schedule_policy

        return schedule_policy(source or load_config().source)
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
    "/api/setup/activate",
    "/api/setup/client-status",
    "/api/setup/request-activation",
    "/api/setup/request-activation/status",
    "/api/setup/test-activation",
    "/api/setup/test-aviationstack",
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


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    logger.info("Session started | component=ui")
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)
    asyncio.create_task(manager.broadcast_loop())
    from localflight.sources.web.relay_beat import _heartbeat_loop
    asyncio.create_task(_heartbeat_loop())

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

try:
    from importlib.metadata import version as _pkg_version
    _APP_VERSION = _pkg_version("localflight")
except Exception:
    _APP_VERSION = "0.2.7"

templates.env.globals["app_version"] = _APP_VERSION


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


def _activate_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/activate")


def _activation_request_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url or _relay_url_default(), "/v1/activation-request")


def _activation_request_status_url(relay_url: str) -> str:
    return _activation_request_url(relay_url).rstrip("/") + "/status"


_DOC_PAGES: Dict[str, Dict[str, str]] = {
    "readme": {
        "title": "Project README",
        "filename": "README.md",
        "summary": "Friendly overview, quick path chooser, previews, and links to deeper docs.",
        "github_url": "https://github.com/tr3y4rch/local-flight#readme",
    },
    "install": {
        "title": "Install Guide",
        "filename": "install.md",
        "summary": "Platform install steps for Windows, macOS, Raspberry Pi, source checkout, and mobile testing.",
        "github_url": "https://github.com/tr3y4rch/local-flight/blob/main/docs/install.md",
    },
    "display-modes": {
        "title": "Display Modes",
        "filename": "display-modes.md",
        "summary": "How native desktop, LAN browser, Pi kiosk, mobile, and Matrix clients fit together.",
        "github_url": "https://github.com/tr3y4rch/local-flight/blob/main/docs/display-modes.md",
    },
    "client-notes": {
        "title": "0.2.7 Client Notes",
        "filename": "release-notes-0.2.7.md",
        "summary": "0.2.7 polish pass: Network Admin presence framing, sign-out + idle auto-logoff, calmer admin styling.",
        "github_url": "https://github.com/tr3y4rch/local-flight/blob/main/docs/release-notes-0.2.7.md",
    },
    "privacy": {
        "title": "Privacy & Diagnostics",
        "filename": "PRIVACY.md",
        "summary": "What stays local, what reporting can send, and how diagnostics modes work.",
        "github_url": "https://github.com/tr3y4rch/local-flight/blob/main/PRIVACY.md",
    },
    "changelog": {
        "title": "Release Notes",
        "filename": "CHANGELOG.md",
        "summary": "Version history and recent release changes.",
        "github_url": "https://github.com/tr3y4rch/local-flight/blob/main/CHANGELOG.md",
    },
    "third-party": {
        "title": "Third-Party Notices",
        "filename": "THIRD_PARTY_NOTICES.md",
        "summary": "Bundled font licenses and source attribution for local app assets.",
        "github_url": "https://github.com/tr3y4rch/local-flight/blob/main/THIRD_PARTY_NOTICES.md",
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

    return {
        "slug": doc_slug,
        "title": page["title"],
        "summary": page["summary"],
        "filename": page["filename"],
        "github_url": page["github_url"],
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

@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request) -> HTMLResponse:
    from localflight.ui.setup_guidance import guidance_context

    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={"relay_url_default": _relay_url_default(), "setup_guidance": guidance_context()},
    )


@app.get("/api/setup/client-info")
def setup_client_info() -> Dict[str, Any]:
    from localflight.storage.install import get_activation_token, get_install_fingerprint, get_install_id

    token = get_activation_token().strip()
    return {
        "install_id": get_install_id(),
        "install_fingerprint": get_install_fingerprint(),
        "relay_url": _relay_url_default(),
        "activation_token_present": bool(token),
        "activation_token_prefix": token[:10] if token else "",
    }


class ApiKeyTestIn(BaseModel):
    key: str = Field(..., min_length=1, max_length=256)


class ActivationSetupIn(BaseModel):
    relay_url: str = Field("", max_length=300)
    airport_iata: str = Field("", max_length=4)
    airport_icao: str = Field("", max_length=4)
    display_name: str = Field("", max_length=80)
    requested_mode: str = Field("community", max_length=20)


class ClientStatusSetupIn(BaseModel):
    relay_url: str = Field("", max_length=300)
    activation_token: str = Field("", max_length=256)


class ActivationTokenTestIn(BaseModel):
    relay_url: str = Field("", max_length=300)
    activation_token: str = Field("", max_length=256)


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
                err = data["error"]
                return {"ok": False, "error": err.get("info", "Invalid key")}
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/setup/test-aviationstack")
async def setup_test_aviationstack_post(body: ApiKeyTestIn) -> Dict[str, Any]:
    return await _test_aviationstack_key(body.key)


@app.get("/api/setup/test-aviationstack")
async def setup_test_aviationstack_get(key: str = Query(...)) -> Dict[str, Any]:
    return await _test_aviationstack_key(key)


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
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/setup/test-rapidapi")
async def setup_test_rapidapi_post(body: ApiKeyTestIn) -> Dict[str, Any]:
    return await _test_rapidapi_key(body.key)


@app.get("/api/setup/test-rapidapi")
async def setup_test_rapidapi_get(key: str = Query(...)) -> Dict[str, Any]:
    return await _test_rapidapi_key(key)


@app.post("/api/setup/activate")
async def setup_activate(body: ActivationSetupIn) -> Dict[str, Any]:
    import requests as _req
    from localflight.storage.install import get_install_fingerprint, get_install_id, set_activation_token

    try:
        relay_url = _validated_setup_relay_url(body.relay_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        response = _req.post(
            _activate_url(relay_url),
            json={
                "install_id": get_install_id(),
                "install_fingerprint": get_install_fingerprint(),
                "display_name": (body.display_name or "").strip(),
                "requested_mode": (body.requested_mode or "community").strip().lower(),
                "app_version": _APP_VERSION,
            },
            headers={"Accept": "application/json"},
            timeout=12,
        )
    except Exception as exc:
        return {"ok": False, "error": f"Relay activation failed: {exc}"}

    try:
        payload = response.json()
    except Exception:
        payload = {"detail": f"Relay returned HTTP {response.status_code}"}
    if response.status_code >= 400:
        return {"ok": False, "error": str(payload.get("detail") or payload.get("error") or f"HTTP {response.status_code}")}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Relay activation response was invalid"}
    token = str(payload.get("activation_token") or "").strip()
    if token:
        try:
            set_activation_token(token)
        except Exception:
            pass
        payload["activation_token_present"] = True
        payload["activation_token_prefix"] = payload.get("token_prefix") or token[:10]
        payload.pop("activation_token", None)
    payload.setdefault("ok", True)
    return payload


@app.post("/api/setup/client-status")
async def setup_client_status(body: ClientStatusSetupIn) -> Dict[str, Any]:
    import requests as _req
    from localflight.sources.web.relay_heartbeat import relay_client_metadata
    from localflight.storage.config import load_config
    from localflight.storage.install import get_activation_token, get_install_id

    try:
        relay_url = _validated_setup_relay_url(body.relay_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    activation_token = (body.activation_token or "").strip() or get_activation_token().strip()
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
        response = _req.post(
            _client_checkin_url(relay_url),
            json={
                "install_id": get_install_id(),
                "activation_token": activation_token,
                **metadata,
            },
            headers={"Accept": "application/json"},
            timeout=12,
        )
    except Exception as exc:
        return {"ok": False, "error": f"Relay status check failed: {exc}"}

    try:
        payload = response.json()
    except Exception:
        payload = {"detail": f"Relay returned HTTP {response.status_code}"}
    if response.status_code >= 400:
        return {"ok": False, "error": str(payload.get("detail") or payload.get("error") or f"HTTP {response.status_code}")}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Relay status response was invalid"}
    payload.setdefault("ok", True)
    return payload


@app.post("/api/setup/request-activation")
async def setup_request_activation_compat(body: ActivationSetupIn) -> Dict[str, Any]:
    return await setup_activate(body)


@app.post("/api/setup/request-activation/status")
async def setup_request_activation_status_compat(body: ClientStatusSetupIn) -> Dict[str, Any]:
    return await setup_client_status(body)


@app.post("/api/setup/test-activation")
async def setup_test_activation(body: ActivationTokenTestIn) -> Dict[str, Any]:
    import requests as _req
    from localflight.sources.web.relay_heartbeat import relay_client_metadata
    from localflight.storage.install import get_activation_token, get_install_fingerprint, get_install_id

    try:
        relay_url = _validated_setup_relay_url(body.relay_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    token = body.activation_token.strip() or get_activation_token().strip()
    if not token:
        return {"ok": False, "error": "Managed activation token is not loaded on this machine yet."}
    try:
        response = _req.get(
            _client_status_url(relay_url),
            params={"install_id": get_install_id(), "activation_token": token, **relay_client_metadata()},
            headers={"Accept": "application/json"},
            timeout=12,
        )
    except Exception as exc:
        return {"ok": False, "error": f"Relay verification failed: {exc}"}

    try:
        payload = response.json()
    except Exception:
        payload = {"detail": f"Relay returned HTTP {response.status_code}"}

    if response.status_code >= 400:
        return {"ok": False, "error": str(payload.get("detail") or payload.get("error") or f"HTTP {response.status_code}")}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Relay verification response was invalid"}

    return {
        "ok": bool(payload.get("ok", True)),
        "install_fingerprint": payload.get("install_fingerprint") or get_install_fingerprint(),
        "token_prefix": payload.get("token_prefix") or token[:10],
        "providers": payload.get("providers") or {},
        "limits": payload.get("limits") or {},
        "plan": payload.get("plan") or "managed",
        "provider_revision": payload.get("provider_revision"),
        "label": payload.get("label") or "",
    }


@app.post("/api/setup/complete")
async def setup_complete(request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Save setup wizard results â€” write .env, save config, mark setup complete."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    airport_iata = (data.get("airport_iata") or "ZRH").upper().strip()
    airport_icao = (data.get("airport_icao") or "LSZH").upper().strip()
    timezone_str = data.get("timezone") or "Europe/Zurich"
    source = data.get("source") or "real"
    setup_mode = str(data.get("setup_mode") or "").strip().lower()
    if setup_mode == "virtual":
        source = "virtual"
    elif setup_mode in {"community", "managed", "byok"}:
        source = "real"
    if source not in ALLOWED_SOURCES:
        source = "real"
    diagnostics_mode = str(data.get("diagnostics_mode") or DEFAULT_DIAGNOSTICS_MODE).strip().lower()
    if diagnostics_mode not in ALLOWED_DIAGNOSTICS_MODES:
        diagnostics_mode = DEFAULT_DIAGNOSTICS_MODE

    # â”€â”€ Find .env path â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # __file__ is src/localflight/ui/server.py â†’ project root is 3 levels up
    here = Path(__file__).resolve().parent
    src_dir = here.parent.parent
    env_path = src_dir.parent / ".env"

    existing: Dict[str, str] = {}
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
        except Exception:
            pass

    as_key = data.get("aviationstack_key", "").strip()
    rp_key = data.get("rapidapi_key", "").strip()
    activation_token = data.get("activation_token", "").strip()
    relay_url = data.get("relay_url", "").strip()
    if setup_mode in {"managed", "community"}:
        try:
            relay_url = _validated_setup_relay_url(relay_url)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    os_id = data.get("opensky_id", "").strip()
    os_sec = data.get("opensky_secret", "").strip()

    if setup_mode in {"managed", "community"} and not activation_token:
        try:
            from localflight.storage.install import get_activation_token

            activation_token = get_activation_token().strip()
        except Exception:
            activation_token = ""

    def _clear_real_data_keys(*, clear_activation: bool = True) -> None:
        if clear_activation:
            existing.pop("LOCALFLIGHT_ACTIVATION_TOKEN", None)
        existing.pop("AVIATIONSTACK_API_KEY", None)
        existing.pop("RAPIDAPI_KEY", None)
        existing["LOCALFLIGHT_AVIATIONSTACK_ENABLED"] = "0"

    if setup_mode == "managed":
        _clear_real_data_keys()
        if activation_token:
            existing["LOCALFLIGHT_ACTIVATION_TOKEN"] = activation_token
        existing["LOCALFLIGHT_RELAY_URL"] = relay_url or _relay_url_default()
    elif setup_mode == "byok":
        existing.pop("LOCALFLIGHT_ACTIVATION_TOKEN", None)
        existing.pop("LOCALFLIGHT_RELAY_URL", None)
        existing.pop("AVIATIONSTACK_API_KEY", None)
        existing.pop("RAPIDAPI_KEY", None)
        if as_key:
            existing["AVIATIONSTACK_API_KEY"] = as_key
            existing["LOCALFLIGHT_AVIATIONSTACK_ENABLED"] = "1"
            current_as_limit = existing.get("LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT", "").strip()
            if not current_as_limit or current_as_limit == "10000":
                existing["LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT"] = "90"
        else:
            existing["LOCALFLIGHT_AVIATIONSTACK_ENABLED"] = "0"
        if rp_key:
            existing["RAPIDAPI_KEY"] = rp_key
            existing.setdefault("LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT", "10000")
    elif setup_mode == "community":
        _clear_real_data_keys(clear_activation=False)
        if activation_token:
            existing["LOCALFLIGHT_ACTIVATION_TOKEN"] = activation_token
        else:
            existing.pop("LOCALFLIGHT_ACTIVATION_TOKEN", None)
        existing["LOCALFLIGHT_RELAY_URL"] = relay_url or _relay_url_default()
    else:
        _clear_real_data_keys()
        existing.pop("LOCALFLIGHT_RELAY_URL", None)

    if os_id:
        existing["OPENSKY_CLIENT_ID"] = os_id
    elif setup_mode in {"managed", "community", "virtual"}:
        existing.pop("OPENSKY_CLIENT_ID", None)
    if os_sec:
        existing["OPENSKY_CLIENT_SECRET"] = os_sec
    elif setup_mode in {"managed", "community", "virtual"}:
        existing.pop("OPENSKY_CLIENT_SECRET", None)

    try:
        lines = ["# Local Flight â€” environment variables\n"]
        for k, v in existing.items():
            lines.append(f"{k}={v}\n")
        env_path.write_text("".join(lines), encoding="utf-8")

        for k, v in existing.items():
            os.environ[k] = v
        try:
            from localflight.storage.install import set_activation_token

            set_activation_token(existing.get("LOCALFLIGHT_ACTIVATION_TOKEN", ""))
        except Exception:
            pass
    except Exception as exc:
        logger.error("Setup: could not write .env: %s", exc)
        return JSONResponse({"ok": False, "error": f"Could not save config: {exc}"}, status_code=500)

    cfg = AppConfig(
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        timezone=timezone_str,
        source=source,
        display_name=str(data.get("display_name") or "Local Flight").strip()[:40] or "Local Flight",
        refresh_seconds=_coerce_refresh_for_policy(28800 if source == "real" else 900, source),
        diagnostics_mode=diagnostics_mode,
    )
    save_config(cfg)
    logger.info("Setup complete: %s/%s source=%s", airport_iata, airport_icao, source)

    _mark_setup_complete()
    from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

    notify_config_updated(cfg, reason="setup_complete")
    background_tasks.add_task(restart_scheduler_and_notify, "setup_complete")
    try:
        from localflight.sources.web.relay_beat import fire_heartbeat
        fire_heartbeat()
    except Exception:
        pass

    return {"ok": True}


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
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "cfg": cfg,
            "state": state,
            "profiles": profiles,
            "settings_options": _settings_options_for_policy(schedule_policy),
            "schedule_policy": schedule_policy,
            "saved": (saved == "1"),
            "profile_msg": profile_msg,
        },
    )


# â”€â”€ Log helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _list_log_files() -> list[str]:
    d = logs_dir()
    return [p.name for p in sorted(d.glob("localflight_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)]


def _tail_lines(path: Path, n: int = 500) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ["(log file not found)"]
    lines = text.splitlines()
    return lines[-n:] if len(lines) > n else lines


@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, file: Optional[str] = Query(None)) -> HTMLResponse:
    files = _list_log_files()
    base = {
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
        all_lines = (logs_dir() / selected).read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return JSONResponse({"lines": [], "total": 0})

    return JSONResponse({"lines": all_lines[after:] if after < len(all_lines) else [], "total": len(all_lines)})


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
) -> RedirectResponse:
    src = (source or DEFAULT_SOURCE).strip().lower()
    if src not in ALLOWED_SOURCES:
        src = DEFAULT_SOURCE
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
    surface_enabled = str(radar_surface_enabled or "").strip().lower() in {"1", "true", "yes", "on"}

    form_data = await request.form()
    raw_outputs = form_data.getlist("display_outputs")
    display_outputs = [o for o in raw_outputs if o in ALLOWED_OUTPUTS] or list(DEFAULT_OUTPUTS)
    old_cfg = load_config()

    cfg = AppConfig(
        airport_icao=airport_icao.upper().strip(),
        airport_iata=airport_iata.upper().strip(),
        refresh_seconds=rs,
        display_name=display_name.strip()[:40] or "Local Flight",
        theme=(theme or "dark").strip() or "dark",
        source=src,
        timezone=timezone.strip() or "UTC",
        skin=sk,
        display_outputs=display_outputs,
        diagnostics_mode=diag_mode,
        web_row_limit=web_rows,
        web_rotation_seconds=web_rotate,
        display_grace_minutes=grace_minutes,
        display_horizon_hours=horizon_hours,
        radar_surface_enabled=surface_enabled,
    )
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
        cfg.radar_surface_enabled,
    )

    from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

    notify_config_updated(cfg, reason="desktop_settings")
    if _scheduler_config_changed(old_cfg, cfg):
        logger.info("Triggering scheduler restart after settings save")
        background_tasks.add_task(restart_scheduler_and_notify, "desktop_settings")
    else:
        logger.info("Settings save did not change scheduler fields")
    try:
        from localflight.sources.web.relay_beat import fire_heartbeat
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
    cfg = load_profile(profile_name)
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
    """Delete the setup_complete marker so the setup wizard runs again on next visit."""
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
