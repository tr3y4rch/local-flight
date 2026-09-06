from __future__ import annotations

"""
bug_reporter.py

Two entry points:
  submit_report(title, description) — user-initiated via /feedback form
  submit_crash(error_msg, ...)      — automatic crash/error reporter

Developer-owned Linear credentials are not shipped with Local Flight.
Reports are sanitized locally, then forwarded to the hosted relay's
/v1/reports gateway. The relay owns Linear secrets, team routing, rate
limits, and cross-install dedupe.
"""

import hashlib
import json
import logging
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from localflight.core.redaction import redact_sensitive as _redact_sensitive
from localflight.version import app_version as _app_version

log = logging.getLogger(__name__)

def _gui_launch_context() -> dict[str, str]:
    """Best-effort GUI shell context for Linear reports."""
    try:
        from localflight.platform.detect import detect
        from localflight.platform.gui_launcher import decide_gui_launch

        decision = decide_gui_launch(detect())
        return {
            "requested": decision.requested_mode,
            "effective": decision.effective_mode,
            "platform": decision.platform.value,
            "display": "yes" if decision.display_available else "no",
            "qt": "yes" if decision.native_available else "no",
            "fullscreen": "yes" if decision.fullscreen else "no",
            "reason": decision.reason,
        }
    except Exception:
        return {
            "requested": (os.getenv("LOCALFLIGHT_GUI_MODE") or "auto").strip().lower() or "auto",
            "effective": "unknown",
            "platform": platform.system() or "unknown",
            "display": "unknown",
            "qt": "unknown",
            "fullscreen": "unknown",
            "reason": "launch decision unavailable",
        }


def _schedule_mode_context(source: str) -> dict[str, Any]:
    source_name = str(source or "real").strip().lower() or "real"
    details: dict[str, Any] = {
        "mode_label": "unknown",
        "transport": "unknown",
        "shared_snapshot": False,
        "relay_url": "",
    }
    if source_name == "virtual":
        details.update(
            {
                "mode_label": "virtual",
                "transport": "none",
                "shared_snapshot": False,
            }
        )
        return details

    try:
        from localflight.sources.web.aviationstack_client import (
            _get_relay_url,
            _has_activation_token,
            _has_community_api_key,
            _has_enabled_byok_key,
            _relay_uses_shared_schedule,
        )

        shared_snapshot = bool(_relay_uses_shared_schedule(source_name))
        relay_url = _get_relay_url()

        if _has_enabled_byok_key():
            details.update({"mode_label": "byok", "transport": "direct"})
        elif _has_activation_token():
            details.update(
                {
                    "mode_label": "managed relay",
                    "transport": "relay",
                    "shared_snapshot": shared_snapshot,
                    "relay_url": relay_url,
                }
            )
        elif _has_community_api_key():
            details.update({"mode_label": "community direct key", "transport": "direct"})
        else:
            details.update(
                {
                    "mode_label": "Beacon Relay",
                    "transport": "relay",
                    "shared_snapshot": shared_snapshot,
                    "relay_url": relay_url,
                }
            )
        if details["transport"] == "relay" and details["shared_snapshot"]:
            details["mode_label"] = f"{details['mode_label']} (shared snapshot)"
    except Exception:
        pass
    return details


def _system_context(client_context: str = "") -> str:
    try:
        from localflight.storage.config import load_config
        cfg = load_config()
        airport = cfg.airport_iata or "?"
        source  = cfg.source or "?"
        timezone_name = getattr(cfg, "timezone", "") or "?"
        diagnostics_mode = cfg.diagnostics_mode or "unset"
        display_grace_minutes = str(getattr(cfg, "display_grace_minutes", "?"))
        display_horizon_hours = str(getattr(cfg, "display_horizon_hours", "?"))
        web_row_limit = str(getattr(cfg, "web_row_limit", "?"))
        web_rotation_seconds = str(getattr(cfg, "web_rotation_seconds", "?"))
    except Exception:
        airport = "?"
        source  = "?"
        timezone_name = "?"
        diagnostics_mode = "unset"
        display_grace_minutes = "?"
        display_horizon_hours = "?"
        web_row_limit = "?"
        web_rotation_seconds = "?"

    try:
        from localflight.storage.install import get_install_fingerprint
        install_id = get_install_fingerprint()
    except Exception:
        install_id = "unknown"

    schedule_context = _schedule_mode_context(source)
    gui_context = _gui_launch_context()

    text = (
        f"- **Version:** {_app_version()}\n"
        f"- **Install fingerprint:** `{install_id}`\n"
        f"- **OS:** {platform.platform()}\n"
        f"- **Arch:** {platform.machine()}\n"
        f"- **Python:** {sys.version.split()[0]}\n"
        f"- **Airport:** {airport}\n"
        f"- **Timezone:** {timezone_name}\n"
        f"- **Source:** {source}\n"
        f"- **Schedule mode:** {schedule_context['mode_label']}\n"
        f"- **Transport:** {schedule_context['transport']}\n"
        f"- **Shared snapshot path:** {'yes' if schedule_context['shared_snapshot'] else 'no'}\n"
        f"- **Display window:** -{display_grace_minutes}m / +{display_horizon_hours}h\n"
        f"- **Web board:** {web_row_limit} rows, rotate {web_rotation_seconds}s\n"
        f"- **Diagnostics mode:** {diagnostics_mode}\n"
        f"- **GUI requested:** {gui_context['requested']}\n"
        f"- **GUI effective shell:** {gui_context['effective']}\n"
        f"- **GUI display available:** {gui_context['display']}\n"
        f"- **GUI Qt available:** {gui_context['qt']}\n"
        f"- **GUI fullscreen:** {gui_context['fullscreen']}\n"
        f"- **GUI decision:** {gui_context['reason']}\n"
    )
    relay_url = str(schedule_context.get("relay_url") or "").strip()
    if relay_url:
        text += f"- **Relay URL:** {relay_url}\n"
    if client_context.strip():
        text += "\n**Reporter environment**\n"
        text += _redact_sensitive(client_context.strip())[:1600] + "\n"
    return text


def _auto_diagnostics_mode() -> str:
    try:
        from localflight.storage.config import load_config

        mode = str(load_config().diagnostics_mode or "").strip().lower()
    except Exception:
        mode = "unset"
    return mode if mode in {"unset", "manual", "auto", "auto_logs"} else "unset"


def _api_mode() -> str:
    try:
        from localflight.sources.web.aviationstack_client import _is_relay_mode

        return "Beacon Relay" if _is_relay_mode() else "BYOK"
    except Exception:
        return "unknown"


def _install_metadata() -> Dict[str, str]:
    try:
        from localflight.storage.install import get_activation_token, get_install_fingerprint, get_install_id

        return {
            "install_id": get_install_id(),
            "install_fingerprint": get_install_fingerprint(),
            "activation_token": get_activation_token(),
        }
    except Exception:
        return {"install_id": "", "install_fingerprint": "unknown", "activation_token": ""}


def _system_metadata() -> Dict[str, str]:
    try:
        from localflight.storage.config import load_config

        cfg = load_config()
        airport = cfg.airport_iata or "?"
        source = cfg.source or "?"
        diagnostics_mode = cfg.diagnostics_mode or "unset"
        schedule_context = _schedule_mode_context(source)
        api_mode = str(schedule_context.get("mode_label") or _api_mode())
    except Exception:
        airport = "?"
        source = "?"
        diagnostics_mode = "unset"
        api_mode = "unknown"

    install = _install_metadata()
    return {
        **install,
        "app_version": _app_version(),
        "platform": platform.system() or "unknown",
        "os": platform.platform(),
        "arch": platform.machine(),
        "python_version": sys.version.split()[0],
        "airport": airport,
        "source": source,
        "api_mode": api_mode,
        "diagnostics_mode": diagnostics_mode,
    }


def _origin_for_report(report_type: str, context: str = "", client_context: str = "") -> str:
    hint = f"{context}\n{client_context}".lower()
    if "native/gui" in hint or context.startswith("native/"):
        return "desktop"
    if "ios" in hint:
        return "ios"
    if "android" in hint:
        return "android"
    if "companion id" in hint or "mobile id" in hint or context.startswith("mobile/"):
        return "mobile"
    if context.startswith("web/"):
        return "web"
    if context.startswith("scheduler/"):
        return "scheduler"
    if context.startswith("thread/") or context == "main-thread":
        return "server"
    return "desktop" if report_type == "manual" else "server"


def _reports_url() -> str:
    from localflight.sources.web.relay_defaults import default_public_relay_url, relay_endpoint_url

    return relay_endpoint_url(default_public_relay_url(), "/v1/reports")


def _post_relay_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    import requests

    try:
        request_payload = dict(payload)
        access_token = str(request_payload.pop("activation_token", "") or "").strip()
        for key, value in tuple(request_payload.items()):
            if key not in {"install_id", "install_fingerprint"} and isinstance(value, str):
                request_payload[key] = _redact_sensitive(value)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if access_token.startswith("lfr_"):
            headers["Authorization"] = f"Bearer {access_token}"
        elif access_token:
            # Kept only for pre-license relay compatibility.
            request_payload["activation_token"] = access_token
        response = requests.post(
            _reports_url(),
            json=request_payload,
            headers=headers,
            timeout=12,
        )
        try:
            data = response.json()
        except Exception:
            data = {}
        if response.status_code >= 400:
            return {"ok": False, "error": data.get("detail") or f"Relay report HTTP {response.status_code}"}
        if isinstance(data, dict) and data.get("ok") is True:
            return data
        return {"ok": False, "error": "Relay report response was not accepted"}
    except Exception as exc:
        safe_error = _redact_sensitive(str(exc))
        log.warning("Relay report submission failed: %s", safe_error)
        return {"ok": False, "error": safe_error}


def _build_payload(
    *,
    report_type: str,
    origin: str,
    title: str = "",
    description: str = "",
    message: str = "",
    traceback_str: str = "",
    context: str = "",
    client_context: str = "",
) -> Dict[str, Any]:
    metadata = _system_metadata()
    report_context = _system_context(client_context)
    return {
        "report_type": report_type,
        "origin": origin,
        "install_id": metadata["install_id"],
        "install_fingerprint": metadata["install_fingerprint"],
        "activation_token": metadata["activation_token"],
        "title": _redact_sensitive(title)[:200],
        "description": _redact_sensitive(description)[:4000],
        "message": _redact_sensitive(message)[:500],
        "traceback": _redact_sensitive(traceback_str)[-5000:],
        "context": _redact_sensitive(context)[:120],
        "client_context": _redact_sensitive(report_context)[:2000],
        "app_version": metadata["app_version"],
        "platform": metadata["platform"],
        "os": metadata["os"],
        "arch": metadata["arch"],
        "python_version": metadata["python_version"],
        "airport": metadata["airport"],
        "source": metadata["source"],
        "api_mode": metadata["api_mode"],
        "diagnostics_mode": metadata["diagnostics_mode"],
    }


# ── Crash report deduplication ────────────────────────────────────────────────

_CRASH_DEDUP_HOURS = 6


def _crash_dedup_path() -> Path:
    try:
        from localflight.storage.config import config_path

        return config_path().parent / "bug_report_dedup.json"
    except Exception:
        return Path.home() / ".localflight" / "bug_report_dedup.json"


def _load_crash_dedup() -> dict:
    p = _crash_dedup_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _save_crash_dedup(data: dict) -> None:
    try:
        p = _crash_dedup_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _crash_fingerprint(msg: str, context: str = "") -> str:
    fingerprint_basis = f"{str(context or '').strip().lower()}|{msg[:120]}"
    return hashlib.sha1(fingerprint_basis.encode()).hexdigest()[:12]


def _already_crash_filed(fp: str) -> bool:
    filed_at = _load_crash_dedup().get(fp)
    if not filed_at:
        return False
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(filed_at)).total_seconds() / 3600
        return age_h < _CRASH_DEDUP_HOURS
    except Exception:
        return False


def _mark_crash_filed(fp: str) -> None:
    dedup = _load_crash_dedup()
    dedup[fp] = datetime.now(timezone.utc).isoformat()
    cutoff = datetime.now(timezone.utc)
    dedup = {k: v for k, v in dedup.items() if (cutoff - datetime.fromisoformat(v)).total_seconds() < 48 * 3600}
    _save_crash_dedup(dedup)


def _read_log_tail(n_lines: int = 50) -> str:
    try:
        from localflight.storage.logging_setup import log_path

        p = log_path()
        if not p.exists():
            return "(no log file this session)"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-n_lines:] if len(lines) > n_lines else lines
        return "\n".join(tail)
    except Exception as exc:
        return f"(could not read log: {exc})"


def submit_crash(
    error_msg: str,
    traceback_str: str = "",
    context: str = "app",
    client_context: str = "",
) -> dict:
    """
    Auto-file a crash/error report through the hosted relay.
    Deduped per 6h by crash context plus error fingerprint. Never raises.
    """
    try:
        diagnostics_mode = _auto_diagnostics_mode()
        if diagnostics_mode in {"unset", "manual"}:
            return {"ok": False, "error": "automatic diagnostics disabled"}

        fp = _crash_fingerprint(error_msg, context=context)
        if _already_crash_filed(fp):
            return {"ok": False, "error": "duplicate (deduped)"}

        log_tail = _read_log_tail(50) if diagnostics_mode == "auto_logs" else ""
        payload = _build_payload(
            report_type="crash",
            origin=_origin_for_report("crash", context, client_context),
            message=error_msg,
            description=log_tail,
            traceback_str=traceback_str,
            context=context,
            client_context=client_context,
        )
        result = _post_relay_report(payload)
        if result.get("ok"):
            _mark_crash_filed(fp)
        return result
    except Exception as exc:
        safe_error = _redact_sensitive(str(exc))
        log.warning("Auto crash report failed (non-fatal): %s", safe_error)
        return {"ok": False, "error": safe_error}


def submit_report(title: str, description: str = "", client_context: str = "") -> dict:
    """
    File a user-submitted bug report / feedback issue through the hosted relay.

    Returns {"ok": True, "url": "..."} or {"ok": False, "error": "..."}.
    Never raises.
    """
    if not title or not title.strip():
        return {"ok": False, "error": "Title is required"}

    payload = _build_payload(
        report_type="manual",
        origin=_origin_for_report("manual", "", client_context),
        title=title.strip(),
        description=description.strip(),
        client_context=client_context,
    )
    return _post_relay_report(payload)
