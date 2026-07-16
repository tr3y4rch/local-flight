from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse

DEFAULT_PUBLIC_RELAY_HOST = "relay.beacontools.cc"
DEFAULT_ADMIN_RELAY_HOST = "network.beacontools.cc"
DEFAULT_PUBLIC_RELAY_URL = f"https://{DEFAULT_PUBLIC_RELAY_HOST}"
OFFICIAL_PUBLIC_RELAY_HOSTS = {DEFAULT_PUBLIC_RELAY_HOST, "localflight-community-relay.fly.dev"}


def default_public_relay_url() -> str:
    return os.getenv("LOCALFLIGHT_RELAY_URL", DEFAULT_PUBLIC_RELAY_URL).strip()


def relay_root_url(relay_url: str) -> str:
    clean = (relay_url or default_public_relay_url()).strip().rstrip("/")
    if clean.endswith("/v1/flights"):
        return clean[: -len("/v1/flights")]
    if clean.endswith("/flights"):
        return clean[: -len("/flights")]
    return clean


def relay_endpoint_url(relay_url: str, suffix: str) -> str:
    suffix = "/" + suffix.lstrip("/")
    return relay_root_url(relay_url) + suffix


def _bool_env(key: str) -> bool:
    return os.getenv(key, "").strip().lower() in {"1", "true", "yes", "on"}


def _hostname(value: str) -> str:
    host = (value or "").strip().lower()
    if host.startswith("[") and "]" in host:
        return host[1 : host.index("]")]
    return host


def _is_private_or_local_host(host: str) -> bool:
    clean = _hostname(host)
    if clean in {"localhost", "0.0.0.0", "::", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(clean)
    except ValueError:
        return clean.endswith(".local")
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified


def validate_public_relay_url(relay_url: str, *, trusted_default: str = "") -> str:
    """Validate setup-provided relay roots before the local app calls them."""
    clean = (relay_url or default_public_relay_url()).strip().rstrip("/")
    root = relay_root_url(clean)
    trusted_root = relay_root_url(trusted_default or default_public_relay_url())
    if root == trusted_root:
        return clean

    parsed = urlparse(root)
    host = _hostname(parsed.hostname or "")
    if not parsed.scheme or not host:
        raise ValueError("Relay URL must include an absolute https:// host")

    allow_custom = _bool_env("LOCALFLIGHT_ALLOW_CUSTOM_RELAY_URL")
    allow_private = _bool_env("LOCALFLIGHT_ALLOW_PRIVATE_RELAY_URL")
    if _is_private_or_local_host(host) and not allow_private:
        raise ValueError("Private or local relay URLs require LOCALFLIGHT_ALLOW_PRIVATE_RELAY_URL=1")
    if parsed.scheme != "https" and not allow_private:
        raise ValueError("Relay URL must use https unless private relay URLs are explicitly enabled")
    if host not in OFFICIAL_PUBLIC_RELAY_HOSTS and not allow_custom and not allow_private:
        raise ValueError("Custom relay hosts require LOCALFLIGHT_ALLOW_CUSTOM_RELAY_URL=1")
    return clean


def relay_radar_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url, "/v1/radar")


def relay_schedule_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url, "/v1/schedule")


def relay_airport_surface_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url, "/v1/airport-surface")


def relay_airport_ground_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url, "/v1/airport-ground")


def relay_heartbeat_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url, "/v1/heartbeat")
