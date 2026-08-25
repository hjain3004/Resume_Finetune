"""TailoredDraft -> RenderDoc mapping (M8P-5 Task 1). Pure; no model, no
network, no DB, no pdflatex."""
import json
from dataclasses import replace

import pytest

from src.profile import load_profile
from src.render.tailored import SECTION_ORDER, TailoredRenderError, render_doc_from_draft
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.s2 import parse_s2_response
from src.tailor.s3 import S3Response, build_s3_request, hydrate_s3
from tests.fixtures.tailor.m8p5_drafts import draft_bullet, make_draft
from tests.tailor.test_s2 import _request, _valid


@pytest.fixture(scope="module")
def profile():
    return load_profile("config/master_profile.yaml")


def _build_real_draft():
    """A genuinely consistent, unedited TailoredDraft for the real profile's
    "backend" variant: alignment_fingerprint is computed by the same
    alignment_from_profile() the implementation recomputes against, and
    every bullet's canonical medium phrasing (e.g. int_b1's "**anti-
    corruption layer**") already carries real emphasis markup."""
    profile = load_profile("config/master_profile.yaml")
    s2_request = _request()
    s2_response = parse_s2_response(json.dumps(_valid(s2_request)), s2_request)
    alignment = alignment_from_profile(profile, s2_request, s2_response)
    s3_request = build_s3_request(1, "Example", "Engineer", s2_request.s1, s2_request.s0, s2_response, alignment)
    return hydrate_s3(s3_request, S3Response(bullet_edits=(), skill_additions=()))


@pytest.fixture
def real_draft():
    return _build_real_draft()


@pytest.fixture
def real_draft_with_emphasis(real_draft):
    return real_draft


def test_doc_uses_canonical_section_order_and_profile_identity(profile, real_draft):
    doc = render_doc_from_draft(profile, real_draft)
    assert doc.section_order == SECTION_ORDER
    assert doc.identity == dict(profile.identity)
    assert doc.ats == dict(profile.ats)
    assert doc.education


def test_every_draft_bullet_is_emitted_exactly_once(profile, real_draft):
    doc = render_doc_from_draft(profile, real_draft)
    emitted = [b.bullet_id for b in doc.all_bullets()]
    assert sorted(emitted) == sorted(b.bullet_id for b in real_draft.bullets)
    assert len(emitted) == len(set(emitted))


def test_bullets_are_placed_under_their_canonical_owner(profile, real_draft):
    doc = render_doc_from_draft(profile, real_draft)
    for entry in doc.projects + doc.experience:
        for bullet in entry.bullets:
            source = next(b for b in real_draft.bullets if b.bullet_id == bullet.bullet_id)
            assert source.owner_id == entry.entry_id


def test_unknown_project_id_fails_closed(profile, real_draft):
    broken = make_draft(bullets=real_draft.bullets, project_ids=("no_such_project",),
                        experience_ids=real_draft.experience_ids, skills=real_draft.skills,
                        fingerprint=real_draft.alignment_fingerprint)
    with pytest.raises(TailoredRenderError, match="no_such_project"):
        render_doc_from_draft(profile, broken)


def test_bullet_with_unselected_owner_fails_closed_rather_than_dropping(profile, real_draft):
    orphan = draft_bullet("b_orphan", "not_selected", "project", "Did a thing")
    broken = make_draft(bullets=real_draft.bullets + (orphan,),
                        project_ids=real_draft.project_ids,
                        experience_ids=real_draft.experience_ids,
                        skills=real_draft.skills,
                        fingerprint=real_draft.alignment_fingerprint)
    with pytest.raises(TailoredRenderError, match="b_orphan"):
        render_doc_from_draft(profile, broken)


def test_stored_plain_text_disagreeing_with_marked_text_fails_closed(profile, real_draft):
    tampered = replace(real_draft.bullets[0], plain_text="something else entirely")
    broken = make_draft(bullets=(tampered,) + real_draft.bullets[1:],
                        project_ids=real_draft.project_ids,
                        experience_ids=real_draft.experience_ids,
                        skills=real_draft.skills,
                        fingerprint=real_draft.alignment_fingerprint)
    with pytest.raises(TailoredRenderError, match="plain_text"):
        render_doc_from_draft(profile, broken)


def test_fingerprint_mismatch_fails_closed(profile, real_draft):
    with pytest.raises(TailoredRenderError, match="fingerprint"):
        render_doc_from_draft(profile, replace(real_draft, alignment_fingerprint="wrong"))


def test_emphasis_spans_survive_into_render_bullets(profile, real_draft_with_emphasis):
    doc = render_doc_from_draft(profile, real_draft_with_emphasis)
    marked = next(b for b in doc.all_bullets() if b.emphasis)
    assert marked.emphasis


def test_modified_bullet_ids_detects_only_changed_text():
    from src.render.tailored import modified_bullet_ids
    draft = make_draft(bullets=(draft_bullet("b1", "p1", "project", "New wording here"),
                                draft_bullet("b2", "p1", "project", "Same wording")),
                       project_ids=("p1",), experience_ids=(), skills=())
    assert modified_bullet_ids(draft, {"b1": "Old wording here", "b2": "Same wording"}) == frozenset({"b1"})
