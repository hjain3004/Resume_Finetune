import json
from dataclasses import replace

import pytest

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

    # Force int_b1 to have Python in its text so it doesn't need an edit to satisfy placement
    bullets = []
    for b in alignment.bullets:
        if b.bullet_id == "int_b1":
            from dataclasses import replace
            b = replace(b, source_text=b.source_text + " Python")
        bullets.append(b)
    alignment = replace(alignment, bullets=tuple(bullets))

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


# ---------------------------------------------------------------------------
# Adversarial matrix (M8P-3R): every listed mutation must independently fail
# static G1 at the earliest deterministic boundary. Built on a real,
# non-trivial valid bundle (one accepted edit, real emphasis, real metrics)
# so each mutation is meaningful rather than trivially vacuous.
# ---------------------------------------------------------------------------


def _valid_bundle():
    from tests.tailor.test_s3 import _request_fixture

    request = _clean(_request_fixture())
    after = (
        "Built the **anti-corruption layer** between a commercial bank's core systems and "
        "four external providers as **four asynchronous Python microservices "
        "(FastAPI, SQLAlchemy 2.0, PostgreSQL)**."
    )
    raw = {
        "bullet_edits": [{"bullet_id": "int_b1", "after": after, "motivating_terms": ["Python"], "rule": "terminology_mirroring"}],
        "skill_additions": [],
    }
    response = parse_s3_response(json.dumps(raw), request)
    draft = hydrate_s3(request, response)
    report = run_static_g1(request, response, draft, ())
    assert report.status is G1Status.STATIC_PASS, report.violations
    return request, response, draft


def _mutate_field(text, find, replace_with):
    """Reparse a bullet's text through parse_emphasis after a substring
    edit, so plain_text/emphasis stay internally consistent -- isolating
    whichever specific G1 rule a case targets from the unrelated
    reparse-consistency check (G0)."""
    from src.render.emphasis import parse_emphasis as _pe

    new_text = text.replace(find, replace_with, 1)
    plain, emphasis = _pe(new_text)
    return new_text, plain, emphasis


def _case_job_identity(request, response, draft):
    return request, response, replace(draft, job_id=draft.job_id + 999)


def _case_base_variant(request, response, draft):
    return request, response, replace(draft, base_variant="ml")


def _case_project_order(request, response, draft):
    return request, response, replace(draft, project_ids=("not-selected",))


def _case_experience_order(request, response, draft):
    return request, response, replace(draft, experience_ids=tuple(reversed(draft.experience_ids)) or ("not-selected",))


def _case_bullet_membership(request, response, draft):
    return request, response, replace(draft, bullets=draft.bullets[:-1])


def _case_bullet_order(request, response, draft):
    return request, response, replace(draft, bullets=tuple(reversed(draft.bullets)))


def _case_owner_id(request, response, draft):
    bullets = list(draft.bullets)
    bullets[-1] = replace(bullets[-1], owner_id="fabricated-owner")
    return request, response, replace(draft, bullets=tuple(bullets))


def _case_owner_kind(request, response, draft):
    bullets = list(draft.bullets)
    other = "experience" if bullets[-1].owner_kind == "project" else "project"
    bullets[-1] = replace(bullets[-1], owner_kind=other)
    return request, response, replace(draft, bullets=tuple(bullets))


def _case_unedited_bullet_text(request, response, draft):
    # bullets[-1] is not "int_b1" (the only edited id) in this fixture.
    unedited = draft.bullets[-1]
    text, plain, emphasis = _mutate_field(unedited.text, unedited.plain_text.split()[0], unedited.plain_text.split()[0] + " Extra")
    bullets = list(draft.bullets)
    bullets[-1] = replace(unedited, text=text, plain_text=plain, emphasis=emphasis)
    return request, response, replace(draft, bullets=tuple(bullets))


def _case_edited_bullet_text_mismatch(request, response, draft):
    edited = next(b for b in draft.bullets if b.bullet_id == "int_b1")
    text, plain, emphasis = _mutate_field(edited.text, "anti-corruption layer", "anti-corruption layer (v2)")
    bullets = tuple(replace(b, text=text, plain_text=plain, emphasis=emphasis) if b.bullet_id == "int_b1" else b for b in draft.bullets)
    return request, response, replace(draft, bullets=bullets)


def _case_stored_plain_text(request, response, draft):
    bullets = list(draft.bullets)
    bullets[0] = replace(bullets[0], plain_text=bullets[0].plain_text + " tampered")
    return request, response, replace(draft, bullets=tuple(bullets))


def _case_stored_emphasis(request, response, draft):
    bullets = list(draft.bullets)
    bullets[0] = replace(bullets[0], emphasis=((0, 1),) + bullets[0].emphasis)
    return request, response, replace(draft, bullets=tuple(bullets))


def _case_skill_removal(request, response, draft):
    category, items = draft.skills[0]
    skills = ((category, items[1:]),) + draft.skills[1:]
    return request, response, replace(draft, skills=skills)


def _case_skill_reorder(request, response, draft):
    category, items = draft.skills[0]
    if len(items) < 2:
        items = items + ("Extra Skill",)
    skills = ((category, tuple(reversed(items))),) + draft.skills[1:]
    return request, response, replace(draft, skills=skills)


def _case_undeclared_skill_addition(request, response, draft):
    category, items = draft.skills[0]
    skills = ((category, items + ("Undeclared Skill",)),) + draft.skills[1:]
    return request, response, replace(draft, skills=skills)


def _case_alignment_fingerprint(request, response, draft):
    return request, response, replace(draft, alignment_fingerprint="0" * 64)


def _case_metric(request, response, draft):
    # "four"/"five" are words, not digits -- _numeric_tokens only matches
    # digit-based tokens, so mutate the one real numeric token ("2.0").
    edited_after = draft.bullets[0].text.replace("2.0", "3.0", 1)
    from src.render.emphasis import parse_emphasis as _pe

    plain, emphasis = _pe(edited_after)
    edited_response = replace(response, bullet_edits=(replace(response.bullet_edits[0], after=edited_after),))
    bullets = tuple(replace(b, text=edited_after, plain_text=plain, emphasis=emphasis) if b.bullet_id == "int_b1" else b for b in draft.bullets)
    return request, edited_response, replace(draft, bullets=bullets)


def _case_first_verb(request, response, draft):
    edited_after = draft.bullets[0].text.replace("Built the", "Designed the", 1)
    from src.render.emphasis import parse_emphasis as _pe

    plain, emphasis = _pe(edited_after)
    edited_response = replace(response, bullet_edits=(replace(response.bullet_edits[0], after=edited_after),))
    bullets = tuple(replace(b, text=edited_after, plain_text=plain, emphasis=emphasis) if b.bullet_id == "int_b1" else b for b in draft.bullets)
    return request, edited_response, replace(draft, bullets=bullets)


def _case_do_not_claim(request, response, draft):
    request = replace(request, alignment=replace(request.alignment, do_not_claim=("Python",)))
    return request, response, draft


ADVERSARIAL_CASES = [
    ("job_identity", _case_job_identity, "G0"),
    ("base_variant", _case_base_variant, "G0"),
    ("project_order", _case_project_order, "L1"),
    ("experience_order", _case_experience_order, "L1"),
    ("bullet_membership", _case_bullet_membership, "L1"),
    ("bullet_order", _case_bullet_order, "L1"),
    ("owner_id", _case_owner_id, "G0"),
    ("owner_kind", _case_owner_kind, "G0"),
    ("unedited_bullet_text", _case_unedited_bullet_text, "L1"),
    ("edited_bullet_text_mismatch", _case_edited_bullet_text_mismatch, "L1"),
    ("stored_plain_text", _case_stored_plain_text, "G0"),
    ("stored_emphasis", _case_stored_emphasis, "G0"),
    ("skill_removal", _case_skill_removal, "L1"),
    ("skill_reorder", _case_skill_reorder, "L1"),
    ("undeclared_skill_addition", _case_undeclared_skill_addition, "L1"),
    ("alignment_fingerprint", _case_alignment_fingerprint, "G0"),
    ("metric", _case_metric, "L4"),
    ("first_verb", _case_first_verb, "L4"),
    ("do_not_claim", _case_do_not_claim, "L6"),
]


@pytest.mark.parametrize("label,mutate,expected_rule", ADVERSARIAL_CASES, ids=[c[0] for c in ADVERSARIAL_CASES])
def test_g1_adversarial_matrix_fails_at_earliest_boundary(label, mutate, expected_rule):
    request, response, draft = _valid_bundle()
    mutated_request, mutated_response, mutated_draft = mutate(request, response, draft)
    report = run_static_g1(mutated_request, mutated_response, mutated_draft, ())
    assert report.status is G1Status.FAIL, f"{label}: expected FAIL"
    assert any(v.rule == expected_rule for v in report.violations), f"{label}: expected a {expected_rule} violation, got {report.violations}"


def test_g1_adversarial_banned_term_fails():
    request, response, draft = _valid_bundle()
    report = run_static_g1(request, response, draft, ("Python",))
    assert report.status is G1Status.FAIL
    assert any(v.rule == "L2" for v in report.violations)


def test_g1_adversarial_edit_budget_over_15_percent_fails():
    from src.tailor.alignment_view import AlignmentBullet, AlignmentView
    from src.tailor.s3 import DraftBullet, TailoredDraft

    request, response, draft = _valid_bundle()
    base_text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
    alignment = AlignmentView("backend", (), (), (AlignmentBullet("b", "e", "experience", "", base_text, (), (), "verified"),), (), (), "0" * 64)
    synthetic_request = replace(request, alignment=alignment, s1=replace(request.s1, must_have=()), s2=replace(request.s2, coverage=()))
    over_budget_text = " ".join(base_text.split()[:16])  # 4/20 = 0.20 > 0.15
    synthetic_draft = TailoredDraft(
        synthetic_request.job_id, synthetic_request.company, synthetic_request.title, "backend", (), (),
        (DraftBullet("b", "e", "experience", "", over_budget_text, ()),), (), "0" * 64,
    )
    empty_response = parse_s3_response('{"bullet_edits": [], "skill_additions": []}', synthetic_request)
    report = run_static_g1(synthetic_request, empty_response, synthetic_draft, ())
    assert report.status is G1Status.FAIL
    assert any(v.rule == "L5" for v in report.violations)

def test_g1_length_growth_bound():
    from src.tailor.s1 import Requirement
    from src.tailor.s2 import CoverageEntry
    request, _ = _fixture()
    b0 = request.alignment.bullets[0]
    # base text is 120 chars
    # motivate with a 10 char term
    terms = ["TenCharTerm"]
    s1 = replace(request.s1, must_have=(Requirement("TenCharTerm", "q"),))
    s2 = replace(request.s2, coverage=(CoverageEntry("TenCharTerm", "covered", ("b1",)),))
    request = replace(request, s1=s1, s2=s2)

    from src.tailor.s3 import S3Response, DraftBullet, BulletEdit
    from src.tailor.g1 import TailoredDraft

    # +10 length exactly
    after_exact = b0.plain_text + "TenCharTer" # exactly 10 chars added
    response_exact = S3Response(bullet_edits=(BulletEdit(b0.bullet_id, after_exact, ("TenCharTerm",), ""),), skill_additions=())
    draft_exact = TailoredDraft(
        request.job_id, request.company, request.title, request.alignment.base_variant, request.alignment.project_ids, request.alignment.experience_ids,
        tuple(DraftBullet(b.bullet_id, b.owner_id, b.owner_kind, after_exact, after_exact, ()) if b.bullet_id == b0.bullet_id else DraftBullet(b.bullet_id, b.owner_id, b.owner_kind, b.source_text, b.plain_text, ()) for b in request.alignment.bullets),
        request.alignment.skills, request.alignment.fingerprint
    )
    report_exact = run_static_g1(request, response_exact, draft_exact, ())
    assert not any(v.rule == "L4" for v in report_exact.violations)

    # +12 length
    after_over = b0.plain_text + "TenCharTermX" # 12 chars added (budget is 11)
    response_over = S3Response(bullet_edits=(BulletEdit(b0.bullet_id, after_over, ("TenCharTerm",), ""),), skill_additions=())
    draft_over = TailoredDraft(
        request.job_id, request.company, request.title, request.alignment.base_variant, request.alignment.project_ids, request.alignment.experience_ids,
        tuple(DraftBullet(b.bullet_id, b.owner_id, b.owner_kind, after_over, after_over, ()) if b.bullet_id == b0.bullet_id else DraftBullet(b.bullet_id, b.owner_id, b.owner_kind, b.source_text, b.plain_text, ()) for b in request.alignment.bullets),
        request.alignment.skills, request.alignment.fingerprint
    )
    report_over = run_static_g1(request, response_over, draft_over, ())
    assert any(v.rule == "L4" for v in report_over.violations)
