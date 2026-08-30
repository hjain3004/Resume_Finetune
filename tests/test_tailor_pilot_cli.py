"""Coverage for scripts/tailor_pilot.py (M8P-7 Task 5): the one-job pilot
operator CLI (select/run/cost/gate/index). All fixtures use a temporary
SQLite database and a temporary applications root; data/jobs.db is never
touched. In-process CLI invocation (main(argv) -> int, capsys for
stdout/stderr) -- the same convention used for scripts/tailor_s3.py and
scripts/tailor_g3.py's own test suites, not a real subprocess spawn."""
import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.tailor_pilot import build_parser, main
from src import db
from src.models import Status
from tests.tailor.test_pilot import _build_pilot_root, _write_clean_prompt_dir, _write_feedback_record


def test_pilot_cli_contract_exists():
    assert callable(main)
    parser = build_parser()
    assert parser.parse_args(["select", "--db", "x"]).command == "select"
    assert parser.parse_args(["run", "--job-id", "1", "--db", "x"]).command == "run"
    assert parser.parse_args(["cost"]).command == "cost"
    assert parser.parse_args(["gate"]).command == "gate"
    assert parser.parse_args(["index"]).command == "index"


@dataclass
class TmpRepo:
    root: Path
    db: Path
    applications: Path
    prompts: Path


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
def tmp_repo(tmp_path):
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
    prompts_dir = tmp_path / "prompts"
    _write_clean_prompt_dir(prompts_dir)
    return TmpRepo(root=tmp_path, db=db_path, applications=tmp_path / "applications", prompts=prompts_dir)


@pytest.fixture
def db_checksum(tmp_repo):
    def _checksum():
        return hashlib.sha256(tmp_repo.db.read_bytes()).hexdigest()
    return _checksum


@pytest.fixture
def three_completed_applications(tmp_repo):
    return _build_pilot_root(tmp_repo.root)


@pytest.fixture
def failing_feedback(tmp_repo):
    feedback_dir = tmp_repo.root / "feedback"
    _write_feedback_record(
        feedback_dir, job_id=119, fingerprint="fp119",
        unsupported_claims=[{"bullet_id": "b1", "quoted_text": "p99 latency", "why": "never measured"}],
    )
    _write_feedback_record(feedback_dir, job_id=213, fingerprint="fp213")
    _write_feedback_record(feedback_dir, job_id=225, fingerprint="fp225")
    return feedback_dir


def test_select_is_read_only_and_prints_reasons(tmp_repo, db_checksum, capsys):
    before = db_checksum()
    code = main(["select", "--count", "3", "--db", str(tmp_repo.db)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.count("reason:") == 3
    assert db_checksum() == before


def test_run_dry_run_writes_nothing(tmp_repo):
    code = main(["run", "--job-id", "225", "--dry-run", "--db", str(tmp_repo.db),
                "--root", str(tmp_repo.applications), "--prompts", str(tmp_repo.prompts)])
    assert code == 0
    assert not tmp_repo.applications.exists()


def test_run_prohibited_job_exits_nonzero(tmp_repo, capsys):
    code = main(["run", "--job-id", "279", "--db", str(tmp_repo.db),
                "--root", str(tmp_repo.applications), "--prompts", str(tmp_repo.prompts)])
    captured = capsys.readouterr()
    assert code == 1
    assert "prohibited" in captured.err


def test_gate_exits_nonzero_when_a_condition_fails(tmp_repo, failing_feedback, capsys):
    code = main(["gate", "--root", str(tmp_repo.applications), "--feedback-dir", str(failing_feedback)])
    captured = capsys.readouterr()
    assert code == 1
    assert "unsupported_claims" in captured.out


def test_index_regenerates_applications_index(tmp_repo, three_completed_applications):
    code = main(["index", "--root", str(tmp_repo.applications)])
    assert code == 0
    text = (tmp_repo.applications / "INDEX.md").read_text(encoding="utf-8")
    assert text.count("|") >= 3


def test_index_does_not_build_a_by_date_symlink_view(tmp_repo, three_completed_applications):
    main(["index", "--root", str(tmp_repo.applications)])
    assert not (tmp_repo.applications / "by-date").exists()


def test_cli_never_prints_more_than_260_chars_per_line(tmp_repo, capsys):
    code = main(["run", "--job-id", "999999", "--db", str(tmp_repo.db), "--root", str(tmp_repo.applications)])
    captured = capsys.readouterr()
    assert code == 1
    assert max((len(line) for line in captured.err.splitlines()), default=0) <= 260
