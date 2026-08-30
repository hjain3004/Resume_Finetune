"""Deterministic early-career experience math over employment intervals.

Months are modeled as a zero-based ordinal (``year * 12 + month - 1``) so that a
period is a half-open ``[start, end)`` range and its length is a plain integer
subtraction: ``2023-01`` to ``2026-01`` is 36 months. Overlapping periods are
merged before summing, and everything at or before graduation is clipped away.

Internship intervals are deliberately not handled here; the call site excludes
them explicitly before invoking :func:`professional_experience_months`.
"""

from __future__ import annotations

import re

from src.resume_evidence.model import EmploymentInterval
from src.resume_evidence.serde import EvidenceValidationError

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def parse_month(value: str) -> int:
    """Return the zero-based month ordinal for a strict ``YYYY-MM`` string.

    Rejects non-strings (booleans included), malformed formats, and out-of-range
    months with :class:`EvidenceValidationError`.
    """
    if not isinstance(value, str) or isinstance(value, bool):
        raise EvidenceValidationError(f"invalid month: {value!r}")
    match = _MONTH_RE.fullmatch(value)
    if not match:
        raise EvidenceValidationError(f"invalid month: {value!r}")
    year, month = (int(part) for part in match.groups())
    return year * 12 + month - 1


def _merge_pairs(pairs: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Merge overlapping/adjacent ``(start, end)`` ordinal pairs, sorted ascending."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(pairs):
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _validated_pair(interval: EmploymentInterval) -> tuple[int, int]:
    start, end = parse_month(interval.start_month), parse_month(interval.end_month)
    if end <= start:
        raise EvidenceValidationError("employment interval end must be after start")
    return start, end


def merge_intervals(
    intervals: tuple[EmploymentInterval, ...],
) -> tuple[tuple[int, int], ...]:
    """Parse, validate, and merge employment intervals into ordinal pairs.

    Reversed and zero-length intervals raise :class:`EvidenceValidationError`.
    """
    return _merge_pairs([_validated_pair(item) for item in intervals])


def professional_experience_months(
    intervals: tuple[EmploymentInterval, ...],
    graduation_month: str,
) -> int:
    """Total post-graduation months covered by ``intervals`` after merging overlaps.

    Intervals ending at or before graduation contribute nothing; an interval that
    straddles graduation is clipped so it starts at graduation.
    """
    graduation = parse_month(graduation_month)
    clipped: list[tuple[int, int]] = []
    for item in intervals:
        start, end = _validated_pair(item)
        if end > graduation:
            clipped.append((max(start, graduation), end))
    return sum(end - start for start, end in _merge_pairs(clipped))
