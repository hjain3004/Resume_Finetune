"""Credential redaction for anything the harness writes to disk or reports.

Applied to plans (which must never carry API keys at all -- see
plan.validate_plan), to orchestrator run records, and to reports, so a
credential pasted into a free-text field (a human reviewer's note, a raw
provider error message) never survives into a committed artifact.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Env-var-style secret names and common provider API key shapes.
_KEY_NAME_PATTERN = re.compile(
    r"(?i)\b\w*(api[_-]?key|secret|token|password|bearer)\w*\b"
)
_KEY_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),  # Google-style
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{10,}"),
]


def looks_like_credential_key(key: str) -> bool:
    return bool(_KEY_NAME_PATTERN.search(key))


def redact_text(text: str) -> str:
    redacted = text
    for pattern in _KEY_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact a dict: any key that *looks like* a credential name
    has its value replaced outright (regardless of shape); every remaining
    string value is scanned for credential-shaped substrings."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if looks_like_credential_key(str(key)):
            out[key] = REDACTED
        else:
            out[key] = redact_value(value)
    return out


def find_credential_like_keys(data: dict[str, Any], _prefix: str = "") -> list[str]:
    """Dotted-path keys that look like they hold a credential. Used by
    plan validation to hard-reject a plan rather than silently redact it --
    a plan must never carry one in the first place."""
    found: list[str] = []
    for key, value in data.items():
        path = f"{_prefix}.{key}" if _prefix else str(key)
        if looks_like_credential_key(str(key)):
            found.append(path)
        if isinstance(value, dict):
            found.extend(find_credential_like_keys(value, path))
    return found
