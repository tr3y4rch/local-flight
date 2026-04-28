from __future__ import annotations

import os

DEFAULT_PUBLIC_RELAY_HOST = "relay.localflight.app"
DEFAULT_ADMIN_RELAY_HOST = "network.localflight.app"
DEFAULT_PUBLIC_RELAY_URL = f"https://{DEFAULT_PUBLIC_RELAY_HOST}/v1/flights"


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


def relay_radar_url(relay_url: str) -> str:
    return relay_endpoint_url(relay_url, "/v1/radar")
