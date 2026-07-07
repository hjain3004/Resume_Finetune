"""Dataclasses, enums, and normalization helpers shared across the pipeline."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    DISCOVERED = "DISCOVERED"
    RESOLVED = "RESOLVED"
    RESOLVE_FAILED = "RESOLVE_FAILED"
    FILTERED_OUT = "FILTERED_OUT"
    SCORED = "SCORED"
    SHORTLISTED = "SHORTLISTED"
    TAILORED = "TAILORED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


# Source priority for dedup conflict resolution, best first.
SOURCE_PRIORITY: tuple[str, ...] = (
    "inbox",
    "tracker_simplify",
    "tracker_vansh",
    "tracker_jobright",
)


@dataclass(frozen=True)
class DiscoveredJob:
    company: str
    title: str
    location: str | None
    url: str
    source: str
    date_posted: str | None  # ISO date or None


@dataclass(frozen=True)
class ResolvedJD:
    jd_text: str
    resolver: str
    raw_title: str | None = None
    raw_location: str | None = None
    ats_url: str | None = None
    flags: list[str] | None = None
    jd_quality: str | None = None
    notes: str | None = None


_CORP_SUFFIXES = {"inc", "llc", "ltd", "corp", "co"}
_REMOTE_LOCATIONS = {
    "remote",
    "remote us",
    "remote usa",
    "united states remote",
    "us remote",
}
_TRAILING_REQ_ID_RE = re.compile(r"\s*#?\d{4,}\s*$")
_REQ_PAREN_RE = re.compile(r"\s*\(req[^)]*\)\s*$", re.IGNORECASE)
_BRACKET_ID_RE = re.compile(r"\s*\[[A-Za-z]?-?\d[\w-]*\]\s*$")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Lowercase, strip accents/punctuation/requisition IDs, collapse whitespace."""
    s = s or ""
    s = _TRAILING_REQ_ID_RE.sub("", s)
    s = _REQ_PAREN_RE.sub("", s)
    s = _BRACKET_ID_RE.sub("", s)
    s = s.lower()
    s = _strip_accents(s)
    s = _PUNCT_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()

    words = s.split(" ")
    while words and words[-1] in _CORP_SUFFIXES:
        words.pop()
    return " ".join(words)


def norm_loc(s: str | None) -> str:
    if not s:
        return "unknown"
    normalized = norm(s)
    if normalized in _REMOTE_LOCATIONS:
        return "remote-us"
    return normalized or "unknown"


def dedup_key(company: str, title: str, location: str | None) -> str:
    payload = f"{norm(company)}|{norm(title)}|{norm_loc(location)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
