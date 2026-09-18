"""Deterministic report generation over evaluation results.

Every writer here sorts its inputs by a stable key (`target_id`) before
emitting anything, so two runs over the same result set byte-for-byte agree
-- required for the reports to be diffable across pipeline versions.
Failure classification is explicit rather than inferred from free text:
`status == "REJECTED_FATAL"` is a factual failure, `SKIPPED_BUDGET` /
`RENDER_FAILED_FALLBACK` are operational failures, `NEEDS_HUMAN_REVIEW` /
`ACCEPTED_WITH_WARNINGS` are subjective-quality concerns, a non-empty
`evidence_gaps` is an evidence gap regardless of status, and a non-empty
`render_summary.layout_warnings` is a layout concern regardless of status.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from src.tailor.artifacts import write_json_atomic
from src.tailor2_eval.schemas import AggregateSummary, ReleaseGateDecision, TargetResult, aggregate_summary_to_dict, release_gate_decision_to_dict, target_result_to_dict


def _sorted(results: list[TargetResult]) -> list[TargetResult]:
    return sorted(results, key=lambda r: r.target_id)


def classify_failures(results: list[TargetResult]) -> dict[str, list[str]]:
    """target_ids bucketed by failure/concern category (a target may appear
    in more than one bucket, e.g. a NEEDS_HUMAN_REVIEW run with an evidence
    gap appears under both)."""
    buckets: dict[str, list[str]] = {
        "factual_failures": [],
        "operational_failures": [],
        "subjective_quality_concerns": [],
        "evidence_gaps": [],
        "layout_concerns": [],
    }
    for r in _sorted(results):
        if r.status == "REJECTED_FATAL":
            buckets["factual_failures"].append(r.target_id)
        if r.status in ("SKIPPED_BUDGET", "RENDER_FAILED_FALLBACK", "INTERRUPTED"):
            buckets["operational_failures"].append(r.target_id)
        if r.status in ("NEEDS_HUMAN_REVIEW", "ACCEPTED_WITH_WARNINGS"):
            buckets["subjective_quality_concerns"].append(r.target_id)
        if r.evidence_gaps:
            buckets["evidence_gaps"].append(r.target_id)
        if r.render_summary.layout_warnings:
            buckets["layout_concerns"].append(r.target_id)
    return buckets


def generate_json_summary(results: list[TargetResult], summary: AggregateSummary, out_path: Path) -> None:
    payload = {
        "aggregate": aggregate_summary_to_dict(summary),
        "targets": [target_result_to_dict(r) for r in _sorted(results)],
    }
    write_json_atomic(out_path, payload)


def generate_csv_matrix(results: list[TargetResult], out_path: Path) -> None:
    fieldnames = [
        "target_id", "company", "role", "status", "provider_call_count",
        "estimated_cost_usd", "latency_seconds", "repair_count",
        "one_page", "layout_warning_count", "evidence_gap_count",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in _sorted(results):
        writer.writerow(
            {
                "target_id": r.target_id,
                "company": r.company,
                "role": r.role,
                "status": r.status,
                "provider_call_count": r.provider_call_count,
                "estimated_cost_usd": r.estimated_cost_usd,
                "latency_seconds": r.latency_seconds if r.latency_seconds is not None else "",
                "repair_count": r.repair_count,
                "one_page": r.render_summary.one_page if r.render_summary.one_page is not None else "",
                "layout_warning_count": len(r.render_summary.layout_warnings),
                "evidence_gap_count": len(r.evidence_gaps),
            }
        )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(buf.getvalue(), encoding="utf-8")


def generate_markdown_report(
    results: list[TargetResult],
    summary: AggregateSummary,
    gate: ReleaseGateDecision,
    out_path: Path,
) -> None:
    buckets = classify_failures(results)
    lines = [
        f"# Tailor2 Evaluation Report -- plan `{summary.plan_id}`",
        "",
        "## Aggregate metrics",
        f"- Targets evaluated: {summary.target_count}",
        f"- Usable-artifact rate: {summary.usable_artifact_rate:.2%}",
        f"- Fatal-integrity rate: {summary.fatal_integrity_rate:.2%}",
        f"- Warning/human-review rate: {summary.warning_or_human_review_rate:.2%}",
        f"- Repair frequency: {summary.repair_frequency:.2%}",
        f"- Avg provider calls: {summary.avg_provider_calls:.2f}",
        f"- Avg cost (USD): {summary.avg_cost_usd:.4f}",
        f"- Avg latency (s): {summary.avg_latency_seconds:.2f}",
        f"- One-page success rate: {summary.one_page_success_rate:.2%}",
        f"- Layout-warning rate: {summary.layout_warning_rate:.2%}",
        f"- Evidence-gap rate: {summary.evidence_gap_rate:.2%}",
        "",
        "## Release gate " + ("(PASS)" if gate.overall_pass else "(FAIL)"),
        "**Proposed thresholds, not established repo policy.**" if not gate.is_established_policy else "",
    ]
    for c in gate.criteria:
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"- [{mark}] {c.criterion_id}: {c.description} (observed={c.observed_value!r}, threshold={c.threshold!r})")

    lines += ["", "## Failure & concern inventory"]
    for bucket, ids in buckets.items():
        lines.append(f"- {bucket}: {', '.join(ids) if ids else 'none'}")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_failure_inventory(results: list[TargetResult], out_path: Path) -> None:
    write_json_atomic(out_path, classify_failures(results))


def generate_cost_latency_summary(results: list[TargetResult], out_path: Path) -> None:
    rows = [
        {
            "target_id": r.target_id,
            "provider_call_count": r.provider_call_count,
            "estimated_cost_usd": r.estimated_cost_usd,
            "latency_seconds": r.latency_seconds,
        }
        for r in _sorted(results)
    ]
    write_json_atomic(out_path, rows)


def generate_human_preference_summary(summary: AggregateSummary, out_path: Path) -> None:
    write_json_atomic(out_path, summary.human_preference_summary)


def generate_unresolved_evidence_report(results: list[TargetResult], out_path: Path) -> None:
    rows = [
        {"target_id": r.target_id, "evidence_gaps": list(r.evidence_gaps)}
        for r in _sorted(results)
        if r.evidence_gaps
    ]
    write_json_atomic(out_path, rows)


def generate_all_reports(
    results: list[TargetResult],
    summary: AggregateSummary,
    gate: ReleaseGateDecision,
    out_dir: Path,
) -> dict[str, Path]:
    out_dir = Path(out_dir)
    paths = {
        "json_summary": out_dir / "summary.json",
        "csv_matrix": out_dir / "targets.csv",
        "markdown_report": out_dir / "report.md",
        "failure_inventory": out_dir / "failure_inventory.json",
        "cost_latency_summary": out_dir / "cost_latency.json",
        "human_preference_summary": out_dir / "human_preference.json",
        "unresolved_evidence_report": out_dir / "unresolved_evidence.json",
    }
    generate_json_summary(results, summary, paths["json_summary"])
    generate_csv_matrix(results, paths["csv_matrix"])
    generate_markdown_report(results, summary, gate, paths["markdown_report"])
    generate_failure_inventory(results, paths["failure_inventory"])
    generate_cost_latency_summary(results, paths["cost_latency_summary"])
    generate_human_preference_summary(summary, paths["human_preference_summary"])
    generate_unresolved_evidence_report(results, paths["unresolved_evidence_report"])
    write_json_atomic(out_dir / "release_gate.json", release_gate_decision_to_dict(gate))
    return paths
