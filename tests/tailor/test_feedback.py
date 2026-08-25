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


# ---------------------------------------------------------------------------
# Task 2: immutable append-only feedback storage and summary
# ---------------------------------------------------------------------------

from src.tailor.feedback import (  # noqa: E402 -- Task 2 additions, appended per plan
    DEFAULT_FEEDBACK_DIR,
    FeedbackOutcomeKind,
    load_feedback_index,
    store_feedback,
    summarize_feedback,
)

_BULLET_TEXT = KW["bullet_plain_text_by_id"]


@pytest.fixture
def record():
    return parse_feedback_form(form(), **KW)


@pytest.fixture
def revised_record():
    """A differing second assessment of the SAME (job_id, fingerprint) key."""
    return parse_feedback_form(
        form(would_submit="not_as_is", free_form="on second look, reword the latency bullet"),
        **KW,
    )


@pytest.fixture
def other_fingerprint_record():
    """Same job_id, a genuinely different alignment_fingerprint -- a
    different draft entirely, so it must never collide with `record`."""
    other_kw = dict(KW, alignment_fingerprint="fpDIFFERENT00")
    return parse_feedback_form(form(alignment_fingerprint="fpDIFFERENT00"), **other_kw)


@pytest.fixture
def mixed_records():
    """Three records across two distinct job ids, no revision collisions,
    with varied accept/would_submit/scores for summary-statistics coverage."""
    first = parse_feedback_form(form(), **KW)  # job 225, accept, yes, 3/3
    second_kw = dict(KW, alignment_fingerprint="fpSECONDXXXXX")
    second = parse_feedback_form(
        form(alignment_fingerprint="fpSECONDXXXXX", accept="reject", would_submit="no",
             company_alignment=1, visual_quality=1),
        **second_kw,
    )
    third_kw = dict(job_id=999, alignment_fingerprint="fpTHIRDXXXXXX",
                    changed_bullet_ids=frozenset({"b1"}), bullet_plain_text_by_id=_BULLET_TEXT)
    third = parse_feedback_form(
        form(job_id=999, alignment_fingerprint="fpTHIRDXXXXXX", would_submit="not_as_is",
             needs_another_revision="yes", company_alignment=2, visual_quality=2),
        **third_kw,
    )
    return [first, second, third]


def test_default_feedback_dir_is_under_gitignored_data():
    assert DEFAULT_FEEDBACK_DIR.parts[0] == "data"


def test_first_record_is_revision_one(tmp_path, record):
    outcome = store_feedback(record, feedback_dir=tmp_path)
    assert outcome.kind is FeedbackOutcomeKind.RECORDED
    assert outcome.revision == 1
    assert outcome.path.name.endswith("-r1.json")
    assert len(load_feedback_index(tmp_path)) == 1


def test_identical_rerecord_is_idempotent(tmp_path, record):
    store_feedback(record, feedback_dir=tmp_path)
    before = (tmp_path / "index.jsonl").read_bytes()
    outcome = store_feedback(record, feedback_dir=tmp_path)
    assert outcome.kind is FeedbackOutcomeKind.ALREADY_RECORDED
    assert (tmp_path / "index.jsonl").read_bytes() == before


def test_differing_second_assessment_creates_r2_and_preserves_r1(tmp_path, record, revised_record):
    first = store_feedback(record, feedback_dir=tmp_path)
    original = first.path.read_bytes()
    second = store_feedback(revised_record, feedback_dir=tmp_path)
    assert second.revision == 2
    assert first.path.read_bytes() == original
    assert len(load_feedback_index(tmp_path)) == 2


def test_records_for_different_fingerprints_do_not_collide(tmp_path, record, other_fingerprint_record):
    store_feedback(record, feedback_dir=tmp_path)
    other = store_feedback(other_fingerprint_record, feedback_dir=tmp_path)
    assert other.revision == 1


def test_summary_counts_match_the_records(tmp_path, mixed_records):
    for item in mixed_records:
        store_feedback(item, feedback_dir=tmp_path)
    summary = summarize_feedback(tmp_path)
    assert summary.total == len(mixed_records)
    assert summary.accepted + summary.rejected == summary.total
    assert 1.0 <= summary.mean_visual_quality <= 3.0


def test_summary_can_filter_by_job(tmp_path, mixed_records):
    for item in mixed_records:
        store_feedback(item, feedback_dir=tmp_path)
    assert summarize_feedback(tmp_path, job_id=225).total < summarize_feedback(tmp_path).total


def test_summary_is_read_only(tmp_path, record):
    store_feedback(record, feedback_dir=tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    summarize_feedback(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# ---------------------------------------------------------------------------
# Task 3: taste-candidate derivation (pure, writes nothing)
# ---------------------------------------------------------------------------

from pathlib import Path as _Path  # noqa: E402 -- Task 3 addition, appended per plan

from src.tailor.feedback import derive_taste_candidates  # noqa: E402


@pytest.fixture
def record_with_reword():
    return parse_feedback_form(
        form(bullet_feedback=[{"bullet_id": "b1", "verdict": "reword", "comment": "too generic, name the tool"}]),
        **KW,
    )


@pytest.fixture
def record_with_empty_reword_comment():
    return parse_feedback_form(
        form(bullet_feedback=[{"bullet_id": "b1", "verdict": "reword", "comment": ""}]),
        **KW,
    )


@pytest.fixture
def record_overemphasized():
    return parse_feedback_form(form(overemphasized_skills=["Kubernetes"]), **KW)


@pytest.fixture
def record_unsupported():
    claim = [{"bullet_id": "b1", "quoted_text": "sharding the write path", "why": "I only tuned it"}]
    return parse_feedback_form(form(unsupported_claims=claim), **KW)


def test_reword_with_comment_yields_a_candidate(record_with_reword):
    candidates = derive_taste_candidates(record_with_reword)
    assert any("reword" in c.evidence for c in candidates)
    assert all(c.date == record_with_reword.reviewed_at for c in candidates)


def test_reword_without_comment_yields_nothing(record_with_empty_reword_comment):
    assert derive_taste_candidates(record_with_empty_reword_comment) == ()


def test_overemphasized_skill_is_mechanically_enforceable(record_overemphasized):
    candidate = next(c for c in derive_taste_candidates(record_overemphasized)
                     if "overemphas" in c.evidence)
    assert candidate.mechanically_enforceable is True


def test_unsupported_claim_is_not_mechanically_enforceable(record_unsupported):
    candidate = next(c for c in derive_taste_candidates(record_unsupported)
                     if "unsupported" in c.evidence)
    assert candidate.mechanically_enforceable is False


def test_derivation_writes_nothing(record_with_reword):
    taste_before = _Path("config/taste.md").read_bytes()
    banned_before = _Path("config/banned_words.txt").read_bytes()
    derive_taste_candidates(record_with_reword)
    assert _Path("config/taste.md").read_bytes() == taste_before
    assert _Path("config/banned_words.txt").read_bytes() == banned_before


def test_derivation_is_deterministic(record_with_reword):
    assert derive_taste_candidates(record_with_reword) == derive_taste_candidates(record_with_reword)


def test_feedback_module_makes_no_model_call():
    source = _Path("src/tailor/feedback.py").read_text(encoding="utf-8")
    assert "src.tailor.invoke" not in source
    assert "src.llm_trace" not in source
