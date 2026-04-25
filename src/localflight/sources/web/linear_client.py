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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_GRAPHQL_URL = "https://api.linear.app/graphql"
_DEDUP_HOURS = 6


# ── Credentials ────────────────────────────────────────────────────────────────

def _api_key() -> Optional[str]:
    return os.getenv("LINEAR_API_KEY", "").strip() or None


def _team_id() -> Optional[str]:
    return os.getenv("LINEAR_TEAM_ID", "").strip() or None


def is_available() -> bool:
    return bool(_api_key() and _team_id())


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
        title = f"{label}Scheduler error — {error_msg[:80]}"

        description = (
            f"**Local Flight scheduler error**\n\n"
            f"- **Time:** {ts}\n"
            f"- **Source:** {source_name}\n"
            f"- **Airport:** {airport_iata or '—'}\n\n"
            f"**Error:**\n```\n{error_msg}\n```\n"
        )

        url = _post_issue(title, description)
        _mark_filed(fp)
        log.info("Linear: filed issue %s", url or "(no url)")

    except Exception as exc:
        log.warning("Linear issue filing failed (non-fatal): %s", exc)
