"""Reusable pairing-link helpers for Local Flight companion clients."""
from __future__ import annotations

import io
import ipaddress
import socket
from urllib.parse import urlencode, urlparse


DEFAULT_PAIRING_PORT = 8000
PAIRING_SCHEME = "localflight"


def build_pairing_deep_link(server_url: str, *, source: str = "qt", server_fingerprint: str = "") -> str:
    """Return the reusable companion deep link for one Local Flight server."""
    normalized = _normalize_http_url(server_url)
    payload = {"server": normalized, "source": source}
    fingerprint = _normalize_server_fingerprint(server_fingerprint)
    if fingerprint:
        payload["server_fingerprint"] = fingerprint
    query = urlencode(payload)
    return f"{PAIRING_SCHEME}://pair?{query}"


def pairing_gateway_payload(
    *,
    base_url: str = "",
    port: int = DEFAULT_PAIRING_PORT,
    server_fingerprint: str = "",
) -> dict[str, object]:
    """Build URL, deep-link, and manual fallback data for companion pairing UI."""
    manual_urls = lan_url_candidates(base_url=base_url, port=port)
    preferred_url = manual_urls[0] if manual_urls else f"http://localflight.local:{port}"
    fingerprint = _normalize_server_fingerprint(server_fingerprint) or _safe_install_fingerprint()
    return {
        "preferred_url": preferred_url,
        "manual_urls": manual_urls,
        "server_fingerprint": fingerprint,
        "deep_link": build_pairing_deep_link(preferred_url, source="qt", server_fingerprint=fingerprint),
    }


def lan_url_candidates(*, base_url: str = "", port: int = DEFAULT_PAIRING_PORT) -> list[str]:
    """Return LAN-friendly server URLs, with loopback avoided for phone pairing."""
    candidates: list[str] = []
    parsed_base = urlparse(base_url or "")
    base_host = (parsed_base.hostname or "").strip("[]")
    if base_host and _is_private_ipv4(base_host):
        base_port = parsed_base.port or port
        candidates.append(f"{parsed_base.scheme or 'http'}://{base_host}:{base_port}")

    for host in _local_ipv4_addresses():
        if _is_private_ipv4(host):
            candidates.append(f"http://{host}:{port}")

    if base_host and _is_lan_hostname(base_host) and base_host.lower() != "localflight.local":
        base_port = parsed_base.port or port
        candidates.append(f"{parsed_base.scheme or 'http'}://{base_host}:{base_port}")

    candidates.append(f"http://localflight.local:{port}")

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        normalized = _normalize_http_url(candidate)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique


def pairing_qr_png_bytes(text: str, *, size: int = 220) -> bytes | None:
    """Render a QR PNG if the optional qrcode dependency is available."""
    try:
        import qrcode
        from PIL import Image
    except Exception:
        return None

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(text)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#07111d", back_color="#f4fbff").convert("RGB")
    if size > 0:
        resampling = getattr(getattr(Image, "Resampling", Image), "NEAREST")
        image = image.resize((size, size), resampling)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _normalize_http_url(value: str) -> str:
    trimmed = str(value or "").strip()
    if not trimmed:
        return ""
    if not trimmed.lower().startswith(("http://", "https://")):
        trimmed = f"http://{trimmed}"
    return trimmed.rstrip("/")


def _safe_install_fingerprint() -> str:
    try:
        from localflight.storage.install import get_install_fingerprint

        return str(get_install_fingerprint() or "").strip()
    except Exception:
        return ""


def _normalize_server_fingerprint(value: str) -> str:
    fingerprint = str(value or "").strip()
    if len(fingerprint) > 24:
        return ""
    return fingerprint


def _local_ipv4_addresses() -> list[str]:
    addresses: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            if info and info[4]:
                addresses.append(str(info[4][0]))
    except Exception:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.2)
            sock.connect(("8.8.8.8", 80))
            addresses.append(str(sock.getsockname()[0]))
    except Exception:
        pass

    return addresses


def _is_private_ipv4(host: str) -> bool:
    lowered = host.lower()
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return bool(address.version == 4 and address.is_private and not address.is_loopback)


def _is_lan_hostname(host: str) -> bool:
    lowered = host.lower()
    try:
        ipaddress.ip_address(lowered)
    except ValueError:
        return lowered.endswith(".local")
    return False


__all__ = [
    "build_pairing_deep_link",
    "lan_url_candidates",
    "pairing_gateway_payload",
    "pairing_qr_png_bytes",
]
