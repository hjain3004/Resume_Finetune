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


import sqlite3

from src import db
from src.tailor.provenance import JD_PROVENANCE_SCHEMA, parse_provenance_dict


def test_export_jd_writes_text_and_prints_metadata(tmp_path, capsys):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD, base_variant="backend")
    out = tmp_path / "jd" / "225.txt"
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 0
    assert out.read_text(encoding="utf-8") == JD
    sidecar_path = tmp_path / "jd" / "225.txt.provenance.json"
    assert sidecar_path.exists()
    prov_data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    prov = parse_provenance_dict(prov_data)
    assert prov.schema_version == JD_PROVENANCE_SCHEMA
    assert prov.job_id == 225
    assert prov.company == "Notion"
    assert prov.title == "SWE"
    assert prov.source_type == "ats"
    assert prov.jd_quality == "ats"
    assert prov.attestation is None

    printed = capsys.readouterr().out
    assert "Notion" in printed and "SWE" in printed and "backend" in printed and "ats" in printed
    assert f"--db {db_path}" in printed
    assert "Recommended tailoring command:" in printed


def test_export_jd_refuses_aggregator_quality(tmp_path, capsys):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD)
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE jobs SET jd_quality = 'aggregator' WHERE id = 225")
    conn.commit()
    conn.close()

    out = tmp_path / "jd" / "225.txt"
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "only 'ats' quality jobs may be exported" in err
    assert not out.exists()
    assert not (tmp_path / "jd" / "225.txt.provenance.json").exists()


def test_export_jd_refuses_short_jd(tmp_path, capsys):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text="Short text")
    out = tmp_path / "jd" / "225.txt"
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "shorter than 300 characters" in err
    assert not out.exists()


def test_export_jd_refuses_aggregator_url(tmp_path, capsys):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD)
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE jobs SET url = 'https://www.linkedin.com/jobs/view/123', ats_url = NULL WHERE id = 225")
    conn.commit()
    conn.close()

    out = tmp_path / "jd" / "225.txt"
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "aggregator URL" in err
    assert not out.exists()


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
        "schema_version": "m8n0.lane_manifest.v2", "job_id": -9, "jd_sha256": "a" * 64, "jd_path": "x",
        "company": "Acme", "title": "Engineer", "variant": "backend", "model": "sonnet",
        "claude_cmd": ["claude"], "jd_quality": "ats", "created_at": "2026-09-01T00:00:00+00:00",
        "provider": "claude", "provenance_fingerprint": "f" * 64, "source_url": "https://example.com/job/1",
        "ats_url": "https://example.com/job/1", "attestation_digest": None,
    }), encoding="utf-8")
    rc = cli.main(["status", "--root", str(tmp_path / "apps")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "acme-engineer" in out and "sonnet" in out and "s2" in out


def test_attest_cli_success(tmp_path, capsys):
    jd_file = tmp_path / "custom_jd.txt"
    jd_file.write_text(JD, encoding="utf-8")
    rc = cli.main([
        "attest",
        "--jd", str(jd_file),
        "--company", "Acme",
        "--title", "Staff Engineer",
        "--source-url", "https://jobs.lever.co/acme/123",
        "--notes", "Verified official page",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "wrote provenance sidecar" in out
    assert "user_attested" in out
    sidecar = tmp_path / "custom_jd.txt.provenance.json"
    assert sidecar.exists()


def test_attest_cli_fails_on_aggregator_url(tmp_path, capsys):
    jd_file = tmp_path / "custom_jd.txt"
    jd_file.write_text(JD, encoding="utf-8")
    rc = cli.main([
        "attest",
        "--jd", str(jd_file),
        "--company", "Acme",
        "--title", "Staff Engineer",
        "--source-url", "https://www.linkedin.com/jobs/view/123",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "cannot attest an aggregator URL" in err
    assert not (tmp_path / "custom_jd.txt.provenance.json").exists()


def test_export_jd_refuses_when_destinations_exist(tmp_path, capsys):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD)
    out = tmp_path / "jd" / "225.txt"
    sidecar = tmp_path / "jd" / "225.txt.provenance.json"

    # 1. Success on fresh destination
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    assert sidecar.is_file()

    # 2. Refuses when out exists
    rc2 = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc2 == 1
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "Refusing to overwrite" in err
    assert "deliberately remove both existing files" in err

    # 3. Refuses when only sidecar exists
    out.unlink()
    rc3 = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc3 == 1
    err3 = capsys.readouterr().err
    assert "already exists" in err3
    assert "Refusing to overwrite" in err3


def test_export_jd_fs_failure_jd_temp_write(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD)
    out = tmp_path / "jd" / "225.txt"

    orig_write_text = Path.write_text

    def fail_jd_write(self, text, *args, **kwargs):
        if "tmp" in self.name and not self.name.endswith(".provenance.json"):
            raise OSError("Disk full simulation on JD temp write")
        return orig_write_text(self, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_jd_write)
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 1

    all_files = list(tmp_path.rglob("*"))
    files_in_out = [p for p in all_files if p.is_file() and p != db_path]
    assert files_in_out == []


def test_export_jd_fs_failure_sidecar_temp_write(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD)
    out = tmp_path / "jd" / "225.txt"

    orig_write_text = Path.write_text

    def fail_sidecar_write(self, text, *args, **kwargs):
        if "provenance.json.tmp" in self.name:
            raise OSError("Disk full simulation on sidecar temp write")
        return orig_write_text(self, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_sidecar_write)
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 1

    all_files = list(tmp_path.rglob("*"))
    files_in_out = [p for p in all_files if p.is_file() and p != db_path]
    assert files_in_out == []


def test_export_jd_fs_failure_staged_validation(tmp_path, monkeypatch):
    import src.tailor.provenance as prov_mod

    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD)
    out = tmp_path / "jd" / "225.txt"

    def fail_validation(*args, **kwargs):
        raise prov_mod.ProvenanceError("Simulated staged validation rejection")

    monkeypatch.setattr(prov_mod, "validate_provenance_for_tailoring", fail_validation)
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 1

    all_files = list(tmp_path.rglob("*"))
    files_in_out = [p for p in all_files if p.is_file() and p != db_path]
    assert files_in_out == []


def test_export_jd_fs_failure_sidecar_install(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD)
    out = tmp_path / "jd" / "225.txt"
    sidecar_target = str(out.parent / f"{out.name}.provenance.json")

    orig_replace = Path.replace

    def fail_sidecar_replace(self, target):
        if str(target) == sidecar_target:
            raise OSError("Permission denied replacing sidecar")
        return orig_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_sidecar_replace)
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 1

    all_files = list(tmp_path.rglob("*"))
    files_in_out = [p for p in all_files if p.is_file() and p != db_path]
    assert files_in_out == []


def test_export_jd_fs_failure_jd_install_rolls_back_sidecar(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD)
    out = tmp_path / "jd" / "225.txt"
    jd_target = str(out)

    orig_replace = Path.replace

    def fail_jd_replace(self, target):
        if str(target) == jd_target:
            raise OSError("I/O error replacing JD")
        return orig_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_jd_replace)
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 1

    all_files = list(tmp_path.rglob("*"))
    files_in_out = [p for p in all_files if p.is_file() and p != db_path]
    assert files_in_out == []


def test_export_jd_validates_pair_with_state_a_validator(tmp_path):
    from src.tailor.provenance import validate_provenance_for_tailoring

    db_path = tmp_path / "jobs.db"
    _seed_db(db_path, job_id=225, company="Notion", title="SWE", jd_text=JD)
    out = tmp_path / "jd" / "225.txt"
    rc = cli.main(["export-jd", "--db", str(db_path), "--job-id", "225", "--out", str(out)])
    assert rc == 0

    sidecar_path = tmp_path / "jd" / "225.txt.provenance.json"
    conn = db.get_readonly_connection(db_path)
    try:
        prov = validate_provenance_for_tailoring(
            out,
            company="Notion",
            title="SWE",
            db_conn=conn,
            sidecar_path=sidecar_path,
        )
        assert prov.jd_quality == "ats"
        assert prov.job_id == 225
    finally:
        conn.close()
