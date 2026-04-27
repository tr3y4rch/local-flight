"""
localflight/storage/install.py

Persistent installation identifier.

Generated once on first run and stored at ~/.localflight/install_id.
Never changes across restarts, updates, or airport switches.

Used as an anonymous token when the app calls the community relay
instead of a user-supplied AviationStack key.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path


def _id_path() -> Path:
    from localflight.storage.config import config_path
    return config_path().parent / "install_id"


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
