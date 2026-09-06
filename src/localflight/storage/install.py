from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localflight.storage.private_files import ensure_private_dir, ensure_private_file, write_private_text


IDENTITY_BUNDLE_VERSION = 1
RELAY_ACCESS_STATE_VERSION = 1
RELAY_LOCAL_STATES = {"none", "checking", "active", "inactive", "unreachable", "release_pending"}
LICENSE_ACCESS_STATES = {"active", "suspended", "refunded", "revoked"}


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


def _relay_access_state_path() -> Path:
    return _config_dir() / "relay_access.json"


def _relay_access_mode_path() -> Path:
    return _config_dir() / "relay_access_mode"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_uuid(value: Any) -> str:
    text = str(value or "").strip()
    try:
        return str(uuid.UUID(text))
    except Exception:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    ensure_private_file(path)
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
            write_private_text(path, json.dumps(bundle, indent=2, sort_keys=True) + "\n")
        except Exception:
            pass
    try:
        legacy = _id_path()
        write_private_text(legacy, install_id)
    except Exception:
        pass


def _identity_candidates() -> list[tuple[str, dict[str, Any]]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for path in (_identity_bundle_path(), _identity_anchor_path()):
        install_id, bundle = _install_id_from_bundle(path)
        if install_id:
            candidates.append((install_id, bundle))
    try:
        ensure_private_file(_id_path())
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


def _read_activation_file() -> str:
    path = _activation_path()
    if not path.exists():
        return ""
    try:
        ensure_private_file(path)
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _remove_legacy_activation_copy() -> None:
    """Remove the old persisted .env copy after credential-file migration."""
    os.environ.pop("LOCALFLIGHT_ACTIVATION_TOKEN", None)
    try:
        from localflight.storage.provider_keys import env_path, read_env, write_env

        path = env_path()
        values = read_env(path)
        if "LOCALFLIGHT_ACTIVATION_TOKEN" not in values:
            return
        values.pop("LOCALFLIGHT_ACTIVATION_TOKEN", None)
        write_env(values, removed={"LOCALFLIGHT_ACTIVATION_TOKEN"}, path=path)
    except Exception:
        # The credential file remains authoritative even if an old read-only
        # source-checkout .env cannot be rewritten.
        pass


def get_stored_activation_token() -> str:
    """Return the credential even while a release retry is pending.

    Ordinary Relay clients must use :func:`get_activation_token`, which blocks
    runtime use while the selected route is free.
    """
    token = _read_activation_file()
    if token:
        _remove_legacy_activation_copy()
        return token
    legacy = os.getenv("LOCALFLIGHT_ACTIVATION_TOKEN", "").strip()
    if not legacy:
        try:
            from localflight.storage.provider_keys import env_path, read_env

            legacy = str(read_env(env_path()).get("LOCALFLIGHT_ACTIVATION_TOKEN") or "").strip()
        except Exception:
            legacy = ""
    if not legacy:
        return ""
    write_private_text(_activation_path(), legacy)
    _remove_legacy_activation_copy()
    return legacy


def get_activation_token() -> str:
    """Return the usable Relay credential from its single private file."""
    token = get_stored_activation_token()
    if not token:
        return ""
    try:
        from localflight.storage.route_transition import runtime_route

        if runtime_route() != "relay":
            return ""
    except Exception:
        # Fail closed if the authoritative route cannot be established.
        return ""
    summary = get_relay_access_summary()
    if token.startswith("lfr_"):
        if summary.get("relay_state") != "active" or summary.get("access_state") != "active":
            return ""
    elif token.startswith("lfm_"):
        explicit = os.getenv("LOCALFLIGHT_ENABLE_LEGACY_RELAY_COMPAT", "").strip().lower()
        legacy_enabled = explicit in {"1", "true", "yes", "on"} or (
            not explicit and os.getenv("RELAY_ACCESS_MODE", "").strip().lower() == "legacy"
        )
        if not legacy_enabled:
            return ""
    else:
        return ""
    if summary.get("relay_state") == "release_pending":
        return ""
    return token


def activation_storage_ready() -> bool:
    """Verify owner-protected credential storage before consuming an activation."""
    path = _config_dir() / f".activation_probe_{uuid.uuid4().hex}"
    try:
        write_private_text(path, "ready\n")
        return path.read_text(encoding="utf-8").strip() == "ready"
    except Exception:
        return False
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def set_activation_token(token: str) -> None:
    token = (token or "").strip()
    path = _activation_path()
    ensure_private_dir(path.parent)
    if token:
        write_private_text(path, token)
    else:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    _remove_legacy_activation_copy()


def get_relay_access_summary() -> dict[str, Any]:
    """Return cached, non-secret Relay Access state for setup/settings UI."""
    raw = _read_json(_relay_access_state_path()) if _relay_access_state_path().exists() else {}
    relay_state = str(raw.get("relay_state") or "none").strip().lower()
    if relay_state not in RELAY_LOCAL_STATES:
        relay_state = "none"
    access_state = str(raw.get("access_state") or "").strip().lower()
    if access_state not in LICENSE_ACCESS_STATES:
        access_state = ""
    token = _read_activation_file()
    if token and relay_state == "none":
        relay_state = "inactive"
    if not token and relay_state in {"active", "release_pending"}:
        relay_state = "none"
    try:
        release_retry_after_s = max(0, int(raw.get("release_retry_after_s") or 0))
    except Exception:
        release_retry_after_s = 0
    return {
        "relay_state": relay_state,
        "access_state": access_state,
        "reason_code": str(raw.get("reason_code") or "")[:80],
        "license_reference": str(raw.get("license_reference") or "")[:80],
        "masked_key_reference": str(raw.get("masked_key_reference") or "")[:40],
        "purchase_source": str(raw.get("purchase_source") or "")[:40],
        "current_main_device_description": str(raw.get("current_main_device_description") or "")[:120],
        "last_successful_check_time": str(raw.get("last_successful_check_time") or "")[:64],
        "release_retry_after_s": release_retry_after_s,
        "release_retry_not_before": str(raw.get("release_retry_not_before") or "")[:64],
        "credential_reference": f"{token[:12]}…" if token else "",
        "credential_present": bool(token),
    }


def update_relay_access_summary(**changes: Any) -> dict[str, Any]:
    current = get_relay_access_summary()
    for key in (
        "relay_state",
        "access_state",
        "reason_code",
        "license_reference",
        "masked_key_reference",
        "purchase_source",
        "current_main_device_description",
        "last_successful_check_time",
        "release_retry_not_before",
    ):
        if key in changes:
            current[key] = str(changes[key] or "")
    if "release_retry_after_s" in changes:
        try:
            current["release_retry_after_s"] = max(0, int(changes["release_retry_after_s"] or 0))
        except Exception:
            current["release_retry_after_s"] = 0
    if current["relay_state"] not in RELAY_LOCAL_STATES:
        current["relay_state"] = "inactive"
    if current["access_state"] not in LICENSE_ACCESS_STATES:
        current["access_state"] = ""
    stored = {
        "version": RELAY_ACCESS_STATE_VERSION,
        **{key: current[key] for key in (
            "relay_state",
            "access_state",
            "reason_code",
            "license_reference",
            "masked_key_reference",
            "purchase_source",
            "current_main_device_description",
            "last_successful_check_time",
            "release_retry_after_s",
            "release_retry_not_before",
        )},
    }
    try:
        write_private_text(_relay_access_state_path(), json.dumps(stored, indent=2, sort_keys=True) + "\n")
    except Exception:
        pass
    return get_relay_access_summary()


def get_relay_access_mode() -> str:
    """Return the non-secret relay product lane associated with this install."""
    env_mode = os.getenv("LOCALFLIGHT_RELAY_ACCESS_MODE", "").strip().lower()
    if env_mode in {"community", "managed", "mobile_standalone"}:
        return env_mode
    path = _relay_access_mode_path()
    try:
        ensure_private_file(path)
        mode = path.read_text(encoding="utf-8").strip().lower()
    except Exception:
        return ""
    return mode if mode in {"community", "managed", "mobile_standalone"} else ""


def set_relay_access_mode(mode: str) -> None:
    clean = str(mode or "").strip().lower()
    path = _relay_access_mode_path()
    if clean in {"community", "managed", "mobile_standalone"}:
        ensure_private_dir(path.parent)
        write_private_text(path, clean)
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def clear_activation_token() -> None:
    """Explicitly remove the local relay token while keeping the install identity."""
    set_activation_token("")
    set_relay_access_mode("")
    update_relay_access_summary(
        relay_state="none",
        access_state="",
        reason_code="",
        current_main_device_description="",
        release_retry_after_s=0,
        release_retry_not_before="",
    )


def new_install_identity() -> str:
    """Create a deliberately new local install identity for operator/dev use."""
    clear_activation_token()
    bundle = _bundle_from_install_id(str(uuid.uuid4()))
    _write_identity_bundle(bundle)
    return str(bundle["install_id"])
