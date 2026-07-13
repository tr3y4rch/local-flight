from __future__ import annotations

import re
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict


NoticeTone = Literal["info", "success", "warning", "error"]


class NoticeAction(TypedDict, total=False):
    kind: Literal["route", "refresh", "settings", "logs", "report"]
    label: str
    target: str


class ClientNotice(TypedDict, total=False):
    code: str
    tone: NoticeTone
    message: str
    next_step: str
    action: NoticeAction


_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I)
_ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\[^\s]+|/(?:Users|home|var|private|data)/[^\s]+)")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:api[_-]?key|token|password|secret|authorization)\s*[=:]\s*[^\s,;]+",
    re.I,
)
_TONES: set[str] = {"info", "success", "warning", "error"}
_ACTION_KINDS = {"route", "refresh", "settings", "logs", "report"}
_SAFE_LOCAL_TARGETS = {
    "/admin",
    "/display",
    "/feedback",
    "/fids",
    "/history",
    "/logs",
    "/matrix-preview",
    "/radar",
    "/settings",
    "/setup",
}


def _safe_text(value: Any, *, limit: int = 280) -> str:
    text = " ".join(str(value or "").split())[:limit]
    text = _UUID_RE.sub("[support-id]", text)
    text = _ABSOLUTE_PATH_RE.sub("[local-path]", text)
    text = _SECRET_ASSIGNMENT_RE.sub("[redacted]", text)
    return text


def sanitize_client_payload(value: Any) -> Any:
    """Recursively remove raw identities, local paths, and secret assignments."""
    if isinstance(value, dict):
        return {str(key): sanitize_client_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_client_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_client_payload(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value, limit=2000)
    return value


def make_notice(
    code: str,
    tone: NoticeTone,
    message: str,
    *,
    next_step: str = "",
    action: NoticeAction | None = None,
) -> ClientNotice:
    clean_code = str(code or "").strip().lower()
    if not _CODE_RE.fullmatch(clean_code):
        raise ValueError(f"Invalid notice code: {code!r}")
    clean_tone = str(tone or "info").strip().lower()
    if clean_tone not in _TONES:
        raise ValueError(f"Invalid notice tone: {tone!r}")
    notice: ClientNotice = {
        "code": clean_code,
        "tone": clean_tone,  # type: ignore[typeddict-item]
        "message": _safe_text(message),
    }
    if next_step:
        notice["next_step"] = _safe_text(next_step)
    if action:
        action_kind = str(action.get("kind") or "route").strip().lower()
        if action_kind not in _ACTION_KINDS:
            action_kind = "route"
        safe_action: NoticeAction = {
            "kind": action_kind,  # type: ignore[typeddict-item]
            "label": _safe_text(action.get("label", "Open"), limit=60),
        }
        target = str(action.get("target") or "").strip()
        if target in _SAFE_LOCAL_TARGETS:
            safe_action["target"] = target[:160]
        notice["action"] = safe_action
    return notice


class NoticeRegistry:
    """Bounded, process-local diagnostic metadata with no raw error payloads."""

    def __init__(self, max_entries: int = 100) -> None:
        self.max_entries = max(10, int(max_entries))
        self._lock = threading.Lock()
        self._rows: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def record(
        self,
        notice: ClientNotice,
        *,
        route_family: str,
        source_category: str,
    ) -> None:
        code = str(notice.get("code") or "notice.unknown")
        now = datetime.now(timezone.utc).isoformat()
        key = f"{code}|{route_family}|{source_category}"
        with self._lock:
            previous = self._rows.pop(key, None) or {}
            self._rows[key] = {
                "code": code,
                "tone": notice.get("tone", "info"),
                "message": notice.get("message", ""),
                "route_family": _safe_text(route_family, limit=80),
                "source_category": _safe_text(source_category, limit=80),
                "first_seen": previous.get("first_seen") or now,
                "last_seen": now,
                "occurrence_count": int(previous.get("occurrence_count") or 0) + 1,
            }
            while len(self._rows) > self.max_entries:
                self._rows.popitem(last=False)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._rows.values())[-max(1, min(int(limit), self.max_entries)) :]
        return [dict(row) for row in reversed(rows)]

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


registry = NoticeRegistry()


def attach_notices(
    payload: dict[str, Any],
    notices: list[ClientNotice],
    *,
    route_family: str,
    source_category: str,
) -> dict[str, Any]:
    clean = [dict(item) for item in notices if item.get("message")]
    payload["notices"] = clean
    for item in clean:
        registry.record(item, route_family=route_family, source_category=source_category)
    return payload


__all__ = [
    "ClientNotice",
    "NoticeAction",
    "NoticeRegistry",
    "attach_notices",
    "make_notice",
    "registry",
    "sanitize_client_payload",
]
