from __future__ import annotations

import base64
import json
import secrets
from typing import Any


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(str(value or "").encode("ascii"), validate=True)


def _b64url_decode(value: str) -> bytes:
    clean = str(value or "").strip()
    padding = "=" * (-len(clean) % 4)
    return base64.urlsafe_b64decode((clean + padding).encode("ascii"))


def remote_aad(*, install_ref: str, grant_ref: str, request_id: str, direction: str) -> bytes:
    payload = {
        "direction": str(direction or ""),
        "grant_ref": str(grant_ref or ""),
        "install_ref": str(install_ref or ""),
        "request_id": str(request_id or ""),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def encrypt_envelope(payload: dict[str, Any], *, remote_key: str, aad: bytes) -> dict[str, str]:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception as exc:
        raise RuntimeError("cryptography is required for Remote Companion AES-GCM") from exc

    key = _b64url_decode(remote_key)
    if len(key) != 32:
        raise ValueError("Remote Companion key must be 32 bytes")
    nonce = secrets.token_bytes(12)
    plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sealed = AESGCM(key).encrypt(nonce, plaintext, aad)
    return {
        "alg": "A256GCM",
        "nonce": _b64(nonce),
        "ciphertext": _b64(sealed[:-16]),
        "tag": _b64(sealed[-16:]),
    }


def decrypt_envelope(envelope: dict[str, Any], *, remote_key: str, aad: bytes) -> dict[str, Any]:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception as exc:
        raise RuntimeError("cryptography is required for Remote Companion AES-GCM") from exc

    if str(envelope.get("alg") or "A256GCM") != "A256GCM":
        raise ValueError("Unsupported Remote Companion envelope algorithm")
    key = _b64url_decode(remote_key)
    if len(key) != 32:
        raise ValueError("Remote Companion key must be 32 bytes")
    nonce = _b64decode(str(envelope.get("nonce") or ""))
    if len(nonce) != 12:
        raise ValueError("Remote Companion nonce must be 12 bytes")
    ciphertext = _b64decode(str(envelope.get("ciphertext") or ""))
    tag = _b64decode(str(envelope.get("tag") or ""))
    if len(tag) != 16:
        raise ValueError("Remote Companion tag must be 16 bytes")
    plaintext = AESGCM(key).decrypt(nonce, ciphertext + tag, aad)
    data = json.loads(plaintext.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Remote Companion payload must be an object")
    return data


__all__ = ["decrypt_envelope", "encrypt_envelope", "remote_aad"]
