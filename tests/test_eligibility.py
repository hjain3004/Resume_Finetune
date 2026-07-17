from __future__ import annotations

from dataclasses import replace

import pytest

from src.eligibility import (
    EligibilityDisposition,
    EligibilityStage,
    evaluate,
    load_eligibility_config,
)


def _decision(title: str, location: str | None, jd_text: str | None, *, stage=EligibilityStage.POST_RESOLUTION, flags=()):
    return evaluate(
        stage=stage,
        title=title,
        location=location,
        jd_text=jd_text,
        existing_flags=flags,
        config=load_eligibility_config(),
    )


@pytest.mark.parametrize(
    ("title", "location", "jd", "reason"),
    [
        ("Software Engineer", "Toronto, Canada", "Starts in 2027", "eligibility:country"),
        ("Software Engineer Co-op", "New York, NY", "Spring 2027", "eligibility:opportunity_type"),
        ("Software Engineer Intern", "New York, NY", "Summer 2027 internship", "eligibility:start_window"),
        ("Marketing Analyst", "New York, NY", "Starts in 2027", "eligibility:role_family"),
        ("Senior Software Engineer", "New York, NY", "Starts in 2027", "eligibility:seniority"),
        ("Software Engineer", "New York, NY", "Requires 7 years of backend experience. Starts in 2027.", "eligibility:seniority"),
        ("Software Engineer", "New York, NY", "Starts in 2027. We are unable to sponsor visas.", "eligibility:work_authorization"),
    ],
)
def test_post_resolution_filters_with_stable_reason_codes(title: str, location: str, jd: str, reason: str) -> None:
    decision = _decision(title, location, jd)

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == reason


def test_country_mismatch_short_circuits_later_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.eligibility as eligibility

    def fail(*args, **kwargs):
        raise AssertionError("later classifier should not run")

    monkeypatch.setattr(eligibility, "classify_opportunity_type", fail)

    decision = _decision("Not Software", "Remote - Canada", "unable to sponsor")

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:country"


def test_unknown_country_defers_pre_and_passes_with_flag_post() -> None:
    pre = _decision("Software Engineer", "Remote", None, stage=EligibilityStage.PRE_RESOLUTION)
    post = _decision("Software Engineer", "Remote", "Starts in 2027")

    assert pre.disposition is EligibilityDisposition.DEFER
    assert pre.reason_code is None
    assert post.disposition is EligibilityDisposition.PASS
    assert post.flags == ("country_unknown", "opportunity_type_inferred")


def test_full_time_unknown_start_defers_pre_and_passes_with_flag_post() -> None:
    pre = _decision("Software Engineer", "New York, NY", None, stage=EligibilityStage.PRE_RESOLUTION)
    post = _decision("Software Engineer", "New York, NY", "Build backend systems.")

    assert pre.disposition is EligibilityDisposition.DEFER
    assert post.disposition is EligibilityDisposition.PASS
    assert "start_date_unknown" in post.flags


def test_year_only_internship_defers_pre_and_filters_post() -> None:
    pre = _decision("Software Engineering Intern 2027", "New York, NY", None, stage=EligibilityStage.PRE_RESOLUTION)
    post = _decision("Software Engineering Intern 2027", "New York, NY", "2027 internship")

    assert pre.disposition is EligibilityDisposition.DEFER
    assert post.disposition is EligibilityDisposition.FILTER
    assert post.reason_code == "eligibility:start_window"


@pytest.mark.parametrize(
    ("title", "jd"),
    [
        ("Software Engineer", "New Grad 2027 role."),
        ("Software Engineering Intern", "Spring 2027 internship."),
        ("Software Engineering Intern", "Internship starts May 2027."),
    ],
)
def test_eligible_full_time_and_spring_internship_pass(title: str, jd: str) -> None:
    decision = _decision(title, "Austin, Texas", jd)

    assert decision.disposition is EligibilityDisposition.PASS


@pytest.mark.parametrize(
    "jd",
    [
        "We are unable to sponsor employment visas.",
        "No visa sponsorship is available.",
        "US citizens only.",
        "US citizenship is required.",
    ],
)
def test_explicit_work_authorization_negative_filters(jd: str) -> None:
    decision = _decision("Software Engineer", "New York, NY", f"Starts in 2027. {jd}", flags=("sponsor_likely",))

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:work_authorization"


@pytest.mark.parametrize(
    "jd",
    [
        # Verbatim phrasings from calibration round 2026-07-16-r1, which scored six
        # clearance-gated postings that should never have passed eligibility.
        "Active Top-Secret clearance with SCI eligibility",  # id=26 Amentum
        "Amentum is searching for a Top-Secret cleared Cloud Developer",  # id=26
        "Ability to obtain and maintain a DoD Security Clearance is required",  # id=29, id=31
        "Active Top Secret, Top Secret SCI, or DOE Level Q clearance",  # id=34
        "Active Top Secret, Top Secret SCI, or DOE Level Q clearance, or the ability and willingness to obtain one",  # id=35
        "Must possess an active TS/SCI clearance",
        "A security clearance is required for this position.",
    ],
)
def test_clearance_requirement_filters_as_work_authorization(jd: str) -> None:
    # TS/SCI and DoD clearances are granted only to US citizens, and no sponsorship
    # path exists, so a clearance requirement is a work-authorization rejection for
    # this candidate -- not a scoring problem. See DECISIONS.md.
    decision = _decision("Software Engineer", "Washington, DC", f"Starts in 2027. {jd}")

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:work_authorization"


@pytest.mark.parametrize(
    "jd",
    [
        # A bare mention is not a requirement. id=28's JD carries only this heading;
        # rejecting on the word alone would discard jobs the candidate can hold.
        "Security Clearance",
        "An active security clearance is a plus.",
        "Clearance preferred but not required.",
        "No clearance required for this role.",
    ],
)
def test_clearance_mentioned_without_requirement_does_not_filter(jd: str) -> None:
    decision = _decision("Software Engineer", "New York, NY", f"Starts in 2027. {jd}")

    assert decision.disposition is not EligibilityDisposition.FILTER


@pytest.mark.parametrize(
    ("jd", "expected_flags"),
    [
        ("Starts in 2027.", ("opportunity_type_inferred",)),
        ("Starts in 2027. Visa sponsorship is available.", ("opportunity_type_inferred",)),
        ("Starts in 2027. Must be authorized to work in the US.", ("authorization_ambiguous", "opportunity_type_inferred")),
        ("Starts in 2027. We do not discriminate based on citizenship status.", ("opportunity_type_inferred",)),
    ],
)
def test_authorization_silence_positive_ambiguity_and_eeo(jd: str, expected_flags: tuple[str, ...]) -> None:
    decision = _decision("Software Engineer", "New York, NY", jd)

    assert decision.disposition is EligibilityDisposition.PASS
    assert decision.flags == expected_flags


def test_role_patterns_and_years_cap_are_configurable() -> None:
    config = load_eligibility_config()
    relaxed = replace(config, seniority=replace(config.seniority, years_cap=10))

    strict_decision = evaluate(
        stage=EligibilityStage.POST_RESOLUTION,
        title="Software Engineer",
        location="New York, NY",
        jd_text="Requires 7 years of backend experience. Starts in 2027.",
        existing_flags=(),
        config=config,
    )
    relaxed_decision = evaluate(
        stage=EligibilityStage.POST_RESOLUTION,
        title="Software Engineer",
        location="New York, NY",
        jd_text="Requires 7 years of backend experience. Starts in 2027.",
        existing_flags=(),
        config=relaxed,
    )

    assert strict_decision.reason_code == "eligibility:seniority"
    assert relaxed_decision.disposition is EligibilityDisposition.PASS


def test_flags_are_sorted_and_deduplicated() -> None:
    decision = _decision(
        "Software Engineer",
        "Remote",
        "Must be authorized to work in the US.",
        flags=("start_date_unknown", "country_unknown", "country_unknown"),
    )

    assert decision.flags == (
        "authorization_ambiguous",
        "country_unknown",
        "opportunity_type_inferred",
        "start_date_unknown",
    )
