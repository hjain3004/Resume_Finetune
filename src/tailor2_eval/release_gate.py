"""Proposed (NOT established) Tailor2 release-readiness gate.

A repo-wide search for "G2", "G3", "release gate", and "pilot" turned up
only the unrelated legacy `src/tailor/` critic stages (G1 static critic, G2
anchored critic/revision loop, G3 review packet -- see docs/ARCHITECTURE.md
and docs/ROADMAP.md). Those are stages of the OLD `src/tailor/` pipeline,
not a release policy for Tailor2 evaluation results, and this module must
not be confused with them or reuse their names. No Tailor2-evaluation
release policy exists anywhere in the repo today.

Every criterion below is therefore a PROPOSAL, carried in
`ReleaseGateDecision.is_established_policy = False`. It should be reviewed
and either promoted to real policy (recorded in docs/DECISIONS.md, per
CLAUDE.md's "docs are authoritative" rule) or replaced before it is ever
used to block a real release decision.
"""

from __future__ import annotations

from src.tailor2_eval.schemas import AggregateSummary, GateCriterionResult, ReleaseGateDecision

# Mirrors the task's stated "intended release direction": zero fabricated
# claims, zero altered protected metrics, zero unresolved evidence
# violations, usable artifacts for all Top-10 targets, no repeated
# stage-collapse behavior, strong human preference over the prior pipeline.
PROPOSED_THRESHOLDS = {
    "fatal_integrity_rate_max": 0.0,
    "usable_artifact_rate_min": 1.0,
    "human_preference_min_share": 0.6,  # share of non-tie human preferences favoring the candidate
}


def evaluate_release_gate(summary: AggregateSummary) -> ReleaseGateDecision:
    criteria: list[GateCriterionResult] = []

    criteria.append(
        GateCriterionResult(
            criterion_id="zero_fatal_integrity_failures",
            description="No target may end REJECTED_FATAL (fabricated claims, altered protected metrics, unresolved evidence).",
            passed=summary.fatal_integrity_rate <= PROPOSED_THRESHOLDS["fatal_integrity_rate_max"],
            observed_value=summary.fatal_integrity_rate,
            threshold=PROPOSED_THRESHOLDS["fatal_integrity_rate_max"],
        )
    )
    criteria.append(
        GateCriterionResult(
            criterion_id="usable_artifact_for_every_top10_target",
            description="Every Top-10 target must produce a usable artifact (not REJECTED_FATAL or SKIPPED_BUDGET).",
            passed=summary.usable_artifact_rate >= PROPOSED_THRESHOLDS["usable_artifact_rate_min"],
            observed_value=summary.usable_artifact_rate,
            threshold=PROPOSED_THRESHOLDS["usable_artifact_rate_min"],
        )
    )

    preferences = summary.human_preference_summary
    decisive = sum(v for k, v in preferences.items() if k in ("A", "B"))
    candidate_share = (preferences.get("A", 0) / decisive) if decisive else None
    human_preference_passed = candidate_share is not None and candidate_share >= PROPOSED_THRESHOLDS["human_preference_min_share"]
    criteria.append(
        GateCriterionResult(
            criterion_id="strong_human_preference_over_prior_pipeline",
            description=(
                "Human reviewers must prefer the candidate pipeline (side 'A' in each comparison) "
                "over the baseline in at least the proposed share of decisive (non-tie) comparisons."
            ),
            passed=human_preference_passed,
            observed_value=candidate_share,
            threshold=PROPOSED_THRESHOLDS["human_preference_min_share"],
        )
    )

    return ReleaseGateDecision(
        schema_version="1.0",
        plan_id=summary.plan_id,
        is_established_policy=False,
        overall_pass=all(c.passed for c in criteria),
        criteria=tuple(criteria),
    )
