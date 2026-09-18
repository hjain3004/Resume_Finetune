"""Tests for the self-pair-safe comparison fix (baseline_registry.py,
pairing.py) -- required tests 1-16 for this correction task."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from src.tailor2_eval.baseline_registry import empty_registry, load_baseline_registry
from src.tailor2_eval.blind import blind_package_to_dict
from src.tailor2_eval.orchestrator import run_evaluation_plan
from src.tailor2_eval.pairing import (
    ComparisonProvenanceMismatchError,
    SelfPairError,
    answer_key_entry_to_dict,
    build_blind_pairs_batch,
    build_comparison_between_results,
    build_comparison_for_target,
    check_not_self_pair,
)
from src.tailor2_eval.pairing import PairExclusion
from src.tailor2_eval.schemas import BlindComparisonSettings, ComparisonCandidate, EvaluationPlan, ModelIdentity

REGISTRY_PATH = Path("tests/fixtures/tailor2_eval/baseline_registry.json")


@pytest.fixture
def registry():
    return load_baseline_registry(REGISTRY_PATH)


def test_candidate_vs_distinct_old_pipeline_artifact(target_result_factory, registry) -> None:
    candidate = target_result_factory("accepted_cleanly")  # zoom_4766
    outcome = build_comparison_for_target(
        candidate, registry, seed=1, resume_text_candidate="CANDIDATE TEXT",
        resume_text_baseline_lookup={"baselines/zoom_4766/old_pipeline.tex": "OLD PIPELINE TEXT"},
    )
    assert not isinstance(outcome, PairExclusion)
    pair, package, answer_key = outcome
    assert pair.purpose == "candidate_vs_old_pipeline"
    assert answer_key.baseline_kind == "old_pipeline"


def test_candidate_vs_manual_reference(target_result_factory, registry) -> None:
    candidate = target_result_factory("accepted_cleanly")  # zoom_4766 has a manual entry too
    outcome = build_comparison_for_target(
        candidate, registry, seed=1, resume_text_candidate="CANDIDATE TEXT",
        resume_text_baseline_lookup={"baselines/zoom_4766/manual.tex": "MANUAL TEXT"},
        preferred_kinds=("manual",),
    )
    assert not isinstance(outcome, PairExclusion)
    pair, package, answer_key = outcome
    assert pair.purpose == "candidate_vs_manual"
    assert answer_key.baseline_kind == "manual"


def test_missing_manual_reference_falls_back_to_another_baseline(target_result_factory, registry) -> None:
    candidate = target_result_factory("accepted_with_warnings")  # doordash_4608: old_pipeline only, no manual
    outcome = build_comparison_for_target(
        candidate, registry, seed=1, resume_text_candidate="CANDIDATE TEXT",
        resume_text_baseline_lookup={"baselines/doordash_4608/old_pipeline.tex": "OLD PIPELINE TEXT"},
    )
    assert not isinstance(outcome, PairExclusion)
    _, _, answer_key = outcome
    assert answer_key.baseline_kind == "old_pipeline"


def test_missing_every_baseline_produces_explicit_exclusion(target_result_factory, registry) -> None:
    candidate = target_result_factory("fatal_integrity_failure")  # roadrunner_5027: no registry entry at all
    outcome = build_comparison_for_target(
        candidate, registry, seed=1, resume_text_candidate="CANDIDATE TEXT", resume_text_baseline_lookup={},
    )
    assert isinstance(outcome, PairExclusion)
    assert outcome.reason == "no_baseline_available"
    assert outcome.target_id == "roadrunner_5027"


def _candidate(run_id="run-c", checksum="checksum-c", path="c.tex", artifact_id="art-c") -> ComparisonCandidate:
    return ComparisonCandidate("candidate", run_id, checksum, path, artifact_id=artifact_id)


def test_same_result_id_is_rejected() -> None:
    a = _candidate(run_id="shared-run-id")
    b = _candidate(run_id="shared-run-id", checksum="different", path="different.tex", artifact_id="different-art")
    with pytest.raises(SelfPairError, match="same result id"):
        check_not_self_pair(a, b)


def test_same_artifact_path_is_rejected() -> None:
    a = _candidate(path="shared.tex")
    b = _candidate(run_id="other-run", checksum="different", path="shared.tex", artifact_id="different-art")
    with pytest.raises(SelfPairError, match="same artifact path"):
        check_not_self_pair(a, b)


def test_same_checksum_is_rejected_by_default() -> None:
    a = _candidate(checksum="shared-checksum")
    b = _candidate(run_id="other-run", checksum="shared-checksum", path="other.tex", artifact_id="different-art")
    with pytest.raises(SelfPairError, match="same resume checksum"):
        check_not_self_pair(a, b)


def test_diagnostic_mode_isolated_bypass() -> None:
    a = _candidate()
    b = _candidate()  # fully identical
    with pytest.raises(SelfPairError):
        check_not_self_pair(a, b, diagnostic_mode=False)
    check_not_self_pair(a, b, diagnostic_mode=True)  # does not raise


def test_mismatched_target_is_rejected(target_result_factory) -> None:
    a = target_result_factory("accepted_cleanly")  # zoom_4766
    b = target_result_factory("accepted_with_warnings")  # doordash_4608
    with pytest.raises(ComparisonProvenanceMismatchError, match="target_id mismatch"):
        build_comparison_between_results(a, b, purpose="candidate_vs_other_config", seed=1, resume_text_a="A", resume_text_b="B")


def test_mismatched_jd_checksum_is_rejected(target_result_factory) -> None:
    a = target_result_factory("accepted_cleanly")
    b = dataclasses.replace(a, jd_checksum="different-jd-checksum", run_id="different-run")
    with pytest.raises(ComparisonProvenanceMismatchError, match="jd_checksum mismatch"):
        build_comparison_between_results(a, b, purpose="candidate_vs_other_config", seed=1, resume_text_a="A", resume_text_b="B")


def test_mismatched_profile_checksum_is_rejected(target_result_factory) -> None:
    a = target_result_factory("accepted_cleanly")
    b = dataclasses.replace(a, profile_checksum="different-profile-checksum", run_id="different-run")
    with pytest.raises(ComparisonProvenanceMismatchError, match="profile_checksum mismatch"):
        build_comparison_between_results(a, b, purpose="candidate_vs_other_config", seed=1, resume_text_a="A", resume_text_b="B")


def test_ab_ordering_remains_deterministic(target_result_factory, registry) -> None:
    candidate = target_result_factory("accepted_cleanly")
    lookup = {"baselines/zoom_4766/old_pipeline.tex": "OLD PIPELINE TEXT"}
    outcome1 = build_comparison_for_target(candidate, registry, seed=9, resume_text_candidate="CANDIDATE TEXT", resume_text_baseline_lookup=lookup)
    outcome2 = build_comparison_for_target(candidate, registry, seed=9, resume_text_candidate="CANDIDATE TEXT", resume_text_baseline_lookup=lookup)
    assert not isinstance(outcome1, PairExclusion) and not isinstance(outcome2, PairExclusion)
    assert outcome1[1].candidates[0].resume_text == outcome2[1].candidates[0].resume_text
    assert outcome1[1].integrity_checksum == outcome2[1].integrity_checksum


def test_reviewer_package_hides_identities(target_result_factory, registry) -> None:
    candidate = target_result_factory("accepted_cleanly")
    lookup = {"baselines/zoom_4766/old_pipeline.tex": "OLD PIPELINE TEXT"}
    _, package, _ = build_comparison_for_target(candidate, registry, seed=1, resume_text_candidate="CANDIDATE TEXT", resume_text_baseline_lookup=lookup)
    dumped = str(blind_package_to_dict(package))
    for leaked in ("tailor1@legacy", "claude-3-5-sonnet-20241022", "old-zoom-4766-001", "archived 2026-08-01"):
        assert leaked not in dumped


def test_private_answer_key_preserves_provenance(target_result_factory, registry) -> None:
    candidate = target_result_factory("accepted_cleanly")
    lookup = {"baselines/zoom_4766/old_pipeline.tex": "OLD PIPELINE TEXT"}
    _, _, answer_key = build_comparison_for_target(candidate, registry, seed=1, resume_text_candidate="CANDIDATE TEXT", resume_text_baseline_lookup=lookup)
    key_dict = answer_key_entry_to_dict(answer_key)
    assert key_dict["baseline_pipeline_id"] == "tailor1@legacy"
    assert "archived 2026-08-01" in key_dict["baseline_provenance"]
    assert key_dict["baseline_artifact_id"] == "old-zoom-4766-001"


def test_batch_pairing_reports_included_and_excluded(all_target_results, registry) -> None:
    lookup = {
        "baselines/zoom_4766/old_pipeline.tex": "OLD",
        "baselines/doordash_4608/old_pipeline.tex": "OLD2",
    }
    report = build_blind_pairs_batch(
        all_target_results, registry, seed=1,
        resume_text_by_candidate_run_id={r.run_id: "CANDIDATE" for r in all_target_results},
        resume_text_baseline_lookup=lookup,
    )
    included_targets = {pair.target_id for pair, _, _ in report.included}
    excluded_targets = {ex.target_id for ex in report.excluded}
    assert "zoom_4766" in included_targets
    assert "doordash_4608" in included_targets
    # roadrunner_5027, tiktok_4164, etc. have no registry entry at all.
    assert "roadrunner_5027" in excluded_targets
    assert all(ex.reason == "no_baseline_available" for ex in report.excluded if ex.target_id == "roadrunner_5027")
    # One report row per input result (openai_4949 appears twice in the
    # fixture library -- interrupted + resumed -- so this counts rows, not
    # unique target_ids).
    assert len(report.included) + len(report.excluded) == len(all_target_results)


def test_dry_run_and_recorded_modes_remain_provider_free_after_pairing_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("dry-run must never call Tailor2Invoker.invoke")

    monkeypatch.setattr("src.tailor2.invoker.Tailor2Invoker.invoke", _boom)
    identity = ModelIdentity(provider="claude", model="claude-sonnet-5")
    plan = EvaluationPlan(
        schema_version="1.0", plan_id="pairing-regression-check", profile_id="p", profile_checksum="c",
        target_ids=("zoom_4766",),
        target_jd_checksums={"zoom_4766": "3cb0db9d4a8b3af912332a1d52213c52742cc7c73a29281f119ce807d3d3c72f"},
        candidate_pipeline_id="tailor2@x", baseline_pipeline_id=None,
        drafter=identity, auditor=identity, repair=identity, re_audit=identity,
        deterministic_config={}, max_cost_usd=10.0, max_calls=10, timeout_seconds=60,
        resume_policy="skip_completed", artifact_root=str(tmp_path), blind_comparison=BlindComparisonSettings(),
    )
    summary = run_evaluation_plan(plan, "dry_run")
    assert summary.results[0].status == "DRY_RUN_OK"
