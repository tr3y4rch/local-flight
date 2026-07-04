"""Typed-ish service adapters for the native shell.

The local FastAPI app stays the source of truth.  These adapters keep PySide6
pages from hand-parsing every response shape and give the redesign a stable
place to harden route contracts without changing public HTTP APIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from localflight.native.api_client import LocalApiClient
from localflight.native.design import list_payload


@dataclass(frozen=True)
class FidsBoard:
    view: str
    rows: list[dict[str, Any]]
    config: dict[str, Any]
    health: dict[str, Any] | None
    weather: dict[str, Any] | None
    health_error: str = ""
    weather_error: str = ""


@dataclass(frozen=True)
class RadarPayload:
    radius_nm: float
    blips: list[dict[str, Any]]
    payload: dict[str, Any]
    config: dict[str, Any]
    surface: dict[str, Any] | None = None
    radar_map: dict[str, Any] | None = None
    surface_error: str = ""
    weather: dict[str, Any] | None = None
    weather_error: str = ""


@dataclass(frozen=True)
class MatrixState:
    presets: list[dict[str, Any]]
    configs: list[dict[str, Any]]
    devices: list[dict[str, Any]]
    default_config_id: str
    panel_presets: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AdminSummary:
    config: dict[str, Any]
    system: dict[str, Any]
    budget: dict[str, Any]
    connections: dict[str, Any]
    scheduler: dict[str, Any]
    updates: dict[str, Any]
    history_stats: dict[str, Any]
    weather: dict[str, Any] | None


@dataclass(frozen=True)
class RequestLogPayload:
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    payload: dict[str, Any]


@dataclass(frozen=True)
class LogTail:
    files: list[Any]
    selected: str
    lines: list[Any]
    total: int
    metadata: dict[str, Any]


class NativeApiService:
    """Small native-facing facade over the local HTTP client."""

    def __init__(self, client: LocalApiClient) -> None:
        self.client = client

    def config(self) -> dict[str, Any]:
        return self.client.get_json("/api/config")

    def health(self) -> dict[str, Any]:
        return self.client.get_json("/api/health")

    def clear_cache(self) -> None:
        self.client.clear_cache()

    def quit_app(self) -> dict[str, Any]:
        return self.client.post_json("/api/quit", {})

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch_json("/api/config", payload)

    def radar_map(self, *, radius_nm: float = 5.0, terrain: bool = False, refresh_runways: bool = False) -> dict[str, Any]:
        return self.client.get_json(
            "/api/radar/map",
            params={"radius_nm": float(radius_nm), "terrain": bool(terrain), "refresh_runways": bool(refresh_runways)},
        )

    def setup_client_info(self) -> dict[str, Any]:
        return self.client.get_json("/api/setup/client-info")

    def setup_activate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post_json("/api/setup/activate", payload)

    def setup_client_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post_json("/api/setup/client-status", payload)

    def setup_test_activation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post_json("/api/setup/test-activation", payload)

    def setup_test_provider_key(self, path: str, key: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"key": key}
        if extra:
            payload.update(extra)
        return self.client.post_json(path, payload)

    def setup_complete(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post_json("/api/setup/complete", payload)

    def setup_reset(self) -> dict[str, Any]:
        return self.client.post_json("/api/setup/reset", {})

    def provider_keys_status(self) -> dict[str, Any]:
        return self.client.get_json("/api/provider-keys/status")

    def provider_keys_save(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post_json("/api/provider-keys/save", payload)

    def provider_keys_clear(self) -> dict[str, Any]:
        return self.client.post_json("/api/provider-keys/clear", {})

    def airport_search(self, query: str, *, limit: int = 10) -> Any:
        return self.client.get_any_json("/api/airports/search", params={"q": query, "limit": limit})

    def metar(self) -> dict[str, Any]:
        return self.client.get_json("/api/metar")

    def fids_board(self, *, view: str = "departures", limit: int = 80) -> FidsBoard:
        cfg = self.config()
        payload = self.client.get_any_json("/api/fids", params={"view": view, "limit": limit})
        try:
            health = self.health()
            health_error = ""
        except Exception as exc:
            health = None
            health_error = str(exc)
        try:
            weather = self.metar()
            weather_error = ""
        except Exception as exc:
            weather = None
            weather_error = str(exc)
        return FidsBoard(
            view=view,
            rows=list_payload(payload),
            config=cfg,
            health=health,
            weather=weather,
            health_error=health_error,
            weather_error=weather_error,
        )

    def fids_detail(self, callsign: str) -> dict[str, Any]:
        return self.client.get_json("/api/fids/detail", params={"callsign": callsign})

    def radar(
        self,
        *,
        radius_nm: float,
        include_surface: bool = True,
        traffic: str = "all",
        min_alt_ft: float | None = None,
        max_alt_ft: float | None = None,
        terrain: bool = False,
    ) -> RadarPayload:
        cfg: dict[str, Any] = {}
        surface = None
        radar_map = None
        surface_error = ""
        try:
            cfg = self.config()
        except Exception:
            cfg = {}
        try:
            radar_map = self.client.get_json("/api/radar/map", params={"radius_nm": float(radius_nm), "terrain": bool(terrain)})
        except Exception as exc:
            surface_error = str(exc)
        if include_surface:
            if cfg.get("radar_surface_enabled") and not isinstance(radar_map, dict):
                try:
                    surface = self.client.get_json("/api/radar/surface", params={"radius_nm": min(5, radius_nm)})
                    surface_error = ""
                except Exception as exc:
                    surface = None
                    surface_error = str(exc)
        params: dict[str, Any] = {"radius_nm": float(radius_nm), "traffic": traffic}
        if min_alt_ft is not None:
            params["min_alt_ft"] = float(min_alt_ft)
        if max_alt_ft is not None:
            params["max_alt_ft"] = float(max_alt_ft)
        payload = self.client.get_json("/api/radar", params=params)
        try:
            weather = self.metar()
            weather_error = ""
        except Exception as exc:
            weather = None
            weather_error = str(exc)
        return RadarPayload(
            radius_nm=float(payload.get("radius_nm") or radius_nm),
            blips=list_payload(payload, "blips"),
            payload=payload,
            config=cfg,
            surface=surface,
            radar_map=radar_map,
            surface_error=surface_error,
            weather=weather,
            weather_error=weather_error,
        )

    def matrix_state(self) -> MatrixState:
        presets = self.client.get_json("/api/matrix/v2/presets")
        configs = self.client.get_json("/api/matrix/v2/configs")
        devices = self.client.get_json("/api/matrix/v2/devices")
        return MatrixState(
            presets=list_payload(presets, "presets"),
            configs=list_payload(configs, "configs"),
            devices=list_payload(devices, "devices"),
            default_config_id=str(configs.get("default_config_id") or "default"),
            panel_presets=list_payload(presets, "panel_presets"),
        )

    def matrix_compat_config(self) -> dict[str, Any]:
        return self.client.get_json("/api/matrix/config")

    def matrix_compat_rows(self, *, view: str = "departures", limit: int = 32) -> list[dict[str, Any]]:
        payload = self.client.get_any_json("/api/fids", params={"view": view, "limit": limit})
        return list_payload(payload)

    def matrix_feed(
        self,
        *,
        device_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        path = f"/api/matrix/v2/devices/{device_id}/feed" if device_id else "/api/matrix/v2/devices/preview/feed"
        payload = self.client.get_json(path, params=params)
        return payload, list_payload(payload, "rows")

    def matrix_save_config(self, *, config_id: str | None, payload: dict[str, Any], v2_available: bool) -> dict[str, Any]:
        if v2_available and config_id:
            return self.client.patch_json(f"/api/matrix/v2/configs/{config_id}", payload)
        return self.client.post_json(
            "/api/matrix/config",
            {
                "brightness": payload["brightness"],
                "max_rows": payload["max_rows"],
                "refresh_seconds": payload["refresh_seconds"],
                "default_view": payload.get("default_view", "departures"),
                "page_rotation_seconds": payload["page_rotation_seconds"],
                "animation_enabled": payload["animation_enabled"],
                "animation_mode": payload.get("animation_mode", "split_flap"),
                "animation_speed": payload.get("animation_speed", 3),
                "status_animation_enabled": payload.get("status_animation_enabled", True),
                "show_weather": payload.get("show_weather", True),
                "show_gate_info": payload.get("show_gate_info", True),
                "palette": payload.get("palette", "pax_blue"),
                "options": payload.get("options", {}),
            },
        )

    def matrix_create_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post_json("/api/matrix/v2/configs", payload)

    def matrix_delete_config(self, config_id: str) -> dict[str, Any]:
        return self.client.delete_json(f"/api/matrix/v2/configs/{config_id}")

    def matrix_set_default_config(self, config_id: str) -> dict[str, Any]:
        return self.client.post_json(f"/api/matrix/v2/configs/{config_id}/default", {})

    def matrix_save_device_assignment(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch_json(f"/api/matrix/v2/devices/{device_id}", payload)

    def matrix_generate_script(self, payload: dict[str, Any]) -> str:
        return self.client.post_text("/api/matrix/script", payload)

    def _history_params(
        self,
        *,
        hours: int,
        direction: str = "both",
        limit: int | None = None,
        include_direction: bool = True,
        status: str | None = None,
        callsign: str | None = None,
        airline_iata: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"hours": hours}
        if include_direction:
            params["direction"] = direction
        if limit is not None:
            params["limit"] = limit
        if status:
            params["status"] = status
        if callsign:
            params["callsign"] = callsign
        if airline_iata:
            params["airline_iata"] = airline_iata
        return params

    def history_rows(
        self,
        *,
        hours: int = 24,
        direction: str = "both",
        limit: int = 500,
        status: str | None = None,
        callsign: str | None = None,
        airline_iata: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = self.client.get_json(
            "/api/history",
            params=self._history_params(
                hours=hours,
                direction=direction,
                limit=limit,
                status=status,
                callsign=callsign,
                airline_iata=airline_iata,
            ),
        )
        return list_payload(payload, "flights")

    def history_payload(
        self,
        *,
        hours: int = 24,
        direction: str = "both",
        limit: int = 500,
        status: str | None = None,
        callsign: str | None = None,
        airline_iata: str | None = None,
    ) -> dict[str, Any]:
        return self.client.get_json(
            "/api/history",
            params=self._history_params(
                hours=hours,
                direction=direction,
                limit=limit,
                status=status,
                callsign=callsign,
                airline_iata=airline_iata,
            ),
        )

    def history_flight(self, callsign: str, *, days: int = 30) -> dict[str, Any]:
        return self.client.get_json("/api/history/flight", params={"callsign": callsign, "days": days})

    def history_summary(
        self,
        *,
        hours: int,
        direction: str = "both",
        status: str | None = None,
        callsign: str | None = None,
        airline_iata: str | None = None,
    ) -> dict[str, Any]:
        return self.client.get_json(
            "/api/history/summary",
            params=self._history_params(
                hours=hours,
                direction=direction,
                include_direction=direction != "both" or bool(status or callsign or airline_iata),
                status=status,
                callsign=callsign,
                airline_iata=airline_iata,
            ),
        )

    def history_stats(self) -> dict[str, Any]:
        return self.client.get_json("/api/history/stats")

    def request_log(self, *, hours: int = 24, limit: int = 300, client_type: str = "all") -> RequestLogPayload:
        params: dict[str, Any] = {"hours": hours, "limit": limit}
        if client_type != "all":
            params["client_type"] = client_type
        payload = self.client.get_json("/api/admin/requests", params=params)
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        return RequestLogPayload(rows=list_payload(payload, "requests"), summary=summary, payload=payload)

    def request_log_rows(self, *, hours: int = 24, limit: int = 300, client_type: str = "all") -> list[dict[str, Any]]:
        return self.request_log(hours=hours, limit=limit, client_type=client_type).rows

    def log_files(self) -> dict[str, Any]:
        return self.client.get_json("/api/logs")

    def log_tail(self, *, selected: str | None = None) -> LogTail:
        meta_params = {"file": selected} if selected else None
        meta = self.client.get_json("/api/logs", params=meta_params)
        active = selected or str(meta.get("selected") or "") or None
        tail_params = {"file": active, "after": 0} if active else {"after": 0}
        payload = self.client.get_json("/logs/tail", params=tail_params)
        lines = payload.get("lines") if isinstance(payload.get("lines"), list) else []
        total = int(payload.get("total") or len(lines))
        files = meta.get("files") if isinstance(meta.get("files"), list) else []
        return LogTail(
            files=files,
            selected=str(active or meta.get("selected") or ""),
            lines=lines,
            total=total,
            metadata=meta,
        )

    def feedback_context(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        return self.config(), self.client.get_json("/api/admin/system"), self.setup_client_info()

    def send_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post_json("/api/feedback", payload)

    def restart_scheduler(self) -> dict[str, Any]:
        return self.client.post_json("/api/admin/scheduler/restart", {})

    def save_profile(self, name: str) -> dict[str, Any]:
        return self.client.post_form("/profiles/save", {"profile_name": name})

    def load_profile(self, name: str) -> dict[str, Any]:
        return self.client.post_form("/profiles/load", {"profile_name": name})

    def delete_profile(self, name: str) -> dict[str, Any]:
        return self.client.post_form("/profiles/delete", {"profile_name": name})

    def admin_summary(self) -> AdminSummary:
        weather: dict[str, Any] | None
        try:
            weather = self.client.get_json("/api/metar")
        except Exception:
            weather = None
        return AdminSummary(
            config=self.client.get_json("/api/config"),
            system=self.client.get_json("/api/admin/system"),
            budget=self.client.get_json("/api/admin/budget"),
            connections=self.client.get_json("/api/admin/connections"),
            scheduler=self.client.get_json("/api/admin/scheduler"),
            updates=self.client.get_json("/api/admin/updates"),
            history_stats=self.history_stats(),
            weather=weather,
        )

    def connections(self) -> dict[str, Any]:
        return self.client.get_json("/api/admin/connections")

    def reset_companions(self) -> dict[str, Any]:
        return self.client.delete_json("/api/admin/companion")

    def remote_companion_status(self) -> dict[str, Any]:
        return self.client.get_json("/api/mobile/remote/status")

    def remote_companion_invite(self) -> dict[str, Any]:
        return self.client.post_json("/api/mobile/remote/invite", {})

    def remote_companion_revoke(self, grant_ref: str) -> dict[str, Any]:
        return self.client.post_json("/api/mobile/remote/revoke", {"grant_ref": grant_ref})
