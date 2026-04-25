from __future__ import annotations

"""
bug_reporter.py

Sends user feedback / bug reports to the Local Flight developer's Linear board.
Credentials are intentionally hardcoded — this is a dedicated isolated workspace
used only for inbound reports. Rotate the key at linear.app if abused.

End users do not need a Linear account or any configuration.
"""

import base64
import logging
import os
import platform
import sys
from typing import Optional

log = logging.getLogger(__name__)

_GRAPHQL_URL  = "https://api.linear.app/graphql"
_REPORTER_KEY = base64.b64decode(
    b"bGluX2FwaV9UU2dJc3RxVVJCNmZFVFhzZXZWOENPZU1VTGFqVkxiNWJUUGowUDhM"
).decode()
_TEAM_ID      = "d343f047-5892-4e90-a15d-1c1c6b1b0423"

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


def _system_context() -> str:
    try:
        from localflight.storage.config import load_config
        cfg = load_config()
        airport = cfg.airport_iata or "?"
        source  = cfg.source or "?"
    except Exception:
        airport = "?"
        source  = "?"

    return (
        f"- **Version:** {_app_version()}\n"
        f"- **Platform:** {platform.system()} {platform.release()}\n"
        f"- **Python:** {sys.version.split()[0]}\n"
        f"- **Airport:** {airport}\n"
        f"- **Source:** {source}\n"
    )


def submit_report(title: str, description: str = "") -> dict:
    """
    File a user-submitted bug report / feedback issue in the developer's Linear board.

    Returns {"ok": True, "url": "..."} or {"ok": False, "error": "..."}.
    Never raises.
    """
    import requests

    if not title or not title.strip():
        return {"ok": False, "error": "Title is required"}

    full_description = ""
    if description.strip():
        full_description += description.strip() + "\n\n"
    full_description += "---\n**System info**\n" + _system_context()

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
