"""Load and validate an EvaluationPlan against the real files it names.

`schemas.validate_plan_dict` checks shape and enums on synthetic data with no
filesystem access. This module adds the second, filesystem-backed layer:
does `profile_checksum` actually match `config/master_profile.yaml` right
now, does each `target_jd_checksums[target_id]` match the JD file the Top-10
manifest points at. A plan that fails either check is rejected before any
run starts -- this is what "controlled provider configurations" and
"old-versus-new output comparisons" depend on being trustworthy later.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from src.tailor2_eval.checksums import sha256_file
from src.tailor2_eval.schemas import EvaluationPlan, plan_from_dict, plan_to_dict, validate_plan_dict
from src.tailor2_eval.targets import load_top10_targets

DEFAULT_PROFILE_PATH = Path("config/master_profile.yaml")


class PlanValidationError(ValueError):
    """Raised when a plan fails filesystem-backed (checksum) validation."""


def load_plan(path: Path) -> EvaluationPlan:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return plan_from_dict(data)


def validate_plan_file(path: Path, *, profile_path: Path = DEFAULT_PROFILE_PATH) -> EvaluationPlan:
    """Full validation: structural (schemas.validate_plan_dict, already run
    inside plan_from_dict) plus checksum freshness against real files."""
    plan = load_plan(path)
    validate_plan_against_repo(plan, profile_path=profile_path)
    return plan


def validate_plan_against_repo(plan: EvaluationPlan, *, profile_path: Path = DEFAULT_PROFILE_PATH) -> None:
    validate_plan_dict(plan_to_dict(plan))

    profile_path = Path(profile_path)
    if profile_path.exists():
        actual_profile_checksum = sha256_file(profile_path)
        if actual_profile_checksum != plan.profile_checksum:
            raise PlanValidationError(
                f"plan.profile_checksum {plan.profile_checksum!r} does not match current "
                f"{profile_path} checksum {actual_profile_checksum!r}"
            )

    targets_by_id = {t.target_id: t for t in load_top10_targets()}
    for target_id in plan.target_ids:
        if target_id not in targets_by_id:
            raise PlanValidationError(f"plan references unknown target_id: {target_id!r} (not in Top-10 manifest)")
        target = targets_by_id[target_id]
        if not target.jd_path.exists():
            raise PlanValidationError(f"target {target_id!r} JD file missing: {target.jd_path}")
        actual_jd_checksum = sha256_file(target.jd_path)
        expected = plan.target_jd_checksums[target_id]
        if actual_jd_checksum != expected:
            raise PlanValidationError(
                f"plan.target_jd_checksums[{target_id!r}]={expected!r} does not match current "
                f"JD checksum {actual_jd_checksum!r} for {target.jd_path}"
            )


def plan_with_profile_checksum(plan: EvaluationPlan, profile_path: Path = DEFAULT_PROFILE_PATH) -> EvaluationPlan:
    """Convenience for building a plan from a template: stamps the current
    on-disk profile checksum in. Never called implicitly by validation --
    validation always compares against whatever checksum the plan already
    recorded, so a stale plan is caught rather than silently re-stamped."""
    return replace(plan, profile_checksum=sha256_file(profile_path))
