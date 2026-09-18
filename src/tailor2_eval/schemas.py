"""Versioned data contracts for the Tailor2 offline evaluation harness.

Every schema here carries its own `schema_version` string, is a plain
dataclass (no pydantic/jsonschema dependency -- CLAUDE.md's approved
dependency list does not include either), and has a paired `validate_*`
function that raises `EvalSchemaError` on a structural or enum violation.
`to_dict`/`from_dict` round-trip through `dataclasses.asdict`-compatible
plain dicts so results can be written with the existing
`src.tailor.artifacts.write_json_atomic` helper.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PLAN_SCHEMA_VERSION = "1.0"
TARGET_RESULT_SCHEMA_VERSION = "1.0"
COMPARISON_PAIR_SCHEMA_VERSION = "1.1"  # +purpose, +ComparisonCandidate provenance fields (additive)
HUMAN_REVIEW_SCHEMA_VERSION = "1.0"
AGGREGATE_SUMMARY_SCHEMA_VERSION = "1.0"
RELEASE_GATE_SCHEMA_VERSION = "1.0"

RunMode = Literal["dry_run", "recorded", "live"]
ResumePolicy = Literal["skip_completed", "retry_failed_only", "rerun_all"]
TargetRuntimeStatus = Literal[
    "ACCEPTED",
    "ACCEPTED_WITH_WARNINGS",
    "NEEDS_HUMAN_REVIEW",
    "REJECTED_FATAL",
    "RENDER_FAILED_FALLBACK",
    "INTERRUPTED",
    "SKIPPED_BUDGET",
    "DRY_RUN_OK",
]
HumanPreference = Literal["A", "B", "TIE", "NEITHER"]


class EvalSchemaError(ValueError):
    """Raised when a plan, result, or response fails schema validation."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvalSchemaError(message)


# ---------------------------------------------------------------------------
# Evaluation plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelIdentity:
    provider: str
    model: str


@dataclass(frozen=True)
class BlindComparisonSettings:
    enabled: bool = False
    seed: int = 0
    dimensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationPlan:
    """A fully-specified, credential-free description of one evaluation run.

    `profile_checksum` and `target_jd_checksums` pin the exact inputs so a
    plan can be re-validated byte-for-byte before any comparison is trusted.
    `candidate_pipeline_id` / `baseline_pipeline_id` are opaque labels (e.g.
    "tailor2@<git-sha>", "tailor1@legacy") -- this module does not interpret
    them, it only requires they be present and distinct concepts so a
    comparison always knows which side is which.
    """

    schema_version: str
    plan_id: str
    profile_id: str
    profile_checksum: str
    target_ids: tuple[str, ...]
    target_jd_checksums: dict[str, str]
    candidate_pipeline_id: str
    baseline_pipeline_id: str | None
    drafter: ModelIdentity
    auditor: ModelIdentity
    repair: ModelIdentity
    re_audit: ModelIdentity
    deterministic_config: dict[str, Any]
    max_cost_usd: float
    max_calls: int
    timeout_seconds: int
    resume_policy: ResumePolicy
    artifact_root: str
    blind_comparison: BlindComparisonSettings = field(default_factory=BlindComparisonSettings)


def plan_to_dict(plan: EvaluationPlan) -> dict[str, Any]:
    return asdict(plan)


def plan_from_dict(data: dict[str, Any]) -> EvaluationPlan:
    validate_plan_dict(data)
    identities = {
        key: ModelIdentity(**data[key]) for key in ("drafter", "auditor", "repair", "re_audit")
    }
    blind_raw = data.get("blind_comparison") or {}
    blind = BlindComparisonSettings(
        enabled=bool(blind_raw.get("enabled", False)),
        seed=int(blind_raw.get("seed", 0)),
        dimensions=tuple(blind_raw.get("dimensions", ())),
    )
    return EvaluationPlan(
        schema_version=str(data["schema_version"]),
        plan_id=str(data["plan_id"]),
        profile_id=str(data["profile_id"]),
        profile_checksum=str(data["profile_checksum"]),
        target_ids=tuple(data["target_ids"]),
        target_jd_checksums=dict(data["target_jd_checksums"]),
        candidate_pipeline_id=str(data["candidate_pipeline_id"]),
        baseline_pipeline_id=data.get("baseline_pipeline_id"),
        drafter=identities["drafter"],
        auditor=identities["auditor"],
        repair=identities["repair"],
        re_audit=identities["re_audit"],
        deterministic_config=dict(data.get("deterministic_config", {})),
        max_cost_usd=float(data["max_cost_usd"]),
        max_calls=int(data["max_calls"]),
        timeout_seconds=int(data["timeout_seconds"]),
        resume_policy=data["resume_policy"],
        artifact_root=str(data["artifact_root"]),
        blind_comparison=blind,
    )


_REQUIRED_PLAN_FIELDS = (
    "schema_version",
    "plan_id",
    "profile_id",
    "profile_checksum",
    "target_ids",
    "target_jd_checksums",
    "candidate_pipeline_id",
    "drafter",
    "auditor",
    "repair",
    "re_audit",
    "max_cost_usd",
    "max_calls",
    "timeout_seconds",
    "resume_policy",
    "artifact_root",
)
_VALID_RESUME_POLICIES = ("skip_completed", "retry_failed_only", "rerun_all")


def validate_plan_dict(data: dict[str, Any]) -> None:
    """Structural validation only (schema shape, enums, no-credentials).
    Checksum *freshness* against real files is plan.validate_plan's job --
    this function must work on synthetic data with no filesystem access."""
    _require(isinstance(data, dict), "plan must be a JSON object")
    missing = [f for f in _REQUIRED_PLAN_FIELDS if f not in data]
    _require(not missing, f"plan missing required fields: {missing}")

    from src.tailor2_eval.redact import find_credential_like_keys

    credential_keys = find_credential_like_keys(data)
    _require(not credential_keys, f"plan must never store credentials; found key(s): {credential_keys}")

    _require(
        isinstance(data["target_ids"], (list, tuple)) and len(data["target_ids"]) > 0,
        "plan.target_ids must be a non-empty list",
    )
    _require(
        isinstance(data["target_jd_checksums"], dict)
        and set(data["target_jd_checksums"]) == set(data["target_ids"]),
        "plan.target_jd_checksums must have exactly one entry per target_id",
    )
    for identity_key in ("drafter", "auditor", "repair", "re_audit"):
        identity = data[identity_key]
        _require(
            isinstance(identity, dict) and "provider" in identity and "model" in identity,
            f"plan.{identity_key} must be an object with 'provider' and 'model'",
        )
    _require(
        isinstance(data["max_cost_usd"], (int, float)) and data["max_cost_usd"] > 0,
        "plan.max_cost_usd must be a positive number",
    )
    _require(isinstance(data["max_calls"], int) and data["max_calls"] > 0, "plan.max_calls must be a positive integer")
    _require(
        isinstance(data["timeout_seconds"], int) and data["timeout_seconds"] > 0,
        "plan.timeout_seconds must be a positive integer",
    )
    _require(
        data["resume_policy"] in _VALID_RESUME_POLICIES,
        f"plan.resume_policy must be one of {_VALID_RESUME_POLICIES}, got {data['resume_policy']!r}",
    )
    _require(isinstance(data["artifact_root"], str) and data["artifact_root"], "plan.artifact_root must be a non-empty string")

    blind = data.get("blind_comparison")
    if blind is not None:
        _require(isinstance(blind, dict), "plan.blind_comparison must be an object")
        if "seed" in blind:
            _require(isinstance(blind["seed"], int), "plan.blind_comparison.seed must be an integer")


def validate_plan(plan: EvaluationPlan) -> None:
    """Validate an already-constructed EvaluationPlan object (re-runs the
    same structural checks via its dict form, for callers that built the
    dataclass directly rather than parsing JSON)."""
    validate_plan_dict(plan_to_dict(plan))


# ---------------------------------------------------------------------------
# Per-target result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderSummary:
    page_count: int | None = None
    one_page: bool | None = None
    layout_warnings: tuple[str, ...] = ()
    render_status: str = "not_rendered"  # not_rendered | rendered | render_failed_fallback


@dataclass(frozen=True)
class ResumabilityState:
    state: str = "not_started"  # not_started | in_progress | completed | interrupted
    last_completed_stage: str | None = None


@dataclass(frozen=True)
class TargetResult:
    schema_version: str
    run_id: str
    target_id: str
    company: str
    role: str
    jd_checksum: str
    profile_checksum: str
    drafter: ModelIdentity
    auditor: ModelIdentity
    repair: ModelIdentity
    re_audit: ModelIdentity
    started_at: str
    ended_at: str | None
    latency_seconds: float | None
    provider_call_count: int
    estimated_cost_usd: float
    status: TargetRuntimeStatus
    repair_count: int
    warnings: tuple[str, ...]
    fatal_integrity_findings: tuple[str, ...]
    artifact_paths: dict[str, str]
    resume_checksum: str | None
    render_summary: RenderSummary
    resumability: ResumabilityState
    evidence_gaps: tuple[str, ...] = ()
    mode: RunMode = "recorded"


_VALID_TARGET_STATUSES = (
    "ACCEPTED",
    "ACCEPTED_WITH_WARNINGS",
    "NEEDS_HUMAN_REVIEW",
    "REJECTED_FATAL",
    "RENDER_FAILED_FALLBACK",
    "INTERRUPTED",
    "SKIPPED_BUDGET",
    "DRY_RUN_OK",
)


def target_result_to_dict(result: TargetResult) -> dict[str, Any]:
    return asdict(result)


def target_result_from_dict(data: dict[str, Any]) -> TargetResult:
    validate_target_result_dict(data)
    identities = {
        key: ModelIdentity(**data[key]) for key in ("drafter", "auditor", "repair", "re_audit")
    }
    render_raw = data.get("render_summary") or {}
    render_summary = RenderSummary(
        page_count=render_raw.get("page_count"),
        one_page=render_raw.get("one_page"),
        layout_warnings=tuple(render_raw.get("layout_warnings", ())),
        render_status=render_raw.get("render_status", "not_rendered"),
    )
    resumability_raw = data.get("resumability") or {}
    resumability = ResumabilityState(
        state=resumability_raw.get("state", "not_started"),
        last_completed_stage=resumability_raw.get("last_completed_stage"),
    )
    return TargetResult(
        schema_version=str(data["schema_version"]),
        run_id=str(data["run_id"]),
        target_id=str(data["target_id"]),
        company=str(data["company"]),
        role=str(data["role"]),
        jd_checksum=str(data["jd_checksum"]),
        profile_checksum=str(data["profile_checksum"]),
        drafter=identities["drafter"],
        auditor=identities["auditor"],
        repair=identities["repair"],
        re_audit=identities["re_audit"],
        started_at=str(data["started_at"]),
        ended_at=data.get("ended_at"),
        latency_seconds=data.get("latency_seconds"),
        provider_call_count=int(data["provider_call_count"]),
        estimated_cost_usd=float(data["estimated_cost_usd"]),
        status=data["status"],
        repair_count=int(data["repair_count"]),
        warnings=tuple(data.get("warnings", ())),
        fatal_integrity_findings=tuple(data.get("fatal_integrity_findings", ())),
        artifact_paths=dict(data.get("artifact_paths", {})),
        resume_checksum=data.get("resume_checksum"),
        render_summary=render_summary,
        resumability=resumability,
        evidence_gaps=tuple(data.get("evidence_gaps", ())),
        mode=data.get("mode", "recorded"),
    )


_REQUIRED_TARGET_RESULT_FIELDS = (
    "schema_version",
    "run_id",
    "target_id",
    "company",
    "role",
    "jd_checksum",
    "profile_checksum",
    "drafter",
    "auditor",
    "repair",
    "re_audit",
    "started_at",
    "provider_call_count",
    "estimated_cost_usd",
    "status",
    "repair_count",
)


def validate_target_result_dict(data: dict[str, Any]) -> None:
    _require(isinstance(data, dict), "target result must be a JSON object")
    missing = [f for f in _REQUIRED_TARGET_RESULT_FIELDS if f not in data]
    _require(not missing, f"target result missing required fields: {missing}")
    _require(
        data["status"] in _VALID_TARGET_STATUSES,
        f"target result status must be one of {_VALID_TARGET_STATUSES}, got {data['status']!r}",
    )
    _require(
        isinstance(data["provider_call_count"], int) and data["provider_call_count"] >= 0,
        "provider_call_count must be a non-negative integer",
    )
    _require(
        isinstance(data["estimated_cost_usd"], (int, float)) and data["estimated_cost_usd"] >= 0,
        "estimated_cost_usd must be a non-negative number",
    )
    _require(isinstance(data["repair_count"], int) and data["repair_count"] >= 0, "repair_count must be a non-negative integer")


def validate_target_result(result: TargetResult) -> None:
    validate_target_result_dict(target_result_to_dict(result))


# ---------------------------------------------------------------------------
# Comparison pair
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComparisonCandidate:
    label: str  # opaque source label, e.g. "candidate", "baseline", "manual", "render_fill"
    result_run_id: str
    resume_checksum: str
    resume_text_path: str
    # ---- Added for baseline-registry pairing (see pairing.py) ----
    # A stable identifier for the underlying artifact, independent of
    # `result_run_id` -- used by pairing.check_not_self_pair so a candidate
    # and baseline drawn from genuinely different sources are never
    # collapsed onto the same identity by accident. Defaults to "" so every
    # pre-existing call site (which never set this) keeps working; callers
    # that don't set it explicitly get one derived by
    # pairing.make_artifact_id.
    artifact_id: str = ""
    # Pipeline/configuration identifier (e.g. "tailor2@<sha>", "tailor1@legacy").
    pipeline_id: str = ""
    # Provider/model identities for this side. Retained for the private
    # answer key (pairing.AnswerKeyEntry) only -- blind.blind_package_to_dict
    # never reads this field, so it can never leak into a reviewer package.
    model_identities: dict[str, Any] = field(default_factory=dict)
    # Free-text provenance note (e.g. "Tailor1 legacy run, 2026-08-01").
    provenance: str = ""


@dataclass(frozen=True)
class ComparisonPair:
    schema_version: str
    comparison_id: str
    target_id: str
    jd_checksum: str
    profile_checksum: str
    candidate_a: ComparisonCandidate
    candidate_b: ComparisonCandidate
    # Why this pair exists (e.g. "candidate_vs_old_pipeline",
    # "candidate_vs_manual", "diagnostic_same_system"). Optional/additive;
    # "" for any pair built before this field existed.
    purpose: str = ""


def comparison_pair_to_dict(pair: ComparisonPair) -> dict[str, Any]:
    return asdict(pair)


def comparison_pair_from_dict(data: dict[str, Any]) -> ComparisonPair:
    validate_comparison_pair_dict(data)
    return ComparisonPair(
        schema_version=str(data["schema_version"]),
        comparison_id=str(data["comparison_id"]),
        target_id=str(data["target_id"]),
        jd_checksum=str(data["jd_checksum"]),
        profile_checksum=str(data["profile_checksum"]),
        candidate_a=ComparisonCandidate(**data["candidate_a"]),
        candidate_b=ComparisonCandidate(**data["candidate_b"]),
        purpose=str(data.get("purpose", "")),
    )


def validate_comparison_pair_dict(data: dict[str, Any]) -> None:
    _require(isinstance(data, dict), "comparison pair must be a JSON object")
    required = ("schema_version", "comparison_id", "target_id", "jd_checksum", "profile_checksum", "candidate_a", "candidate_b")
    missing = [f for f in required if f not in data]
    _require(not missing, f"comparison pair missing required fields: {missing}")
    for side in ("candidate_a", "candidate_b"):
        candidate = data[side]
        _require(
            isinstance(candidate, dict) and {"label", "result_run_id", "resume_checksum", "resume_text_path"} <= set(candidate),
            f"comparison pair {side} must have label, result_run_id, resume_checksum, resume_text_path",
        )


# ---------------------------------------------------------------------------
# Human review response
# ---------------------------------------------------------------------------

RUBRIC_DIMENSIONS: tuple[str, ...] = (
    "factual_trustworthiness",
    "target_role_fit",
    "recruiter_scan_quality",
    "clarity",
    "achievement_strength",
    "metric_interpretability",
    "interview_defensibility",
    "mechanism_outcome_balance",
    "redundancy",
    "ai_slop",
    "skills_credibility",
    "visual_readability",
    "page_utilization",
    "overall_preference",
)

_VALID_PREFERENCES = ("A", "B", "TIE", "NEITHER")


@dataclass(frozen=True)
class HumanReviewResponse:
    schema_version: str
    comparison_id: str
    reviewer_id: str
    dimension_preferences: dict[str, str]  # dimension -> "A" | "B" | "TIE" | "NEITHER"
    overall_preference: str  # "A" | "B" | "TIE" | "NEITHER"
    reviewer_confidence: float  # 0.0 - 1.0
    free_text_concerns: str = ""
    factual_error_flags: tuple[str, ...] = ()


def human_review_to_dict(response: HumanReviewResponse) -> dict[str, Any]:
    return asdict(response)


def human_review_from_dict(data: dict[str, Any]) -> HumanReviewResponse:
    validate_human_review_dict(data)
    return HumanReviewResponse(
        schema_version=str(data["schema_version"]),
        comparison_id=str(data["comparison_id"]),
        reviewer_id=str(data["reviewer_id"]),
        dimension_preferences=dict(data["dimension_preferences"]),
        overall_preference=data["overall_preference"],
        reviewer_confidence=float(data["reviewer_confidence"]),
        free_text_concerns=str(data.get("free_text_concerns", "")),
        factual_error_flags=tuple(data.get("factual_error_flags", ())),
    )


def validate_human_review_dict(data: dict[str, Any]) -> None:
    _require(isinstance(data, dict), "human review response must be a JSON object")
    required = ("schema_version", "comparison_id", "reviewer_id", "dimension_preferences", "overall_preference", "reviewer_confidence")
    missing = [f for f in required if f not in data]
    _require(not missing, f"human review response missing required fields: {missing}")
    _require(
        data["overall_preference"] in _VALID_PREFERENCES,
        f"overall_preference must be one of {_VALID_PREFERENCES}, got {data['overall_preference']!r}",
    )
    for dim, pref in data["dimension_preferences"].items():
        _require(pref in _VALID_PREFERENCES, f"dimension_preferences[{dim!r}]={pref!r} must be one of {_VALID_PREFERENCES}")
    confidence = data["reviewer_confidence"]
    _require(isinstance(confidence, (int, float)) and 0.0 <= confidence <= 1.0, "reviewer_confidence must be between 0.0 and 1.0")


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AggregateSummary:
    schema_version: str
    plan_id: str
    target_count: int
    usable_artifact_rate: float
    fatal_integrity_rate: float
    warning_or_human_review_rate: float
    repair_frequency: float
    avg_provider_calls: float
    avg_cost_usd: float
    avg_latency_seconds: float
    one_page_success_rate: float
    layout_warning_rate: float
    evidence_gap_rate: float
    human_preference_summary: dict[str, int]
    factual_error_report_count: int
    status_counts: dict[str, int] = field(default_factory=dict)


def aggregate_summary_to_dict(summary: AggregateSummary) -> dict[str, Any]:
    return asdict(summary)


def validate_aggregate_summary_dict(data: dict[str, Any]) -> None:
    _require(isinstance(data, dict), "aggregate summary must be a JSON object")
    required = (
        "schema_version",
        "plan_id",
        "target_count",
        "usable_artifact_rate",
        "fatal_integrity_rate",
    )
    missing = [f for f in required if f not in data]
    _require(not missing, f"aggregate summary missing required fields: {missing}")
    for rate_field in ("usable_artifact_rate", "fatal_integrity_rate"):
        value = data[rate_field]
        _require(isinstance(value, (int, float)) and 0.0 <= value <= 1.0, f"{rate_field} must be between 0.0 and 1.0")


# ---------------------------------------------------------------------------
# Release-gate decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateCriterionResult:
    criterion_id: str
    description: str
    passed: bool
    observed_value: Any
    threshold: Any


@dataclass(frozen=True)
class ReleaseGateDecision:
    schema_version: str
    plan_id: str
    is_established_policy: bool  # False: these are proposed gates, not repo policy
    overall_pass: bool
    criteria: tuple[GateCriterionResult, ...]


def release_gate_decision_to_dict(decision: ReleaseGateDecision) -> dict[str, Any]:
    return asdict(decision)


def validate_release_gate_decision_dict(data: dict[str, Any]) -> None:
    _require(isinstance(data, dict), "release gate decision must be a JSON object")
    required = ("schema_version", "plan_id", "is_established_policy", "overall_pass", "criteria")
    missing = [f for f in required if f not in data]
    _require(not missing, f"release gate decision missing required fields: {missing}")
    _require(isinstance(data["criteria"], list) and len(data["criteria"]) > 0, "release gate decision must list at least one criterion")
    for criterion in data["criteria"]:
        _require(
            {"criterion_id", "description", "passed", "observed_value", "threshold"} <= set(criterion),
            "each gate criterion must have criterion_id, description, passed, observed_value, threshold",
        )
