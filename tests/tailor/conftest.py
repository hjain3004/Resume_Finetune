"""Shared M8P-4 fixtures: a real, non-trivial S3Request/S3Bundle pair (one
edited bullet, twelve unchanged bullets) and a matching G2Request, built
from config/master_profile.yaml and the existing M8P-3 test builders. No
network, no model call, no production DB."""
import json
from dataclasses import replace

import pytest

from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.g1 import run_static_g1
from src.tailor.s2 import parse_s2_response
from src.tailor.s3 import (
    build_s3_request,
    calculate_edit_budget,
    derive_change_log,
    derive_unified_diff,
    hydrate_s3,
    parse_s3_response,
)
from src.tailor.s3_pipeline import S3Bundle
from tests.tailor.test_s2 import _request, _valid

#: The one bullet this fixture edits. Its accepted "after" text is a
#: shortening edit already proven valid elsewhere in the M8P-3 suite:
#: preserves the leading verb, every metric (incl. "2.0"), and shrinks
#: rather than grows the canonical text.
EDITED_BULLET_ID = "int_b1"
EDITED_BULLET_AFTER = (
    "Built the **anti-corruption layer** between a commercial bank's core systems and "
    "four external providers as **four asynchronous Python microservices "
    "(FastAPI, SQLAlchemy 2.0, PostgreSQL)**."
)
#: A bullet this fixture never touches -- used by tests asserting that a
#: finding may not target an unchanged bullet.
UNCHANGED_BULLET_ID = "int_b2"


def _build_s3_pair():
    profile = load_profile("config/master_profile.yaml")
    s2_request = _request()
    s2_response = parse_s2_response(json.dumps(_valid(s2_request)), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2_response)
    request = build_s3_request(
        1, "Example", "Engineer", s2_request.s1, s2_request.s0, s2_response,
        replace(alignment, do_not_claim=()),
    )
    raw = json.dumps({
        "bullet_edits": [{
            "bullet_id": EDITED_BULLET_ID,
            "after": EDITED_BULLET_AFTER,
            "motivating_terms": ["Python"],
            "rule": "terminology_mirroring",
        }],
        "skill_additions": [],
    })
    response = parse_s3_response(raw, request)
    draft = hydrate_s3(request, response)
    report = run_static_g1(request, response, draft, ())
    assert report.status.value == "static_pass", report.violations
    bundle = S3Bundle(
        "m8p3.s3_bundle.v1", request.job_id, request.company, request.title,
        request.alignment.fingerprint, response, draft,
        derive_change_log(request, response, draft), derive_unified_diff(request, draft),
        calculate_edit_budget(request, draft), report,
    )
    return request, bundle


@pytest.fixture
def s3_pair_with_bundle():
    return _build_s3_pair()


@pytest.fixture
def g2_request_one_edit():
    from src.tailor.g2 import build_g2_request

    request, bundle = _build_s3_pair()
    return build_g2_request(request, bundle, round_index=1, banned_terms=(), taste_lessons=())
