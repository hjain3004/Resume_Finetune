"""Shared text-similarity helpers: JD normalization, content hashing, and
5-word-shingle Jaccard similarity. Used by scripts/export_batch.py (near-dup
clustering) and src/freshness.py (M6.8 content-based repost detection) so the
two callers agree on what "the same posting" means."""

from __future__ import annotations

import hashlib
import re

SHINGLE_SIZE = 5

_AGO_LINE_RE = re.compile(r"^.{0,60}·\s*\d+\s*(?:minutes?|hours?|days?)\s+ago.*$", re.MULTILINE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_jd(text: str) -> str:
    """Lowercase, strip relative-time chrome lines, collapse whitespace."""
    text = (text or "").lower()
    text = _AGO_LINE_RE.sub("", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_jd(text).encode("utf-8")).hexdigest()


def shingles(text: str, n: int = SHINGLE_SIZE) -> set[str]:
    words = normalize_jd(text).split(" ")
    words = [w for w in words if w]
    if not words:
        return set()
    if len(words) < n:
        return {" ".join(words)}
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
