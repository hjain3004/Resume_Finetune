"""Top-10 evaluation orchestration: dry-run, recorded, and bounded live lanes.

Design invariant: only `_run_live_target` can invoke a real provider, and it
requires explicit `live_authorized=True`. The Codex-subscription lane uses
ChatGPT-managed Codex CLI authentication; platform-provider lanes remain
credential-gated and interface-only. `--dry-run` and `--recorded` never construct a
`src.tailor2.invoker.Tailor2Invoker` with real credentials at all, so there
is no path from those two modes to a network call.

Resumability: each target's result is written to
`<artifact_root>/<target_id>/result.json` before moving to the next target.
A re-run with `resume_policy="skip_completed"` reads whatever result files
already exist and only (re)runs targets that are missing or, under
`"retry_failed_only"`, previously ended in a failed/interrupted status.
"""

from __future__ import annotations

import datetime
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.tailor.artifacts import write_json_atomic
from src.tailor2_eval.checksums import sha256_file, sha256_text
from src.tailor2.codex_subscription import (
    CODEX_MODEL,
    CodexPilotBudget,
    CodexPilotInterrupted,
    CodexSubscriptionInvoker,
)
from src.tailor2.lane import run_tailor2_lane
from src.tailor2_eval.redact import redact_mapping
from src.tailor2_eval.schemas import (
    EvaluationPlan,
    ModelIdentity,
    RenderSummary,
    ResumabilityState,
    TargetResult,
    target_result_from_dict,
    target_result_to_dict,
    validate_target_result,
)
from src.tailor2_eval.targets import Top10Target, load_top10_targets

LIVE_CREDENTIAL_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
_LIVE_IDENTITY_FIELDS = ("drafter", "auditor", "repair", "re_audit")

_FAILED_OR_INTERRUPTED_STATUSES = ("REJECTED_FATAL", "INTERRUPTED", "SKIPPED_BUDGET")


class LiveModeNotAuthorizedError(RuntimeError):
    """Raised whenever live mode is requested without explicit authorization
    and a configured credential -- this is the single choke point that keeps
    every non-`--live` invocation offline."""


class BudgetExhaustedError(RuntimeError):
    """Raised internally to unwind the run loop safely once max_cost_usd or
    max_calls would be exceeded; callers see it surface as remaining targets
    marked SKIPPED_BUDGET, never as an unhandled crash."""


@dataclass
class OrchestratorRunSummary:
    plan_id: str
    mode: str
    results: list[TargetResult] = field(default_factory=list)
    provider_calls_made: int = 0
    total_cost_usd: float = 0.0
    stopped_on_budget: bool = False
    cost_status: str = "reported"
    provider_metadata: dict[str, object] = field(default_factory=dict)


def _target_result_path(artifact_root: Path, target_id: str) -> Path:
    return Path(artifact_root) / target_id / "result.json"


def _load_existing_result(artifact_root: Path, target_id: str) -> TargetResult | None:
    path = _target_result_path(artifact_root, target_id)
    if not path.exists():
        return None
    import json

    return target_result_from_dict(json.loads(path.read_text(encoding="utf-8")))


def _should_run(existing: TargetResult | None, resume_policy: str) -> bool:
    if existing is None:
        return True
    if resume_policy == "rerun_all":
        return True
    if resume_policy == "retry_failed_only":
        return existing.status in _FAILED_OR_INTERRUPTED_STATUSES
    # "skip_completed": anything already recorded, successful or not, stands.
    return False


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _base_result_kwargs(plan: EvaluationPlan, target: Top10Target, mode: str) -> dict:
    return dict(
        schema_version="1.0",
        run_id=f"{target.target_id}-{_now_iso()}",
        target_id=target.target_id,
        company=target.company,
        role=target.role,
        jd_checksum=plan.target_jd_checksums[target.target_id],
        profile_checksum=plan.profile_checksum,
        drafter=plan.drafter,
        auditor=plan.auditor,
        repair=plan.repair,
        re_audit=plan.re_audit,
        started_at=_now_iso(),
        mode=mode,
    )


def _run_dry_run_target(plan: EvaluationPlan, target: Top10Target) -> TargetResult:
    """Validates the target is runnable (JD exists and matches checksum) and
    records a DRY_RUN_OK placeholder. Invokes no provider, no
    src.tailor2.invoker.Tailor2Invoker instance is even constructed."""
    started = _now_iso()
    result = TargetResult(
        **_base_result_kwargs(plan, target, "dry_run"),
        ended_at=_now_iso(),
        latency_seconds=0.0,
        provider_call_count=0,
        estimated_cost_usd=0.0,
        status="DRY_RUN_OK",
        repair_count=0,
        warnings=(),
        fatal_integrity_findings=(),
        artifact_paths={},
        resume_checksum=None,
        render_summary=RenderSummary(),
        resumability=ResumabilityState(state="completed", last_completed_stage="dry_run_validated"),
    )
    validate_target_result(result)
    return result


def _run_recorded_target(target: Top10Target, recorded_dir: Path) -> TargetResult:
    """Reads a pre-baked TargetResult JSON fixture for this target. Never
    imports or constructs src.tailor2.invoker.Tailor2Invoker -- recorded
    mode is pure file I/O, matching the task's "Recorded mode makes no
    provider calls" requirement."""
    import json

    fixture_path = Path(recorded_dir) / f"{target.target_id}.json"
    if not fixture_path.exists():
        raise FileNotFoundError(f"no recorded run fixture for target {target.target_id!r}: {fixture_path}")
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = target_result_from_dict(data)
    validate_target_result(result)
    return result


def _run_live_target(
    plan: EvaluationPlan,
    target: Top10Target,
    *,
    live_authorized: bool,
    provider: str | None = None,
    budget: CodexPilotBudget | None = None,
) -> TargetResult:
    unresolved = [
        f"{field}.model={getattr(plan, field).model}"
        for field in _LIVE_IDENTITY_FIELDS
        if "${" in getattr(plan, field).model
    ]
    if unresolved:
        raise LiveModeNotAuthorizedError(
            "live plan contains unresolved model placeholders: " + ", ".join(unresolved)
        )
    if not live_authorized:
        raise LiveModeNotAuthorizedError(
            "live mode requires the orchestrator to be called with live_authorized=True "
            "(only the CLI's explicit --live flag may set this)"
        )
    if provider == "codex_subscription":
        if not live_authorized:
            raise LiveModeNotAuthorizedError("codex_subscription live mode requires explicit --live authorization")
        if any(identity.provider != "codex_subscription" or identity.model != CODEX_MODEL for identity in (plan.drafter, plan.auditor, plan.repair, plan.re_audit)):
            raise LiveModeNotAuthorizedError(
                f"codex_subscription live mode requires all four plan identities to be codex_subscription:{CODEX_MODEL}"
            )
        return _run_codex_target(plan, target, budget=budget)
    if not any(os.environ.get(var) for var in LIVE_CREDENTIAL_ENV_VARS):
        raise LiveModeNotAuthorizedError(
            f"live mode requires one of {LIVE_CREDENTIAL_ENV_VARS} to be configured in the environment"
        )
    # Platform-provider live evaluation remains interface-only.
    raise NotImplementedError(
        "live evaluation is not implemented by this task; run_evaluation_plan(mode='live') defines "
        "the authorization interface only (see docs/tailor2_evaluation_harness.md)"
    )


def _result_artifacts(out_dir: Path) -> tuple[dict[str, str], str | None]:
    paths = {}
    for name in ("run_manifest.json", "resume.pdf", "resume.tex", "job_description.txt"):
        path = out_dir / name
        if path.exists():
            paths[name] = str(path)
    resume_path = out_dir / "resume.pdf"
    return paths, sha256_file(resume_path) if resume_path.exists() else None


def _codex_metadata(invokers: dict[str, CodexSubscriptionInvoker]) -> dict[str, object]:
    return {role: invoker.metadata for role, invoker in invokers.items()}


def _run_codex_target(plan: EvaluationPlan, target: Top10Target, *, budget: CodexPilotBudget | None) -> TargetResult:
    started_at = _now_iso()
    started_monotonic = time.monotonic()
    out_dir = Path(plan.artifact_root) / target.target_id
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = out_dir / "traces"
    invokers = {
        role: CodexSubscriptionInvoker(
            role=role,
            timeout_seconds=plan.timeout_seconds,
            trace_dir=trace_dir,
            budget=budget,
        )
        for role in ("draft", "audit", "repair", "re_audit")
    }
    identities = tuple(ModelIdentity(provider="codex_subscription", model=CODEX_MODEL) for _ in range(4))
    base_kwargs = _base_result_kwargs(plan, target, "live")
    base_kwargs.update(
        drafter=identities[0],
        auditor=identities[1],
        repair=identities[2],
        re_audit=identities[3],
    )
    try:
        lane_result = run_tailor2_lane(
            target.jd_path,
            target.company,
            target.role,
            target.base_variant,
            invokers["draft"],
            out_dir,
            auditor_invoker=invokers["audit"],
            repair_invoker=invokers["repair"],
            re_audit_invoker=invokers["re_audit"],
        )
        status = lane_result.status or ("ACCEPTED" if lane_result.success else "REJECTED_FATAL")
        artifacts, resume_checksum = _result_artifacts(out_dir)
        return TargetResult(
            **base_kwargs,
            ended_at=_now_iso(),
            latency_seconds=round(time.monotonic() - started_monotonic, 3),
            provider_call_count=sum(invoker.invocation_count for invoker in invokers.values()),
            estimated_cost_usd=0.0,
            cost_status="not_applicable_subscription",
            status=status,
            repair_count=1 if lane_result.repair_performed else 0,
            warnings=tuple(lane_result.warnings),
            fatal_integrity_findings=tuple(lane_result.rejection_reasons),
            artifact_paths=artifacts,
            resume_checksum=resume_checksum,
            render_summary=RenderSummary(render_status="rendered" if resume_checksum else "not_rendered"),
            resumability=ResumabilityState(state="completed", last_completed_stage="rendered" if resume_checksum else "tailor2"),
            provider_metadata=_codex_metadata(invokers),
        )
    except CodexPilotInterrupted as exc:
        artifacts, resume_checksum = _result_artifacts(out_dir)
        return TargetResult(
            **base_kwargs,
            ended_at=_now_iso(),
            latency_seconds=round(time.monotonic() - started_monotonic, 3),
            provider_call_count=sum(invoker.invocation_count for invoker in invokers.values()),
            estimated_cost_usd=0.0,
            cost_status="not_applicable_subscription",
            status="INTERRUPTED",
            repair_count=0,
            warnings=(str(exc),),
            fatal_integrity_findings=(),
            artifact_paths=artifacts,
            resume_checksum=resume_checksum,
            render_summary=RenderSummary(render_status="not_rendered"),
            resumability=ResumabilityState(state="interrupted"),
            provider_metadata=_codex_metadata(invokers),
        )
    except Exception as exc:
        artifacts, resume_checksum = _result_artifacts(out_dir)
        return TargetResult(
            **base_kwargs,
            ended_at=_now_iso(),
            latency_seconds=round(time.monotonic() - started_monotonic, 3),
            provider_call_count=sum(invoker.invocation_count for invoker in invokers.values()),
            estimated_cost_usd=0.0,
            cost_status="not_applicable_subscription",
            status="REJECTED_FATAL",
            repair_count=0,
            warnings=(),
            fatal_integrity_findings=(str(exc),),
            artifact_paths=artifacts,
            resume_checksum=resume_checksum,
            render_summary=RenderSummary(render_status="not_rendered"),
            resumability=ResumabilityState(state="completed", last_completed_stage="failed"),
            provider_metadata=_codex_metadata(invokers),
        )


def run_evaluation_plan(
    plan: EvaluationPlan,
    mode: str,
    *,
    recorded_dir: Path | None = None,
    live_authorized: bool = False,
    provider: str | None = None,
    targets: list[Top10Target] | None = None,
) -> OrchestratorRunSummary:
    if mode not in ("dry_run", "recorded", "live"):
        raise ValueError(f"unknown mode: {mode!r}")
    if mode == "recorded" and recorded_dir is None:
        raise ValueError("mode='recorded' requires recorded_dir")

    artifact_root = Path(plan.artifact_root)
    artifact_root.mkdir(parents=True, exist_ok=True)

    if provider == "codex_subscription" and len(plan.target_ids) > 10:
        raise ValueError("codex_subscription pilot is bounded to at most 10 targets")
    summary = OrchestratorRunSummary(
        plan_id=plan.plan_id,
        mode=mode,
        cost_status="not_applicable_subscription" if provider == "codex_subscription" else "reported",
    )
    targets_by_id = {t.target_id: t for t in (targets if targets is not None else load_top10_targets())}
    codex_budget = None
    if mode == "live" and provider == "codex_subscription":
        max_duration = int(plan.deterministic_config.get("max_total_duration_seconds", 3600))
        codex_budget = CodexPilotBudget(max_invocations=min(plan.max_calls, 120), deadline_monotonic=time.monotonic() + max_duration)

    for target_id in plan.target_ids:
        target = targets_by_id[target_id]
        existing = _load_existing_result(artifact_root, target_id)
        if not _should_run(existing, plan.resume_policy):
            summary.results.append(existing)  # type: ignore[arg-type]
            continue

        codex_budget_exhausted = codex_budget is not None and codex_budget.used_invocations >= codex_budget.max_invocations
        if summary.provider_calls_made >= plan.max_calls or summary.total_cost_usd >= plan.max_cost_usd or codex_budget_exhausted:
            skipped = TargetResult(
                **_base_result_kwargs(plan, target, mode),
                ended_at=_now_iso(),
                latency_seconds=0.0,
                provider_call_count=0,
                estimated_cost_usd=0.0,
                status="SKIPPED_BUDGET",
                repair_count=0,
                warnings=("stopped before this target: max_calls/max_cost_usd budget reached",),
                fatal_integrity_findings=(),
                artifact_paths={},
                resume_checksum=None,
                render_summary=RenderSummary(),
                resumability=ResumabilityState(state="not_started"),
                cost_status=summary.cost_status,
            )
            _write_result(artifact_root, skipped)
            summary.results.append(skipped)
            summary.stopped_on_budget = True
            continue

        if codex_budget is not None:
            max_target_duration = int(plan.deterministic_config.get("max_target_duration_seconds", plan.timeout_seconds))
            codex_budget.target_deadline_monotonic = time.monotonic() + max_target_duration

        if mode == "dry_run":
            result = _run_dry_run_target(plan, target)
        elif mode == "recorded":
            result = _run_recorded_target(target, recorded_dir)  # type: ignore[arg-type]
        else:
            result = _run_live_target(plan, target, live_authorized=live_authorized, provider=provider, budget=codex_budget)

        summary.provider_calls_made += result.provider_call_count
        summary.total_cost_usd += result.estimated_cost_usd
        summary.cost_status = result.cost_status
        _write_result(artifact_root, result)
        summary.results.append(result)

    return summary


def _write_result(artifact_root: Path, result: TargetResult) -> None:
    path = _target_result_path(artifact_root, result.target_id)
    write_json_atomic(path, redact_mapping(target_result_to_dict(result)))
