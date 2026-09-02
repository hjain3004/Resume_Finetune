"""tailor_now CLI: a thin shell around src.tailor.lane and read-only DB
export. No model, no network; the DB is a seeded temp file."""
import json
from pathlib import Path

import pytest

import scripts.tailor_now as cli
from src.tailor.pilot import MANIFEST_SCHEMA, Stage, StageState, rebuild_manifest, manifest_to_dict, RunOutcome
from src.tailor.preflight import PreflightFinding, PreflightReport
from tests.fixtures.tailor.m8p7_chain import write_chain
from tests.tailor.test_pilot import _seed_db

JD = "Python " * 60


def test_export_jd_writes_text_and_prints_metadata(tmp_path, capsys):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD, base_variant="backend")
    out = tmp_path / "jd" / "225.txt"
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 0
    assert out.read_text(encoding="utf-8") == JD
    printed = capsys.readouterr().out
    assert "Notion" in printed and "SWE" in printed and "backend" in printed and "ats" in printed


def test_export_jd_unknown_job_fails_closed(tmp_path, capsys):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225)
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "999", "--out", str(tmp_path / "x.txt")])
    assert rc == 1
    assert "999" in capsys.readouterr().err
    assert not (tmp_path / "x.txt").exists()


def test_run_success_prints_pdf_path(tmp_path, monkeypatch, capsys):
    directory = write_chain(tmp_path / "apps" / "acme-engineer", job_id=-1, fingerprint="fp", through="g3")
    (directory / "render_result.json").write_text(json.dumps({
        "job_id": -1, "alignment_fingerprint": "fp", "pdf_path": str(directory / "Himanshu_Jain_Resume.pdf")}),
        encoding="utf-8")
    manifest = rebuild_manifest(directory, job_id=-1, company="Acme", title="Engineer")

    def fake_run(jd_path, **kwargs):
        return RunOutcome(manifest=manifest, failed_stage=None, retry_command=None)

    monkeypatch.setattr(cli, "run_manual_application", fake_run)
    jd = tmp_path / "jd.txt"
    jd.write_text(JD, encoding="utf-8")
    rc = cli.main(["run", "--jd", str(jd), "--company", "Acme", "--title", "Engineer", "--variant", "backend",
                   "--root", str(tmp_path / "apps")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "completed" in out and "Himanshu_Jain_Resume.pdf" in out


def test_run_failure_prints_stage_error_and_retry(tmp_path, monkeypatch, capsys):
    from src.tailor.pilot import _prepare_failure
    outcome = _prepare_failure(-1, "preflight_failure", "tailoring_s1.md: bad", "2026-09-01T00:00:00+00:00")
    monkeypatch.setattr(cli, "run_manual_application", lambda jd_path, **kwargs: outcome)
    jd = tmp_path / "jd.txt"
    jd.write_text(JD, encoding="utf-8")
    rc = cli.main(["run", "--jd", str(jd), "--company", "Acme", "--title", "Engineer", "--variant", "backend"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "failed at stage prepare" in err and "tailoring_s1.md" in err


def test_run_lane_error_is_reported_not_raised(tmp_path, monkeypatch, capsys):
    from src.tailor.lane import LaneError

    def boom(jd_path, **kwargs):
        raise LaneError("unknown base variant 'x'")

    monkeypatch.setattr(cli, "run_manual_application", boom)
    jd = tmp_path / "jd.txt"
    jd.write_text(JD, encoding="utf-8")
    rc = cli.main(["run", "--jd", str(jd), "--company", "Acme", "--title", "Engineer", "--variant", "x"])
    assert rc == 1
    assert "unknown base variant" in capsys.readouterr().err


def test_preflight_reports_findings_and_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_preflight", lambda *a, **k: PreflightReport(
        findings=(PreflightFinding("prompt_invariants", "tailoring_s0.md", "shape"),), passed=False))
    assert cli.main(["preflight"]) == 1
    assert "tailoring_s0.md" in capsys.readouterr().out
    monkeypatch.setattr(cli, "run_preflight", lambda *a, **k: PreflightReport(findings=(), passed=True))
    assert cli.main(["preflight"]) == 0


def test_status_lists_lane_applications(tmp_path, capsys):
    directory = write_chain(tmp_path / "apps" / "acme-engineer", job_id=-9, fingerprint="fp", through="s2")
    manifest = rebuild_manifest(directory, job_id=-9, company="Acme", title="Engineer")
    (directory / "run_manifest.json").write_text(json.dumps(manifest_to_dict(manifest)), encoding="utf-8")
    (directory / "lane_manifest.json").write_text(json.dumps({
        "schema_version": "m8n0.lane_manifest.v1", "job_id": -9, "jd_sha256": "a" * 64, "jd_path": "x",
        "company": "Acme", "title": "Engineer", "variant": "backend", "model": "sonnet",
        "claude_cmd": ["claude"], "jd_quality": "ats", "created_at": "2026-09-01T00:00:00+00:00"}), encoding="utf-8")
    rc = cli.main(["status", "--root", str(tmp_path / "apps")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "acme-engineer" in out and "sonnet" in out and "s2" in out
