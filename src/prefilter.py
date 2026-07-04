"""Deterministic pre-filter rules per ARCHITECTURE §7."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from src.models import Status

_YEARS_RE = re.compile(
    r"(?:minimum|at least|required)[^.\n]{0,40}?(\d+)\+?\s*(?:years|yrs)"
    r"|(\d+)\+?\s*(?:years|yrs)[^.\n]{0,40}?(?:minimum|at least|required)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PrefilterResult:
    filtered: bool
    reason: str | None
    flags: list[str]


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _years_required(jd_text: str) -> int | None:
    numbers = []
    for match in _YEARS_RE.finditer(jd_text):
        value = match.group(1) or match.group(2)
        numbers.append(int(value))
    return min(numbers) if numbers else None


def evaluate(title: str, location: str | None, jd_text: str | None, config: dict) -> PrefilterResult:
    jd_text = jd_text or ""
    location = location or ""

    title_include = config.get("title_include") or []
    if title_include and not _any_match(title_include, title):
        return PrefilterResult(True, "title_include", [])

    title_exclude = config.get("title_exclude") or []
    if _any_match(title_exclude, title):
        return PrefilterResult(True, "title_exclude", [])

    location_allow = config.get("location_allow") or []
    if location_allow and not _any_match(location_allow, location):
        return PrefilterResult(True, "location", [])

    years_cap = config.get("years_cap")
    if years_cap is not None:
        required_years = _years_required(jd_text)
        if required_years is not None and required_years > years_cap:
            return PrefilterResult(True, f"yoe:{required_years}", [])

    flags = []
    for flag_name, patterns in (config.get("jd_flags") or {}).items():
        if _any_match(patterns, jd_text):
            flags.append(flag_name)

    return PrefilterResult(False, None, flags)


def run_prefilter(conn: sqlite3.Connection, config: dict) -> int:
    """Evaluate every RESOLVED row without a filter_reason. Returns the count
    newly marked FILTERED_OUT."""
    filtered_count = 0
    rows = conn.execute(
        "SELECT id, title, location, jd_text FROM jobs WHERE status = ? AND filter_reason IS NULL",
        (Status.RESOLVED,),
    ).fetchall()
    for row in rows:
        result = evaluate(row["title"], row["location"], row["jd_text"], config)
        if result.filtered:
            conn.execute(
                "UPDATE jobs SET status = ?, filter_reason = ? WHERE id = ?",
                (Status.FILTERED_OUT, result.reason, row["id"]),
            )
            filtered_count += 1
        elif result.flags:
            conn.execute(
                "UPDATE jobs SET flags = ? WHERE id = ?",
                (json.dumps(result.flags), row["id"]),
            )
    conn.commit()
    return filtered_count
