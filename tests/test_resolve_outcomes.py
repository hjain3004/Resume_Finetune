import pytest

from src.models import ResolvedJD
from src.resolve import outcomes as outcomes_module
from src.resolve.outcomes import (
    ResolutionIssue,
    ResolutionOutcome,
    ResolutionOutcomeKind,
    ResolutionSummary,
)


def _row(job_id=1, url="https://example.com/job/1", source="tracker_vansh"):
    return {"id": job_id, "url": url, "source": source}


# --- ResolutionOutcome constructors and invariants -------------------------


def test_resolved_outcome_carries_the_result():
    result = ResolvedJD("jd text", "greenhouse")
    outcome = ResolutionOutcome.resolved(result)
    assert outcome.kind == ResolutionOutcomeKind.RESOLVED
    assert outcome.result is result


def test_resolved_kind_without_result_is_rejected():
    with pytest.raises(ValueError):
        ResolutionOutcome(ResolutionOutcomeKind.RESOLVED, result=None)


def test_non_resolved_kind_with_a_result_is_rejected():
    result = ResolvedJD("jd text", "greenhouse")
    with pytest.raises(ValueError):
        ResolutionOutcome(ResolutionOutcomeKind.CONTENT_FAILURE, result=result)


def test_content_failure_constructor():
    outcome = ResolutionOutcome.content_failure("no_acceptable_content")
    assert outcome.kind == ResolutionOutcomeKind.CONTENT_FAILURE
    assert outcome.result is None
    assert outcome.reason_code == "no_acceptable_content"


def test_transient_constructor_captures_reason_and_message():
    exc = ConnectionError("Connection aborted.")
    outcome = ResolutionOutcome.transient("http_transport", exc)
    assert outcome.kind == ResolutionOutcomeKind.TRANSIENT_FAILURE
    assert outcome.reason_code == "http_transport"
    assert "Connection aborted." in outcome.message


def test_internal_constructor_captures_reason_and_message():
    exc = RuntimeError("boom")
    outcome = ResolutionOutcome.internal("unexpected_exception", exc)
    assert outcome.kind == ResolutionOutcomeKind.INTERNAL_ERROR
    assert outcome.reason_code == "unexpected_exception"
    assert "boom" in outcome.message


def test_outcome_message_is_bounded():
    exc = RuntimeError("x" * 10_000)
    outcome = ResolutionOutcome.internal("unexpected_exception", exc)
    assert len(outcome.message) <= 500


# --- ResolutionIssue --------------------------------------------------------


def test_resolution_issue_message_is_bounded():
    issue = ResolutionIssue(
        job_id=1,
        url="https://example.com/job/1",
        kind=ResolutionOutcomeKind.INTERNAL_ERROR,
        reason_code="unexpected_exception",
        message="x" * 10_000,
    )
    assert len(issue.message) <= 500


# --- ResolutionSummary -------------------------------------------------------


def test_summary_records_a_resolved_tier1_outcome():
    summary = ResolutionSummary()
    result = ResolvedJD("jd text", "greenhouse")
    summary.record(_row(source="tracker_vansh"), ResolutionOutcome.resolved(result))

    assert summary.resolved == 1
    assert summary.tier1 == 1
    assert summary.tier2 == 0
    assert summary.per_source["tracker_vansh"] == {"resolved": 1, "failed": 0}
    assert summary.issues == []


def test_summary_records_a_resolved_tier2_outcome():
    summary = ResolutionSummary()
    result = ResolvedJD("jd text", "browser", jd_quality="ats")
    summary.record(_row(), ResolutionOutcome.resolved(result))

    assert summary.tier2 == 1
    assert summary.tier1 == 0


def test_summary_records_a_content_failure():
    summary = ResolutionSummary()
    summary.record(
        _row(job_id=2, source="tracker_simplify"),
        ResolutionOutcome.content_failure("no_acceptable_content"),
    )

    assert summary.content_failed == 1
    assert summary.resolved == 0
    assert summary.per_source["tracker_simplify"] == {"resolved": 0, "failed": 1}
    assert len(summary.issues) == 1
    assert summary.issues[0].job_id == 2
    assert summary.issues[0].reason_code == "no_acceptable_content"


def test_summary_records_a_transient_failure_without_touching_per_source():
    summary = ResolutionSummary()
    summary.record(
        _row(source="tracker_vansh"),
        ResolutionOutcome.transient("http_transport", ConnectionError("reset")),
    )

    assert summary.transient == 1
    assert summary.content_failed == 0
    assert summary.per_source == {}
    assert len(summary.issues) == 1
    assert summary.issues[0].kind == ResolutionOutcomeKind.TRANSIENT_FAILURE


def test_summary_records_an_internal_error_without_touching_per_source():
    summary = ResolutionSummary()
    summary.record(
        _row(source="tracker_vansh"),
        ResolutionOutcome.internal("unexpected_exception", RuntimeError("boom")),
    )

    assert summary.internal == 1
    assert summary.per_source == {}
    assert len(summary.issues) == 1
    assert summary.issues[0].kind == ResolutionOutcomeKind.INTERNAL_ERROR


def test_summary_accumulates_across_multiple_records():
    summary = ResolutionSummary()
    summary.record(_row(job_id=1, source="a"), ResolutionOutcome.resolved(ResolvedJD("t", "greenhouse")))
    summary.record(_row(job_id=2, source="a"), ResolutionOutcome.content_failure("no_acceptable_content"))
    summary.record(_row(job_id=3, source="b"), ResolutionOutcome.transient("http_transport", ConnectionError()))

    assert summary.resolved == 1
    assert summary.content_failed == 1
    assert summary.transient == 1
    assert summary.per_source["a"] == {"resolved": 1, "failed": 1}
    assert "b" not in summary.per_source
