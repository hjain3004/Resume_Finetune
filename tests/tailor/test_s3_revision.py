"""Additive S3 revision context (M8P-4 Task 4, post-M8P-3R integration).
Only new symbols; no pre-existing src/tailor/s3.py function is modified."""
import pytest

from src.tailor.g2 import G2Dimension, G2Finding, G2TargetKind
from src.tailor.s3 import (
    BulletEdit,
    S3EditRule,
    S3RevisionContext,
    S3Response,
    S3SemanticError,
    build_s3_revision_prompt,
    validate_revision_scope,
)
from tests.tailor.conftest import EDITED_BULLET_ID


@pytest.fixture
def s3_request(s3_pair_with_bundle):
    request, _ = s3_pair_with_bundle
    return request


@pytest.fixture
def prev_response(s3_pair_with_bundle):
    _, bundle = s3_pair_with_bundle
    return bundle.response


@pytest.fixture
def ctx_one_finding():
    finding = G2Finding(
        dimension=G2Dimension.C5,
        rule_id="C5.template_phrasing",
        target_kind=G2TargetKind.BULLET,
        target_id=EDITED_BULLET_ID,
        quoted_line="quote",
        explanation="explanation",
    )
    return S3RevisionContext(round_index=2, findings=(finding,))


@pytest.fixture
def ctx_names_b_flagged():
    finding = G2Finding(
        dimension=G2Dimension.C4,
        rule_id="C4.signal_below_fold",
        target_kind=G2TargetKind.BULLET,
        target_id="b_flagged",
        quoted_line="quote",
        explanation="explanation",
    )
    return S3RevisionContext(round_index=2, findings=(finding,))


@pytest.fixture
def make_response_editing():
    def _make(bullet_id: str) -> S3Response:
        return S3Response(
            bullet_edits=(BulletEdit(bullet_id, "placeholder after", ("Python",), S3EditRule.TERMINOLOGY_MIRRORING),),
            skill_additions=(),
        )

    return _make


def test_revision_may_not_edit_a_bullet_no_finding_named(prev_response, ctx_one_finding, make_response_editing):
    revised = make_response_editing("b_untouched")
    with pytest.raises(S3SemanticError, match="outside revision scope"):
        validate_revision_scope(revised, prev_response, ctx_one_finding)


def test_revision_may_edit_a_previously_edited_bullet(prev_response, ctx_one_finding, make_response_editing):
    validate_revision_scope(make_response_editing(EDITED_BULLET_ID), prev_response, ctx_one_finding)


def test_revision_may_edit_a_bullet_a_finding_named(prev_response, ctx_names_b_flagged, make_response_editing):
    validate_revision_scope(make_response_editing("b_flagged"), prev_response, ctx_names_b_flagged)


def test_revision_prompt_requires_its_marker(s3_request, ctx_one_finding):
    with pytest.raises(ValueError):
        build_s3_revision_prompt("{{S3_REQUEST_JSON}} only", s3_request, ctx_one_finding)


def test_revision_prompt_requires_request_marker_too(s3_request, ctx_one_finding):
    with pytest.raises(ValueError):
        build_s3_revision_prompt("{{S3_REVISION_JSON}} only", s3_request, ctx_one_finding)


def test_revision_prompt_embeds_both_markers(s3_request, ctx_one_finding):
    template = "REQUEST: {{S3_REQUEST_JSON}}\nREVISION: {{S3_REVISION_JSON}}"
    prompt = build_s3_revision_prompt(template, s3_request, ctx_one_finding)
    assert "{{S3_REQUEST_JSON}}" not in prompt
    assert "{{S3_REVISION_JSON}}" not in prompt
    assert '"round_index": 2' in prompt
    assert EDITED_BULLET_ID in prompt
