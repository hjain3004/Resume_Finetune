from __future__ import annotations

from dataclasses import replace
from datetime import date

from src.eligibility import (
    DateWindow,
    OpportunityType,
    OpportunityTypePolicy,
    classify_opportunity_type,
    extract_start_evidence,
    load_eligibility_config,
)


def _config():
    return load_eligibility_config()


def test_classification_order_prefers_specific_title_type_before_jd_full_time() -> None:
    result = classify_opportunity_type(
        "Software Engineering Intern",
        "This is a full-time role after graduation.",
        _config(),
    )

    assert result.opportunity_type is OpportunityType.INTERNSHIP
    assert result.inferred is False


def test_title_is_checked_before_jd() -> None:
    result = classify_opportunity_type(
        "New Grad Software Engineer",
        "Prior internship experience preferred.",
        _config(),
    )

    assert result.opportunity_type is OpportunityType.FULL_TIME
    assert result.inferred is False


def test_unmarked_role_defaults_to_configured_full_time_with_inferred_flag() -> None:
    result = classify_opportunity_type("Software Engineer", "Build distributed systems.", _config())

    assert result.opportunity_type is OpportunityType.FULL_TIME
    assert result.inferred is True


def test_disabled_type_is_still_recognized() -> None:
    result = classify_opportunity_type("Software Engineer Co-op", None, _config())

    assert result.opportunity_type is OpportunityType.CO_OP
    assert result.inferred is False


def test_default_type_is_configurable_without_code_change() -> None:
    config = _config()
    changed = replace(
        config,
        opportunity_types=replace(config.opportunity_types, default_when_unmarked="internship"),
    )

    assert classify_opportunity_type("Software Engineer", None, changed).opportunity_type is OpportunityType.INTERNSHIP


def test_enabled_type_policy_is_configurable_without_code_change() -> None:
    config = _config()
    changed_types = dict(config.opportunity_types.types)
    changed_types["co_op"] = replace(changed_types["co_op"], enabled=True)
    changed = replace(config, opportunity_types=replace(config.opportunity_types, types=changed_types))

    assert changed.opportunity_types.types["co_op"].enabled is True


def test_full_time_start_evidence_recognizes_2027_forms() -> None:
    evidence = extract_start_evidence(
        "New Grad 2027 role starts in 2027. Start date August 2027 or 2027-09-01.",
        _config(),
    )

    assert 2027 in evidence.years
    assert (2027, 8) in evidence.month_years
    assert date(2027, 9, 1) in evidence.exact_dates


def test_start_evidence_keeps_out_of_window_years_visible() -> None:
    evidence = extract_start_evidence("Start date in 2026 or January 2028.", _config())

    assert 2026 in evidence.years
    assert (2028, 1) in evidence.month_years


def test_missing_start_has_no_evidence() -> None:
    evidence = extract_start_evidence("Build backend systems for customers.", _config())

    assert evidence.exact_dates == ()
    assert evidence.month_years == ()
    assert evidence.seasons == ()
    assert evidence.years == ()


def test_multiple_starts_preserve_matching_option() -> None:
    evidence = extract_start_evidence("Available start dates are July 2026, February 2027, and June 2028.", _config())

    assert (2027, 2) in evidence.month_years


def test_internship_start_evidence_recognizes_spring_and_january_through_may() -> None:
    evidence = extract_start_evidence("Spring 2027 internship starts January 2027, May 2027, or 2027-03-15.", _config())

    assert ("spring", 2027) in evidence.seasons
    assert (2027, 1) in evidence.month_years
    assert (2027, 5) in evidence.month_years
    assert date(2027, 3, 15) in evidence.exact_dates


def test_internship_out_of_window_evidence_is_visible_but_not_spring() -> None:
    evidence = extract_start_evidence("Summer 2027 or Fall 2027 internship starts June 2027.", _config())

    assert ("summer", 2027) in evidence.seasons
    assert ("fall", 2027) in evidence.seasons
    assert (2027, 6) in evidence.month_years


def test_year_only_internship_is_insufficient_specific_evidence() -> None:
    evidence = extract_start_evidence("2027 internship", _config())

    assert evidence.years == (2027,)
    assert evidence.month_years == ()
    assert evidence.seasons == ()


def test_unrelated_years_are_not_start_evidence() -> None:
    evidence = extract_start_evidence("Founded in 2027. Copyright 2027 Example Corp.", _config())

    assert evidence.years == ()


def test_full_time_window_and_season_months_are_configurable() -> None:
    config = _config()
    changed_types = dict(config.opportunity_types.types)
    changed_types["full_time"] = replace(
        changed_types["full_time"],
        start_windows=(DateWindow(date(2028, 1, 1), date(2028, 12, 31)),),
    )
    changed_seasons = dict(config.seasons)
    changed_seasons["spring"] = replace(changed_seasons["spring"], months=(3, 4))
    changed = replace(
        config,
        opportunity_types=replace(config.opportunity_types, types=changed_types),
        seasons=changed_seasons,
    )

    assert changed.opportunity_types.types["full_time"].start_windows == (
        DateWindow(date(2028, 1, 1), date(2028, 12, 31)),
    )
    assert changed.seasons["spring"].months == (3, 4)
