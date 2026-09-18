"""End-to-end CLI coverage (scripts/evaluate_tailor2.py) and report generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.evaluate_tailor2 import main
from src.tailor2_eval.reports import generate_all_reports
from src.tailor2_eval.metrics import compute_aggregate_summary
from src.tailor2_eval.release_gate import evaluate_release_gate

from .conftest import INVALID_PLAN_MISSING_FIELD_PATH, VALID_PLAN_PATH


def _write_plan_for_artifact_root(tmp_path: Path, artifact_root: Path) -> Path:
    data = json.loads(VALID_PLAN_PATH.read_text(encoding="utf-8"))
    data["artifact_root"] = str(artifact_root)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(data), encoding="utf-8")
    return plan_path


def test_cli_validate_plan_success(capsys: pytest.CaptureFixture) -> None:
    code = main(["validate-plan", str(VALID_PLAN_PATH)])
    assert code == 0
    assert "valid" in capsys.readouterr().out


def test_cli_validate_plan_failure() -> None:
    code = main(["validate-plan", str(INVALID_PLAN_MISSING_FIELD_PATH)])
    assert code == 1


def test_cli_run_dry_run_never_touches_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("dry-run CLI path must never call a provider")

    monkeypatch.setattr("src.tailor2.invoker.Tailor2Invoker.invoke", _boom)
    plan_path = _write_plan_for_artifact_root(tmp_path, tmp_path / "artifacts")
    code = main(["run", str(plan_path), "--dry-run"])
    assert code == 0


def test_cli_run_recorded_and_aggregate_and_blind_pairs(tmp_path: Path, scenarios: dict) -> None:
    artifact_root = tmp_path / "artifacts"
    recorded_dir = tmp_path / "recorded"
    recorded_dir.mkdir()

    for name, target_id in (("accepted_cleanly", "zoom_4766"), ("accepted_with_warnings", "doordash_4608")):
        fixture = dict(scenarios["target_results"][name])
        fixture["target_id"] = target_id
        (recorded_dir / f"{target_id}.json").write_text(json.dumps(fixture), encoding="utf-8")

    plan_path = _write_plan_for_artifact_root(tmp_path, artifact_root)
    assert main(["run", str(plan_path), "--recorded", str(recorded_dir)]) == 0
    assert (artifact_root / "zoom_4766" / "result.json").exists()
    assert (artifact_root / "doordash_4608" / "result.json").exists()

    baseline_registry_path = Path("tests/fixtures/tailor2_eval/baseline_registry.json")
    assert main(["build-blind-pairs", str(artifact_root), "--baseline-registry", str(baseline_registry_path)]) == 0
    blind_pairs_dir = artifact_root / "blind_pairs"
    # zoom_4766 and doordash_4608 both resolve a real, distinct baseline
    # (old_pipeline) from the registry -- never self-paired.
    assert (blind_pairs_dir / "cmp-zoom_4766-old_pipeline.json").exists()
    assert (blind_pairs_dir / "cmp-doordash_4608-old_pipeline.json").exists()
    assert (blind_pairs_dir / "answer_key" / "cmp-zoom_4766-old_pipeline.json").exists()
    pairing_report = json.loads((blind_pairs_dir / "pairing_report.json").read_text(encoding="utf-8"))
    assert set(pairing_report["included"]) == {"cmp-zoom_4766-old_pipeline", "cmp-doordash_4608-old_pipeline"}
    assert pairing_report["excluded"] == []

    # A reviewer package never contains the answer key's identifying fields.
    package_dump = (blind_pairs_dir / "cmp-zoom_4766-old_pipeline.json").read_text(encoding="utf-8")
    assert "tailor1@legacy" not in package_dump
    assert "candidate_1" in package_dump and "candidate_2" in package_dump

    assert main(["build-blind-pairs", str(artifact_root)]) == 0  # no --baseline-registry given

    assert main(["aggregate", str(artifact_root)]) == 0
    reports_dir = artifact_root / "reports"
    for name in ("summary.json", "targets.csv", "report.md", "failure_inventory.json", "release_gate.json"):
        assert (reports_dir / name).exists()

    summary_data = json.loads((reports_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary_data["aggregate"]["target_count"] == 2


def test_reports_are_deterministic_across_runs(tmp_path: Path, all_target_results) -> None:
    summary = compute_aggregate_summary("plan-det", all_target_results)
    gate = evaluate_release_gate(summary)
    out1, out2 = tmp_path / "run1", tmp_path / "run2"
    generate_all_reports(all_target_results, summary, gate, out1)
    generate_all_reports(all_target_results, summary, gate, out2)
    assert (out1 / "summary.json").read_text() == (out2 / "summary.json").read_text()
    assert (out1 / "targets.csv").read_text() == (out2 / "targets.csv").read_text()
    assert (out1 / "report.md").read_text() == (out2 / "report.md").read_text()
