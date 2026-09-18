"""Data models and JSON contracts for the LLM-first tailoring lane (Tailor2)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

REQUIRED_AUDIT_DIMENSIONS: tuple[str, ...] = (
    "factual_fidelity",
    "metric_fidelity",
    "technology_fidelity",
    "technical_guarantee_fidelity",
    "relevance",
    "star_xyz_coherence",
    "readability",
    "recruiter_scan_quality",
    "ai_slop_risk",
)

# Whole-résumé dimensions: evaluated ONCE per audit call against the complete
# résumé projection (see audit_projection.py), not per bullet. These catch
# defects that only exist at the whole-document level -- a title mismatch,
# a Skills entry with no supporting bullet anywhere, the same "agentic"
# vocabulary repeated across three sections -- which no per-bullet
# evaluation can see in isolation.
REQUIRED_WHOLE_RESUME_DIMENSIONS: tuple[str, ...] = (
    "metric_interpretability",
    "interview_defensibility",
    "whole_resume_positioning",
    "skills_evidence_integrity",
    "title_identity_fidelity",
    "mechanism_outcome_balance",
    "cross_bullet_repetition",
    "misleading_implication",
)


class ModelContractError(ValueError):
    """Raised when a model response fails schema or contract validation."""


def strip_markdown_fences(text: str) -> str:
    """Strip markdown code block fences (e.g. ```json ... ```) if present."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


@dataclass(frozen=True)
class AtomicRequirement:
    id: str
    term: str
    quote: str
    importance: Literal["must_have", "nice_to_have"] = "must_have"


@dataclass(frozen=True)
class DraftBullet:
    bullet_id: str
    evidence_ids: list[str]
    supported_requirement_ids: list[str]
    section: Literal["Experience", "Projects"]
    entry_id: str
    text: str


@dataclass(frozen=True)
class AmdocsOmission:
    evidence_id: str
    category: Literal["relevance", "space"]
    reason: str


@dataclass(frozen=True)
class DraftResponse:
    atomic_requirements: list[AtomicRequirement]
    selected_evidence_ids: list[str]
    amdocs_omission_ledger: list[AmdocsOmission]
    section_order: list[str]
    bullets: list[DraftBullet]
    # entry_id -> proposed displayed title. Optional; absent or empty means
    # every entry renders its canonical profile title. See title_policy.py
    # for why this exists and how a proposal is resolved/auto-corrected.
    entry_title_overrides: dict[str, str] = field(default_factory=dict)
    # category -> list of proposed skills to display. Optional; absent means
    # default canonical profile skills are evaluated.
    skills: dict[str, list[str]] | None = None


@dataclass(frozen=True)
class DimensionScore:
    score: int  # 1, 2, or 3
    findings: str


@dataclass(frozen=True)
class BulletAuditEvaluation:
    bullet_id: str
    dimensions: dict[str, DimensionScore]
    verdict: Literal["ACCEPT", "REJECT"]
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WholeResumeEvaluation:
    """Result of auditing the complete résumé projection as a single unit
    (title fidelity, skills-to-evidence integrity, cross-bullet repetition,
    whole-résumé positioning, and the other REQUIRED_WHOLE_RESUME_DIMENSIONS).
    """

    dimensions: dict[str, DimensionScore]
    verdict: Literal["ACCEPT", "REJECT"]
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuditResponse:
    evaluations: list[BulletAuditEvaluation]
    overall_verdict: Literal["PASS", "REPAIR_REQUIRED"]
    # Optional for backward compatibility with recorded fixtures/tests
    # written against the pre-whole-résumé-audit contract. New runs always
    # request and receive this; a legacy fixture that omits it is treated as
    # "whole-résumé auditing was not performed for this run" rather than a
    # parse error -- lane.py surfaces that as a disclosed warning, never as
    # a silent skip.
    whole_resume: WholeResumeEvaluation | None = None


@dataclass(frozen=True)
class RepairedBullet:
    bullet_id: str
    text: str


@dataclass(frozen=True)
class RepairResponse:
    repaired_bullets: list[RepairedBullet]


@dataclass(frozen=True)
class Tailor2Manifest:
    run_id: str
    created_at: str
    # provider/model retained unchanged for backward compatibility: this is
    # always the DRAFTER's identity (the historical single-invoker meaning).
    provider: str
    model: str
    company: str
    title: str
    variant: str
    call_count: int
    repair_performed: bool
    status: str
    rejection_details: list[str] = field(default_factory=list)
    # ---- Added for model-identity separation (see invoker.py / lane.py) ----
    drafter_provider: str = ""
    drafter_model: str = ""
    auditor_provider: str = ""
    auditor_model: str = ""
    repair_provider: str = ""
    repair_model: str = ""
    re_audit_provider: str = ""
    re_audit_model: str = ""
    # True when the auditor stage used the identical provider+model as the
    # drafter stage. A live run in this configuration must have received an
    # explicit override (see invoker.py SAME_MODEL_OVERRIDE_ENV /
    # Tailor2Invoker(..., acknowledge_same_model=True)); this field is the
    # durable, auditable record of that fact so no downstream reader can
    # mistake a same-model run for an independently cross-checked one.
    same_model_draft_and_audit: bool = False
    # ---- Added for the severity model / richer outcomes ----
    # One of severity.RunStatus's values; `status` above also carries this
    # same string for backward compatibility (old readers only look at
    # `status`), this field exists so new readers don't have to guess that
    # `status` is now a RunStatus rather than the old ad-hoc FAILED_* string.
    run_status: str = ""
    warnings: list[str] = field(default_factory=list)
    auto_corrections: list[str] = field(default_factory=list)
    advisory_gaps: list[str] = field(default_factory=list)
    # Preserves every dimension's score+findings from the (re-)audit that
    # produced the final result, keyed by "bullet:<id>:<dimension>" or
    # "whole_resume:<dimension>", so the original rubric detail survives
    # even when the final run_status collapses many dimensions into one
    # outcome. Required by the task's "preserve the original dimension
    # scores and reasons in the manifest" instruction.
    dimension_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    title_resolutions: list[dict[str, Any]] = field(default_factory=list)
    selection_schema_version: str = "1.0"
    selection_enabled: bool = False
    selection_artifacts: dict[str, Any] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    render_fill_artifacts: dict[str, Any] = field(default_factory=dict)


def parse_draft_response(raw_text: str) -> DraftResponse:
    clean_text = strip_markdown_fences(raw_text)
    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError as exc:
        raise ModelContractError(f"Draft response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ModelContractError("Draft response must be a JSON object")

    for key in ("atomic_requirements", "selected_evidence_ids", "amdocs_omission_ledger", "section_order", "bullets"):
        if key not in data:
            raise ModelContractError(f"Draft response missing required key: {key!r}")

    atomic_requirements = []
    for idx, item in enumerate(data["atomic_requirements"]):
        if not isinstance(item, dict):
            raise ModelContractError(f"atomic_requirements[{idx}] must be an object")
        for req_key in ("id", "term", "quote"):
            if req_key not in item:
                raise ModelContractError(f"atomic_requirements[{idx}] missing required key: {req_key!r}")
        atomic_requirements.append(
            AtomicRequirement(
                id=str(item["id"]),
                term=str(item["term"]),
                quote=str(item["quote"]),
                importance=item.get("importance", "must_have"),
            )
        )

    amdocs_omission_ledger = []
    for idx, item in enumerate(data["amdocs_omission_ledger"]):
        if not isinstance(item, dict):
            raise ModelContractError(f"amdocs_omission_ledger[{idx}] must be an object")
        for om_key in ("evidence_id", "category", "reason"):
            if om_key not in item:
                raise ModelContractError(f"amdocs_omission_ledger[{idx}] missing required key: {om_key!r}")
        amdocs_omission_ledger.append(
            AmdocsOmission(
                evidence_id=str(item["evidence_id"]),
                category=item["category"],
                reason=str(item["reason"]),
            )
        )

    bullets = []
    for idx, item in enumerate(data["bullets"]):
        if not isinstance(item, dict):
            raise ModelContractError(f"bullets[{idx}] must be an object")
        for b_key in ("bullet_id", "evidence_ids", "supported_requirement_ids", "section", "entry_id", "text"):
            if b_key not in item:
                raise ModelContractError(f"bullets[{idx}] missing required key: {b_key!r}")
        bullets.append(
            DraftBullet(
                bullet_id=str(item["bullet_id"]),
                evidence_ids=[str(eid) for eid in item["evidence_ids"]],
                supported_requirement_ids=[str(rid) for rid in item["supported_requirement_ids"]],
                section=item["section"],
                entry_id=str(item["entry_id"]),
                text=str(item["text"]),
            )
        )

    raw_title_overrides = data.get("entry_title_overrides", {}) or {}
    if not isinstance(raw_title_overrides, dict):
        raise ModelContractError("entry_title_overrides must be an object if present")
    entry_title_overrides = {str(k): str(v) for k, v in raw_title_overrides.items()}

    raw_skills = data.get("skills")
    skills = None
    if raw_skills is not None and isinstance(raw_skills, dict):
        skills = {str(k): [str(v) for v in vals] for k, vals in raw_skills.items()}

    return DraftResponse(
        atomic_requirements=atomic_requirements,
        selected_evidence_ids=[str(eid) for eid in data["selected_evidence_ids"]],
        amdocs_omission_ledger=amdocs_omission_ledger,
        section_order=[str(sec) for sec in data["section_order"]],
        bullets=bullets,
        entry_title_overrides=entry_title_overrides,
        skills=skills,
    )


def parse_audit_response(raw_text: str) -> AuditResponse:
    clean_text = strip_markdown_fences(raw_text)
    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError as exc:
        raise ModelContractError(f"Audit response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ModelContractError("Audit response must be a JSON object")

    if "evaluations" not in data or "overall_verdict" not in data:
        raise ModelContractError("Audit response missing 'evaluations' or 'overall_verdict'")

    evaluations = []
    for idx, item in enumerate(data["evaluations"]):
        if not isinstance(item, dict):
            raise ModelContractError(f"evaluations[{idx}] must be an object")
        for key in ("bullet_id", "dimensions", "verdict"):
            if key not in item:
                raise ModelContractError(f"evaluations[{idx}] missing required key: {key!r}")

        dims_data = item["dimensions"]
        if not isinstance(dims_data, dict):
            raise ModelContractError(f"evaluations[{idx}].dimensions must be an object")

        dimensions = {}
        for dim in REQUIRED_AUDIT_DIMENSIONS:
            if dim not in dims_data:
                raise ModelContractError(f"evaluations[{idx}] missing dimension: {dim!r}")
            dim_val = dims_data[dim]
            if not isinstance(dim_val, dict) or "score" not in dim_val or "findings" not in dim_val:
                raise ModelContractError(f"evaluations[{idx}].dimensions[{dim}] must have score and findings")
            dimensions[dim] = DimensionScore(score=int(dim_val["score"]), findings=str(dim_val["findings"]))

        evaluations.append(
            BulletAuditEvaluation(
                bullet_id=str(item["bullet_id"]),
                dimensions=dimensions,
                verdict=item["verdict"],
                rejection_reasons=[str(r) for r in item.get("rejection_reasons", [])],
            )
        )

    whole_resume = None
    raw_whole_resume = data.get("whole_resume")
    if raw_whole_resume is not None:
        if not isinstance(raw_whole_resume, dict) or "dimensions" not in raw_whole_resume or "verdict" not in raw_whole_resume:
            raise ModelContractError("whole_resume must be an object with 'dimensions' and 'verdict'")
        wr_dims_data = raw_whole_resume["dimensions"]
        if not isinstance(wr_dims_data, dict):
            raise ModelContractError("whole_resume.dimensions must be an object")
        wr_dimensions = {}
        for dim in REQUIRED_WHOLE_RESUME_DIMENSIONS:
            if dim not in wr_dims_data:
                raise ModelContractError(f"whole_resume missing dimension: {dim!r}")
            dim_val = wr_dims_data[dim]
            if not isinstance(dim_val, dict) or "score" not in dim_val or "findings" not in dim_val:
                raise ModelContractError(f"whole_resume.dimensions[{dim}] must have score and findings")
            wr_dimensions[dim] = DimensionScore(score=int(dim_val["score"]), findings=str(dim_val["findings"]))
        whole_resume = WholeResumeEvaluation(
            dimensions=wr_dimensions,
            verdict=raw_whole_resume["verdict"],
            rejection_reasons=[str(r) for r in raw_whole_resume.get("rejection_reasons", [])],
        )

    return AuditResponse(
        evaluations=evaluations,
        overall_verdict=data["overall_verdict"],
        whole_resume=whole_resume,
    )


def parse_repair_response(raw_text: str) -> RepairResponse:
    clean_text = strip_markdown_fences(raw_text)
    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError as exc:
        raise ModelContractError(f"Repair response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "repaired_bullets" not in data:
        raise ModelContractError("Repair response must have 'repaired_bullets'")

    repaired_bullets = []
    for idx, item in enumerate(data["repaired_bullets"]):
        if not isinstance(item, dict) or "bullet_id" not in item or "text" not in item:
            raise ModelContractError(f"repaired_bullets[{idx}] must contain bullet_id and text")
        repaired_bullets.append(
            RepairedBullet(
                bullet_id=str(item["bullet_id"]),
                text=str(item["text"]),
            )
        )

    return RepairResponse(repaired_bullets=repaired_bullets)


def draft_response_to_dict(draft: DraftResponse) -> dict[str, Any]:
    return asdict(draft)


def audit_response_to_dict(audit: AuditResponse) -> dict[str, Any]:
    return asdict(audit)


def repair_response_to_dict(repair: RepairResponse) -> dict[str, Any]:
    return asdict(repair)


def manifest_to_dict(manifest: Tailor2Manifest) -> dict[str, Any]:
    return asdict(manifest)


# Re-audit response uses the same schema as audit response
parse_re_audit_response = parse_audit_response
