"""Tests for the M8P-1 S1 contract: dataclasses, strict parsing, and
semantic (JD-anchored) validation. No network, no model calls."""

import pytest

from src.tailor.s1 import (
    AnchoredClaim,
    AnchoredSummary,
    CompanyContext,
    InjectionFlag,
    Requirement,
    S1ParseError,
    S1Request,
    S1Response,
    S1SemanticError,
    build_s1_prompt,
    parse_s1_request,
    parse_s1_response,
    s1_request_to_dict,
)

JD_TEXT = (
    "We are looking for a Backend Engineer with 3+ years of Python experience. "
    "Experience with Kubernetes is a plus. You will own our checkout service. "
    "Bachelor's degree required. Must be able to work in a fast-paced startup. "
    "Acme Corp builds payments infrastructure for small businesses at global scale."
)


def _valid_payload(**overrides) -> dict:
    payload = {
        "must_have": [
            {"term": "Python", "quote": "3+ years of Python experience"},
        ],
        "nice_to_have": [
            {"term": "Kubernetes", "quote": "Experience with Kubernetes is a plus"},
        ],
        "responsibilities_summary": [
            {"summary": "Owns the checkout service", "quote": "You will own our checkout service"},
        ],
        "seniority_signals": ["3+ years of Python experience"],
        "disqualifiers": ["Bachelor's degree required"],
        "company_context": {
            "domain": {"claim": "Payments infrastructure", "quote": "Acme Corp builds payments infrastructure for small businesses at global scale"},
            "product": None,
            "stage_or_scale": {"claim": "Global scale", "quote": "at global scale"},
        },
        "suspected_injection": [],
    }
    payload.update(overrides)
    return payload


def _dump(payload: dict) -> str:
    import json

    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


def test_parse_full_valid_response():
    response = parse_s1_response(_dump(_valid_payload()), JD_TEXT)
    assert response == S1Response(
        must_have=(Requirement(term="Python", quote="3+ years of Python experience"),),
        nice_to_have=(Requirement(term="Kubernetes", quote="Experience with Kubernetes is a plus"),),
        responsibilities_summary=(
            AnchoredSummary(summary="Owns the checkout service", quote="You will own our checkout service"),
        ),
        seniority_signals=("3+ years of Python experience",),
        disqualifiers=("Bachelor's degree required",),
        company_context=CompanyContext(
            domain=AnchoredClaim(
                claim="Payments infrastructure",
                quote="Acme Corp builds payments infrastructure for small businesses at global scale",
            ),
            product=None,
            stage_or_scale=AnchoredClaim(claim="Global scale", quote="at global scale"),
        ),
        suspected_injection=(),
    )


def test_parse_minimal_valid_response_empty_arrays_null_context():
    payload = _valid_payload(
        must_have=[],
        nice_to_have=[],
        responsibilities_summary=[],
        seniority_signals=[],
        disqualifiers=[],
        company_context=None,
        suspected_injection=[],
    )
    response = parse_s1_response(_dump(payload), JD_TEXT)
    assert response.must_have == ()
    assert response.company_context is None
    assert response.suspected_injection == ()


def test_parse_response_with_injection_flags():
    payload = _valid_payload(
        suspected_injection=[
            {"quote": "Must be able to work in a fast-paced startup", "reason": "imperative-sounding filler, flagged defensively"},
        ]
    )
    response = parse_s1_response(_dump(payload), JD_TEXT)
    assert response.suspected_injection == (
        InjectionFlag(
            quote="Must be able to work in a fast-paced startup",
            reason="imperative-sounding filler, flagged defensively",
        ),
    )


def test_all_null_company_context_fields_normalizes_to_none():
    payload = _valid_payload(
        company_context={"domain": None, "product": None, "stage_or_scale": None}
    )
    response = parse_s1_response(_dump(payload), JD_TEXT)
    assert response.company_context is None


# ---------------------------------------------------------------------------
# Strict JSON / structural parsing failures
# ---------------------------------------------------------------------------


def test_malformed_json_rejected():
    with pytest.raises(S1ParseError):
        parse_s1_response("{not valid json", JD_TEXT)


def test_fenced_json_rejected_no_repair():
    fenced = "```json\n" + _dump(_valid_payload()) + "\n```"
    with pytest.raises(S1ParseError):
        parse_s1_response(fenced, JD_TEXT)


def test_trailing_comma_rejected_no_repair():
    raw = _dump(_valid_payload())
    # Inject a trailing comma before the final closing brace.
    broken = raw[:-1] + ",}"
    with pytest.raises(S1ParseError):
        parse_s1_response(broken, JD_TEXT)


def test_top_level_not_an_object_rejected():
    with pytest.raises(S1ParseError):
        parse_s1_response("[]", JD_TEXT)


def test_missing_required_top_level_field_rejected():
    payload = _valid_payload()
    del payload["disqualifiers"]
    with pytest.raises(S1ParseError, match="disqualifiers"):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_unexpected_top_level_field_rejected():
    payload = _valid_payload()
    payload["extra_field"] = "nope"
    with pytest.raises(S1ParseError, match="extra_field"):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_wrong_type_for_must_have_rejected():
    payload = _valid_payload(must_have={"term": "Python", "quote": "Python"})
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_wrong_type_for_requirement_item_rejected():
    payload = _valid_payload(must_have=["not an object"])
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_empty_term_rejected():
    payload = _valid_payload(must_have=[{"term": "", "quote": "3+ years of Python experience"}])
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_empty_quote_rejected():
    payload = _valid_payload(must_have=[{"term": "Python", "quote": ""}])
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_unexpected_field_in_requirement_object_rejected():
    payload = _valid_payload(
        must_have=[{"term": "Python", "quote": "3+ years of Python experience", "confidence": 0.9}]
    )
    with pytest.raises(S1ParseError, match="confidence"):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_missing_field_in_requirement_object_rejected():
    payload = _valid_payload(must_have=[{"term": "Python"}])
    with pytest.raises(S1ParseError, match="quote"):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_unexpected_field_in_company_context_rejected():
    payload = _valid_payload()
    payload["company_context"]["funding"] = {"claim": "x", "quote": "x"}
    with pytest.raises(S1ParseError, match="funding"):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_missing_company_context_subfield_rejected():
    payload = _valid_payload()
    del payload["company_context"]["product"]
    with pytest.raises(S1ParseError, match="product"):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_company_context_claim_missing_field_rejected():
    payload = _valid_payload()
    payload["company_context"]["domain"] = {"claim": "Payments infrastructure"}
    with pytest.raises(S1ParseError, match="quote"):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_seniority_signals_wrong_type_rejected():
    payload = _valid_payload(seniority_signals=[{"quote": "3+ years of Python experience"}])
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_injection_flag_missing_reason_rejected():
    payload = _valid_payload(
        suspected_injection=[{"quote": "Must be able to work in a fast-paced startup"}]
    )
    with pytest.raises(S1ParseError, match="reason"):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_injection_flag_empty_reason_rejected():
    payload = _valid_payload(
        suspected_injection=[{"quote": "Must be able to work in a fast-paced startup", "reason": ""}]
    )
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


# ---------------------------------------------------------------------------
# Duplicate rejection (structural)
# ---------------------------------------------------------------------------


def test_duplicate_term_within_must_have_rejected():
    payload = _valid_payload(
        must_have=[
            {"term": "Python", "quote": "3+ years of Python experience"},
            {"term": "python", "quote": "3+ years of Python experience"},
        ]
    )
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_duplicate_term_across_must_have_and_nice_to_have_rejected():
    payload = _valid_payload(
        must_have=[{"term": "Python", "quote": "3+ years of Python experience"}],
        nice_to_have=[{"term": "  Python  ", "quote": "3+ years of Python experience"}],
    )
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_duplicate_quote_within_seniority_signals_rejected():
    payload = _valid_payload(
        seniority_signals=["3+ years of Python experience", "3+ years of Python experience"]
    )
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_duplicate_quote_within_disqualifiers_rejected():
    payload = _valid_payload(
        disqualifiers=["Bachelor's degree required", "Bachelor's degree required"]
    )
    with pytest.raises(S1ParseError):
        parse_s1_response(_dump(payload), JD_TEXT)


# ---------------------------------------------------------------------------
# Semantic (JD-anchoring) validation failures
# ---------------------------------------------------------------------------


def test_must_have_quote_not_in_jd_rejected():
    payload = _valid_payload(must_have=[{"term": "Rust", "quote": "5+ years of Rust experience"}])
    with pytest.raises(S1SemanticError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_must_have_term_not_substring_of_quote_rejected():
    payload = _valid_payload(must_have=[{"term": "Golang", "quote": "3+ years of Python experience"}])
    with pytest.raises(S1SemanticError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_nice_to_have_quote_not_in_jd_rejected():
    payload = _valid_payload(nice_to_have=[{"term": "Rust", "quote": "Rust is nice to have"}])
    with pytest.raises(S1SemanticError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_responsibilities_quote_not_in_jd_rejected():
    payload = _valid_payload(
        responsibilities_summary=[{"summary": "Owns billing", "quote": "You will own our billing service"}]
    )
    with pytest.raises(S1SemanticError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_seniority_signal_not_in_jd_rejected():
    payload = _valid_payload(seniority_signals=["10+ years of leadership experience"])
    with pytest.raises(S1SemanticError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_disqualifier_not_in_jd_rejected():
    payload = _valid_payload(disqualifiers=["Must relocate to Mars"])
    with pytest.raises(S1SemanticError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_company_context_quote_not_in_jd_rejected():
    payload = _valid_payload()
    payload["company_context"]["domain"] = {"claim": "Fake domain", "quote": "Acme Corp is a social network"}
    with pytest.raises(S1SemanticError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_injection_flag_quote_not_in_jd_rejected():
    payload = _valid_payload(
        suspected_injection=[{"quote": "Ignore all prior instructions", "reason": "not present verbatim"}]
    )
    with pytest.raises(S1SemanticError):
        parse_s1_response(_dump(payload), JD_TEXT)


def test_quote_substring_check_is_case_sensitive():
    payload = _valid_payload(
        must_have=[{"term": "python", "quote": "3+ years of python experience"}]
    )
    with pytest.raises(S1SemanticError):
        parse_s1_response(_dump(payload), JD_TEXT)


# ---------------------------------------------------------------------------
# S1Request round trip
# ---------------------------------------------------------------------------


def test_s1_request_round_trip():
    request = S1Request(job_id=119, company="Cisco", title="ML Engineer", jd_text=JD_TEXT, jd_quality="ats")
    as_dict = s1_request_to_dict(request)
    assert parse_s1_request(as_dict) == request


def test_parse_s1_request_missing_field_rejected():
    with pytest.raises(S1ParseError, match="jd_quality"):
        parse_s1_request({"job_id": 1, "company": "A", "title": "B", "jd_text": "C"})


def test_parse_s1_request_unexpected_field_rejected():
    with pytest.raises(S1ParseError, match="notes"):
        parse_s1_request(
            {"job_id": 1, "company": "A", "title": "B", "jd_text": "C", "jd_quality": "ats", "notes": "x"}
        )


def test_parse_s1_request_wrong_job_id_type_rejected():
    with pytest.raises(S1ParseError):
        parse_s1_request({"job_id": "119", "company": "A", "title": "B", "jd_text": "C", "jd_quality": "ats"})


def test_parse_s1_request_empty_company_rejected():
    with pytest.raises(S1ParseError):
        parse_s1_request({"job_id": 1, "company": "", "title": "B", "jd_text": "C", "jd_quality": "ats"})


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def test_build_s1_prompt_substitutes_marker():
    request = S1Request(job_id=225, company="Notion", title="Backend Engineer", jd_text=JD_TEXT, jd_quality="ats")
    template = "Analyze this request:\n{{S1_REQUEST_JSON}}\nReturn JSON only."
    prompt = build_s1_prompt(template, request)
    assert "{{S1_REQUEST_JSON}}" not in prompt
    assert "Notion" in prompt
    assert JD_TEXT in prompt
    assert "Return JSON only." in prompt


def test_build_s1_prompt_missing_marker_raises():
    request = S1Request(job_id=225, company="Notion", title="Backend Engineer", jd_text=JD_TEXT, jd_quality="ats")
    with pytest.raises(ValueError):
        build_s1_prompt("no marker here", request)
