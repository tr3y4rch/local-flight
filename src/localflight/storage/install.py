from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path


def _config_dir() -> Path:
    from localflight.storage.config import config_path

    return config_path().parent


def _id_path() -> Path:
    return _config_dir() / "install_id"


def _activation_path() -> Path:
    return _config_dir() / "activation_token"


def get_install_id() -> str:
    """Return the persistent install ID, creating it on first call."""
    path = _id_path()
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        except Exception:
            pass
    new_id = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_id, encoding="utf-8")
    except Exception:
        pass
    return new_id


def get_install_fingerprint() -> str:
    """Return a short, stable fingerprint without exposing the relay token."""
    return hashlib.sha256(get_install_id().encode("utf-8")).hexdigest()[:12]


def get_activation_token() -> str:
    """Return a managed-install activation token from env or local storage."""
    env_token = os.getenv("LOCALFLIGHT_ACTIVATION_TOKEN", "").strip()
    if env_token:
        return env_token

    path = _activation_path()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def set_activation_token(token: str) -> None:
    token = (token or "").strip()
    path = _activation_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if token:
        path.write_text(token, encoding="utf-8")
        os.environ["LOCALFLIGHT_ACTIVATION_TOKEN"] = token
    else:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        os.environ.pop("LOCALFLIGHT_ACTIVATION_TOKEN", None)
