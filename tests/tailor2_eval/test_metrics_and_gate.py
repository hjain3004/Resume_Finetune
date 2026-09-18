"""Required tests 15, 16, 18, 19: aggregate metrics, factual-vs-subjective
reporting separation, usable-artifact rate, and release-gate explanations."""

from __future__ import annotations

from src.tailor2_eval.metrics import compute_aggregate_summary
from src.tailor2_eval.release_gate import evaluate_release_gate
from src.tailor2_eval.reports import classify_failures


def test_usable_artifact_rate_computed_correctly(all_target_results) -> None:
    # 8 target results total; only "fatal_integrity_failure" is unusable.
    summary = compute_aggregate_summary("plan-x", all_target_results)
    assert summary.target_count == 8
    expected_usable = 7 / 8
    assert abs(summary.usable_artifact_rate - expected_usable) < 1e-9
    assert abs(summary.fatal_integrity_rate - (1 / 8)) < 1e-9


def test_aggregate_metrics_are_correct_on_known_inputs(target_result_factory) -> None:
    clean = target_result_factory("accepted_cleanly")
    fatal = target_result_factory("fatal_integrity_failure")
    summary = compute_aggregate_summary("plan-x", [clean, fatal])

    assert summary.target_count == 2
    assert summary.usable_artifact_rate == 0.5
    assert summary.fatal_integrity_rate == 0.5
    assert summary.avg_provider_calls == (clean.provider_call_count + fatal.provider_call_count) / 2
    assert summary.avg_cost_usd == (clean.estimated_cost_usd + fatal.estimated_cost_usd) / 2
    assert summary.status_counts == {"ACCEPTED": 1, "REJECTED_FATAL": 1}


def test_aggregate_metrics_empty_input_never_divides_by_zero() -> None:
    summary = compute_aggregate_summary("plan-empty", [])
    assert summary.target_count == 0
    assert summary.usable_artifact_rate == 0.0
    assert summary.fatal_integrity_rate == 0.0


def test_fatal_and_subjective_failures_reported_separately(all_target_results) -> None:
    buckets = classify_failures(all_target_results)
    assert buckets["factual_failures"] == ["roadrunner_5027"]
    assert "tiktok_4164" in buckets["subjective_quality_concerns"]
    assert "tiktok_4164" not in buckets["factual_failures"]
    assert "roadrunner_5027" not in buckets["subjective_quality_concerns"]


def test_release_gate_explains_every_failure(all_target_results) -> None:
    summary = compute_aggregate_summary("plan-x", all_target_results)  # has 1 fatal -> gate must fail
    decision = evaluate_release_gate(summary)

    assert decision.is_established_policy is False
    assert decision.overall_pass is False
    failing = [c for c in decision.criteria if not c.passed]
    assert failing, "at least one criterion must fail given a fatal-integrity result is present"
    for criterion in failing:
        assert criterion.description
        assert criterion.observed_value is not None or criterion.criterion_id == "strong_human_preference_over_prior_pipeline"
        assert criterion.threshold is not None


def test_release_gate_passes_on_all_clean_results(target_result_factory, human_review_factory) -> None:
    clean = target_result_factory("accepted_cleanly")
    review = human_review_factory("ab_preference_new_pipeline")
    summary = compute_aggregate_summary("plan-clean", [clean], [review])
    decision = evaluate_release_gate(summary)
    assert decision.overall_pass is True
    assert all(c.passed for c in decision.criteria)
