import json

import pytest

from src.profile import load_profile
from src.render.mapping import default_phrasing_text
from src.tailor.alignment_view import (
    AlignmentView,
    AlignmentError,
    alignment_from_profile,
    alignment_to_dict,
    parse_alignment,
)
from src.tailor.s2 import parse_s2_response
from tests.tailor.test_s2 import _request, _valid


def test_alignment_view_module_contract_exists():
    assert AlignmentView is not None
    assert callable(alignment_from_profile)


def test_alignment_uses_s2_order_and_omits_private_fields():
    profile = load_profile("config/master_profile.yaml")
    request = _request()
    response = parse_s2_response(json.dumps(_valid(request)), request)
    view = alignment_from_profile(profile, request, response)
    assert tuple(item.bullet_id for item in view.bullets) == response.bullet_order
    rendered = json.loads(json.dumps(alignment_to_dict(view)))
    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value)) if value else set()
        return set()
    for forbidden in ("identity", "education", "evidence", "defense", "interview_risk", "metric_ledger", "ownership_boundary"):
        assert forbidden not in keys(rendered)
    assert parse_alignment(rendered) == view


def test_alignment_uses_medium_then_short_fallback():
    profile = load_profile("config/master_profile.yaml")
    request = _request()
    response = parse_s2_response(json.dumps(_valid(request)), request)
    view = alignment_from_profile(profile, request, response)
    index = {bullet.id: bullet for entry in (*profile.projects, *profile.experience) for bullet in entry.bullets}
    for item in view.bullets:
        assert item.source_text == default_phrasing_text(index[item.bullet_id])


def test_alignment_rejects_fingerprint_tampering():
    profile = load_profile("config/master_profile.yaml")
    request = _request()
    response = parse_s2_response(json.dumps(_valid(request)), request)
    raw = alignment_to_dict(alignment_from_profile(profile, request, response))
    raw["fingerprint"] = "0" * 64
    with pytest.raises(AlignmentError, match="fingerprint"):
        parse_alignment(raw)
