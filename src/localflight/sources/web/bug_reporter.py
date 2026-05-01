from __future__ import annotations

"""
bug_reporter.py

Two entry points:
  submit_report(title, description) — user-initiated via /feedback form
  submit_crash(error_msg, ...)      — automatic crash/error reporter

Both route to the developer's dedicated Linear workspace.
Credentials are intentionally hardcoded — this is an isolated inbox.
Rotate the key at linear.app if compromised.
End users need no account or configuration.
"""

import base64
import hashlib
import json
import logging
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# Sentinel passed as client_context to submit_report() by submit_crash()
# to signal that system info is already embedded — don't append it again.
_SYSTEM_CONTEXT_SENTINEL = "__system_context_already_included__"

_GRAPHQL_URL  = "https://api.linear.app/graphql"
_REPORTER_KEY = base64.b64decode(
    b"bGluX2FwaV9UU2dJc3RxVVJCNmZFVFhzZXZWOENPZU1VTGFqVkxiNWJUUGowUDhM"
).decode()
_TEAM_ID      = "d343f047-5892-4e90-a15d-1c1c6b1b0423"

_SECRET_PATTERNS = (
    (re.compile(r"(AVIATIONSTACK_API_KEY|RAPIDAPI_KEY|OPENSKY_CLIENT_SECRET|LINEAR_API_KEY)=\S+", re.I), r"\1=[redacted]"),
    (re.compile(r"(access_key=)[^&\s]+", re.I), r"\1[redacted]"),
    (re.compile(r"(X-RapidAPI-Key['\":\s]+)[A-Za-z0-9._-]+", re.I), r"\1[redacted]"),
    (re.compile(r"lin_api_[A-Za-z0-9_]+", re.I), "[redacted-linear-token]"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "[redacted-uuid]"),
    (re.compile(r"\b10\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b"), r"10.\1.\2.x"),
    (re.compile(r"\b192\.168\.(\d{1,3})\.(\d{1,3})\b"), r"192.168.\1.x"),
    (re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.(\d{1,3})\.(\d{1,3})\b"), r"172.\1.\2.x"),
)

_CREATE_MUTATION = """
mutation CreateIssue($title: String!, $description: String!, $teamId: String!) {
  issueCreate(input: {
    title: $title
    description: $description
    teamId: $teamId
  }) {
    success
    issue { id identifier url }
  }
}
"""


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
                    "mode_label": "community relay",
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
    dedup = {k: v for k, v in dedup.items()
             if (cutoff - datetime.fromisoformat(v)).total_seconds() < 48 * 3600}
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
    Auto-file a crash/error report to the developer's Linear.
    Deduped per 6h by crash context plus error fingerprint. Never raises.
    """
    try:
        diagnostics_mode = _auto_diagnostics_mode()
        if diagnostics_mode in {"unset", "manual"}:
            return {"ok": False, "error": "automatic diagnostics disabled"}

        fp = _crash_fingerprint(error_msg, context=context)
        if _already_crash_filed(fp):
            return {"ok": False, "error": "duplicate (deduped)"}

        title = f"[Auto] {context} — {error_msg[:80]}"

        # System info first — most useful for triage
        sys_info = _system_context(client_context)
        body  = f"**Context:** `{context}`\n\n"
        body += f"**Report type:** Automatic crash diagnostics\n"
        body += f"**Delivery:** Developer issue inbox via Linear\n"
        body += f"**Diagnostics mode:** `{diagnostics_mode}`\n"
        body += f"**Traceback included:** {'yes' if traceback_str else 'no'}\n"
        body += f"**Sanitized log excerpt included:** {'yes' if diagnostics_mode == 'auto_logs' else 'no'}\n\n"
        body += f"---\n**System info**\n{sys_info}\n"
        body += f"---\n**Error:**\n```\n{_redact_sensitive(error_msg)[:300]}\n```\n"
        if traceback_str:
            body += f"\n**Traceback:**\n```\n{_redact_sensitive(traceback_str)[-1200:]}\n```\n"
        if diagnostics_mode == "auto_logs":
            log_tail = _read_log_tail(50)
            body += f"\n**Log tail:**\n```\n{_redact_sensitive(log_tail)[-1500:]}\n```"

        # Pass empty description so submit_report doesn't double-append system info
        result = submit_report(title, body[:3800], _SYSTEM_CONTEXT_SENTINEL)
        if result.get("ok"):
            _mark_crash_filed(fp)
        return result
    except Exception as exc:
        log.warning("Auto crash report failed (non-fatal): %s", exc)
        return {"ok": False, "error": str(exc)}


def submit_report(title: str, description: str = "", client_context: str = "") -> dict:
    """
    File a user-submitted bug report / feedback issue in the developer's Linear board.

    Returns {"ok": True, "url": "..."} or {"ok": False, "error": "..."}.
    Never raises.
    """
    import requests

    if not title or not title.strip():
        return {"ok": False, "error": "Title is required"}

    full_description = (
        "**Report type:** Manual report\n"
        "**Delivery:** Developer issue inbox via Linear\n\n"
    )
    if description.strip():
        full_description += _redact_sensitive(description.strip()) + "\n\n"
    if client_context != _SYSTEM_CONTEXT_SENTINEL:
        full_description += "---\n**System info**\n" + _system_context(client_context)

    try:
        resp = requests.post(
            _GRAPHQL_URL,
            json={
                "query": _CREATE_MUTATION,
                "variables": {
                    "title":       title.strip()[:200],
                    "description": full_description[:4000],
                    "teamId":      _TEAM_ID,
                },
            },
            headers={
                "Authorization": _REPORTER_KEY,
                "Content-Type":  "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data   = resp.json()
        result = (data.get("data") or {}).get("issueCreate") or {}
        if result.get("success"):
            url = (result.get("issue") or {}).get("url")
            log.info("Bug report filed: %s", url)
            return {"ok": True, "url": url}
        errors = data.get("errors")
        msg = errors[0]["message"] if errors else "Unknown error from Linear"
        return {"ok": False, "error": msg}
    except Exception as exc:
        log.warning("Bug report submission failed: %s", exc)
        return {"ok": False, "error": str(exc)}
