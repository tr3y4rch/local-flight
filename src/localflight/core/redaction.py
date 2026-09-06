from __future__ import annotations

import re


_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(AVIATIONSTACK_API_KEY|AERODATABOX_API_KEY|RAPIDAPI_KEY|OPENSKY_CLIENT_SECRET|LINEAR_API_KEY|LINEAR_REPORTER_API_KEY)=\S+",
            re.I,
        ),
        r"\1=[redacted]",
    ),
    (
        re.compile(
            r"(LOCALFLIGHT_ACTIVATION_TOKEN|RELAY_ACCESS_HASH_SECRET|RELAY_ACCESS_KEY_SECRET|STRIPE_SECRET_KEY|STRIPE_WEBHOOK_SECRET|RELAY_LICENSE_SMTP_PASSWORD|RELAY_CONTACT_SMTP_PASSWORD|SMTP_PASSWORD)=\S+",
            re.I,
        ),
        r"\1=[redacted]",
    ),
    (re.compile(r"(access_key=)[^&\s]+", re.I), r"\1[redacted]"),
    (re.compile(r"(X-RapidAPI-Key['\":\s]+)[A-Za-z0-9._-]+", re.I), r"\1[redacted]"),
    (re.compile(r"(x-magicapi-key['\":\s]+)[A-Za-z0-9._-]+", re.I), r"\1[redacted]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I), "Bearer [redacted]"),
    (re.compile(r"lin_api_[A-Za-z0-9_]+", re.I), "[redacted-linear-token]"),
    (re.compile(r"lfm_[A-Za-z0-9._~-]+", re.I), "[redacted-activation-token]"),
    (re.compile(r"lfr[a-z0-9]*_[A-Za-z0-9._~-]+", re.I), "[redacted-relay-token]"),
    (
        re.compile(r"\bLFRA(?:[ -]?[0-9A-HJKMNP-TV-Z]){27}\b", re.I),
        "[redacted-relay-license-key]",
    ),
    (
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
        "[redacted-uuid]",
    ),
    (re.compile(r"\b10\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b"), r"10.\1.\2.x"),
    (re.compile(r"\b192\.168\.(\d{1,3})\.(\d{1,3})\b"), r"192.168.\1.x"),
    (re.compile(r"\b172\.(1[6-9]|2\d|3[01])\.(\d{1,3})\.(\d{1,3})\b"), r"172.\1.\2.x"),
)


def redact_sensitive(text: str) -> str:
    """Remove credentials and private identifiers from user-facing diagnostics."""

    redacted = text or ""
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
