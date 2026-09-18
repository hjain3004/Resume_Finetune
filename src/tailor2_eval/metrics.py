"""Aggregate release metrics over a set of TargetResult / HumanReviewResponse.

"Usable artifact" means the run produced a résumé a human could actually
receive: every status except REJECTED_FATAL and SKIPPED_BUDGET (an
ACCEPTED_WITH_WARNINGS, NEEDS_HUMAN_REVIEW, or even a RENDER_FAILED_FALLBACK
result still has *something* to hand a reviewer -- see docs/
tailor2_evaluation_harness.md for why fallback rendering counts as usable).
Rates are computed over `len(results)`, or 0.0 for an empty set (never a
ZeroDivisionError).
"""

from __future__ import annotations

from collections import Counter

from src.tailor2_eval.schemas import AggregateSummary, HumanReviewResponse, TargetResult

_UNUSABLE_STATUSES = ("REJECTED_FATAL", "SKIPPED_BUDGET")
_WARNING_OR_REVIEW_STATUSES = ("ACCEPTED_WITH_WARNINGS", "NEEDS_HUMAN_REVIEW", "RENDER_FAILED_FALLBACK")


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def compute_aggregate_summary(
    plan_id: str,
    results: list[TargetResult],
    human_reviews: list[HumanReviewResponse] | None = None,
) -> AggregateSummary:
    human_reviews = human_reviews or []
    total = len(results)

    status_counts = Counter(r.status for r in results)
    usable = sum(1 for r in results if r.status not in _UNUSABLE_STATUSES)
    fatal = sum(1 for r in results if r.status == "REJECTED_FATAL")
    warn_or_review = sum(1 for r in results if r.status in _WARNING_OR_REVIEW_STATUSES)
    repaired = sum(1 for r in results if r.repair_count > 0)
    one_page = sum(1 for r in results if r.render_summary.one_page is True)
    with_layout_warnings = sum(1 for r in results if r.render_summary.layout_warnings)
    with_evidence_gaps = sum(1 for r in results if r.evidence_gaps)

    calls = [r.provider_call_count for r in results]
    costs = [r.estimated_cost_usd for r in results]
    latencies = [r.latency_seconds for r in results if r.latency_seconds is not None]

    preference_counts = Counter(hr.overall_preference for hr in human_reviews)
    factual_error_reports = sum(1 for hr in human_reviews if hr.factual_error_flags)

    summary = AggregateSummary(
        schema_version="1.0",
        plan_id=plan_id,
        target_count=total,
        usable_artifact_rate=_rate(usable, total),
        fatal_integrity_rate=_rate(fatal, total),
        warning_or_human_review_rate=_rate(warn_or_review, total),
        repair_frequency=_rate(repaired, total),
        avg_provider_calls=(sum(calls) / total) if total else 0.0,
        avg_cost_usd=(sum(costs) / total) if total else 0.0,
        avg_latency_seconds=(sum(latencies) / len(latencies)) if latencies else 0.0,
        one_page_success_rate=_rate(one_page, total),
        layout_warning_rate=_rate(with_layout_warnings, total),
        evidence_gap_rate=_rate(with_evidence_gaps, total),
        human_preference_summary=dict(preference_counts),
        factual_error_report_count=factual_error_reports,
        status_counts=dict(status_counts),
    )
    return summary
