"""Replay real recorded model output as parser fixtures (M8V-1 Task 2). No
model call, no network -- every fixture here is a real I11 trace's
raw_output, extracted once via scripts/record_trace_fixture.py and
committed. Self-authored synthetic fixtures could never have caught the
two live S1 failures this file replays."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.s0 import build_s0_request, parse_s0_response
from src.tailor.s1 import S1ParseError, S1SemanticError, parse_s1_request, parse_s1_response
from src.tailor.s2 import ProjectChoice, S2Response, build_s2_request, parse_s2_response
from src.tailor.s3 import S3ParseError, S3SemanticError, build_s3_request, parse_s3_response
from tests.fixtures.tailor.traces import context

FIXTURES = Path("tests/fixtures/tailor/traces")

# ---------------------------------------------------------------------------
# 2026-09-15 blueprint shape shim.
#
# The frozen traces below were recorded against the base_variants shape that
# existed immediately before commit ca73a01 introduced the approved resume
# blueprint (7 Amdocs / 3 MalyTech / 2+2+1 project bullets). They are real
# model I/O, captured once and committed -- never edited to match a shape
# change. Read from `git show aaefb15:config/master_profile.yaml` (the
# commit right before the blueprint), not invented, not copied from a
# prompt: aaefb15's "ml" variant selected (sepsis_early_warning,
# fake_review_detection) across 12 bullets; its "backend" variant selected
# (clinical_trial_platform, campus_marketplace) across 12 bullets. Both
# projects and every bullet id below still exist, unblocked, in the current
# profile -- only the CURRENT base_variants' proportions moved on. This
# helper overrides just the named variant's shape inside an already-built
# SelectionCatalog so S2's shape validator sees the shape the trace was
# actually recorded against; config/master_profile.yaml is never touched.
# ---------------------------------------------------------------------------

_RECORDING_TIME_VARIANT_SHAPES = {
    "ml": dict(
        projects=("sepsis_early_warning", "fake_review_detection"),
        bullet_order=(
            "int_b1", "int_b2", "int_b3", "am_b00_order_management_domain",
            "am_b04_data_retention", "am_b05_test_automation", "am_b03_audit_trail",
            "am_b01_dlq_consolidation", "am_b02_row_level_entitlement",
            "sepsis_b3", "frd_b1", "frd_b3",
        ),
        experience_order=("bank_integration_internship", "amdocs_software_developer"),
        experience_bullet_counts=(("bank_integration_internship", 3), ("amdocs_software_developer", 6)),
    ),
    "backend": dict(
        projects=("clinical_trial_platform", "campus_marketplace"),
        bullet_order=(
            "int_b1", "int_b2", "int_b3", "am_b00_order_management_domain",
            "am_b04_data_retention", "am_b05_test_automation", "am_b03_audit_trail",
            "am_b01_dlq_consolidation", "ct_b1", "ct_b2", "cm_b1", "cm_b2",
        ),
        experience_order=("bank_integration_internship", "amdocs_software_developer"),
        experience_bullet_counts=(("bank_integration_internship", 3), ("amdocs_software_developer", 5)),
    ),
}


def recording_time_catalog(catalog, variant_name: str):
    """Return `catalog` with `variant_name`'s shape replaced by the shape it
    was actually recorded against (see module docstring above)."""
    shape = _RECORDING_TIME_VARIANT_SHAPES[variant_name]
    variants = tuple(
        replace(v, **shape) if v.name == variant_name else v
        for v in catalog.variants
    )
    return replace(catalog, variants=variants)

from scripts.record_trace_fixture import record_trace_fixture  # noqa: E402


# ---------------------------------------------------------------------------
# The privacy gate
# ---------------------------------------------------------------------------


@pytest.fixture
def trace_with_phone(tmp_path):
    profile = load_profile("config/master_profile.yaml")
    phone = profile.identity["phone"]
    trace_path = tmp_path / "leaky_trace.json"
    trace_path.write_text(json.dumps({
        "invocation_type": "test", "timestamp": "2026-01-01T00:00:00+00:00",
        "model": "test", "prompt_hash": "test", "inputs": [],
        "raw_output": f'{{"note": "call me at {phone}"}}',
    }), encoding="utf-8")
    return trace_path


def test_recorder_refuses_identity_leakage(trace_with_phone, tmp_path):
    with pytest.raises(ValueError, match="identity"):
        record_trace_fixture(trace_with_phone, tmp_path / "leaky.txt")
    assert not (tmp_path / "leaky.txt").exists()


def test_no_committed_fixture_contains_identity():
    values = [v for v in load_profile("config/master_profile.yaml").identity.values() if v]
    for f in FIXTURES.glob("*.txt"):
        text = f.read_text(encoding="utf-8")
        for v in values:
            assert v not in text, f"{f.name} leaks {v!r}"


# ---------------------------------------------------------------------------
# The two live S1 failures this whole task exists to replay
# ---------------------------------------------------------------------------


@pytest.fixture
def s1_request_fixture():
    return parse_s1_request(context.CISCO_S1_REQUEST)


@pytest.fixture
def notion_s1_request_fixture():
    return parse_s1_request(context.NOTION_S1_REQUEST)


def test_recorded_fenced_response_is_rejected_by_the_parser(s1_request_fixture):
    raw = (FIXTURES / "s1_fenced_rejected.txt").read_text(encoding="utf-8")
    with pytest.raises(S1ParseError):
        parse_s1_response(raw, s1_request_fixture.jd_text)


def test_recorded_curly_apostrophe_response_is_rejected(notion_s1_request_fixture):
    raw = (FIXTURES / "s1_curly_apostrophe_rejected.txt").read_text(encoding="utf-8")
    with pytest.raises(S1SemanticError, match="exact substring"):
        parse_s1_response(raw, notion_s1_request_fixture.jd_text)


# ---------------------------------------------------------------------------
# Every recorded accepted response must still parse -- the regression guard
# self-authored fixtures could never provide.
# ---------------------------------------------------------------------------


def _cisco_chain():
    """The real Cisco (119, ml variant) S1->S0->S2 chain, reconstructed from
    committed fixtures against the real profile -- the same construction
    scripts/tailor_pilot.py performs, just replayed offline."""
    profile = load_profile("config/master_profile.yaml")
    s1_request = parse_s1_request(context.CISCO_S1_REQUEST)
    s1_raw = (FIXTURES / "s1_accepted.txt").read_text(encoding="utf-8")
    s1 = parse_s1_response(s1_raw, s1_request.jd_text)

    positioning = profile.for_positioning()
    s0_request = build_s0_request(s1_request.job_id, s1_request.company, s1_request.title, s1, positioning)
    s0_raw = (FIXTURES / "s0_accepted.txt").read_text(encoding="utf-8")
    s0 = parse_s0_response(s0_raw, s0_request)

    catalog = recording_time_catalog(profile.for_selection("ml"), "ml")
    s2_request = build_s2_request(s1_request.job_id, s1_request.company, s1_request.title, s1, s0, catalog)
    s2_raw = (FIXTURES / "s2_accepted.txt").read_text(encoding="utf-8")
    s2 = parse_s2_response(s2_raw, s2_request)

    return profile, s1_request, s1, s0, s2_request, s2


def test_recorded_accepted_s1_parses(s1_request_fixture):
    raw = (FIXTURES / "s1_accepted.txt").read_text(encoding="utf-8")
    assert parse_s1_response(raw, s1_request_fixture.jd_text) is not None


def test_recorded_accepted_s0_parses():
    _, s1_request, s1, s0, _, _ = _cisco_chain()
    assert s0 is not None


def test_recorded_accepted_s2_parses():
    _, _, _, _, s2_request, s2 = _cisco_chain()
    assert s2 is not None


def test_recorded_accepted_s3_parses():
    """A real, accepted, zero-edit S3 response (job 225 Notion) -- S3
    correctly declining to fabricate an edit when there is nothing to
    cover is itself a legitimate accepted response."""
    profile = load_profile("config/master_profile.yaml")
    s1_request = parse_s1_request(context.NOTION_S1_REQUEST)
    s1 = parse_s1_response(context.NOTION_S1_RESPONSE_RAW, s1_request.jd_text)
    s0_request = build_s0_request(s1_request.job_id, s1_request.company, s1_request.title, s1, profile.for_positioning())
    s0 = parse_s0_response(context.NOTION_S0_RESPONSE_RAW, s0_request)
    catalog = recording_time_catalog(profile.for_selection("backend"), "backend")
    s2_request = build_s2_request(s1_request.job_id, s1_request.company, s1_request.title, s1, s0, catalog)
    s2 = parse_s2_response(context.NOTION_S2_RESPONSE_RAW, s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2)
    s3_request = build_s3_request(s1_request.job_id, s1_request.company, s1_request.title, s1, s0, s2, alignment)

    raw = (FIXTURES / "s3_accepted.txt").read_text(encoding="utf-8")
    response = parse_s3_response(raw, s3_request)
    assert response is not None
    assert response.bullet_edits == ()


def test_recorded_accepted_g2_parses():
    """The recorded G2 accepted response (all scores 3, no findings) --
    parse_g2_response needs only the raw JSON's own shape; scores/findings
    validation has nothing to anchor against when findings is empty."""
    from src.tailor.g2 import G2Request, parse_g2_response
    from src.tailor.s0 import S0Response

    request = G2Request(
        job_id=225, company="Notion", title="Software Engineer", context_mode="jd_only",
        round_index=1, positioning=S0Response(context_mode="jd_only", points=()),
        must_have=(), nice_to_have=(), coverage=(), changed_bullets=(), skill_additions=(),
        unchanged_bullets=(), unified_diff="", banned_terms=(), taste_lessons=(),
        prior_findings=(), alignment_fingerprint="", bundle_schema_version="m8p3r.s3_bundle.v1",
    )
    raw = (FIXTURES / "g2_accepted.txt").read_text(encoding="utf-8")
    response = parse_g2_response(raw, request)
    assert response is not None
    assert response.findings == ()


def test_scikit_learn_length_growth_is_still_rejected():
    """The one failure of the eight that was the model misbehaving, not
    our own artifacts -- and the guard caught it correctly. This fixture
    proves the guard keeps catching it."""
    _, s1_request, s1, s0, s2_request, s2 = _cisco_chain()
    profile = load_profile("config/master_profile.yaml")
    alignment = alignment_from_profile(profile, s2_request, s2)
    s3_request = build_s3_request(s1_request.job_id, s1_request.company, s1_request.title, s1, s0, s2, alignment)

    raw = (FIXTURES / "s3_length_growth_rejected.txt").read_text(encoding="utf-8")
    # before: 215 chars ("...fusing them through a logistic-regression...")
    # after:  228 chars ("...fusing them through a scikit-learn logistic-regression...")
    # motivating_term: "scikit-learn" (12 chars)
    # 228 - 215 = 13 > 12 budget. The margin is exactly 1 char, which is intentionally thin and within spec B5.
    with pytest.raises(S3SemanticError, match="length grew beyond the mirrored term"):
        parse_s3_response(raw, s3_request)
