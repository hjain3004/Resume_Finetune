import json

import pytest

from src.tailor.g2 import (
    G2ParseError,
    G2SemanticError,
    build_g2_request,
    g2_request_to_dict,
    parse_g2_request,
    parse_g2_response,
)
from tests.fixtures.tailor.m8p4_builders import finding_dict, valid_scores
from tests.tailor.conftest import UNCHANGED_BULLET_ID


def _keys(value):
    """Structural key walk (matches the M8P-3R alignment-view privacy test
    precedent): checks dict KEYS only, not substrings of string VALUES, so
    a bullet legitimately mentioning e.g. "identity verification" as domain
    vocabulary does not false-positive against the forbidden *field name*
    list below."""
    if isinstance(value, dict):
        return set(value) | (set().union(*(_keys(v) for v in value.values())) if value else set())
    if isinstance(value, list):
        return set().union(*(_keys(v) for v in value)) if value else set()
    return set()


def test_request_round_trips_and_omits_private_fields(s3_pair_with_bundle):
    s3_request, bundle = s3_pair_with_bundle
    request = build_g2_request(
        s3_request, bundle, round_index=1, banned_terms=("spearheaded",), taste_lessons=()
    )
    rendered = json.dumps(g2_request_to_dict(request))
    reparsed = json.loads(rendered)
    for forbidden in (
        "jd_text", "identity", "education", "evidence",
        "defense", "interview_risk", "metric_ledger", "known_gaps",
    ):
        assert forbidden not in _keys(reparsed)
    assert parse_g2_request(reparsed) == request


def test_response_rejects_quote_absent_from_target(g2_request_one_edit):
    raw = json.dumps({
        "scores": valid_scores(C5=2),
        "findings": [finding_dict(quoted_line="text that is not in the bullet")],
    })
    with pytest.raises(G2SemanticError, match="quoted_line"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_finding_targeting_unchanged_bullet(g2_request_one_edit):
    raw = json.dumps({
        "scores": valid_scores(C4=2),
        "findings": [finding_dict(
            dimension="C4", rule_id="C4.signal_below_fold", target_id=UNCHANGED_BULLET_ID,
        )],
    })
    with pytest.raises(G2SemanticError, match="out of scope"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_low_score_without_finding(g2_request_one_edit):
    raw = json.dumps({"scores": valid_scores(C2=2), "findings": []})
    with pytest.raises(G2SemanticError, match="C2"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_finding_on_dimension_scored_three(g2_request_one_edit):
    raw = json.dumps({"scores": valid_scores(), "findings": [finding_dict()]})
    with pytest.raises(G2SemanticError, match="C5"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_rule_id_from_another_dimension(g2_request_one_edit):
    raw = json.dumps({
        "scores": valid_scores(C2=2),
        "findings": [finding_dict(dimension="C2", rule_id="C5.template_phrasing")],
    })
    with pytest.raises(G2SemanticError, match="rule_id"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_markdown_fence(g2_request_one_edit):
    raw = "```json\n{\"scores\": {}, \"findings\": []}\n```"
    with pytest.raises(G2ParseError):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_boolean_score(g2_request_one_edit):
    raw = json.dumps({"scores": valid_scores(C1=True), "findings": []})
    with pytest.raises(G2ParseError, match="C1"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_more_than_eight_findings(g2_request_one_edit):
    raw = json.dumps({
        "scores": valid_scores(C5=2),
        "findings": [finding_dict(explanation=f"issue {i}") for i in range(9)],
    })
    with pytest.raises(G2ParseError, match="findings"):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_rejects_unexpected_field(g2_request_one_edit):
    raw = json.dumps({
        "scores": valid_scores(), "findings": [], "revised_bullet": "any text at all",
    })
    with pytest.raises(G2ParseError):
        parse_g2_response(raw, g2_request_one_edit)


def test_response_accepts_valid_finding_and_round_trips(g2_request_one_edit):
    raw = json.dumps({"scores": valid_scores(C5=2), "findings": [finding_dict()]})
    response = parse_g2_response(raw, g2_request_one_edit)
    assert response.findings[0].target_id == "int_b1"
    from src.tailor.g2 import g2_response_to_dict

    assert json.loads(json.dumps(g2_response_to_dict(response)))["scores"]["C5"] == 2


# ---------------------------------------------------------------------------
# Task 2: verdict rule and finding-resolution checks
# ---------------------------------------------------------------------------


@pytest.fixture
def make_response():
    from src.tailor.g2 import RULE_VOCABULARY, G2Dimension, G2Finding, G2Response, G2TargetKind

    def _make(**scores) -> G2Response:
        full = valid_scores(**scores)
        findings = []
        for key, value in full.items():
            dimension = G2Dimension(key)
            if value < 3:
                findings.append(G2Finding(
                    dimension=dimension,
                    rule_id=next(iter(RULE_VOCABULARY[dimension])),
                    target_kind=G2TargetKind.BULLET,
                    target_id="int_b1",
                    quoted_line="four asynchronous Python microservices",
                    explanation="synthetic",
                ))
        return G2Response(
            scores=tuple((G2Dimension(key), value) for key, value in full.items()),
            findings=tuple(findings),
        )

    return _make


@pytest.fixture
def one_finding():
    from src.tailor.g2 import G2Dimension, G2Finding, G2TargetKind

    return G2Finding(
        dimension=G2Dimension.C5,
        rule_id="C5.template_phrasing",
        target_kind=G2TargetKind.BULLET,
        target_id="int_b1",
        quoted_line="improved throughput by 40%",
        explanation="reads as template output",
    )


def test_pass_requires_c1_exactly_three(make_response):
    from src.tailor.g2 import G2Verdict, evaluate_verdict

    assert evaluate_verdict(make_response(C1=3, C2=2, C3=2, C4=2, C5=2), round_index=1) is G2Verdict.PASS
    assert evaluate_verdict(make_response(C1=2, C2=3, C3=3, C4=3, C5=3), round_index=1) is G2Verdict.REVISE


def test_any_dimension_at_one_fails(make_response):
    from src.tailor.g2 import G2Verdict, evaluate_verdict

    assert evaluate_verdict(make_response(C1=3, C2=1, C3=3, C4=3, C5=3), round_index=1) is G2Verdict.REVISE


def test_final_round_failure_becomes_open_flags(make_response):
    from src.tailor.g2 import G2Verdict, evaluate_verdict

    assert evaluate_verdict(make_response(C1=2, C2=3, C3=3, C4=3, C5=3), round_index=2) is G2Verdict.OPEN_FLAGS


def test_unresolved_findings_detects_untouched_quote(one_finding):
    from src.tailor.g2 import unresolved_findings

    still = unresolved_findings((one_finding,), {"int_b1": "improved throughput by 40%"})
    assert still == (one_finding,)


def test_unresolved_findings_clears_when_quote_gone(one_finding):
    from src.tailor.g2 import unresolved_findings

    assert unresolved_findings((one_finding,), {"int_b1": "raised throughput 40%"}) == ()


def test_unresolved_findings_clears_when_target_missing(one_finding):
    from src.tailor.g2 import unresolved_findings

    assert unresolved_findings((one_finding,), {}) == ()
