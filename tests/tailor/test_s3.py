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
    calculate_edit_budget,
    derive_change_log,
    derive_unified_diff,
    hydrate_s3,
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
def test_s3_rejects_verb_newline_or_uncited_vocabulary(after):
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


def test_s3_hydration_preserves_structure_skills_and_derives_change_log():
    request = _request_fixture()
    source = next(item.source_text for item in request.alignment.bullets if item.bullet_id == "int_b1")
    after = "Built the **anti-corruption layer** between a commercial bank's core systems and four external providers as **four asynchronous Python microservices (FastAPI, SQLAlchemy 2.0, PostgreSQL)**."
    response = parse_s3_response(json.dumps({"bullet_edits": [_edit(request, after=after)], "skill_additions": []}), request)
    draft = hydrate_s3(request, response)
    assert tuple(item.bullet_id for item in draft.bullets) == request.s2.bullet_order
    assert draft.bullets[0].text == after
    assert tuple(category for category, _ in draft.skills) == tuple(category for category, _ in request.alignment.skills)
    changes = derive_change_log(request, response, draft)
    assert changes[0].before == source
    assert changes[0].motivating_jd_quotes == ("Python",)
    assert "--- canonical" in derive_unified_diff(request, draft)

def test_s3_length_growth_bound():
    request = _request_fixture()
    s1 = replace(request.s1, must_have=(Requirement("Distributed Systems", "q"),))
    s2 = replace(request.s2, coverage=(CoverageEntry("Distributed Systems", "covered", ("int_b1",)),))
    request = replace(request, s1=s1, s2=s2)

    # original int_b1 length: 173 chars. Motivating term "Distributed Systems" length: 19. Budget: 19.
    # Base text: "Built the **anti-corruption layer** between a commercial bank's core systems and four external providers as **four asynchronous Python microservices (FastAPI, SQLAlchemy 2.0, PostgreSQL)**."

    base_after = "Built the **anti-corruption layer** between a commercial bank's core systems and four external providers - telecom messaging, real-time interbank transfers, identity verification, and AML sanctions screening - then the **Core onboarding service** above those four as the single front door and system of record: **five asynchronous Python microservices** (FastAPI, SQLAlchemy 2.0, PostgreSQL)."

    # We want +19 exact. Motivating term "Distributed Systems" is 19 chars.
    after_over_budget = base_after.replace("microservices** (FastAPI", "microservices** Distributed Systems (FastAPI") # +20
    after_exactly_budget = after_over_budget.replace("four external", "the external") # -1 => +19

    # accepted
    parse_s3_response(json.dumps({"bullet_edits": [_edit(request, after=after_exactly_budget, terms=["Distributed Systems"])], "skill_additions": [{"category": "languages", "term": "Distributed Systems", "motivating_term": "Distributed Systems"}]}), request)

    # rejected (+1)
    with pytest.raises(S3SemanticError, match="length grew beyond the mirrored term"):
        parse_s3_response(json.dumps({"bullet_edits": [_edit(request, after=after_over_budget, terms=["Distributed Systems"])], "skill_additions": []}), request)

    # rejected (uncited word within budget)
    after_uncited = "Built the **anti-corruption layer** between a commercial bank's core systems and four external providers as **four asynchronous Python microservices (FastAPI, SQLAlchemy 2.0, PostgreSQL)** uncited"
    with pytest.raises(S3SemanticError, match="uncited vocabulary"):
        parse_s3_response(json.dumps({"bullet_edits": [_edit(request, after=after_uncited, terms=["Distributed Systems"])], "skill_additions": []}), request)




def test_s3_edit_budget_exactly_exposes_tokens_and_ratio():
    request = _request_fixture()
    # This pure synthetic boundary checks the calculation independently of S2 ordering.
    from src.tailor.alignment_view import AlignmentBullet, AlignmentView
    from src.tailor.s3 import DraftBullet, TailoredDraft
    base_text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
    alignment = AlignmentView("backend", (), (), (AlignmentBullet("b", "e", "experience", "", base_text, (), (), "verified"),), (), (), "0" * 64)
    synthetic = replace(request, alignment=alignment)
    for count, expected_ratio in ((17, 0.15), (16, 0.2)):
        text = " ".join(base_text.split()[:count])
        draft = TailoredDraft(1, "C", "T", "backend", (), (), (DraftBullet("b", "e", "experience", "", text, ()),), (), "0" * 64)
        budget = calculate_edit_budget(synthetic, draft)
        assert budget.changed_tokens == 20 - count
        assert budget.base_tokens == 20
        assert budget.ratio == expected_ratio

def test_s3_placement_projection_missing_skills_only():
    from src.tailor.s3 import s3_request_to_dict
    request = _request_fixture()
    from dataclasses import replace
    bullets = []
    for b in request.alignment.bullets:
        bullets.append(replace(b, source_text=b.source_text + " Python", plain_text=b.plain_text + " Python"))
    skills = [] # empty skills
    req2 = replace(request, alignment=replace(request.alignment, bullets=tuple(bullets), skills=tuple(skills)))
    d = s3_request_to_dict(req2)
    reqs = d.get("placement_requirements", [])
    r = next((x for x in reqs if x["term"] == "Python"), None)
    assert r is not None
    assert r["missing_from"] == ["skills"]

def test_s3_placement_projection_missing_bullet_only():
    from src.tailor.s3 import s3_request_to_dict
    request = _request_fixture()
    from dataclasses import replace
    bullets = []
    for b in request.alignment.bullets:
        bullets.append(replace(b, source_text=b.source_text.replace("Python", ""), plain_text=b.plain_text.replace("Python", "")))
    skills = [("languages", ("Python",))]
    req2 = replace(request, alignment=replace(request.alignment, bullets=tuple(bullets), skills=tuple(skills)))
    d = s3_request_to_dict(req2)
    reqs = d.get("placement_requirements", [])
    r = next((x for x in reqs if x["term"] == "Python"), None)
    assert r is not None
    assert r["missing_from"] == ["bullet"]

def test_s3_placement_projection_missing_both():
    from src.tailor.s3 import s3_request_to_dict
    request = _request_fixture()
    from dataclasses import replace
    bullets = []
    for b in request.alignment.bullets:
        bullets.append(replace(b, source_text=b.source_text.replace("Python", ""), plain_text=b.plain_text.replace("Python", "")))
    skills = []
    req2 = replace(request, alignment=replace(request.alignment, bullets=tuple(bullets), skills=tuple(skills)))
    d = s3_request_to_dict(req2)
    reqs = d.get("placement_requirements", [])
    r = next((x for x in reqs if x["term"] == "Python"), None)
    assert r is not None
    assert r["missing_from"] == ["bullet", "skills"]

def test_s3_placement_projection_missing_neither():
    from src.tailor.s3 import s3_request_to_dict
    request = _request_fixture()
    from dataclasses import replace
    bullets = []
    for b in request.alignment.bullets:
        bullets.append(replace(b, source_text=b.source_text + " Python", plain_text=b.plain_text + " Python"))
    skills = [("languages", ("Python",))]
    req2 = replace(request, alignment=replace(request.alignment, bullets=tuple(bullets), skills=tuple(skills)))
    d = s3_request_to_dict(req2)
    reqs = d.get("placement_requirements", [])
    r = next((x for x in reqs if x["term"] == "Python"), None)
    assert r is None

def test_s3_validation_rejects_partial_placement():
    request = _request_fixture()
    from dataclasses import replace
    bullets = list(request.alignment.bullets)
    b0 = bullets[0]
    bullets[0] = replace(b0, source_text=b0.source_text.replace("Python", ""), plain_text=b0.plain_text.replace("Python", ""))
    skills = []
    req2 = replace(request, alignment=replace(request.alignment, bullets=tuple(bullets), skills=tuple(skills)))

    # Attempting to return no edits when placements are missing
    with pytest.raises(S3SemanticError, match="placement: missing mapped-bullet placement"):
        parse_s3_response(json.dumps(_empty()), req2)

def test_s3_validation_accepts_already_dual_placed():
    request = _request_fixture()
    from dataclasses import replace
    bullets = list(request.alignment.bullets)
    b0 = bullets[0]
    bullets[0] = replace(b0, source_text=b0.source_text + " Python", plain_text=b0.plain_text + " Python")
    skills = [("languages", ("Python",))]
    req2 = replace(request, alignment=replace(request.alignment, bullets=tuple(bullets), skills=tuple(skills)))

    # Should cleanly pass with no edits
    parse_s3_response(json.dumps(_empty()), req2)

def test_s3_validation_rejects_wrong_mapped_bullet():
    request = _request_fixture()
    from dataclasses import replace
    bullets = list(request.alignment.bullets)
    b0 = bullets[0]
    b1 = bullets[1] # not mapped
    bullets[0] = replace(b0, source_text=b0.source_text.replace("Python", ""), plain_text=b0.plain_text.replace("Python", ""))
    bullets[1] = replace(b1, source_text=b1.source_text + " Python", plain_text=b1.plain_text + " Python")
    skills = [("languages", ("Python",))]
    req2 = replace(request, alignment=replace(request.alignment, bullets=tuple(bullets), skills=tuple(skills)))

    # Python is in b1, but b0 is the mapped bullet. So mapped-bullet placement is missing.
    with pytest.raises(S3SemanticError, match="placement: missing mapped-bullet placement"):
        parse_s3_response(json.dumps(_empty()), req2)
