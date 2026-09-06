from __future__ import annotations

import hashlib
import hmac
import base64
import re
import secrets

from .models import AccessConfigurationError, InvalidLicenseKey


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_KEY_BODY_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{27}$")


def require_secret(value: str, label: str) -> bytes:
    clean = (value or "").strip()
    if len(clean) < 24:
        raise AccessConfigurationError(f"{label} must contain at least 24 characters")
    return clean.encode("utf-8")


def keyed_hash(secret: bytes, namespace: str, value: str) -> str:
    return hmac.new(secret, f"{namespace}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def _crockford_encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    width = (len(raw) * 8 + 4) // 5
    encoded = []
    for _ in range(width):
        encoded.append(_CROCKFORD[number & 31])
        number >>= 5
    return "".join(reversed(encoded)).rjust(width, "0")


def _checksum(body: str) -> str:
    total = sum((index + 1) * _CROCKFORD.index(char) for index, char in enumerate(body))
    return _CROCKFORD[total % len(_CROCKFORD)]


def derive_license_key(secret: bytes, license_id: str, key_version: int) -> str:
    material = hmac.new(
        secret,
        f"license-key:{license_id}:{key_version}".encode("utf-8"),
        hashlib.sha256,
    ).digest()[:16]
    body = _crockford_encode(material)
    body = f"{body}{_checksum(body)}"
    groups = "-".join(body[index:index + 4] for index in range(0, len(body), 4))
    return f"LFRA-{groups}"


def normalize_license_key(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]", "", value or "").upper()
    if not clean.startswith("LFRA"):
        raise InvalidLicenseKey("Relay Access key is not valid")
    body = clean[4:]
    if not _KEY_BODY_RE.fullmatch(body) or _checksum(body[:-1]) != body[-1]:
        raise InvalidLicenseKey("Relay Access key is not valid")
    return f"LFRA{body}"


def license_key_hash(secret: bytes, value: str) -> str:
    return keyed_hash(secret, "license-key", normalize_license_key(value))


def generated_license_key_hash(secret: bytes, value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return keyed_hash(secret, "license-key", normalized)


def random_token(prefix: str, nbytes: int = 32) -> str:
    return f"{prefix}{secrets.token_urlsafe(nbytes)}"


def seal_value(secret: bytes, namespace: str, value: str) -> str:
    """Encrypt a recoverable contact value without persisting plaintext."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise AccessConfigurationError("Encrypted Relay Access contacts are unavailable") from exc
    key = hmac.new(secret, f"sealed:{namespace}".encode("utf-8"), hashlib.sha256).digest()
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), namespace.encode("utf-8"))
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def open_value(secret: bytes, namespace: str, value: str) -> str:
    if not value:
        return ""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        if len(raw) < 29:
            raise ValueError("sealed value is too short")
        key = hmac.new(secret, f"sealed:{namespace}".encode("utf-8"), hashlib.sha256).digest()
        return AESGCM(key).decrypt(raw[:12], raw[12:], namespace.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        raise AccessConfigurationError("Encrypted Relay Access contact could not be opened") from exc
