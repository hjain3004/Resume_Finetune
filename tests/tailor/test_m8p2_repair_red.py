import json

import pytest

from src.profile import load_profile
from src.tailor.profile_views import ProfileViewError, parse_selection, selection_to_dict
from src.tailor.s2 import S2ValidationError, build_s2_request, parse_s2_response
from tests.tailor.test_m8p2_contracts import _fixtures


def _response(catalog, bullet_order, coverage_bullet="ct_b1"):
    return {
        "base_variant": "backend",
        "projects": [
            {"project_id": project, "reason": "selected", "s0_point_indexes": [0]}
            for project in catalog.variants[0].projects
        ],
        "bullet_order": list(bullet_order),
        "coverage": [{"term": "Python", "status": "covered", "bullet_ids": [coverage_bullet]}],
    }


def test_fabricated_catalog_bullet_is_rejected():
    # 2026-09-15 blueprint: backend no longer selects clinical_trial_platform
    # (ct_b1's owner), so removing ct_b1 orphans nothing anymore. Use
    # "cm_b1" instead -- read live from the profile, not hardcoded: it is
    # currently the ONLY bullet campus_marketplace contributes to backend's
    # selection (per the approved blueprint's "Campus Marketplace: 1
    # bullet"), so removing it and replacing it with a fabricated bullet
    # under the same (still-selected) owner_id orphans that project's
    # reference exactly as ct_b1 used to for clinical_trial_platform.
    profile = load_profile("config/master_profile.yaml")
    raw = selection_to_dict(profile.for_selection("backend"))
    raw["bullets"] = [
        bullet for bullet in raw["bullets"] if bullet["id"] != "cm_b1"
    ] + [{
        "id": "fabricated_bullet",
        "owner_id": "campus_marketplace",
        "owner_kind": "project",
        "priority": 1,
        "claim_type": "verified",
        "keywords_hit": ["Python"],
    }]
    with pytest.raises(ProfileViewError):
        parse_selection(raw)


def test_experience_groups_cannot_be_reordered():
    profile = load_profile("config/master_profile.yaml")
    catalog = profile.for_selection("backend")
    _, _, s1, s0 = _fixtures()
    request = build_s2_request(1, "Example", "Engineer", s1, s0, catalog)
    order = list(catalog.variants[0].bullet_order)
    reordered = order[3:9] + order[:3] + order[9:]
    with pytest.raises(S2ValidationError):
        parse_s2_response(json.dumps(_response(catalog, reordered)), request)
