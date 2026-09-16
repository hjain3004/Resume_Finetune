"""G3 review packet builder (M8P-6 Task 5). No model call, no network, no
pdflatex -- every input here is a synthetic, hand-built or code-built
dataclass; no real S3/G2/render CLI is invoked."""
import json

import pytest

from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.g1 import run_static_g1
from src.tailor.g2 import G2Dimension, G2Finding, G2Response, G2TargetKind, G2Verdict
from src.tailor.g2_pipeline import G2Bundle, G2Round
from src.tailor.publish import RenderResult
from src.tailor.s0 import build_s0_request, parse_s0_response
from src.tailor.s1 import parse_s1_response
from src.tailor.s2 import build_s2_request, parse_s2_response
from src.tailor.s3 import (
    build_s3_request,
    calculate_edit_budget,
    derive_change_log,
    derive_unified_diff,
    hydrate_s3,
    parse_s3_response,
)
from src.tailor.s3_pipeline import S3Bundle

EDITED_BULLET_ID = "int_b1"
EDITED_BULLET_AFTER = (
    "Built the **anti-corruption layer** and **Core onboarding service** "
    "orchestrating three of four adapter services, five asynchronous Python "
    "microservices in all."
)


def _build_chain(
    *, base_variant="backend",
    must_have_terms=(("Python", "Python"),),
    coverage=(("Python", "covered", ("int_b1",)),),
    open_findings=(),
    injection=(),
    l7_violations=(),
):
    """A genuinely consistent (S3Bundle, G2Bundle, RenderResult, S1, S0, S2)
    tuple built from the real config/master_profile.yaml, parameterized for
    the handful of scenarios Task 5's tests need. No model call, no CLI.
    `coverage` must cover exactly `must_have_terms`, in the same order --
    that is an S2 structural rule, not an M8P-6 one."""
    profile = load_profile("config/master_profile.yaml")
    positioning = profile.for_positioning()
    catalog = profile.for_selection(base_variant)

    jd_text = " ".join(quote for _, quote in must_have_terms) or "Python"
    s1 = parse_s1_response(json.dumps({
        "must_have": [{"term": term, "quote": quote} for term, quote in must_have_terms],
        "nice_to_have": [], "responsibilities_summary": [], "seniority_signals": [],
        "disqualifiers": [], "company_context": None,
        "suspected_injection": [{"quote": q, "reason": r} for q, r in injection],
    }), jd_text)

    s0_request = build_s0_request(1, "Example", "Engineer", s1, positioning)
    s0 = parse_s0_response(json.dumps({
        "context_mode": "jd_only",
        "points": [
            {"sentence": "Lead with backend delivery for this role.",
             "profile_ids": [positioning.projects[0].id],
             "requirement_terms": [must_have_terms[0][0]], "jd_quotes": [must_have_terms[0][1]]},
            {"sentence": "Support the claim with production experience.",
             "profile_ids": [positioning.experiences[0].id],
             "requirement_terms": [must_have_terms[0][0]], "jd_quotes": [must_have_terms[0][1]]},
        ],
    }), s0_request)

    s2_request = build_s2_request(1, "Example", "Engineer", s1, s0, catalog)
    variant = next(item for item in s2_request.catalog.variants if item.name == base_variant)
    raw_s2 = {
        "base_variant": base_variant,
        "projects": [{"project_id": p, "reason": "selected for this role", "s0_point_indexes": [0]} for p in variant.projects],
        "bullet_order": list(variant.bullet_order),
        "coverage": [{"term": term, "status": status, "bullet_ids": list(bids)} for term, status, bids in coverage],
    }
    s2 = parse_s2_response(json.dumps(raw_s2), s2_request)
    # The real profile's "backend" variant canonical bullet order includes
    # ct_b1 (mentions "Kubernetes") while "Kubernetes" is the sole
    # do_not_claim entry -- a pre-existing profile-content condition
    # (M8P-3R/M8P-4/M8P-5), out of scope to fix here. Stripped the same way
    # tests/tailor/conftest.py does for synthetic-chain fixtures.
    from dataclasses import replace as _replace
    alignment = _replace(alignment_from_profile(profile, s2_request, s2), do_not_claim=())
    s3_request = build_s3_request(1, "Example", "Engineer", s1, s0, s2, alignment)

    response = parse_s3_response(json.dumps({
        "bullet_edits": [{
            "bullet_id": EDITED_BULLET_ID, "after": EDITED_BULLET_AFTER,
            "motivating_terms": ["Python"], "rule": "terminology_mirroring",
        }],
        "skill_additions": [],
    }), s3_request)
    draft = hydrate_s3(s3_request, response)
    report = run_static_g1(s3_request, response, draft, ())
    assert report.status.value == "static_pass", report.violations
    change_log = derive_change_log(s3_request, response, draft)
    unified_diff = derive_unified_diff(s3_request, draft)
    edit_budget = calculate_edit_budget(s3_request, draft)
    fingerprint = s3_request.alignment.fingerprint
    s3_bundle = S3Bundle(
        "test.s3_bundle.v1", 1, "Example", "Engineer", fingerprint,
        response, draft, change_log, unified_diff, edit_budget, report,
    )

    findings = tuple(open_findings)
    verdict = G2Verdict.OPEN_FLAGS if findings else G2Verdict.PASS
    flagged_dims = {finding.dimension for finding in findings}
    scores = tuple(
        (dim, 1 if dim in flagged_dims else 3)
        for dim in (G2Dimension.C1, G2Dimension.C2, G2Dimension.C3, G2Dimension.C4, G2Dimension.C5)
    )
    g2_response = G2Response(scores=scores, findings=findings)
    g2_round = G2Round(round_index=1, response=g2_response, verdict=verdict, trace_path=None)
    g2_bundle = G2Bundle(
        "m8p4.g2_bundle.v1", 1, "Example", "Engineer", fingerprint,
        s3_bundle, (g2_round,), verdict, findings, 1, 1,
    )

    render_result = RenderResult(
        "test.render_result.v1", 1, "Example", "Engineer", fingerprint, s3_bundle.schema_version,
        "applications/example-engineer/resume.tex",
        "applications/example-engineer/Himanshu_Jain_Resume.pdf",
        "0" * 64, 1, 12345, (EDITED_BULLET_ID,), ((EDITED_BULLET_ID, 2),),
        tuple(l7_violations), "pass" if not l7_violations else "fail",
    )

    return s3_bundle, g2_bundle, render_result, s1, s0, s2


@pytest.fixture(scope="module")
def full_inputs():
    return _build_chain()


@pytest.fixture(scope="module")
def clean_inputs():
    return _build_chain()


@pytest.fixture(scope="module")
def many_requirements_inputs():
    extra_terms = tuple((f"Skill{i}", f"Skill{i}") for i in range(15))
    must_have_terms = (("Python", "Python"),) + extra_terms
    coverage = (("Python", "covered", ("int_b1",)),) + tuple((term, "gap", ()) for term, _ in extra_terms)
    return _build_chain(must_have_terms=must_have_terms, coverage=coverage)


@pytest.fixture(scope="module")
def gap_and_flag_inputs():
    finding = G2Finding(
        dimension=G2Dimension.C5, rule_id="C5.template_phrasing", target_kind=G2TargetKind.BULLET,
        target_id=EDITED_BULLET_ID, quoted_line="five asynchronous Python microservices",
        explanation="reads as template output",
    )
    return _build_chain(
        must_have_terms=(("Python", "Python"), ("Kubernetes", "Kubernetes required")),
        coverage=(("Python", "covered", ("int_b1",)), ("Kubernetes", "gap", ())),
        open_findings=(finding,),
    )


@pytest.fixture(scope="module")
def other_inputs():
    return _build_chain(base_variant="ml")


@pytest.fixture
def mismatched_inputs(full_inputs):
    from dataclasses import replace
    s3_bundle, g2_bundle, render_result, s1, s0, s2 = full_inputs
    tampered_render = replace(render_result, alignment_fingerprint="0" * 64)
    return s3_bundle, g2_bundle, tampered_render, s1, s0, s2


from src.tailor.g3 import (  # noqa: E402
    G3OutcomeKind,
    MAX_LISTED_REQUIREMENTS,
    build_review_packet,
    packet_to_dict,
    parse_packet,
    publish_packet,
    render_review_markdown,
)


def test_markdown_sections_appear_in_fixed_order(full_inputs):
    text = render_review_markdown(build_review_packet(*full_inputs))
    order = ["## Warnings and open flags", "## What this job asks for",
             "## What was selected and why", "## What changed", "## Coverage",
             "## Gate detail", "## Full diff"]
    positions = [text.index(heading) for heading in order]
    assert positions == sorted(positions)


def test_empty_warnings_render_as_none_not_omitted(clean_inputs):
    text = render_review_markdown(build_review_packet(*clean_inputs))
    section = text.split("## Warnings and open flags", 1)[1].split("##", 1)[0]
    assert "None." in section


def test_long_requirement_list_is_capped_explicitly(many_requirements_inputs):
    packet = build_review_packet(*many_requirements_inputs)
    assert len(packet.requirements) == MAX_LISTED_REQUIREMENTS
    assert packet.requirements_omitted > 0
    assert f"(+{packet.requirements_omitted} more)" in render_review_markdown(packet)


def test_markdown_is_byte_identical_across_runs(full_inputs):
    packet = build_review_packet(*full_inputs)
    assert render_review_markdown(packet) == render_review_markdown(packet)


def test_packet_round_trips_strictly(full_inputs):
    packet = build_review_packet(*full_inputs)
    assert parse_packet(packet_to_dict(packet)) == packet


def test_fingerprint_disagreement_between_inputs_fails_closed(mismatched_inputs):
    from src.tailor.g3 import G3Error
    with pytest.raises(G3Error, match="fingerprint"):
        build_review_packet(*mismatched_inputs)


def test_gap_terms_and_open_findings_appear_in_warnings(gap_and_flag_inputs):
    packet = build_review_packet(*gap_and_flag_inputs)
    joined = " ".join(packet.warnings)
    assert "GAP" in joined
    assert "C5" in joined


def test_publish_refuses_to_overwrite_a_different_packet(full_inputs, tmp_path, other_inputs):
    packet = build_review_packet(*full_inputs)
    publish_packet(packet, ("b1",), tmp_path)
    before = (tmp_path / "packet.json").read_bytes()
    outcome = publish_packet(build_review_packet(*other_inputs), ("b1",), tmp_path)
    assert outcome.kind is G3OutcomeKind.CONFLICT
    assert (tmp_path / "packet.json").read_bytes() == before


def test_publish_is_idempotent_for_the_same_packet(full_inputs, tmp_path):
    packet = build_review_packet(*full_inputs)
    publish_packet(packet, ("b1",), tmp_path)
    assert publish_packet(packet, ("b1",), tmp_path).kind is G3OutcomeKind.ALREADY_BUILT


def test_publish_emits_all_three_files(full_inputs, tmp_path):
    publish_packet(build_review_packet(*full_inputs), ("b1",), tmp_path)
    for name in ("review.md", "packet.json", "feedback_form.yaml"):
        assert (tmp_path / name).exists()


def test_g3_module_makes_no_model_call():
    from pathlib import Path
    source = Path("src/tailor/g3.py").read_text(encoding="utf-8")
    assert "src.tailor.invoke" not in source and "src.llm_trace" not in source
