"""Deterministic, privacy-bounded review reports for resume evidence corpora."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass

from src.resume_evidence.importer import ValidatedCorpus
from src.resume_evidence.model import SCHEMA_VERSION


@dataclass(frozen=True)
class ReportOutcome:
    reference_id: str
    admission_status: str
    admission_reasons: tuple[str, ...]
    disposition: str
    exclusion_reason: str | None
    source_kind: str
    role_family: str
    outcome_tier: str
    evidence_confidence: str
    representation: str
    professional_experience_months: int


@dataclass(frozen=True)
class ResearchReport:
    schema_version: str
    corpus_version: str
    outcomes: tuple[ReportOutcome, ...]
    duplicates: tuple[tuple[str, str, str, float], ...]
    outcome_counts: tuple[tuple[str, int], ...]
    disposition_counts: tuple[tuple[str, int], ...]
    canonical_counts: tuple[tuple[str, int], ...]
    source_kind_counts: tuple[tuple[str, int], ...]
    role_family_counts: tuple[tuple[str, int], ...]
    outcome_tier_counts: tuple[tuple[str, int], ...]
    evidence_confidence_counts: tuple[tuple[str, int], ...]
    representation_counts: tuple[tuple[str, int], ...]


def _count(values) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def build_report(validated: ValidatedCorpus) -> ResearchReport:
    """Build a stable report containing annotations and decisions, never snapshots."""
    candidates = {item.reference_id: item for item in validated.outcomes}
    rows = []
    for decision in sorted(validated.decisions, key=lambda item: item.reference_id):
        candidate = candidates[decision.reference_id]
        rows.append(
            ReportOutcome(
                reference_id=decision.reference_id,
                admission_status=decision.admission.status.value,
                admission_reasons=tuple(sorted(decision.admission.reasons)),
                disposition=decision.disposition,
                exclusion_reason=decision.exclusion_reason,
                source_kind=candidate.source_kind.value,
                role_family=candidate.role_family.value,
                outcome_tier=candidate.outcome_tier.value,
                evidence_confidence=candidate.outcome_evidence_confidence.value,
                representation=candidate.resume_representation.value,
                professional_experience_months=decision.admission.computed_experience_months,
            )
        )
    canonical_outcomes = sum(row.disposition == "promote" for row in rows)
    status_counts = Counter(row.admission_status for row in rows)
    outcome_counts = tuple(
        sorted(
            {
                "accepted": status_counts["accepted"],
                "needs_review": status_counts["needs_review"],
                "rejected": status_counts["rejected"],
                "total": len(rows),
            }.items()
        )
    )
    duplicate_rows = tuple(
        sorted(
            (
                pair.left_id,
                pair.right_id,
                pair.kind,
                round(pair.similarity, 6),
            )
            for pair in validated.duplicates
        )
    )
    return ResearchReport(
        schema_version=SCHEMA_VERSION,
        corpus_version=validated.corpus_version,
        outcomes=tuple(rows),
        duplicates=duplicate_rows,
        outcome_counts=outcome_counts,
        disposition_counts=_count(row.disposition for row in rows),
        canonical_counts=tuple(
            sorted(
                {
                    "outcomes": canonical_outcomes,
                    "doctrine": len(validated.doctrine),
                    "patterns": len(validated.patterns),
                }.items()
            )
        ),
        source_kind_counts=_count(row.source_kind for row in rows),
        role_family_counts=_count(row.role_family for row in rows),
        outcome_tier_counts=_count(row.outcome_tier for row in rows),
        evidence_confidence_counts=_count(row.evidence_confidence for row in rows),
        representation_counts=_count(row.representation for row in rows),
    )


def report_to_dict(report: ResearchReport) -> dict[str, object]:
    def counts(value: tuple[tuple[str, int], ...]) -> dict[str, int]:
        return dict(value)

    return {
        "schema_version": report.schema_version,
        "corpus_version": report.corpus_version,
        "outcome_counts": counts(report.outcome_counts),
        "disposition_counts": counts(report.disposition_counts),
        "canonical_counts": counts(report.canonical_counts),
        "duplicate_count": len(report.duplicates),
        "source_kind_counts": counts(report.source_kind_counts),
        "role_family_counts": counts(report.role_family_counts),
        "outcome_tier_counts": counts(report.outcome_tier_counts),
        "evidence_confidence_counts": counts(report.evidence_confidence_counts),
        "representation_counts": counts(report.representation_counts),
        "outcomes": [
            {
                "reference_id": row.reference_id,
                "admission_status": row.admission_status,
                "admission_reasons": list(row.admission_reasons),
                "disposition": row.disposition,
                "exclusion_reason": row.exclusion_reason,
                "source_kind": row.source_kind,
                "role_family": row.role_family,
                "outcome_tier": row.outcome_tier,
                "evidence_confidence": row.evidence_confidence,
                "representation": row.representation,
                "professional_experience_months": row.professional_experience_months,
            }
            for row in report.outcomes
        ],
        "duplicates": [
            {
                "left_id": left,
                "right_id": right,
                "kind": kind,
                "similarity": similarity,
            }
            for left, right, kind, similarity in report.duplicates
        ],
    }


def _canonical_json(report: ResearchReport) -> str:
    return (
        json.dumps(
            report_to_dict(report),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )


def report_sha256(report: ResearchReport) -> str:
    return hashlib.sha256(_canonical_json(report).encode("utf-8")).hexdigest()


def render_report_markdown(report: ResearchReport) -> str:
    """Render a stable human review surface with an explicit, non-approving command."""
    digest = report_sha256(report)
    lines = [
        "# Resume Evidence Research Report",
        "",
        f"Corpus version: `{report.corpus_version}`",
        f"Report SHA-256: `{digest}`",
        "",
        "## Outcome dispositions",
        "",
        "| ID | Admission | Manifest disposition | Exclusion reason |",
        "|---|---|---|---|",
    ]
    for row in report.outcomes:
        reason = row.exclusion_reason or "—"
        lines.append(
            f"| {row.reference_id} | {row.admission_status} | {row.disposition} | {reason} |"
        )
    lines.extend(
        [
            "",
            "## Duplicate review",
            "",
            "| Left | Right | Kind | Similarity |",
            "|---|---|---|---:|",
        ]
    )
    if report.duplicates:
        for left, right, kind, similarity in report.duplicates:
            lines.append(f"| {left} | {right} | {kind} | {similarity:.6f} |")
    else:
        lines.append("| — | — | none | 0.000000 |")
    lines.extend(
        [
            "",
            "## Approval command (run only after human review)",
            "",
            "```bash",
            "python -m scripts.resume_evidence import-corpus \\",
            "  --inbox <PRIVATE_INBOX> --manifest <MANIFEST> --bank-root config/resume_evidence_bank \\",
            f"  --approved-report-sha256 {digest} --approved-at <UTC_TIMESTAMP>",
            "```",
            "",
        ]
    )
    return "\n".join(lines)

