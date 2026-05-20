from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IDENTITY_BUNDLE_VERSION = 1


def _config_dir() -> Path:
    from localflight.storage.config import config_path

    return config_path().parent


def _id_path() -> Path:
    return _config_dir() / "install_id"


def _identity_bundle_path() -> Path:
    return _config_dir() / "install_identity.json"


def _identity_anchor_path() -> Path:
    home_override = os.getenv("LOCALFLIGHT_HOME") or os.getenv("HOME")
    base_home = Path(home_override) if home_override else Path.home()
    return base_home / ".localflight_identity.json"


def _activation_path() -> Path:
    return _config_dir() / "activation_token"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_uuid(value: Any) -> str:
    text = str(value or "").strip()
    try:
        return str(uuid.UUID(text))
    except Exception:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _bundle_from_install_id(install_id: str, *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    current = existing or {}
    return {
        "version": IDENTITY_BUNDLE_VERSION,
        "install_id": install_id,
        "created_at": str(current.get("created_at") or _utc_now()),
        "recovery_marker": str(current.get("recovery_marker") or f"lfr_{uuid.uuid4().hex}"),
    }


def _install_id_from_bundle(path: Path) -> tuple[str, dict[str, Any]]:
    bundle = _read_json(path)
    return _valid_uuid(bundle.get("install_id")), bundle


def _write_identity_bundle(bundle: dict[str, Any]) -> None:
    install_id = _valid_uuid(bundle.get("install_id"))
    if not install_id:
        return
    bundle = _bundle_from_install_id(install_id, existing=bundle)
    for path in (_identity_bundle_path(), _identity_anchor_path()):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except Exception:
            pass
    try:
        legacy = _id_path()
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(install_id, encoding="utf-8")
    except Exception:
        pass


def _identity_candidates() -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for path in (_identity_bundle_path(), _identity_anchor_path()):
        install_id, bundle = _install_id_from_bundle(path)
        if install_id:
            candidates.append((install_id, bundle))
    try:
        legacy_id = _valid_uuid(_id_path().read_text(encoding="utf-8").strip())
    except Exception:
        legacy_id = ""
    if legacy_id:
        candidates.append((legacy_id, {}))
    return candidates


def get_install_id() -> str:
    """Return the persistent install ID, creating it on first call."""
    for install_id, bundle in _identity_candidates():
        _write_identity_bundle(_bundle_from_install_id(install_id, existing=bundle))
        return install_id
    bundle = _bundle_from_install_id(str(uuid.uuid4()))
    _write_identity_bundle(bundle)
    return str(bundle["install_id"])


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


def clear_activation_token() -> None:
    """Explicitly remove the local relay token while keeping the install identity."""
    set_activation_token("")


def new_install_identity() -> str:
    """Create a deliberately new local install identity for operator/dev use."""
    clear_activation_token()
    bundle = _bundle_from_install_id(str(uuid.uuid4()))
    _write_identity_bundle(bundle)
    return str(bundle["install_id"])
