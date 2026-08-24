import copy
import json
from dataclasses import replace

import pytest

from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.s1 import Requirement
from src.tailor.s2 import CoverageEntry, parse_s2_response
from src.tailor.s3 import (
    BulletEdit,
    S3ParseError,
    S3Response,
    S3SemanticError,
    build_s3_request,
    parse_s3_request,
    parse_s3_response,
    s3_request_to_dict,
    s3_response_to_dict,
)
from tests.tailor.test_s2 import _request, _valid


def test_s3_contract_module_exists():
    assert BulletEdit is not None
    assert S3Response is not None
    assert callable(parse_s3_response)


def _request_fixture():
    profile = load_profile("config/master_profile.yaml")
    s2_request = _request()
    s2_response = parse_s2_response(json.dumps(_valid(s2_request)), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2_response)
    return build_s3_request(1, "Example", "Engineer", s2_request.s1, s2_request.s0, s2_response, alignment)


def _empty():
    return {"bullet_edits": [], "skill_additions": []}


def _edit(request, after=None, bullet_id="int_b1", terms=None):
    source = next((item.source_text for item in request.alignment.bullets if item.bullet_id == bullet_id), "")
    return {
        "bullet_id": bullet_id,
        "after": after if after is not None else source.replace("Built the **anti-corruption layer**", "Built the **anti-corruption layer** across", 1),
        "motivating_terms": terms or ["Python"],
        "rule": "terminology_mirroring",
    }


def test_s3_accepts_empty_response_and_round_trips():
    request = _request_fixture()
    response = parse_s3_response(json.dumps(_empty()), request)
    assert response == S3Response((), ())
    assert s3_response_to_dict(response) == _empty()


def test_s3_request_round_trips_strictly():
    request = _request_fixture()
    assert parse_s3_request(s3_request_to_dict(request)) == request


@pytest.mark.parametrize("raw", ["not json", "```json\n{}\n```", '{"bullet_edits": [],}'])
def test_s3_rejects_non_strict_json(raw):
    with pytest.raises(S3ParseError):
        parse_s3_response(raw, _request_fixture())


def test_s3_rejects_ninth_edit_duplicate_edit_and_unchanged_source():
    request = _request_fixture()
    raw = _empty()
    raw["bullet_edits"] = [{"bullet_id": f"b{i}", "after": "x", "motivating_terms": ["Python"], "rule": "terminology_mirroring"} for i in range(9)]
    with pytest.raises(S3ParseError, match="at most 8"):
        parse_s3_response(json.dumps(raw), request)
    raw["bullet_edits"] = [_edit(request), _edit(request)]
    with pytest.raises(S3ParseError, match="duplicate id"):
        parse_s3_response(json.dumps(raw), request)
    raw["bullet_edits"] = [_edit(request, after=request.alignment.bullets[0].source_text)]
    with pytest.raises(S3ParseError, match="unchanged"):
        parse_s3_response(json.dumps(raw), request)


def test_s3_rejects_unselected_bullet_and_bad_motivating_term():
    request = _request_fixture()
    with pytest.raises(S3SemanticError, match="not selected"):
        parse_s3_response(json.dumps({"bullet_edits": [_edit(request, after="x", bullet_id="sepsis_b3")], "skill_additions": []}), request)
    with pytest.raises(S3SemanticError, match="not an exact must-have"):
        parse_s3_response(json.dumps({"bullet_edits": [_edit(request, terms=["Go"])], "skill_additions": []}), request)


@pytest.mark.parametrize("after", [
    "Designed the **anti-corruption layer** across four asynchronous Python microservices.",
    "Built the **anti-corruption layer** across four asynchronous Python microservices.\nExtra",
    "Built the **anti-corruption layer** across four asynchronous Python Kubernetes microservices.",
    "Built the **anti-corruption layer** across four asynchronous Python microservices with additional wording.",
])
def test_s3_rejects_verb_newline_uncited_vocabulary_or_length_growth(after):
    request = _request_fixture()
    with pytest.raises(S3SemanticError):
        parse_s3_response(json.dumps({"bullet_edits": [_edit(request, after=after)], "skill_additions": []}), request)


def test_s3_rejects_metric_changes_and_invalid_emphasis():
    request = _request_fixture()
    for after in (
        "Built the **anti-corruption layer** across five asynchronous Python microservices.",
        "Built the **anti-corruption layer across four asynchronous Python microservices.",
    ):
        with pytest.raises(S3SemanticError):
            parse_s3_response(json.dumps({"bullet_edits": [_edit(request, after=after)], "skill_additions": []}), request)


def test_s3_accepts_exact_covered_skill_addition_and_rejects_duplicates():
    request = _request_fixture()
    s1 = replace(request.s1, must_have=(Requirement("anti-corruption layer", "anti-corruption layer"),))
    s2 = replace(request.s2, coverage=(CoverageEntry("anti-corruption layer", "covered", ("int_b1",)),))
    request = replace(request, s1=s1, s2=s2)
    raw = {"bullet_edits": [], "skill_additions": [{"category": "frameworks", "term": "anti-corruption layer", "motivating_term": "anti-corruption layer"}]}
    response = parse_s3_response(json.dumps(raw), request)
    assert response.skill_additions[0].term == "anti-corruption layer"
    raw["skill_additions"].append(copy.deepcopy(raw["skill_additions"][0]))
    with pytest.raises(S3SemanticError, match="duplicate"):
        parse_s3_response(json.dumps(raw), request)
