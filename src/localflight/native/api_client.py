"""HTTP clients used by the optional native Local Flight UIs."""
from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from threading import RLock, local
from typing import Any, Optional
from urllib.parse import urljoin

import requests


class NativeApiError(RuntimeError):
    """Raised when a local or relay API request fails."""


@dataclass
class LocalApiClient:
    base_url: str = "http://127.0.0.1:8000"
    timeout_s: float = 10.0
    _thread_local: local = field(default_factory=local, init=False, repr=False)
    _cache: dict[tuple[str, str], tuple[float, Any]] = field(default_factory=dict, init=False, repr=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _cache_hits: int = field(default=0, init=False, repr=False)
    _cache_misses: int = field(default=0, init=False, repr=False)
    _install_id: str = field(default="", init=False, repr=False)

    def _url(self, path: str) -> str:
        return urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self._headers())
            self._thread_local.session = session
        return session

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": f"LocalFlight Native/{self._app_version()}",
            "X-LocalFlight-Client-Type": "native",
            "X-LocalFlight-Client-Platform": platform.system() or "desktop",
            "X-LocalFlight-Companion-Id": self._client_id(),
        }

    def _app_version(self) -> str:
        try:
            return version("localflight")
        except PackageNotFoundError:
            return "0.2.7"

    def _client_id(self) -> str:
        if self._install_id:
            return self._install_id
        try:
            from localflight.storage.install import get_install_id

            self._install_id = str(get_install_id() or "")
        except Exception:
            self._install_id = ""
        return self._install_id or "native-local"

    def _cache_key(self, path: str, params: Optional[dict[str, Any]]) -> tuple[str, str]:
        normalized = json.dumps(params or {}, sort_keys=True, default=str, separators=(",", ":"))
        return path, normalized

    def _cache_ttl(self, path: str) -> float:
        """Short local cache to avoid hammering the same backend routes from Qt pages."""
        if path in {"/api/config", "/api/setup/client-info", "/api/matrix/config"}:
            return 2.0
        if path == "/api/health":
            return 2.0
        if path.startswith("/api/matrix/v2/"):
            return 2.0
        if path in {"/api/fids", "/api/radar", "/api/fids/detail"}:
            return 2.0
        if path == "/api/metar":
            return 30.0
        if path == "/api/airports/search":
            return 30.0
        if path in {"/api/radar/map", "/api/radar/surface"}:
            return 300.0
        if path.startswith("/api/admin/") or path.startswith("/api/history"):
            return 5.0
        if path in {"/api/logs", "/logs/tail"}:
            return 2.0
        return 0.0

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def cache_counters(self) -> dict[str, int]:
        with self._lock:
            return {"hits": self._cache_hits, "misses": self._cache_misses}

    def get_json(self, path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        payload = self.get_any_json(path, params=params)
        if not isinstance(payload, dict):
            raise NativeApiError("Response JSON was not an object")
        return payload

    def get_any_json(self, path: str, *, params: Optional[dict[str, Any]] = None) -> Any:
        ttl = self._cache_ttl(path)
        key = self._cache_key(path, params)
        now = time.monotonic()
        if ttl > 0:
            with self._lock:
                cached = self._cache.get(key)
                if cached and now - cached[0] <= ttl:
                    self._cache_hits += 1
                    return cached[1]
                self._cache_misses += 1
        try:
            response = self._session().get(self._url(path), params=params, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
        if response.status_code >= 400:
            raise NativeApiError(f"HTTP {response.status_code}: {response.text[:180]}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise NativeApiError("Response was not JSON") from exc
        if ttl > 0:
            with self._lock:
                self._cache[key] = (time.monotonic(), payload)
        return payload

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.clear_cache()
        try:
            response = self._session().post(self._url(path), json=payload, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
        if response.status_code >= 400:
            raise NativeApiError(f"HTTP {response.status_code}: {response.text[:180]}")
        try:
            data = response.json()
        except json.JSONDecodeError:
            return {"ok": True, "status_code": response.status_code}
        return data if isinstance(data, dict) else {"ok": True, "data": data}

    def patch_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.clear_cache()
        try:
            response = self._session().patch(self._url(path), json=payload, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
        if response.status_code >= 400:
            raise NativeApiError(f"HTTP {response.status_code}: {response.text[:180]}")
        try:
            data = response.json()
        except json.JSONDecodeError:
            return {"ok": True, "status_code": response.status_code}
        return data if isinstance(data, dict) else {"ok": True, "data": data}

    def delete_json(self, path: str) -> dict[str, Any]:
        self.clear_cache()
        try:
            response = self._session().delete(self._url(path), timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
        if response.status_code >= 400:
            raise NativeApiError(f"HTTP {response.status_code}: {response.text[:180]}")
        try:
            data = response.json()
        except json.JSONDecodeError:
            return {"ok": True, "status_code": response.status_code}
        return data if isinstance(data, dict) else {"ok": True, "data": data}

    def post_form(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.clear_cache()
        try:
            response = self._session().post(self._url(path), data=payload, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
        if response.status_code >= 400:
            raise NativeApiError(f"HTTP {response.status_code}: {response.text[:180]}")
        try:
            data = response.json()
        except json.JSONDecodeError:
            return {"ok": True, "status_code": response.status_code}
        return data if isinstance(data, dict) else {"ok": True, "data": data}

    def post_text(self, path: str, payload: dict[str, Any]) -> str:
        self.clear_cache()
        try:
            response = self._session().post(self._url(path), json=payload, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
        if response.status_code >= 400:
            raise NativeApiError(f"HTTP {response.status_code}: {response.text[:180]}")
        return response.text


@dataclass
class RelayAdminClient:
    base_url: str
    username: str
    password: str
    timeout_s: float = 12.0

    def _url(self, path: str) -> str:
        return urljoin(_normalize_relay_base_url(self.base_url) + "/", path.lstrip("/"))

    def get_json(self, path: str) -> dict[str, Any]:
        try:
            response = requests.get(
                self._url(path),
                auth=(self.username, self.password),
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
        if response.status_code == 401:
            raise NativeApiError("Admin credentials were rejected")
        if response.status_code >= 400:
            raise NativeApiError(f"HTTP {response.status_code}: {response.text[:180]}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise NativeApiError("Response was not JSON") from exc
        if not isinstance(payload, dict):
            raise NativeApiError("Response JSON was not an object")
        return payload

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.post(
                self._url(path),
                json=payload,
                auth=(self.username, self.password),
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
        if response.status_code == 401:
            raise NativeApiError("Admin credentials were rejected")
        if response.status_code >= 400:
            raise NativeApiError(f"HTTP {response.status_code}: {response.text[:180]}")
        try:
            data = response.json()
        except json.JSONDecodeError:
            return {"ok": True, "status_code": response.status_code}
        return data if isinstance(data, dict) else {"ok": True, "data": data}


def _normalize_relay_base_url(value: str) -> str:
    """Accept either the relay root or the human admin page URL."""
    base = (value or "").strip().rstrip("/")
    for suffix in ("/admin/api", "/admin"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base or "https://localflight-community-relay.fly.dev"
