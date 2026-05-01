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
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)

_SECRET_PATTERNS = (
    (re.compile(r"(AVIATIONSTACK_API_KEY|RAPIDAPI_KEY|OPENSKY_CLIENT_SECRET|LINEAR_API_KEY|LINEAR_REPORTER_API_KEY)=\S+", re.I), r"\1=[redacted]"),
    (re.compile(r"(access_key=)[^&\s]+", re.I), r"\1[redacted]"),
    (re.compile(r"(X-RapidAPI-Key['\":\s]+)[A-Za-z0-9._-]+", re.I), r"\1[redacted]"),
    (re.compile(r"lin_api_[A-Za-z0-9_]+", re.I), "[redacted-linear-token]"),
    (re.compile(r"lfm_[A-Za-z0-9._-]+", re.I), "[redacted-activation-token]"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "[redacted-uuid]"),
    (re.compile(r"\b10\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b"), r"10.\1.\2.x"),
    (re.compile(r"\b192\.168\.(\d{1,3})\.(\d{1,3})\b"), r"192.168.\1.x"),
    (re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.(\d{1,3})\.(\d{1,3})\b"), r"172.\1.\2.x"),
)


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("localflight")
    except Exception:
        return "unknown"


def _redact_sensitive(text: str) -> str:
    redacted = text or ""
    for pattern, repl in _SECRET_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return redacted


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

        return "community relay" if _is_relay_mode() else "byok"
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
    except Exception:
        airport = "?"
        source = "?"
        diagnostics_mode = "unset"

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
        "api_mode": _api_mode(),
        "diagnostics_mode": diagnostics_mode,
    }


def _origin_for_report(report_type: str, context: str = "", client_context: str = "") -> str:
    hint = f"{context}\n{client_context}".lower()
    if "ios" in hint:
        return "ios"
    if "companion id" in hint or context.startswith("mobile/"):
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
        response = requests.post(
            _reports_url(),
            json=payload,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
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
        log.warning("Relay report submission failed: %s", exc)
        return {"ok": False, "error": str(exc)}


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
        "client_context": _redact_sensitive(client_context)[:2000],
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


def _crash_fingerprint(msg: str) -> str:
    return hashlib.sha1(msg[:120].encode()).hexdigest()[:12]


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
    Deduped per 6h by error fingerprint. Never raises.
    """
    try:
        diagnostics_mode = _auto_diagnostics_mode()
        if diagnostics_mode in {"unset", "manual"}:
            return {"ok": False, "error": "automatic diagnostics disabled"}

        fp = _crash_fingerprint(error_msg)
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
        log.warning("Auto crash report failed (non-fatal): %s", exc)
        return {"ok": False, "error": str(exc)}


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
