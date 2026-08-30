"""Boundary matrix for deterministic early-career experience calculation."""

from __future__ import annotations

import pytest

from src.resume_evidence.experience import (
    merge_intervals,
    parse_month,
    professional_experience_months,
)
from src.resume_evidence.model import EmploymentInterval
from src.resume_evidence.serde import EvidenceValidationError

# NOTE: The plan's matrix listed the two-interval overlap row as 18 months. That
# is an arithmetic error under the plan's own half-open month convention
# ("2023-01 to 2026-01 is 36 months"): the merged span 2023-01..2024-06 is
# 12 + 5 = 17 months. Corrected to 17 here per the stated convention.
_MATRIX = [
    ((EmploymentInterval("2023-01", "2026-01"),), "2022-05", 36),
    ((EmploymentInterval("2023-01", "2026-02"),), "2022-05", 37),
    ((EmploymentInterval("2022-01", "2024-01"),), "2023-01", 12),
    (
        (
            EmploymentInterval("2023-01", "2024-01"),
            EmploymentInterval("2023-06", "2024-06"),
        ),
        "2022-05",
        17,  # plan said 18; corrected — see module NOTE
    ),
]


@pytest.mark.parametrize("intervals,graduation,expected", _MATRIX)
def test_professional_month_recomputation(intervals, graduation, expected) -> None:
    assert professional_experience_months(intervals, graduation) == expected


def test_pre_graduation_intervals_are_excluded() -> None:
    intervals = (EmploymentInterval("2020-01", "2021-01"),)
    assert professional_experience_months(intervals, "2023-01") == 0


def test_interval_straddling_graduation_is_clipped() -> None:
    intervals = (EmploymentInterval("2022-06", "2024-06"),)
    # graduation 2023-06 -> span 2023-06..2024-06 == 12 months
    assert professional_experience_months(intervals, "2023-06") == 12


# --------------------------------------------------------------------------- #
# parse_month
# --------------------------------------------------------------------------- #
def test_parse_month_zero_indexes_january() -> None:
    assert parse_month("2026-02") - parse_month("2023-01") == 37


@pytest.mark.parametrize("bad", ["2023-13", "2023-1", "23-01", "2023-00", "202301", ""])
def test_parse_month_rejects_malformed_strings(bad) -> None:
    with pytest.raises(EvidenceValidationError):
        parse_month(bad)


@pytest.mark.parametrize("bad", [None, 202301, 3.5, True, False, ("2023", "01")])
def test_parse_month_rejects_non_strings(bad) -> None:
    with pytest.raises(EvidenceValidationError):
        parse_month(bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# merge_intervals
# --------------------------------------------------------------------------- #
def test_merge_intervals_merges_overlap() -> None:
    intervals = (
        EmploymentInterval("2023-01", "2024-01"),
        EmploymentInterval("2023-06", "2024-06"),
    )
    assert merge_intervals(intervals) == (
        (parse_month("2023-01"), parse_month("2024-06")),
    )


def test_merge_intervals_merges_adjacent_and_sorts() -> None:
    intervals = (
        EmploymentInterval("2023-06", "2023-09"),
        EmploymentInterval("2023-01", "2023-06"),
    )
    assert merge_intervals(intervals) == (
        (parse_month("2023-01"), parse_month("2023-09")),
    )


def test_merge_intervals_keeps_disjoint_separate() -> None:
    intervals = (
        EmploymentInterval("2023-01", "2023-06"),
        EmploymentInterval("2024-01", "2024-06"),
    )
    assert merge_intervals(intervals) == (
        (parse_month("2023-01"), parse_month("2023-06")),
        (parse_month("2024-01"), parse_month("2024-06")),
    )


def test_merge_intervals_empty() -> None:
    assert merge_intervals(()) == ()


# --------------------------------------------------------------------------- #
# rejection cases
# --------------------------------------------------------------------------- #
def test_reversed_interval_rejected() -> None:
    intervals = (EmploymentInterval("2024-01", "2023-01"),)
    with pytest.raises(EvidenceValidationError):
        professional_experience_months(intervals, "2022-01")
    with pytest.raises(EvidenceValidationError):
        merge_intervals(intervals)


def test_zero_length_interval_rejected() -> None:
    intervals = (EmploymentInterval("2023-01", "2023-01"),)
    with pytest.raises(EvidenceValidationError):
        professional_experience_months(intervals, "2022-01")
    with pytest.raises(EvidenceValidationError):
        merge_intervals(intervals)


@pytest.mark.parametrize("graduation", [None, "", "2023-13", "not-a-month"])
def test_missing_or_invalid_graduation_rejected(graduation) -> None:
    intervals = (EmploymentInterval("2023-01", "2024-01"),)
    with pytest.raises(EvidenceValidationError):
        professional_experience_months(intervals, graduation)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "interval",
    [
        EmploymentInterval(True, "2024-01"),  # type: ignore[arg-type]
        EmploymentInterval("2023-01", False),  # type: ignore[arg-type]
        EmploymentInterval(None, "2024-01"),  # type: ignore[arg-type]
    ],
)
def test_non_string_month_values_rejected(interval) -> None:
    with pytest.raises(EvidenceValidationError):
        professional_experience_months((interval,), "2022-01")
