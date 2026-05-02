"""HTTP clients used by the optional native Local Flight UIs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urljoin

import requests


class NativeApiError(RuntimeError):
    """Raised when a local or relay API request fails."""


@dataclass
class LocalApiClient:
    base_url: str = "http://127.0.0.1:8000"
    timeout_s: float = 10.0

    def _url(self, path: str) -> str:
        return urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

    def get_json(self, path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        try:
            response = requests.get(self._url(path), params=params, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
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
            response = requests.post(self._url(path), json=payload, timeout=self.timeout_s)
        except requests.RequestException as exc:
            raise NativeApiError(str(exc)) from exc
        if response.status_code >= 400:
            raise NativeApiError(f"HTTP {response.status_code}: {response.text[:180]}")
        try:
            data = response.json()
        except json.JSONDecodeError:
            return {"ok": True, "status_code": response.status_code}
        return data if isinstance(data, dict) else {"ok": True, "data": data}


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
