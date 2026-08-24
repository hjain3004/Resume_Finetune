import json

import pytest

from src.profile import load_profile
from src.tailor.s0 import S0ParseError, S0SemanticError, build_s0_prompt, build_s0_request, parse_s0_response
from src.tailor.s1 import parse_s1_response


@pytest.fixture
def s0_request_fixture():
    profile = load_profile("config/master_profile.yaml")
    s1 = parse_s1_response(json.dumps({
        "must_have": [{"term": "Python", "quote": "Python"}],
        "nice_to_have": [], "responsibilities_summary": [], "seniority_signals": [],
        "disqualifiers": [], "company_context": None, "suspected_injection": [],
    }), "Python")
    return build_s0_request(4, "Company", "Role", s1, profile.for_positioning())


def _raw(points=2, **overrides):
    point = {"sentence": "Lead with Python.", "profile_ids": ["peerchat_peer_discovery"], "requirement_terms": ["Python"], "jd_quotes": ["Python"]}
    values = {"context_mode": "jd_only", "points": [point, {**point, "sentence": "Support with delivery."}]}
    values.update(overrides)
    values["points"] = values["points"][:points] if points <= 2 else values["points"] + [dict(point, sentence=f"Point {i}") for i in range(3, points + 1)]
    return json.dumps(values)


@pytest.mark.parametrize("raw", ["not json", "```json\n{}\n```", '{"context_mode":"jd_only",}'])
def test_s0_rejects_non_strict_json(raw, s0_request_fixture):
    with pytest.raises(S0ParseError):
        parse_s0_response(raw, s0_request_fixture)


@pytest.mark.parametrize("points", [1, 5])
def test_s0_enforces_point_bounds(points, s0_request_fixture):
    with pytest.raises(S0ParseError):
        parse_s0_response(_raw(points), s0_request_fixture)


def test_s0_rejects_unknown_quote_term_and_context(s0_request_fixture):
    for field, value in (("jd_quotes", ["not in S1"]), ("requirement_terms", ["Go"]), ("profile_ids", ["fake"])):
        raw = json.loads(_raw())
        raw["points"][0][field] = value
        with pytest.raises(S0SemanticError):
            parse_s0_response(json.dumps(raw), s0_request_fixture)
    raw = json.loads(_raw()); raw["context_mode"] = "company_bank"
    with pytest.raises(S0SemanticError):
        parse_s0_response(json.dumps(raw), s0_request_fixture)


def test_s0_rejects_duplicate_normalized_sentence_and_point_citations(s0_request_fixture):
    raw = json.loads(_raw()); raw["points"][1]["sentence"] = "  LEAD   WITH python. "
    with pytest.raises(S0ParseError):
        parse_s0_response(json.dumps(raw), s0_request_fixture)
    raw = json.loads(_raw()); raw["points"][0]["requirement_terms"] = ["Python", " python "]
    with pytest.raises(S0ParseError):
        parse_s0_response(json.dumps(raw), s0_request_fixture)


def test_s0_prompt_requires_marker_and_contains_contract(s0_request_fixture):
    template = open("docs/prompts/tailoring_s0.md").read()
    prompt = build_s0_prompt(template, s0_request_fixture)
    assert '"context_mode": "jd_only"' in prompt and '"points"' in template
    with pytest.raises(ValueError):
        build_s0_prompt("no marker", s0_request_fixture)
