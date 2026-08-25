"""Human feedback contract (M8P-6 Task 1): strictly validated YAML review
form parsing. No model, no network, no DB, no filesystem I/O in this task."""
import pytest

from src.tailor.feedback import (
    Accept,
    FeedbackParseError,
    FeedbackValidationError,
    WouldSubmit,
    build_feedback_form,
    feedback_record_to_dict,
    parse_feedback_form,
    parse_feedback_record,
)
from tests.fixtures.tailor.m8p6_forms import form

KW = dict(job_id=225, alignment_fingerprint="fp0123456789ab",
          changed_bullet_ids=frozenset({"b1"}),
          bullet_plain_text_by_id={"b1": "Cut p99 latency 40% by sharding the write path"})


def test_emitted_form_parses_after_the_required_fields_are_filled():
    blank = build_feedback_form(225, "fp0123456789ab", ("b1",))
    assert "bullet_id: b1" in blank
    with pytest.raises(FeedbackValidationError):
        parse_feedback_form(blank, **KW)      # empty enums must not default


def test_valid_form_round_trips():
    record = parse_feedback_form(form(), **KW)
    assert record.accept is Accept.ACCEPT
    assert parse_feedback_record(feedback_record_to_dict(record)) == record


def test_accept_with_would_not_submit_is_preserved():
    record = parse_feedback_form(form(would_submit="no"), **KW)
    assert record.accept is Accept.ACCEPT and record.would_submit is WouldSubmit.NO


def test_empty_required_enum_is_rejected():
    with pytest.raises(FeedbackValidationError, match="accept"):
        parse_feedback_form(form(accept=""), **KW)


def test_out_of_range_score_is_rejected():
    with pytest.raises(FeedbackValidationError, match="visual_quality"):
        parse_feedback_form(form(visual_quality=4), **KW)


def test_boolean_score_is_rejected():
    with pytest.raises(FeedbackValidationError, match="company_alignment"):
        parse_feedback_form(form(company_alignment=True), **KW)


def test_malformed_date_is_rejected():
    with pytest.raises(FeedbackValidationError, match="reviewed_at"):
        parse_feedback_form(form(reviewed_at="24-08-2026"), **KW)


def test_missing_bullet_feedback_entry_is_rejected():
    with pytest.raises(FeedbackValidationError, match="bullet_feedback"):
        parse_feedback_form(form(bullet_feedback=[]), **KW)


def test_extra_bullet_feedback_entry_is_rejected():
    extra = [{"bullet_id": "b1", "verdict": "keep", "comment": ""},
             {"bullet_id": "b_unknown", "verdict": "keep", "comment": ""}]
    with pytest.raises(FeedbackValidationError, match="b_unknown"):
        parse_feedback_form(form(bullet_feedback=extra), **KW)


def test_duplicate_bullet_feedback_entry_is_rejected():
    dup = [{"bullet_id": "b1", "verdict": "keep", "comment": ""},
           {"bullet_id": "b1", "verdict": "reword", "comment": "x"}]
    with pytest.raises(FeedbackValidationError, match="duplicate"):
        parse_feedback_form(form(bullet_feedback=dup), **KW)


def test_unsupported_claim_quote_must_be_an_exact_substring():
    claim = [{"bullet_id": "b1", "quoted_text": "never appeared", "why": "misleading"}]
    with pytest.raises(FeedbackValidationError, match="quoted_text"):
        parse_feedback_form(form(unsupported_claims=claim), **KW)


def test_unsupported_claim_with_a_real_substring_is_accepted():
    claim = [{"bullet_id": "b1", "quoted_text": "sharding the write path", "why": "I only tuned it"}]
    record = parse_feedback_form(form(unsupported_claims=claim), **KW)
    assert record.unsupported_claims[0].bullet_id == "b1"


def test_fingerprint_disagreement_is_rejected():
    with pytest.raises(FeedbackValidationError, match="fingerprint"):
        parse_feedback_form(form(alignment_fingerprint="different"), **KW)


def test_unknown_schema_version_is_rejected():
    with pytest.raises(FeedbackValidationError, match="schema_version"):
        parse_feedback_form(form(schema_version="m8p6.feedback_record.v99"), **KW)


def test_non_mapping_yaml_is_a_parse_error():
    with pytest.raises(FeedbackParseError):
        parse_feedback_form("- just\n- a list\n", **KW)


def test_duplicate_missing_skill_terms_are_rejected():
    with pytest.raises(FeedbackValidationError, match="missing_skills"):
        parse_feedback_form(form(missing_skills=["Go", "go"]), **KW)
