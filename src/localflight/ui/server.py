from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from localflight.ui.api import router as api_router
from localflight.core.airports import best_label
from localflight.storage.config import (
    AppConfig, load_config, save_config,
    ALLOWED_OUTPUTS, ALLOWED_SOURCES, ALLOWED_SKINS,
    DEFAULT_OUTPUTS, DEFAULT_SOURCE, DEFAULT_SKIN,
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
SCHEDULER_SYNC_FIELDS = ("airport_iata", "airport_icao", "refresh_seconds", "source")


def _scheduler_config_changed(before: AppConfig, after: AppConfig) -> bool:
    return any(getattr(before, field) != getattr(after, field) for field in SCHEDULER_SYNC_FIELDS)


def _network_tools_enabled() -> bool:
    return os.getenv("LOCALFLIGHT_ENABLE_NETWORK_TOOLS", "").strip().lower() in {"1", "true", "yes", "on"}


# ── Setup gate ─────────────────────────────────────────────────────────────────

# Paths always accessible even before setup completes
_SETUP_FREE_PATHS = {
    "/splash",
    "/setup",
    "/api/setup/complete",
    "/api/setup/reset",
    "/api/setup/test-aviationstack",
    "/api/setup/test-rapidapi",
    "/api/airports/search",
    "/static",
    "/health",
    "/ws",
}


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


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request to the local traffic DB (non-fatal)."""

    async def dispatch(self, request: Request, call_next):
        start = _time.monotonic()
        response = await call_next(request)
        latency_ms = int((_time.monotonic() - start) * 1000)
        try:
            from localflight.storage.request_log import log_request
            fwd = request.headers.get("x-forwarded-for", "")
            ip  = fwd.split(",")[0].strip() if fwd else (
                request.client.host if request.client else "unknown"
            )
            log_request(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                latency_ms=latency_ms,
                ip=ip,
                user_agent=request.headers.get("user-agent", ""),
            )
        except Exception:
            pass
        return response


# ── App setup ──────────────────────────────────────────────────────────────────

def _templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


app = FastAPI(title="Local Flight UI", docs_url=None, redoc_url=None)

# Middleware order: RequestLog (outer) → SetupGate (inner) → route
# add_middleware is LIFO so SetupGate must be added first
app.add_middleware(SetupGateMiddleware)
if _network_tools_enabled():
    app.add_middleware(RequestLogMiddleware)

app.mount("/static", StaticFiles(directory=str(_static_dir())), name="static")
app.include_router(api_router)
templates = Jinja2Templates(directory=str(_templates_dir()))

try:
    from importlib.metadata import version as _pkg_version
    _APP_VERSION = _pkg_version("localflight")
except Exception:
    _APP_VERSION = "0.2.2b3"

templates.env.globals["app_version"] = _APP_VERSION


def _safe_local_path(path: str, *, fallback: str = "/display") -> str:
    """Accept only local absolute paths for splash redirects."""
    path = (path or "").strip()
    if not path.startswith("/") or path.startswith("//") or "://" in path:
        return fallback
    return path


# ── WebSocket connection manager ───────────────────────────────────────────────

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
        logger.debug("WS connect — %d active", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.debug("WS disconnect — %d active", len(self._connections))

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


# ── Background fetch helpers ───────────────────────────────────────────────────

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


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def _on_startup() -> None:
    logger.info("Session started | component=ui")
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)
    asyncio.create_task(manager.broadcast_loop())

    import localflight.ui.server as _self
    _self._ws_manager = manager

    try:
        _ = best_label(iata="ZRH", icao="LSZH")
        logger.info("Airport DB loaded | component=ui")
    except Exception as e:
        logger.warning("Airport DB not available: %s", e)


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

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


# ── Setup wizard ───────────────────────────────────────────────────────────────

@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context={},
    )


class ApiKeyTestIn(BaseModel):
    key: str = Field(..., min_length=1, max_length=256)


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
            return {"ok": False, "error": "Rate limit hit — try again shortly"}
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


@app.post("/api/setup/complete")
async def setup_complete(request: Request, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Save setup wizard results — write .env, save config, mark setup complete."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    airport_iata = (data.get("airport_iata") or "ZRH").upper().strip()
    airport_icao = (data.get("airport_icao") or "LSZH").upper().strip()
    timezone_str = data.get("timezone") or "Europe/Zurich"
    source = data.get("source") or "real"
    if source not in ALLOWED_SOURCES:
        source = "real"

    # ── Find .env path ─────────────────────────────────────────────────────────
    # __file__ is src/localflight/ui/server.py → project root is 3 levels up
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
    os_id = data.get("opensky_id", "").strip()
    os_sec = data.get("opensky_secret", "").strip()

    if as_key:
        existing["AVIATIONSTACK_API_KEY"] = as_key
        existing["LOCALFLIGHT_AVIATIONSTACK_ENABLED"] = "1"
        existing.setdefault("LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT", "10000")
    if rp_key:
        existing["RAPIDAPI_KEY"] = rp_key
        existing.setdefault("LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT", "10000")
    if os_id:
        existing["OPENSKY_CLIENT_ID"] = os_id
    if os_sec:
        existing["OPENSKY_CLIENT_SECRET"] = os_sec

    try:
        lines = ["# Local Flight — environment variables\n"]
        for k, v in existing.items():
            lines.append(f"{k}={v}\n")
        env_path.write_text("".join(lines), encoding="utf-8")

        for k, v in existing.items():
            if k not in os.environ:
                os.environ[k] = v
    except Exception as exc:
        logger.error("Setup: could not write .env: %s", exc)
        return JSONResponse({"ok": False, "error": f"Could not save config: {exc}"}, status_code=500)

    cfg = AppConfig(
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        timezone=timezone_str,
        source=source,
        refresh_seconds=28800 if source == "real" else 900,
    )
    save_config(cfg)
    logger.info("Setup complete: %s/%s source=%s", airport_iata, airport_icao, source)

    _mark_setup_complete()
    from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

    notify_config_updated(cfg, reason="setup_complete")
    background_tasks.add_task(restart_scheduler_and_notify, "setup_complete")

    return {"ok": True}


# ── Pages ──────────────────────────────────────────────────────────────────────

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
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "cfg": cfg,
            "state": state,
            "profiles": profiles,
            "saved": (saved == "1"),
            "profile_msg": profile_msg,
        },
    )


# ── Log helpers ────────────────────────────────────────────────────────────────

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


# ── Settings save ──────────────────────────────────────────────────────────────

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
) -> RedirectResponse:
    rs = int(refresh_seconds) if int(refresh_seconds) in ALLOWED_REFRESH_SECONDS else DEFAULT_REFRESH_SECONDS

    src = (source or DEFAULT_SOURCE).strip().lower()
    if src not in ALLOWED_SOURCES:
        src = DEFAULT_SOURCE

    sk = (skin or DEFAULT_SKIN).strip().lower()
    if sk not in ALLOWED_SKINS:
        sk = DEFAULT_SKIN

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
    )
    save_config(cfg)

    logger.info(
        "UI save: %s/%s refresh=%ss theme=%s source=%s skin=%s outputs=%s",
        cfg.airport_iata,
        cfg.airport_icao,
        cfg.refresh_seconds,
        cfg.theme,
        cfg.source,
        cfg.skin,
        cfg.display_outputs,
    )

    from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

    notify_config_updated(cfg, reason="desktop_settings")
    if _scheduler_config_changed(old_cfg, cfg):
        logger.info("Triggering scheduler restart after settings save")
        background_tasks.add_task(restart_scheduler_and_notify, "desktop_settings")
    else:
        logger.info("Settings save did not change scheduler fields")

    return RedirectResponse(url="/?saved=1", status_code=303)


# ── Legacy JSON endpoints ──────────────────────────────────────────────────────

@app.get("/api/status")
def api_status() -> JSONResponse:
    return JSONResponse(asdict(load_state()))


# ── Profiles ───────────────────────────────────────────────────────────────────

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


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


# ── FIDS display ───────────────────────────────────────────────────────────────

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
    airport_label = best_label(iata=cfg.airport_iata, icao=cfg.airport_icao) or cfg.airport_iata

    snap_path = load_latest_snapshot_path(cfg.airport_iata)
    if snap_path:
        raw = _json.loads(snap_path.read_text(encoding="utf-8"))
        source_label = f"real:file:{snap_path.name}"
    else:
        raw = {"flights": []}
        source_label = "real:NO SNAPSHOT"

    def _best_time(f):
        return f.times.actual or f.times.estimated or f.times.scheduled

    now = datetime.now(timezone.utc)
    direction = FlightDirection.DEPARTURE if view == "departures" else FlightDirection.ARRIVAL
    all_flights = [_dict_to_flight(f) for f in (raw.get("flights") or [])]
    flights = [
        f for f in all_flights
        if f.direction == direction
        and (_best_time(f) is None or _best_time(f) >= now)
    ][:12]

    ctx = _build(
        cfg=cfg,
        view=view,
        refresh_seconds=cfg.refresh_seconds,
        flights=flights,
        source_status=f"{source_label} payload={len(all_flights)} showing={len(flights)}",
    )
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


# ── Radar ──────────────────────────────────────────────────────────────────────

@app.get("/radar", response_class=HTMLResponse)
def radar(
    request:   Request,
    embedded:  bool  = Query(False),
    radius_nm: int   = Query(20, ge=5, le=200),
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


# ── Display ────────────────────────────────────────────────────────────────────

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


# ── Matrix preview ─────────────────────────────────────────────────────────────

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
            "panel_w": panel_w,
            "panel_h": panel_h,
            "pixel_size": pixel_size,
            "view": view,
            "rows": rows,
        },
    )


# ── Admin hub ──────────────────────────────────────────────────────────────────

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


# ── Feedback / bug report ──────────────────────────────────────────────────────

@app.get("/feedback", response_class=HTMLResponse)
def feedback_page(request: Request) -> HTMLResponse:
    cfg = load_config()
    return templates.TemplateResponse(
        request=request,
        name="feedback.html",
        context={"cfg": cfg, "state": load_state()},
    )


# ── History browser ────────────────────────────────────────────────────────────

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

# ── Traffic hub ────────────────────────────────────────────────────────────────

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


# ── Quit ───────────────────────────────────────────────────────────────────────

@app.post("/api/setup/reset")
def api_setup_reset() -> dict:
    """Delete the setup_complete marker so the setup wizard runs again on next visit."""
    from localflight.storage.config import config_path
    marker = config_path().parent / "setup_complete"
    try:
        marker.unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    logger.info("Setup reset via UI — setup_complete marker removed")
    return {"ok": True}


@app.post("/api/quit")
def api_quit() -> dict:
    import threading
    import os

    def _shutdown():
        import time
        # Kill the browser process first
        try:
            import localflight.__main__ as _main
            proc = getattr(_main, "_browser_proc", None)
            if proc:
                proc.terminate()
        except Exception:
            pass
        time.sleep(0.5)  # brief pause then kill everything
        logger.info("Quit requested via UI")
        os._exit(0)

    threading.Thread(target=_shutdown, daemon=True).start()
    return {"ok": True}
