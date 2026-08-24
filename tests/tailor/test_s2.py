import copy
import json
from dataclasses import replace

import pytest
from pathlib import Path

from src.profile import load_profile
from src.tailor.s2 import S2ParseError, S2ValidationError, build_s2_request, build_s2_prompt, parse_s2_response
from tests.tailor.test_m8p2_contracts import _fixtures


def _request():
    profile = load_profile("config/master_profile.yaml")
    _, catalog, s1, s0 = _fixtures()
    return build_s2_request(1, "Example", "Engineer", s1, s0, catalog)


def _valid(request):
    variant = next(item for item in request.catalog.variants if item.name == "backend")
    return {
        "base_variant": "backend",
        "projects": [{"project_id": item, "reason": "selected", "s0_point_indexes": [0]} for item in variant.projects],
        "bullet_order": list(variant.bullet_order),
        "coverage": [{"term": "Python", "status": "covered", "bullet_ids": ["int_b1"]}],
    }


def test_s2_valid_shape_round_trips():
    request = _request()
    raw = _valid(request)
    assert parse_s2_response(json.dumps(raw), request).bullet_order == tuple(raw["bullet_order"])


def test_s2_accepts_distinct_s0_point_indexes_in_supplied_order():
    request = _request()
    raw = _valid(request)
    raw["projects"][0]["s0_point_indexes"] = [0, 1]
    response = parse_s2_response(json.dumps(raw), request)
    assert response.projects[0].s0_point_indexes == (0, 1)


def test_s2_rejects_duplicate_s0_point_indexes_within_project_choice():
    request = _request()
    raw = _valid(request)
    raw["projects"][0]["s0_point_indexes"] = [0, 0]
    with pytest.raises(S2ParseError, match=r"projects\[0\]\.s0_point_indexes: duplicate values"):
        parse_s2_response(json.dumps(raw), request)


@pytest.mark.parametrize("change", [
    lambda x: x.__setitem__("base_variant", "unknown"),
    lambda x: x["projects"].append(copy.deepcopy(x["projects"][0])),
    lambda x: x.__setitem__("projects", x["projects"][:-1]),
    lambda x: x["projects"].extend([{"project_id": "campus_marketplace", "reason": "x", "s0_point_indexes": [0]}]),
    lambda x: x["projects"][0].__setitem__("s0_point_indexes", [99]),
    lambda x: x["projects"][0].__setitem__("s0_point_indexes", [-1]),
    lambda x: x["bullet_order"].pop(),
    lambda x: x["bullet_order"].__setitem__(0, "fabricated"),
    lambda x: x["coverage"].__setitem__(0, {"term": "Python", "status": "covered", "bullet_ids": ["missing"]}),
])
def test_s2_rejects_invalid_selection_constraints(change):
    request = _request(); raw = _valid(request); change(raw)
    with pytest.raises((S2ParseError, S2ValidationError)):
        parse_s2_response(json.dumps(raw), request)


@pytest.mark.parametrize("indexes", [[], [True], ["0"]])
def test_s2_rejects_empty_boolean_and_non_integer_s0_indexes(indexes):
    request = _request()
    raw = _valid(request)
    raw["projects"][0]["s0_point_indexes"] = indexes
    with pytest.raises(S2ParseError):
        parse_s2_response(json.dumps(raw), request)


def test_s2_rejects_experience_reordering_and_disjoint_groups():
    request = _request(); raw = _valid(request)
    raw["bullet_order"] = raw["bullet_order"][3:9] + raw["bullet_order"][:3] + raw["bullet_order"][9:]
    with pytest.raises((S2ParseError, S2ValidationError)):
        parse_s2_response(json.dumps(raw), request)
    raw = _valid(request); order = raw["bullet_order"]
    raw["bullet_order"] = [order[0], order[3], order[1]] + order[2:]
    with pytest.raises((S2ParseError, S2ValidationError)):
        parse_s2_response(json.dumps(raw), request)


@pytest.mark.parametrize("coverage", [
    {"term": "Go", "status": "gap", "bullet_ids": []},
    {"term": "Python", "status": "covered", "bullet_ids": []},
    {"term": "Python", "status": "gap", "bullet_ids": ["int_b1"]},
])
def test_s2_rejects_invalid_coverage(coverage):
    request = _request(); raw = _valid(request); raw["coverage"] = [coverage]
    with pytest.raises((S2ParseError, S2ValidationError)):
        parse_s2_response(json.dumps(raw), request)


def test_s2_rejects_keyword_mismatch_and_do_not_claim_collision():
    request = _request(); raw = _valid(request)
    raw["coverage"][0]["bullet_ids"] = ["am_b00_order_management_domain"]
    with pytest.raises(S2ValidationError):
        parse_s2_response(json.dumps(raw), request)


def test_s2_prompt_contains_complete_contract_and_has_one_marker():
    request = _request()
    template = Path("docs/prompts/tailoring_s2.md").read_text()
    prompt = build_s2_prompt(template, request)
    for field in ('"base_variant"', '"projects"', '"project_id"', '"s0_point_indexes"', '"bullet_order"', '"coverage"', '"term"', '"status"', '"bullet_ids"'):
        assert field in prompt
    assert "jd_text" not in prompt and "phrasings" not in prompt and "evidence" not in prompt
    with pytest.raises(ValueError):
        build_s2_prompt(template.replace("{{S2_REQUEST_JSON}}", ""), request)
    request = _request(); raw = _valid(request)
    request = replace(request, catalog=replace(request.catalog, do_not_claim=request.catalog.do_not_claim + ("Python",)))
    with pytest.raises(S2ValidationError):
        parse_s2_response(json.dumps(raw), request)
