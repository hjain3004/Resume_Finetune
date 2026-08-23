import json

from src.profile import load_profile
from src.tailor.profile_views import parse_positioning, parse_selection, positioning_to_dict, selection_to_dict
from src.tailor.s0 import build_s0_request, parse_s0_response, s0_request_to_dict
from src.tailor.s1 import parse_s1_response
from src.tailor.s2 import build_s2_request, parse_s2_response, s2_request_to_dict


def _fixtures():
    profile = load_profile("config/master_profile.yaml")
    positioning = profile.for_positioning()
    catalog = profile.for_selection("backend")
    s1 = parse_s1_response(json.dumps({
        "must_have": [{"term": "Python", "quote": "Python"}],
        "nice_to_have": [], "responsibilities_summary": [],
        "seniority_signals": [], "disqualifiers": [],
        "company_context": None, "suspected_injection": [],
    }), "Python")
    s0_request = build_s0_request(1, "Example", "Engineer", s1, positioning)
    s0 = parse_s0_response(json.dumps({
        "context_mode": "jd_only",
        "points": [
            {"sentence": "Lead with backend delivery.", "profile_ids": [positioning.projects[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
            {"sentence": "Support the claim with production experience.", "profile_ids": [positioning.experiences[0].id], "requirement_terms": ["Python"], "jd_quotes": ["Python"]},
        ],
    }), s0_request)
    return profile, catalog, s1, s0


def test_profile_views_round_trip_without_private_fields():
    profile = load_profile("config/master_profile.yaml")
    positioning = positioning_to_dict(profile.for_positioning())
    catalog = selection_to_dict(profile.for_selection("backend"))
    assert parse_positioning(positioning) == profile.for_positioning()
    assert parse_selection(catalog) == profile.for_selection("backend")
    serialized = json.loads(json.dumps({"positioning": positioning, "catalog": catalog}))
    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(v) for v in value)) if value else set()
        return set()
    for key in ("identity", "phone", "email", "education", "phrasings", "evidence", "defense", "interview_risk", "ownership_boundary", "skills"):
        assert key not in keys(serialized)


def test_s0_round_trip_is_jd_only_and_evidence_anchored():
    _, _, s1, s0 = _fixtures()
    assert s0.context_mode == "jd_only"
    assert s0.points[0].jd_quotes == ("Python",)
    assert "jd_text" not in json.dumps(s0_request_to_dict(build_s0_request(1, "Example", "Engineer", s1, load_profile("config/master_profile.yaml").for_positioning())))


def test_s0_rejects_invented_profile_id():
    _, _, s1, _ = _fixtures()
    request_s0 = build_s0_request(1, "Example", "Engineer", s1, load_profile("config/master_profile.yaml").for_positioning())
    raw = {"context_mode": "jd_only", "points": [{"sentence": "a", "profile_ids": ["fake"], "requirement_terms": ["Python"], "jd_quotes": ["Python"]}, {"sentence": "b", "profile_ids": ["fake"], "requirement_terms": ["Python"], "jd_quotes": ["Python"]}]}
    try:
        parse_s0_response(json.dumps(raw), request_s0)
    except ValueError:
        return
    raise AssertionError("invented id was accepted")


def test_s2_validates_fixed_backend_structure_and_coverage():
    profile, catalog, s1, s0 = _fixtures()
    request = build_s2_request(1, "Example", "Engineer", s1, s0, catalog)
    response = parse_s2_response(json.dumps({
        "base_variant": "backend",
        "projects": [{"project_id": project, "reason": "matches the selected strategy", "s0_point_indexes": [0]} for project in catalog.variants[0].projects],
        "bullet_order": list(catalog.variants[0].bullet_order),
        "coverage": [{"term": "Python", "status": "covered", "bullet_ids": ["int_b1"]}],
    }), request)
    assert response.gap_terms == ()
    assert parse_s2_response(json.dumps({
        "base_variant": response.base_variant,
        "projects": [{"project_id": p.project_id, "reason": p.reason, "s0_point_indexes": list(p.s0_point_indexes)} for p in response.projects],
        "bullet_order": list(response.bullet_order),
        "coverage": [{"term": c.term, "status": c.status, "bullet_ids": list(c.bullet_ids)} for c in response.coverage],
    }), request) == response
    assert "jd_text" not in json.dumps(s2_request_to_dict(request))
