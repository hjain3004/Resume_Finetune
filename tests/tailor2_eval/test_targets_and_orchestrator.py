"""Required tests 3-9 and 20: Top-10 discovery, dry-run/recorded/live safety,
resume/retry semantics, budget termination, and no-repo-mutation."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.tailor2_eval.checksums import sha256_file
from src.tailor2_eval.orchestrator import LiveModeNotAuthorizedError, run_evaluation_plan
from src.tailor2_eval.schemas import BlindComparisonSettings, EvaluationPlan, ModelIdentity, target_result_to_dict
from src.tailor2_eval.targets import get_target, load_top10_targets

from .conftest import VALID_PLAN_PATH
from src.tailor2_eval.plan import load_plan

PROFILE_PATH = Path("config/master_profile.yaml")
TARGETS_JSON = Path("shortlist/tailoring_targets/targets.json")


def _identity() -> ModelIdentity:
    return ModelIdentity(provider="claude", model="claude-sonnet-5")


def _plan(tmp_path: Path, target_ids: tuple[str, ...], **overrides) -> EvaluationPlan:
    base = load_plan(VALID_PLAN_PATH)
    kwargs = dict(
        schema_version=base.schema_version,
        plan_id=base.plan_id,
        profile_id=base.profile_id,
        profile_checksum=base.profile_checksum,
        target_ids=target_ids,
        target_jd_checksums={tid: get_target(tid).jd_sha256 for tid in target_ids},
        candidate_pipeline_id=base.candidate_pipeline_id,
        baseline_pipeline_id=base.baseline_pipeline_id,
        drafter=_identity(),
        auditor=_identity(),
        repair=_identity(),
        re_audit=_identity(),
        deterministic_config={},
        max_cost_usd=100.0,
        max_calls=100,
        timeout_seconds=60,
        resume_policy="skip_completed",
        artifact_root=str(tmp_path),
        blind_comparison=BlindComparisonSettings(),
    )
    kwargs.update(overrides)
    return EvaluationPlan(**kwargs)


def test_top10_discovery_returns_all_targets_sorted_by_rank() -> None:
    targets = load_top10_targets()
    assert len(targets) == 10
    ranks = [t.rank for t in targets]
    assert ranks == sorted(ranks)
    assert len(set(t.target_id for t in targets)) == 10


def test_dry_run_makes_no_provider_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("dry-run must never call Tailor2Invoker.invoke")

    monkeypatch.setattr("src.tailor2.invoker.Tailor2Invoker.invoke", _boom)
    plan = _plan(tmp_path, ("zoom_4766",))
    summary = run_evaluation_plan(plan, "dry_run")
    assert summary.results[0].status == "DRY_RUN_OK"
    assert summary.provider_calls_made == 0


def test_recorded_mode_makes_no_provider_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenarios: dict) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("recorded mode must never call Tailor2Invoker.invoke")

    monkeypatch.setattr("src.tailor2.invoker.Tailor2Invoker.invoke", _boom)

    recorded_dir = tmp_path / "recorded"
    recorded_dir.mkdir()
    fixture = dict(scenarios["target_results"]["accepted_cleanly"])
    (recorded_dir / "zoom_4766.json").write_text(json.dumps(fixture), encoding="utf-8")

    plan = _plan(tmp_path / "artifacts", ("zoom_4766",))
    summary = run_evaluation_plan(plan, "recorded", recorded_dir=recorded_dir)
    assert summary.results[0].status == "ACCEPTED"


def test_live_mode_requires_explicit_authorization(tmp_path: Path) -> None:
    plan = _plan(tmp_path, ("zoom_4766",))
    with pytest.raises(LiveModeNotAuthorizedError):
        run_evaluation_plan(plan, "live", live_authorized=False)


def test_live_mode_requires_configured_credential(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    plan = _plan(tmp_path, ("zoom_4766",))
    with pytest.raises(LiveModeNotAuthorizedError):
        run_evaluation_plan(plan, "live", live_authorized=True)


def test_resume_skips_completed_targets(tmp_path: Path, scenarios: dict) -> None:
    artifact_root = tmp_path / "artifacts"
    recorded_dir = tmp_path / "recorded"
    recorded_dir.mkdir()
    (artifact_root / "zoom_4766").mkdir(parents=True)

    already_done = dict(scenarios["target_results"]["accepted_cleanly"])
    already_done["run_id"] = "PRE-EXISTING-RUN"
    (artifact_root / "zoom_4766" / "result.json").write_text(json.dumps(already_done), encoding="utf-8")

    fresh = dict(scenarios["target_results"]["accepted_with_warnings"])
    fresh["target_id"] = "doordash_4608"
    (recorded_dir / "doordash_4608.json").write_text(json.dumps(fresh), encoding="utf-8")
    # zoom_4766 fixture intentionally absent -- if the orchestrator tried to
    # (re)run it, _run_recorded_target would raise FileNotFoundError.

    plan = _plan(artifact_root, ("zoom_4766", "doordash_4608"), resume_policy="skip_completed")
    summary = run_evaluation_plan(plan, "recorded", recorded_dir=recorded_dir)

    by_id = {r.target_id: r for r in summary.results}
    assert by_id["zoom_4766"].run_id == "PRE-EXISTING-RUN"
    assert by_id["doordash_4608"].status == "ACCEPTED_WITH_WARNINGS"


def test_failed_targets_remain_retryable(tmp_path: Path, scenarios: dict) -> None:
    artifact_root = tmp_path / "artifacts"
    recorded_dir = tmp_path / "recorded"
    recorded_dir.mkdir()
    (artifact_root / "roadrunner_5027").mkdir(parents=True)

    failed = dict(scenarios["target_results"]["fatal_integrity_failure"])
    (artifact_root / "roadrunner_5027" / "result.json").write_text(json.dumps(failed), encoding="utf-8")

    retried = dict(scenarios["target_results"]["accepted_cleanly"])
    retried["target_id"] = "roadrunner_5027"
    (recorded_dir / "roadrunner_5027.json").write_text(json.dumps(retried), encoding="utf-8")

    plan = _plan(artifact_root, ("roadrunner_5027",), resume_policy="retry_failed_only")
    summary = run_evaluation_plan(plan, "recorded", recorded_dir=recorded_dir)
    assert summary.results[0].status == "ACCEPTED"


def test_call_and_cost_budget_terminates_safely(tmp_path: Path, scenarios: dict) -> None:
    recorded_dir = tmp_path / "recorded"
    recorded_dir.mkdir()
    for name, target_id in (("accepted_cleanly", "zoom_4766"), ("accepted_with_warnings", "doordash_4608")):
        fixture = dict(scenarios["target_results"][name])
        fixture["target_id"] = target_id
        (recorded_dir / f"{target_id}.json").write_text(json.dumps(fixture), encoding="utf-8")

    plan = _plan(tmp_path / "artifacts", ("zoom_4766", "doordash_4608"), max_calls=2)
    summary = run_evaluation_plan(plan, "recorded", recorded_dir=recorded_dir)

    assert summary.stopped_on_budget is True
    by_id = {r.target_id: r for r in summary.results}
    assert by_id["zoom_4766"].status == "ACCEPTED"
    assert by_id["doordash_4608"].status == "SKIPPED_BUDGET"


def test_orchestrator_never_mutates_repository_data(tmp_path: Path, scenarios: dict) -> None:
    before_profile = sha256_file(PROFILE_PATH)
    before_targets = sha256_file(TARGETS_JSON)

    recorded_dir = tmp_path / "recorded"
    recorded_dir.mkdir()
    fixture = dict(scenarios["target_results"]["accepted_cleanly"])
    (recorded_dir / "zoom_4766.json").write_text(json.dumps(fixture), encoding="utf-8")

    plan = _plan(tmp_path / "artifacts", ("zoom_4766",))
    run_evaluation_plan(plan, "dry_run")
    run_evaluation_plan(plan, "recorded", recorded_dir=recorded_dir)

    assert sha256_file(PROFILE_PATH) == before_profile
    assert sha256_file(TARGETS_JSON) == before_targets
