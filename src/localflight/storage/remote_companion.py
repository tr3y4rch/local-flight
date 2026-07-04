from __future__ import annotations

import base64
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from localflight.storage.config import config_path
from localflight.storage.install import get_install_fingerprint

REMOTE_INVITE_TTL_SECONDS = 10 * 60


def _state_path() -> Path:
    return config_path().parent / "remote_companion.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _read_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"version": 1, "invites": {}, "grants": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    invites = raw.get("invites")
    grants = raw.get("grants")
    return {
        "version": 1,
        "invites": invites if isinstance(invites, dict) else {},
        "grants": grants if isinstance(grants, dict) else {},
    }


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    clean = str(value or "").strip()
    padding = "=" * (-len(clean) % 4)
    return base64.urlsafe_b64decode((clean + padding).encode("ascii"))


def validate_remote_key(value: str) -> str:
    key = str(value or "").strip()
    try:
        raw = _b64url_decode(key)
    except Exception as exc:
        raise ValueError("Remote key is not valid base64url") from exc
    if len(raw) != 32:
        raise ValueError("Remote key must be a 32-byte AES-256 key")
    return _b64url(raw)


def create_remote_invite(*, relay_url: str, ttl_seconds: int = REMOTE_INVITE_TTL_SECONDS) -> dict[str, Any]:
    state = prune_remote_invites()
    invite_id = "rci_" + secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:18]
    invite = {
        "invite_id": invite_id,
        "relay_url": str(relay_url or "").rstrip("/"),
        "install_ref": get_install_fingerprint(),
        "remote_key": _b64url(secrets.token_bytes(32)),
        "created_at": _utc_now(),
        "expires_at": _iso_after(max(60, min(int(ttl_seconds), 60 * 60))),
    }
    state["invites"][invite_id] = invite
    _write_state(state)
    return invite


def prune_remote_invites() -> dict[str, Any]:
    state = _read_state()
    now = time.time()
    fresh: dict[str, Any] = {}
    for invite_id, invite in state.get("invites", {}).items():
        try:
            expires = datetime.fromisoformat(str(invite.get("expires_at") or ""))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires.timestamp() > now:
                fresh[str(invite_id)] = invite
        except Exception:
            continue
    if fresh != state.get("invites", {}):
        state["invites"] = fresh
        _write_state(state)
    return state


def get_remote_invite(invite_id: str) -> dict[str, Any] | None:
    invite_id = str(invite_id or "").strip()
    if not invite_id:
        return None
    state = prune_remote_invites()
    invite = state.get("invites", {}).get(invite_id)
    return invite if isinstance(invite, dict) else None


def consume_remote_invite(invite_id: str) -> dict[str, Any] | None:
    invite_id = str(invite_id or "").strip()
    state = prune_remote_invites()
    invite = state.get("invites", {}).pop(invite_id, None)
    _write_state(state)
    return invite if isinstance(invite, dict) else None


def create_remote_grant_from_invite(
    invite: dict[str, Any],
    *,
    companion_id: str,
    client_name: str = "",
    mobile_os: str = "",
    device_type: str = "",
    app_version: str = "",
) -> dict[str, Any]:
    key = validate_remote_key(str(invite.get("remote_key") or ""))
    grant_ref = "rcg_" + secrets.token_urlsafe(18).replace("-", "").replace("_", "")[:24]
    now = _utc_now()
    grant = {
        "grant_ref": grant_ref,
        "companion_id": str(companion_id or "").strip()[:120],
        "client_name": str(client_name or "").strip()[:120],
        "mobile_os": str(mobile_os or "").strip()[:40],
        "device_type": str(device_type or "").strip()[:40],
        "app_version": str(app_version or "").strip()[:40],
        "relay_url": str(invite.get("relay_url") or "").rstrip("/"),
        "install_ref": str(invite.get("install_ref") or get_install_fingerprint()).strip(),
        "remote_key": key,
        "created_at": now,
        "last_seen_remote_at": None,
        "revoked_at": None,
    }
    state = _read_state()
    state["grants"][grant_ref] = grant
    _write_state(state)
    return grant


def list_remote_grants(*, include_revoked: bool = True) -> list[dict[str, Any]]:
    state = _read_state()
    grants = []
    for grant in state.get("grants", {}).values():
        if not isinstance(grant, dict):
            continue
        if not include_revoked and grant.get("revoked_at"):
            continue
        grants.append(dict(grant))
    grants.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return grants


def get_remote_grant(grant_ref: str) -> dict[str, Any] | None:
    grant_ref = str(grant_ref or "").strip()
    if not grant_ref:
        return None
    grant = _read_state().get("grants", {}).get(grant_ref)
    return dict(grant) if isinstance(grant, dict) else None


def revoke_remote_grant(grant_ref: str) -> dict[str, Any] | None:
    grant_ref = str(grant_ref or "").strip()
    state = _read_state()
    grant = state.get("grants", {}).get(grant_ref)
    if not isinstance(grant, dict):
        return None
    if not grant.get("revoked_at"):
        grant["revoked_at"] = _utc_now()
    state["grants"][grant_ref] = grant
    _write_state(state)
    return dict(grant)


def mark_remote_grant_used(grant_ref: str) -> None:
    state = _read_state()
    grant = state.get("grants", {}).get(str(grant_ref or "").strip())
    if not isinstance(grant, dict):
        return
    grant["last_seen_remote_at"] = _utc_now()
    state["grants"][str(grant_ref).strip()] = grant
    _write_state(state)


def public_remote_grant(grant: dict[str, Any]) -> dict[str, Any]:
    return {
        "grant_ref": str(grant.get("grant_ref") or ""),
        "companion_id": str(grant.get("companion_id") or ""),
        "client_name": str(grant.get("client_name") or ""),
        "mobile_os": str(grant.get("mobile_os") or ""),
        "device_type": str(grant.get("device_type") or ""),
        "app_version": str(grant.get("app_version") or ""),
        "relay_url": str(grant.get("relay_url") or ""),
        "install_ref": str(grant.get("install_ref") or ""),
        "created_at": grant.get("created_at"),
        "last_seen_remote_at": grant.get("last_seen_remote_at"),
        "revoked_at": grant.get("revoked_at"),
    }


__all__ = [
    "REMOTE_INVITE_TTL_SECONDS",
    "consume_remote_invite",
    "create_remote_grant_from_invite",
    "create_remote_invite",
    "get_remote_grant",
    "get_remote_invite",
    "list_remote_grants",
    "mark_remote_grant_used",
    "prune_remote_invites",
    "public_remote_grant",
    "revoke_remote_grant",
    "validate_remote_key",
]
