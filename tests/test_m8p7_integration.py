"""End-to-end integration coverage for the M8P-7 pilot operator: select ->
run (dry-run) -> cost -> gate -> index, driven entirely through the CLI
(scripts/tailor_pilot.py's main()). No model call, no network, no DB write
-- data/jobs.db is never touched; a fresh temporary DB and applications
root stand in for the real corpus."""
import inspect
import sqlite3
from pathlib import Path

import pytest

import scripts.tailor_pilot as pilot_cli
from scripts.tailor_pilot import main
from src import db
from src.models import Status
from tests.tailor.test_pilot import _build_pilot_root, _write_feedback_record


def _seed_jobs(path: Path, jobs) -> None:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    for job in jobs:
        conn.execute(
            """
            INSERT INTO jobs (id, dedup_key, company, title, location, url, source, discovered_at,
                               status, jd_text, jd_quality, base_variant)
            VALUES (?, ?, ?, ?, 'Remote', 'https://example.test/job',
                    'inbox', '2026-08-01T00:00:00+00:00', ?, ?, 'ats', ?)
            """,
            (job["id"], f"key-{job['id']}", job["company"], job["title"],
             job["status"], job["jd_text"], job["base_variant"]),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def corpus_db(tmp_path):
    db_path = tmp_path / "jobs.db"
    _seed_jobs(db_path, [
        dict(id=225, company="Notion", title="Engineer", status=Status.SHORTLISTED,
             jd_text="n" * 7000, base_variant="backend"),
        dict(id=119, company="Cisco", title="ML Engineer", status=Status.SHORTLISTED,
             jd_text="c" * 13500, base_variant="ml"),
        dict(id=213, company="Citadel Securities", title="Engineer", status=Status.SHORTLISTED,
             jd_text="s" * 2000, base_variant="backend"),
        dict(id=279, company="Blocked Co", title="Blocked Role", status=Status.SHORTLISTED,
             jd_text="b" * 3000, base_variant="ml"),
    ])
    return db_path


def test_select_then_dry_run_then_cost_gate_index(tmp_path, corpus_db, capsys):
    applications = tmp_path / "applications"

    # 1. select: read-only, names the same three jobs the design's own
    #    illustrative §4 example does (one ml/long, one short, one medium).
    code = main(["select", "--count", "3", "--db", str(corpus_db)])
    picked = capsys.readouterr().out
    assert code == 0
    for job_id in ("119", "213", "225"):
        assert job_id in picked

    # 2. run --dry-run for each pick proves the chain composes at zero
    #    cost and writes nothing -- before any real stage is ever invoked.
    for job_id in (119, 213, 225):
        assert main(["run", "--job-id", str(job_id), "--dry-run", "--db", str(corpus_db),
                     "--root", str(applications)]) == 0
    assert not applications.exists()

    # 3. cost/gate/index over an already-complete pilot root (the shape a
    #    real run would leave behind) prove the reporting subcommands
    #    compose correctly end-to-end, through the CLI, not just the
    #    library functions directly.
    completed_root = _build_pilot_root(tmp_path / "completed")

    assert main(["cost", "--root", str(completed_root)]) == 0
    assert "applications: 3" in capsys.readouterr().out

    feedback_dir = tmp_path / "feedback"
    _write_feedback_record(feedback_dir, job_id=119, fingerprint="fp119", would_submit="yes")
    _write_feedback_record(feedback_dir, job_id=213, fingerprint="fp213", would_submit="yes")
    _write_feedback_record(feedback_dir, job_id=225, fingerprint="fp225", would_submit="no")
    assert main(["gate", "--root", str(completed_root), "--feedback-dir", str(feedback_dir)]) == 0
    assert "gate: PASS" in capsys.readouterr().out

    assert main(["index", "--root", str(completed_root)]) == 0
    index_text = (completed_root / "INDEX.md").read_text(encoding="utf-8")
    for company in ("Cisco", "Citadel Securities", "Notion"):
        assert company in index_text
    assert "by-date" not in index_text
    assert not (completed_root / "by-date").exists()


def test_operator_cli_has_no_submission_path():
    source = inspect.getsource(pilot_cli)
    for banned in ("requests", "urllib", "smtplib", "webbrowser", "playwright", "crawl4ai", "firecrawl"):
        assert banned not in source


def test_operator_cli_defines_no_parsing_or_validation_of_its_own():
    source = inspect.getsource(pilot_cli)
    for banned in ("def parse_", "def validate_", "def hydrate_", "def build_prompt"):
        assert banned not in source


def test_select_only_ever_opens_a_readonly_connection():
    assert "get_readonly_connection" in inspect.getsource(pilot_cli.cmd_select)
    assert "get_readonly_connection" not in inspect.getsource(pilot_cli.cmd_run)
