import json
from dataclasses import replace

from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.g1 import G1Report, G1Status, run_static_g1
from src.tailor.s2 import parse_s2_response
from src.tailor.s1 import S1Response
from src.tailor.s3 import build_s3_request, hydrate_s3, parse_s3_response
from tests.tailor.test_s2 import _request, _valid


def test_g1_module_contract_exists():
    assert G1Report is not None
    assert callable(run_static_g1)


def _fixture():
    profile = load_profile("config/master_profile.yaml")
    s2_request = _request()
    s2_response = parse_s2_response(json.dumps(_valid(s2_request)), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2_response)
    request = build_s3_request(1, "Example", "Engineer", s2_request.s1, s2_request.s0, s2_response, alignment)
    return request, parse_s3_response('{"bullet_edits": [], "skill_additions": []}', request)


def _clean(request):
    return replace(request, alignment=replace(request.alignment, do_not_claim=()))


def test_g1_empty_draft_passes_static_checks():
    request, response = _fixture()
    request = _clean(request)
    request = replace(request, s1=replace(request.s1, must_have=()), s2=replace(request.s2, coverage=()))
    report = run_static_g1(request, response, hydrate_s3(request, response), ())
    assert report.status is G1Status.STATIC_PASS
    assert report.violations == ()
    assert report.render_line_check == "pending"


def test_g1_reports_structure_and_banned_term_violations():
    request, response = _fixture()
    request = _clean(request)
    draft = replace(hydrate_s3(request, response), project_ids=("not-selected",))
    report = run_static_g1(request, response, draft, ("Python",))
    assert report.status is G1Status.FAIL
    assert {violation.rule for violation in report.violations} >= {"L1", "L2"}


def test_g1_reports_do_not_claim_and_budget_violations():
    request, response = _fixture()
    draft = hydrate_s3(request, response)
    request = replace(request, alignment=replace(request.alignment, do_not_claim=("Python",)))
    report = run_static_g1(request, response, draft, ())
    assert report.status is G1Status.FAIL
    assert any(item.rule == "L6" for item in report.violations)


def test_g1_reports_edit_invariant_violations():
    request, response = _fixture()
    request = _clean(request)
    source = request.alignment.bullets[0]
    draft = replace(
        hydrate_s3(request, response),
        bullets=(replace(hydrate_s3(request, response).bullets[0], text="Changed **text**", plain_text="Changed text"),)
        + hydrate_s3(request, response).bullets[1:],
    )
    edited_response = replace(response, bullet_edits=(replace(response.bullet_edits[0], bullet_id=source.bullet_id),)) if response.bullet_edits else response
    report = run_static_g1(request, edited_response, draft, ())
    assert report.status is G1Status.FAIL
