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


def test_title_exclude_pattern_filters_even_with_saturated_jd_include_hits() -> None:
    decision = _decision(
        "Casino Game Tester",
        "New York, NY",
        "You will test our platform. Our backend developer team built the infrastructure. "
        "This role is distributed across our full-stack software developer group.",
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family_excluded"


def test_title_include_pattern_still_passes_outright() -> None:
    decision = _decision("Embedded Software Engineer", "New York, NY", "Starts in 2027.")

    assert decision.disposition is EligibilityDisposition.PASS


def test_single_incidental_jd_keyword_no_longer_passes() -> None:
    decision = _decision(
        "Power Electronics PCBA Technician",
        "Santa Cruz, CA",
        "Join our infrastructure buildout team. Starts in 2027.",
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family_excluded"


def test_jd_only_job_with_two_distinct_hits_passes() -> None:
    decision = _decision(
        "Full Stack Developer II",
        "New York, NY",
        "You will build backend services using our distributed platform. Starts in 2027.",
    )

    assert decision.disposition is EligibilityDisposition.PASS


def test_jd_only_job_with_one_distinct_hit_filters() -> None:
    decision = _decision(
        "Product Coordinator",
        "New York, NY",
        "You will coordinate with our platform team. Starts in 2027.",
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family"


def test_pre_resolution_exclude_applies_to_title_without_jd_text() -> None:
    # Note: The title must include start context (e.g., "Starts") for the start evidence
    # to be extracted and prevent deferring on start_window, allowing the role_family
    # exclude check to run. This verifies the exclude pattern is applied at PRE_RESOLUTION.
    decision = _decision(
        "Business Analyst Starts 2027",
        "New York, NY",
        None,
        stage=EligibilityStage.PRE_RESOLUTION,
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family_excluded"


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
        # "U.S." with periods is the ordinary form in American postings, but the original
        # patterns matched only the bare "US" spelling, so the most common phrasing of a
        # hard citizenship requirement passed the gate. Job id=52 reached SCORED this way
        # and was caught only incidentally, by a clearance pattern.
        "U.S. citizenship required.",
        "U.S. citizens only.",
        "Must be a U.S. citizen.",
        "Must be a United States citizen.",
        "United States citizenship is required.",
    ],
)
def test_dotted_and_spelled_out_citizenship_requirements_filter(jd: str) -> None:
    decision = _decision("Software Engineer", "New York, NY", f"Starts in 2027. {jd}")

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
    "jd",
    [
        # Verbatim from calibration round 2026-07-17-r1: id=83 Booz Allen Hamilton
        # reached the scorer, which correctly named the clearance a hard disqualifier
        # in its rationale -- the eligibility gate should have caught it first. Neither
        # bullet uses "active"/"required"/"must obtain"; a clearance level named as a
        # bare qualifications-list item is itself the requirement signal.
        "Must have:\n- Top Secret clearance\n- Bachelor's degree in CS or Engineering",
        "Preferred:\n- TS / SCI clearance",
        # spaced-slash and bare "Secret" (no "Top") variants
        "TS / SCI clearance",
        "Secret clearance",
    ],
)
def test_bare_named_clearance_level_filters_regardless_of_required_or_preferred_framing(jd: str) -> None:
    # A specific clearance level (Top Secret / TS-SCI / Secret / DOE Q) cannot be
    # obtained by a non-citizen under any framing -- "preferred" doesn't make a role
    # holdable, so unlike the generic bare-mention guard above, a *named* level is a
    # reject signal even without "required" wording. See DECISIONS.md.
    decision = _decision("Full-Stack Software Engineer", "Hampton, VA", f"Starts in 2027. {jd}")

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:work_authorization"


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


def test_narrowed_analyst_exclude_pattern_still_catches_functional_analyst() -> None:
    # Regression: "Junior SAP SD Functional Analyst" should still filter because
    # the narrowed pattern "\\b(business|systems?|functional)\\s+analyst\\b" matches
    # "Functional Analyst". This was the original motivating case for the exclude pattern.
    decision = _decision(
        "Junior SAP SD Functional Analyst",
        "New York, NY",
        "Starts in 2027",
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family_excluded"


def test_narrowed_analyst_exclude_pattern_allows_analyst_as_suffix() -> None:
    # Regression: "Technology Software Engineer Rotation Program - Analyst" should PASS
    # because it matches the include pattern "software" and "engineer", and the narrowed
    # exclude pattern "\\b(business|systems?|functional)\\s+analyst\\b" does NOT match
    # "Analyst" without a business|systems|functional prefix.
    decision = _decision(
        "Technology Software Engineer Rotation Program - Analyst",
        "New York, NY",
        "Starts in 2027",
    )

    assert decision.disposition is EligibilityDisposition.PASS


def test_exclude_pattern_takes_precedence_over_include_pattern() -> None:
    # Regression: when a title matches both an include and exclude pattern,
    # the exclude check runs first (line 731 in src/eligibility.py), so the
    # decision should FILTER with "eligibility:role_family_excluded", not PASS.
    # Example: "Business Analyst / Developer" matches exclude pattern
    # "(business|systems?|functional)\\s+analyst" and include pattern "developer".
    decision = _decision(
        "Business Analyst / Developer",
        "New York, NY",
        "Starts in 2027",
    )

    assert decision.disposition is EligibilityDisposition.FILTER
    assert decision.reason_code == "eligibility:role_family_excluded"


@pytest.mark.parametrize(
    "title",
    [
        "Python Engineer (Early-Career)",
        "GPU Compiler Performance",
        "LGV CS Programmer",
        "Machine Learning Engineer",
        "Formal Verification Engineer",
        "Student Assistant – Applications Development - Hybrid",
    ],
)
def test_widened_include_vocabulary_passes_titles_missed_by_narrow_original_list(title: str) -> None:
    # Regression: the live-DB impact preview for the jd_fallback_min_hits change surfaced
    # genuine software-adjacent titles that the original 9-pattern include list (software,
    # swe, backend, back.end, full.?stack, platform, infrastructure, distributed, developer)
    # never matched at the title level, so they had to clear the raised JD-fallback bar
    # instead -- which several of them failed, a false-negative regression this milestone
    # should not introduce. Each of these titles now matches directly via python, compiler,
    # programmer, "machine learning", "formal verification", or "applications development".
    decision = _decision(title, "New York, NY", "Starts in 2027")

    assert decision.disposition is EligibilityDisposition.PASS


def test_widened_include_vocabulary_covers_front_end_and_programming_via_jd_fallback() -> None:
    # Regression: id=137 (InstaLILY AI "Design Engineer") from the live-DB impact preview --
    # title doesn't match any include pattern, but the JD describes "front-end craft" and
    # "product infrastructure", which should now clear the 2-distinct-hit fallback bar via
    # the new front.?end pattern plus the existing infrastructure pattern.
    decision = _decision(
        "Design Engineer",
        "New York, NY",
        "Bring strong front-end craft to interaction design. Build a design system in code "
        "as shared product infrastructure. Starts in 2027.",
    )

    assert decision.disposition is EligibilityDisposition.PASS

    # Regression: id=402 (Baxter "SW Engineer - Test Automation") -- title doesn't match any
    # include pattern, but the JD mentions "software quality" and "programming languages",
    # which should now clear the fallback bar via the existing software pattern plus the new
    # programming pattern.
    decision = _decision(
        "SW Engineer - Test Automation",
        "New York, NY",
        "Ensure software quality and reliability. Experience with programming languages "
        "such as Python, Java, or C#. Starts in 2027.",
    )

    assert decision.disposition is EligibilityDisposition.PASS
