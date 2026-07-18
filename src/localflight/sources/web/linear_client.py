from __future__ import annotations

"""
Linear.app issue filing client.

Files a new Linear issue when the scheduler hits a persistent error.
Deduplicates: same error fingerprint won't be re-filed within 6 hours.
Non-fatal: any exception here is logged and swallowed.

Env vars (read lazily):
  LINEAR_API_KEY  — personal API key (lin_api_...)
  LINEAR_TEAM_ID  — team UUID from Linear settings
"""

import hashlib
import json
import logging
import os
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from localflight.version import app_version

log = logging.getLogger(__name__)

_GRAPHQL_URL = "https://api.linear.app/graphql"
_DEDUP_HOURS = 6

_SECRET_PATTERNS = (
    (re.compile(r"(AVIATIONSTACK_API_KEY|AERODATABOX_API_KEY|RAPIDAPI_KEY|OPENSKY_CLIENT_SECRET|LINEAR_API_KEY|LINEAR_REPORTER_API_KEY)=\S+", re.I), r"\1=[redacted]"),
    (re.compile(r"(access_key=)[^&\s]+", re.I), r"\1[redacted]"),
    (re.compile(r"(X-RapidAPI-Key['\":\s]+)[A-Za-z0-9._-]+", re.I), r"\1[redacted]"),
    (re.compile(r"(x-magicapi-key['\":\s]+)[A-Za-z0-9._-]+", re.I), r"\1[redacted]"),
    (re.compile(r"lin_api_[A-Za-z0-9_]+", re.I), "[redacted-linear-token]"),
    (re.compile(r"lfm_[A-Za-z0-9._-]+", re.I), "[redacted-activation-token]"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "[redacted-uuid]"),
    (re.compile(r"\b10\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b"), r"10.\1.\2.x"),
    (re.compile(r"\b192\.168\.(\d{1,3})\.(\d{1,3})\b"), r"192.168.\1.x"),
    (re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.(\d{1,3})\.(\d{1,3})\b"), r"172.\1.\2.x"),
)


# ── Credentials ────────────────────────────────────────────────────────────────

def _api_key() -> Optional[str]:
    return os.getenv("LINEAR_API_KEY", "").strip() or None


def _team_id() -> Optional[str]:
    return os.getenv("LINEAR_TEAM_ID", "").strip() or None


def is_available() -> bool:
    return bool(_api_key() and _team_id())


def test_connection() -> dict:
    """
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    Makes a lightweight GraphQL viewer query to verify the key is valid.
    """
    import requests
    api_key = _api_key()
    team_id = _team_id()
    if not api_key or not team_id:
        return {"ok": False, "error": "LINEAR_API_KEY or LINEAR_TEAM_ID not set"}
    try:
        r = requests.post(
            _GRAPHQL_URL,
            json={"query": "{ viewer { id name } }"},
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=8,
        )
        if r.status_code == 401:
            return {"ok": False, "error": "API key rejected (401) — generate a new key in Linear Settings → API"}
        if r.status_code != 200:
            return {"ok": False, "error": f"Linear returned HTTP {r.status_code}"}
        data = r.json()
        if data.get("errors"):
            msg = data["errors"][0].get("message", "Unknown error")
            return {"ok": False, "error": msg}
        viewer = (data.get("data") or {}).get("viewer") or {}
        return {"ok": True, "name": viewer.get("name", "")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Deduplication state ────────────────────────────────────────────────────────

def _dedup_path() -> Path:
    from localflight.storage.config import config_path
    return config_path().parent / "linear_dedup.json"


def _load_dedup() -> dict:
    p = _dedup_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_dedup(data: dict) -> None:
    try:
        _dedup_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def _fingerprint(error_msg: str) -> str:
    # Stable hash of first 120 chars — enough to identify error class without noise
    return hashlib.sha1(error_msg[:120].encode()).hexdigest()[:12]


def _redact_sensitive(text: str) -> str:
    redacted = text or ""
    for pattern, repl in _SECRET_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return redacted


def _already_filed(fp: str) -> bool:
    dedup = _load_dedup()
    filed_at = dedup.get(fp)
    if not filed_at:
        return False
    try:
        age_hours = (
            datetime.now(timezone.utc) - datetime.fromisoformat(filed_at)
        ).total_seconds() / 3600
        return age_hours < _DEDUP_HOURS
    except Exception:
        return False


def _mark_filed(fp: str) -> None:
    dedup = _load_dedup()
    dedup[fp] = datetime.now(timezone.utc).isoformat()
    # Prune entries older than 48h
    cutoff = datetime.now(timezone.utc)
    dedup = {
        k: v for k, v in dedup.items()
        if (cutoff - datetime.fromisoformat(v)).total_seconds() < 48 * 3600
    }
    _save_dedup(dedup)


# ── GraphQL request ────────────────────────────────────────────────────────────

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


def _post_issue(title: str, description: str) -> Optional[str]:
    """Returns the issue URL on success, None on failure."""
    import requests

    api_key = _api_key()
    team_id = _team_id()
    if not api_key or not team_id:
        return None

    resp = requests.post(
        _GRAPHQL_URL,
        json={
            "query": _CREATE_MUTATION,
            "variables": {
                "title":       title,
                "description": description,
                "teamId":      team_id,
            },
        },
        headers={
            "Authorization": api_key,
            "Content-Type":  "application/json",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data.get("data", {}).get("issueCreate", {})
    if result.get("success"):
        return result.get("issue", {}).get("url")
    errors = data.get("errors")
    raise RuntimeError(f"Linear rejected issue: {errors}")


# ── Public API ─────────────────────────────────────────────────────────────────

def file_error(
    error_msg: str,
    *,
    source_name: str = "scheduler",
    airport_iata: str = "",
) -> None:
    """
    File a Linear issue for a scheduler error.
    Non-fatal: logs and returns silently on any failure.
    Deduplicates: same error class won't be re-filed within 6 hours.
    """
    if not is_available():
        return

    try:
        fp = _fingerprint(error_msg)
        if _already_filed(fp):
            log.debug("Linear: skipping duplicate error (fp=%s)", fp)
            return

        ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        label = f"[{airport_iata}] " if airport_iata else ""
        safe_error = _redact_sensitive(error_msg)
        title = f"{label}Scheduler error — {safe_error[:80]}"

        try:
            from localflight.storage.install import get_install_fingerprint
            install_id = get_install_fingerprint()
        except Exception:
            install_id = "unknown"

        try:
            from localflight.sources.web.aviationstack_client import _is_relay_mode
            api_mode = "community relay" if _is_relay_mode() else "byok"
        except Exception:
            api_mode = "unknown"

        description = (
            f"**Local Flight operator scheduler error**\n\n"
            f"- **Time:** {ts}\n"
            f"- **Version:** {app_version()}\n"
            f"- **Install fingerprint:** `{install_id}`\n"
            f"- **OS:** {platform.platform()}\n"
            f"- **Arch:** {platform.machine()}\n"
            f"- **Python:** {sys.version.split()[0]}\n"
            f"- **Source:** {source_name}\n"
            f"- **Airport:** {airport_iata or '—'}\n"
            f"- **API mode:** {api_mode}\n\n"
            f"**Error:**\n```\n{safe_error}\n```\n"
        )

        url = _post_issue(title, description)
        _mark_filed(fp)
        log.info("Linear: filed issue %s", url or "(no url)")

    except Exception as exc:
        log.warning("Linear issue filing failed (non-fatal): %s", exc)
