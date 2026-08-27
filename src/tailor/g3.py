"""G3 human review packet: a deterministic Markdown packet plus a typed
JSON twin, built entirely from already-validated artifacts. No model call,
no judgement -- a "concise S1 summary" here means a deterministic
projection of validated fields, never a generated abstract."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.tailor.artifacts import write_json_atomic
from src.tailor.feedback import build_feedback_form

PACKET_SCHEMA = "m8p6.review_packet.v1"
MAX_LISTED_REQUIREMENTS = 12


class G3Error(ValueError):
    """Raised when a review packet cannot be built without losing or
    fabricating content."""


class G3OutcomeKind(str, Enum):
    INPUT_MISMATCH = "input_mismatch"
    ALREADY_BUILT = "already_built"
    CONFLICT = "conflict"
    BUILT = "built"


@dataclass(frozen=True)
class ReviewPacket:
    schema_version: str
    job_id: int
    company: str
    title: str
    base_variant: str
    alignment_fingerprint: str
    pdf_path: str
    gate_status_line: str
    warnings: tuple[str, ...]
    requirements: tuple[tuple[str, str], ...]
    requirements_omitted: int
    selection_reasons: tuple[tuple[str, str], ...]
    positioning: tuple[str, ...]
    changes: tuple[tuple[str, str, str, str, str], ...]
    coverage: tuple[tuple[str, str, tuple[str, ...]], ...]
    edit_budget: tuple[int, int, float]
    g1_violations: tuple[str, ...]
    g2_rounds: tuple[tuple[int, tuple[tuple[str, int], ...], tuple[str, ...]], ...]
    l7_violations: tuple[str, ...]
    line_counts: tuple[tuple[str, int], ...]
    unified_diff: str


@dataclass(frozen=True)
class G3Outcome:
    kind: G3OutcomeKind
    packet: ReviewPacket | None
    error: str | None


def _g1_violation_line(violation) -> str:
    return f"{violation.rule} {violation.location}: {violation.message}"


def _g2_finding_line(finding) -> str:
    return f"{finding.dimension.value} {finding.rule_id} on {finding.target_id}: {finding.quoted_line!r}"


def build_review_packet(s3_bundle, g2_bundle, render_result, s1, s0, s2) -> ReviewPacket:
    """Bind the three post-gate artifacts by alignment_fingerprint and
    job_id before deriving anything else from them; a disagreement fails
    closed rather than silently trusting one input over another."""
    fingerprints = {s3_bundle.alignment_fingerprint, g2_bundle.alignment_fingerprint, render_result.alignment_fingerprint}
    if len(fingerprints) != 1:
        raise G3Error(f"alignment_fingerprint disagreement across inputs: {sorted(fingerprints)}")
    job_ids = {s3_bundle.job_id, g2_bundle.job_id, render_result.job_id}
    if len(job_ids) != 1:
        raise G3Error(f"job_id disagreement across inputs: {sorted(job_ids)}")

    fingerprint = s3_bundle.alignment_fingerprint
    job_id = s3_bundle.job_id
    company = s3_bundle.company
    title = s3_bundle.title
    base_variant = s3_bundle.draft.base_variant

    g1_status = "static_pass" if s3_bundle.g1.status.value == "static_pass" else "fail"
    last_round = g2_bundle.rounds[-1] if g2_bundle.rounds else None
    g2_status = (
        f"G2 {g2_bundle.verdict.value} (round {last_round.round_index})"
        if last_round is not None else f"G2 {g2_bundle.verdict.value}"
    )
    l7_status = "L7 pass" if not render_result.l7_violations else "L7 fail"
    line_status = f"line check {render_result.render_line_check}"
    gate_status_line = f"G1 {g1_status} · {g2_status} · {l7_status} · {line_status}"

    warnings: list[str] = []
    for finding in g2_bundle.open_findings:
        warnings.append(f"open flag: {_g2_finding_line(finding)} -- {finding.explanation}")
    for flag in s1.suspected_injection:
        warnings.append(f"suspected prompt injection: {flag.quote!r} ({flag.reason})")
    for term in s2.gap_terms:
        warnings.append(f"GAP: {term!r} not covered by any selected bullet")
    for violation in render_result.l7_violations:
        warnings.append(f"L7 advisory: {violation}")

    all_requirements = tuple((item.term, item.quote) for item in s1.must_have)
    requirements = all_requirements[:MAX_LISTED_REQUIREMENTS]
    requirements_omitted = max(0, len(all_requirements) - MAX_LISTED_REQUIREMENTS)

    selection_reasons = tuple((choice.project_id, choice.reason) for choice in s2.projects)
    positioning = tuple(point.sentence for point in s0.points)

    changes = tuple(
        (entry.location, entry.before, entry.after, "; ".join(entry.motivating_jd_quotes), entry.rule)
        for entry in s3_bundle.change_log
    )

    coverage = tuple((entry.term, entry.status, entry.bullet_ids) for entry in s2.coverage)

    edit_budget = (s3_bundle.edit_budget.changed_tokens, s3_bundle.edit_budget.base_tokens, s3_bundle.edit_budget.ratio)
    g1_violations = tuple(_g1_violation_line(item) for item in s3_bundle.g1.violations)

    g2_rounds = tuple(
        (
            round_.round_index,
            tuple((dimension.value, score) for dimension, score in round_.response.scores),
            tuple(_g2_finding_line(finding) for finding in round_.response.findings),
        )
        for round_ in g2_bundle.rounds
    )

    return ReviewPacket(
        schema_version=PACKET_SCHEMA, job_id=job_id, company=company, title=title,
        base_variant=base_variant, alignment_fingerprint=fingerprint, pdf_path=render_result.pdf_path,
        gate_status_line=gate_status_line, warnings=tuple(warnings),
        requirements=requirements, requirements_omitted=requirements_omitted,
        selection_reasons=selection_reasons, positioning=positioning, changes=changes,
        coverage=coverage, edit_budget=edit_budget, g1_violations=g1_violations,
        g2_rounds=g2_rounds, l7_violations=tuple(render_result.l7_violations),
        line_counts=render_result.modified_bullet_line_counts, unified_diff=s3_bundle.unified_diff,
    )


def _section(heading: str, body_lines: list[str]) -> str:
    body = "\n".join(body_lines) if body_lines else "None."
    return f"## {heading}\n\n{body}\n"


def render_review_markdown(packet: ReviewPacket) -> str:
    """Plain GitHub-flavoured Markdown, fixed heading order, no timestamps,
    no absolute paths, no set-iteration-order dependence -- every list here
    is already a tuple in a caller-fixed order, so two calls on the same
    packet always produce byte-identical output."""
    parts: list[str] = []

    parts.append(f"# {packet.company} — {packet.title}\n")
    parts.append(
        f"Job {packet.job_id} · variant `{packet.base_variant}` · PDF: `{packet.pdf_path}`\n\n"
        f"{packet.gate_status_line}\n"
    )

    warning_lines = [f"- {item}" for item in packet.warnings]
    parts.append(_section("Warnings and open flags", warning_lines))

    requirement_lines = [f'- **{term}** — "{quote}"' for term, quote in packet.requirements]
    if packet.requirements_omitted:
        requirement_lines.append(f"- (+{packet.requirements_omitted} more)")
    parts.append(_section("What this job asks for", requirement_lines))

    selection_lines = [f"- base variant: `{packet.base_variant}`"]
    selection_lines.extend(f"- {project_id}: {reason}" for project_id, reason in packet.selection_reasons)
    if packet.positioning:
        selection_lines.append("")
        selection_lines.append("**Positioning:**")
        selection_lines.extend(f"- {sentence}" for sentence in packet.positioning)
    parts.append(_section("What was selected and why", selection_lines))

    if packet.changes:
        change_lines = ["| Location | Before | After | JD quote | Rule |", "|---|---|---|---|---|"]
        for location, before, after, quote, rule in packet.changes:
            change_lines.append(f"| {location} | {before} | {after} | {quote} | {rule} |")
    else:
        change_lines = []
    parts.append(_section("What changed", change_lines))

    coverage_lines = []
    for term, status, bullet_ids in packet.coverage:
        if status == "covered":
            coverage_lines.append(f"- {term}: covered by {', '.join(bullet_ids)}")
        else:
            coverage_lines.append(f"- {term}: GAP")
    parts.append(_section("Coverage", coverage_lines))

    changed_tokens, base_tokens, ratio = packet.edit_budget
    gate_lines = [f"Edit budget: {changed_tokens}/{base_tokens} tokens ({ratio:.4f})", ""]
    gate_lines.append("G1 violations:")
    gate_lines.append("None." if not packet.g1_violations else "\n".join(f"- {v}" for v in packet.g1_violations))
    gate_lines.append("")
    gate_lines.append("G2 rounds:")
    if packet.g2_rounds:
        for round_index, scores, findings in packet.g2_rounds:
            score_text = ", ".join(f"{dim}={value}" for dim, value in scores)
            gate_lines.append(f"- round {round_index}: {score_text}")
            gate_lines.extend(f"  - {finding}" for finding in findings)
    else:
        gate_lines.append("None.")
    gate_lines.append("")
    gate_lines.append("L7 violations:")
    gate_lines.append("None." if not packet.l7_violations else "\n".join(f"- {v}" for v in packet.l7_violations))
    gate_lines.append("")
    gate_lines.append("Rendered line counts:")
    if packet.line_counts:
        gate_lines.extend(f"- {bullet_id}: {count}" for bullet_id, count in packet.line_counts)
    else:
        gate_lines.append("None.")
    parts.append(_section("Gate detail", gate_lines))

    diff_lines = [f"```diff\n{packet.unified_diff}\n```"] if packet.unified_diff else []
    parts.append(_section("Full diff", diff_lines))

    return "\n".join(parts)


def packet_to_dict(packet: ReviewPacket) -> dict[str, object]:
    return {
        "schema_version": packet.schema_version,
        "job_id": packet.job_id,
        "company": packet.company,
        "title": packet.title,
        "base_variant": packet.base_variant,
        "alignment_fingerprint": packet.alignment_fingerprint,
        "pdf_path": packet.pdf_path,
        "gate_status_line": packet.gate_status_line,
        "warnings": list(packet.warnings),
        "requirements": [[term, quote] for term, quote in packet.requirements],
        "requirements_omitted": packet.requirements_omitted,
        "selection_reasons": [[pid, reason] for pid, reason in packet.selection_reasons],
        "positioning": list(packet.positioning),
        "changes": [[loc, before, after, quote, rule] for loc, before, after, quote, rule in packet.changes],
        "coverage": [[term, status, list(bullet_ids)] for term, status, bullet_ids in packet.coverage],
        "edit_budget": list(packet.edit_budget),
        "g1_violations": list(packet.g1_violations),
        "g2_rounds": [
            [round_index, [[dim, score] for dim, score in scores], list(findings)]
            for round_index, scores, findings in packet.g2_rounds
        ],
        "l7_violations": list(packet.l7_violations),
        "line_counts": [[bid, count] for bid, count in packet.line_counts],
        "unified_diff": packet.unified_diff,
    }


_PACKET_KEYS = {
    "schema_version", "job_id", "company", "title", "base_variant", "alignment_fingerprint",
    "pdf_path", "gate_status_line", "warnings", "requirements", "requirements_omitted",
    "selection_reasons", "positioning", "changes", "coverage", "edit_budget", "g1_violations",
    "g2_rounds", "l7_violations", "line_counts", "unified_diff",
}


def parse_packet(raw: object) -> ReviewPacket:
    if not isinstance(raw, dict) or set(raw) != _PACKET_KEYS:
        raise G3Error("$: unexpected field set for a review packet")
    if raw["schema_version"] != PACKET_SCHEMA:
        raise G3Error(f"$.schema_version: expected {PACKET_SCHEMA!r}")
    changed_tokens, base_tokens, ratio = raw["edit_budget"]
    return ReviewPacket(
        schema_version=raw["schema_version"], job_id=raw["job_id"], company=raw["company"],
        title=raw["title"], base_variant=raw["base_variant"],
        alignment_fingerprint=raw["alignment_fingerprint"], pdf_path=raw["pdf_path"],
        gate_status_line=raw["gate_status_line"], warnings=tuple(raw["warnings"]),
        requirements=tuple((term, quote) for term, quote in raw["requirements"]),
        requirements_omitted=raw["requirements_omitted"],
        selection_reasons=tuple((pid, reason) for pid, reason in raw["selection_reasons"]),
        positioning=tuple(raw["positioning"]),
        changes=tuple((loc, before, after, quote, rule) for loc, before, after, quote, rule in raw["changes"]),
        coverage=tuple((term, status, tuple(bullet_ids)) for term, status, bullet_ids in raw["coverage"]),
        edit_budget=(changed_tokens, base_tokens, ratio),
        g1_violations=tuple(raw["g1_violations"]),
        g2_rounds=tuple(
            (round_index, tuple((dim, score) for dim, score in scores), tuple(findings))
            for round_index, scores, findings in raw["g2_rounds"]
        ),
        l7_violations=tuple(raw["l7_violations"]),
        line_counts=tuple((bid, count) for bid, count in raw["line_counts"]),
        unified_diff=raw["unified_diff"],
    )


def publish_packet(packet: ReviewPacket, changed_bullet_ids: tuple[str, ...], directory: Path) -> G3Outcome:
    """Write review.md, packet.json, and feedback_form.yaml. An existing
    packet.json for a different fingerprint is a refusal, never an
    overwrite; the same fingerprint is an idempotent no-op."""
    directory = Path(directory)
    packet_path = directory / "packet.json"
    if packet_path.exists():
        existing = parse_packet(json.loads(packet_path.read_text(encoding="utf-8")))
        if existing.alignment_fingerprint == packet.alignment_fingerprint:
            return G3Outcome(G3OutcomeKind.ALREADY_BUILT, existing, None)
        return G3Outcome(
            G3OutcomeKind.CONFLICT, None,
            "an accepted packet.json already exists for this application with a different alignment_fingerprint",
        )

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "review.md").write_text(render_review_markdown(packet), encoding="utf-8")
    form_text = build_feedback_form(packet.job_id, packet.alignment_fingerprint, tuple(changed_bullet_ids))
    (directory / "feedback_form.yaml").write_text(form_text, encoding="utf-8")
    write_json_atomic(packet_path, packet_to_dict(packet))

    return G3Outcome(G3OutcomeKind.BUILT, packet, None)
