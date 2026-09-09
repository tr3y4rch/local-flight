from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Any

import requests

from localflight.version import app_version as _app_version

from localflight.sources.web.relay_defaults import (
    default_public_relay_url,
    relay_endpoint_url,
    validate_public_relay_url,
)
from localflight.storage.install import (
    AUTHORIZED_ACCESS_STATES,
    get_install_fingerprint,
    get_install_id,
    get_stored_activation_token,
    set_activation_token,
    set_relay_access_mode,
)


_AUTO_REPAIR_COOLDOWN_S = 30 * 60
_lock = threading.RLock()
_last_auto_attempt = 0.0
_last_auto_result: dict[str, Any] | None = None
_last_auto_key: tuple[str, str, str, str] | None = None


def legacy_relay_compat_enabled() -> bool:
    """Keep pre-license auto-provisioning behind an explicit migration flag."""
    explicit = os.getenv("LOCALFLIGHT_ENABLE_LEGACY_RELAY_COMPAT", "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "on"}
    return os.getenv("RELAY_ACCESS_MODE", "").strip().lower() == "legacy"


def _metadata() -> dict[str, Any]:
    try:
        from localflight.sources.web.relay_heartbeat import relay_client_metadata

        return relay_client_metadata()
    except Exception:
        return {"app_version": _app_version(), "client_kind": "desktop"}


def _json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _retry_after(response: Any) -> int | None:
    try:
        value = int(str(response.headers.get("Retry-After") or "").strip())
    except Exception:
        return None
    return max(1, value)


def _status_code(response: Any, payload: dict[str, Any]) -> str:
    status = int(getattr(response, "status_code", 0) or 0)
    detail = payload.get("detail") if isinstance(payload, dict) else None
    code = ""
    if isinstance(detail, dict):
        code = str(detail.get("code") or "").strip().lower()
    if not code:
        code = str(payload.get("code") or payload.get("reason_code") or "").strip().lower()
    aliases = {
        "access_rate_limited": "rate_limited",
        "relay_credential_required": "token_invalid",
        "license_not_found": "token_invalid",
        "license_inactive": "license_inactive",
        "invalid_challenge": "token_invalid",
    }
    if code:
        return aliases.get(code, code)
    if status == 429:
        return "rate_limited"
    if status in {401, 403}:
        return "token_invalid"
    if status >= 500:
        return "relay_unreachable"
    return "relay_error"


def _failure(code: str, *, response: Any = None, retry_after_s: int | None = None) -> dict[str, Any]:
    messages = {
        "rate_limited": "The relay is cooling down this request. Local Flight will wait before trying again.",
        "manual_review": "The relay paused automatic linking for safety. Choose Retry later, VATSIM, or your own provider keys.",
        "token_bound_elsewhere": "The stored relay link belongs to another Local Flight install. Request a repaired link for this install.",
        "token_invalid": "The saved relay link is no longer valid. Local Flight can request a repaired link for this install.",
        "license_inactive": "Relay Access is not active for this desktop.",
        "past_due": "Relay Access has a billing problem. Update payment with your provider, or choose BYOK or VATSIM.",
        "expired": "Relay Access has ended. Renew it with your provider, enter a new key, or choose BYOK or VATSIM.",
        "relay_unreachable": "Beacon Relay cannot be reached right now. Your local setup has not been changed.",
        "relay_link_required": "This Local Flight install still needs an active Beacon Relay credential.",
        "relay_error": "Beacon Relay could not verify this install.",
    }
    result: dict[str, Any] = {
        "ok": False,
        "linked": False,
        "status": code,
        "error": messages.get(code, messages["relay_error"]),
    }
    retry = retry_after_s if retry_after_s is not None else (_retry_after(response) if response is not None else None)
    if retry:
        result["retry_after_s"] = int(retry)
    return result


def _verified_payload(payload: dict[str, Any], token: str) -> dict[str, Any]:
    prefix = str(payload.get("token_prefix") or payload.get("activation_token_prefix") or token[:10])
    result = {
        "ok": True,
        "linked": True,
        "status": "ok",
        "known_install": bool(payload.get("known_install", True)),
        "can_reissue": bool(payload.get("can_reissue", True)),
        "token_prefix": prefix,
        "activation_token_prefix": prefix,
        "activation_token_present": True,
    }
    for key in (
        "founder",
        "founder_claim_available",
        "founder_bridge_expires_at",
        "entitlement_kind",
        "effective_state",
        "current_period_end",
        "grace_expires_at",
        "auto_renews",
    ):
        if key in payload:
            result[key] = payload[key]
    return result


def _claim_founder_access(
    relay_url: str,
    legacy_token: str,
    *,
    display_name: str,
    timeout_s: float,
) -> dict[str, Any]:
    """Atomically exchange one eligible legacy credential for its founder receiver."""
    install_id = get_install_id()
    headers = {"Accept": "application/json", "Authorization": f"Bearer {legacy_token}"}
    claim = requests.post(
        relay_endpoint_url(relay_url, "/v1/access/founder/claim"),
        json={"install_id": install_id, "device_name": display_name[:80]},
        headers=headers,
        timeout=timeout_s,
    )
    claim_payload = _json(claim)
    if claim.status_code >= 400:
        return _failure(_status_code(claim, claim_payload), response=claim)
    credential = str(claim_payload.get("credential") or "").strip()
    if (
        not credential.startswith("lfr_")
        or claim_payload.get("ok") is not True
        or str(claim_payload.get("activation_state") or "") != "pending_commit"
    ):
        return _failure("relay_error")

    try:
        set_activation_token(credential)
        if get_stored_activation_token() != credential:
            raise OSError("credential verification failed")
        commit = requests.post(
            relay_endpoint_url(relay_url, "/v1/access/activate/commit"),
            json={"install_id": install_id},
            headers={"Accept": "application/json", "Authorization": f"Bearer {credential}"},
            timeout=timeout_s,
        )
        commit_payload = _json(commit)
        if (
            commit.status_code >= 400
            or commit_payload.get("ok") is not True
            or commit_payload.get("activated") is not True
            or str(commit_payload.get("activation_state") or "") != "active"
        ):
            raise RuntimeError(_status_code(commit, commit_payload))
    except Exception as exc:
        # The old credential remains authoritative during the migration bridge.
        # Restoring it prevents a failed network commit from stranding the host.
        set_activation_token(legacy_token)
        code = str(exc) if str(exc) in {
            "rate_limited", "relay_unreachable", "license_inactive", "token_invalid"
        } else "relay_unreachable"
        return _failure(code)

    set_relay_access_mode("managed")
    return {
        **_verified_payload(commit_payload, credential),
        "founder": True,
        "founder_migrated": True,
        "founder_claim_available": False,
    }


def _verify_token(relay_url: str, token: str, *, timeout_s: float) -> tuple[dict[str, Any], Any]:
    params = {"install_id": get_install_id(), **_metadata()}
    headers = {"Accept": "application/json"}
    if token.startswith("lfr_"):
        headers["Authorization"] = f"Bearer {token}"
        endpoint = "/v1/access/status"
    else:
        # Compatibility for pre-license managed tokens only. Portable Relay
        # device credentials never travel in a URL.
        params["activation_token"] = token
        endpoint = "/v1/client/status"
    response = requests.get(
        relay_endpoint_url(relay_url, endpoint),
        params=params,
        headers=headers,
        timeout=timeout_s,
    )
    payload = _json(response)
    valid = payload.get("ok") is True
    if token.startswith("lfr_"):
        valid = (
            valid
            and payload.get("active") is True
            and str(payload.get("access_state") or "").strip().lower() in AUTHORIZED_ACCESS_STATES
        )
    if response.status_code < 400 and valid:
        return _verified_payload(payload, token), response
    if response.status_code < 400:
        return _failure(_status_code(response, payload) if payload else "relay_error", response=response), response
    return _failure(_status_code(response, payload), response=response), response


def ensure_relay_link(
    *,
    relay_url: str = "",
    display_name: str = "Local Flight device",
    airport_iata: str = "",
    airport_icao: str = "",
    requested_mode: str = "community",
    activation_token: str = "",
    force: bool = False,
    timeout_s: float = 12.0,
) -> dict[str, Any]:
    """Verify or repair the local relay link without activation-request spam."""
    global _last_auto_attempt, _last_auto_result, _last_auto_key

    try:
        relay_root = validate_public_relay_url(relay_url or default_public_relay_url())
    except ValueError:
        return _failure("relay_unreachable")

    with _lock:
        now = time.monotonic()
        # Read the stored value even when runtime use is route-gated. An LFRA
        # credential is never replaced by the legacy repair endpoint.
        stored_token = get_stored_activation_token().strip()
        token = str(activation_token or stored_token).strip()
        token_marker = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else "none"
        attempt_key = (relay_root, get_install_id(), str(requested_mode or "community").strip().lower(), token_marker)
        if (
            not force
            and _last_auto_result is not None
            and not _last_auto_result.get("linked")
            and _last_auto_key == attempt_key
            and now - _last_auto_attempt < _AUTO_REPAIR_COOLDOWN_S
        ):
            result = dict(_last_auto_result)
            result.setdefault("retry_after_s", max(1, int(_AUTO_REPAIR_COOLDOWN_S - (now - _last_auto_attempt))))
            return result

        _last_auto_attempt = now
        _last_auto_key = attempt_key
        if token:
            try:
                verified, _response = _verify_token(relay_root, token, timeout_s=timeout_s)
            except requests.RequestException:
                verified = _failure("relay_unreachable")
            if verified.get("linked"):
                if token.startswith("lfm_") and verified.get("founder_claim_available"):
                    try:
                        migrated = _claim_founder_access(
                            relay_root,
                            token,
                            display_name=str(display_name or "Local Flight device"),
                            timeout_s=timeout_s,
                        )
                    except requests.RequestException:
                        migrated = _failure("relay_unreachable")
                    if migrated.get("linked"):
                        _last_auto_result = migrated
                        return dict(migrated)
                    # Do not cut off an eligible bridge because its one-time
                    # credential upgrade could not finish during this check.
                    verified["founder_migration_status"] = str(
                        migrated.get("status") or "relay_unreachable"
                    )
                if token != stored_token:
                    set_activation_token(token)
                set_relay_access_mode(requested_mode)
                _last_auto_result = verified
                return dict(verified)
            if token.startswith("lfr_"):
                _last_auto_result = verified
                return dict(verified)
            if verified.get("status") not in {"token_invalid", "token_bound_elsewhere"}:
                _last_auto_result = verified
                return dict(verified)

        if not legacy_relay_compat_enabled():
            result = _failure("relay_link_required")
            _last_auto_result = result
            return dict(result)

        try:
            response = requests.post(
                relay_endpoint_url(relay_root, "/v1/activate"),
                json={
                    "install_id": get_install_id(),
                    "install_fingerprint": get_install_fingerprint(),
                    "display_name": str(display_name or "Local Flight device")[:80],
                    "requested_mode": str(requested_mode or "community")[:20],
                    "app_version": _app_version(),
                    "airport_iata": str(airport_iata or "").strip().upper()[:4],
                    "airport_icao": str(airport_icao or "").strip().upper()[:4],
                },
                headers={"Accept": "application/json"},
                timeout=timeout_s,
            )
        except requests.RequestException:
            result = _failure("relay_unreachable")
            _last_auto_result = result
            return dict(result)

        payload = _json(response)
        if response.status_code >= 400:
            result = _failure(_status_code(response, payload), response=response)
            _last_auto_result = result
            return dict(result)
        if str(payload.get("status") or "").strip().lower() == "manual_review":
            result = _failure("manual_review", response=response)
            _last_auto_result = result
            return dict(result)
        issued_token = str(payload.get("activation_token") or "").strip()
        if not issued_token.startswith("lfm_"):
            result = _failure("relay_link_required")
            _last_auto_result = result
            return dict(result)

        # Re-check under the same lock before writing: an LFRA credential always
        # wins over an obsolete auto-issued token.
        if get_stored_activation_token().startswith("lfr_"):
            result = _failure("token_invalid")
            _last_auto_result = result
            return dict(result)
        set_activation_token(issued_token)
        set_relay_access_mode(requested_mode)
        try:
            from localflight.sources.web.aviationstack_client import clear_relay_cooldown

            clear_relay_cooldown("managed")
        except Exception:
            pass
        try:
            verified, _verify_response = _verify_token(relay_root, issued_token, timeout_s=timeout_s)
        except requests.RequestException:
            verified = _failure("relay_unreachable")
        _last_auto_result = verified
        return dict(verified)


def reset_auto_repair_state() -> None:
    global _last_auto_attempt, _last_auto_result, _last_auto_key
    with _lock:
        _last_auto_attempt = 0.0
        _last_auto_result = None
        _last_auto_key = None
