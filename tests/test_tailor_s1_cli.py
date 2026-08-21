"""Tests for scripts/tailor_s1.py (M8P-1): the narrow prepare/invoke CLI.
No network, no real model call -- subprocess.run is patched for `invoke`.
"""

import json
import sqlite3
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts import tailor_s1
from src import db
from src.models import Status

VALID_RESPONSE_JSON = json.dumps(
    {
        "must_have": [{"term": "Python", "quote": "3+ years of Python experience"}],
        "nice_to_have": [],
        "responsibilities_summary": [],
        "seniority_signals": [],
        "disqualifiers": [],
        "company_context": None,
        "suspected_injection": [],
    }
)


def _make_db(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.execute(
        """
        INSERT INTO jobs (dedup_key, company, title, location, url, source, date_posted,
                           discovered_at, status, jd_text, jd_quality, base_variant)
        VALUES ('key-1', 'Cisco', 'ML Engineer', 'Remote', 'https://example.com/job/1',
                'tracker_vansh', NULL, '2026-08-01T00:00:00+00:00', ?,
                'We need a Backend Engineer with 3+ years of Python experience.', 'ats', 'backend')
        """,
        (Status.SHORTLISTED,),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "jobs.db"
    _make_db(path)
    return path


@pytest.fixture
def prompt_template_path(tmp_path):
    path = tmp_path / "tailoring_s1.md"
    path.write_text("Analyze:\n{{S1_REQUEST_JSON}}\nReturn JSON only.")
    return path


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def test_prepare_writes_deterministic_request(tmp_path, db_path, capsys):
    output_dir = tmp_path / "out"
    rc = tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    assert rc == 0
    request_path = output_dir / "s1_request.json"
    assert request_path.exists()
    data = json.loads(request_path.read_text())
    assert data == {
        "job_id": 1,
        "company": "Cisco",
        "title": "ML Engineer",
        "jd_quality": "ats",
        "jd_text": "We need a Backend Engineer with 3+ years of Python experience.",
    }


def test_prepare_does_not_call_model(tmp_path, db_path):
    output_dir = tmp_path / "out"
    with patch.object(subprocess, "run") as mock_run:
        rc = tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    assert rc == 0
    mock_run.assert_not_called()


def test_prepare_rejects_ineligible_job(tmp_path, db_path):
    output_dir = tmp_path / "out"
    rc = tailor_s1.main(["prepare", "--job-id", "999", "--db", str(db_path), "--output", str(output_dir)])
    assert rc != 0
    assert not (output_dir / "s1_request.json").exists()


def test_prepare_run_twice_is_deterministic(tmp_path, db_path):
    output_dir = tmp_path / "out"
    tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    first = (output_dir / "s1_request.json").read_text()
    tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    second = (output_dir / "s1_request.json").read_text()
    assert first == second


# ---------------------------------------------------------------------------
# invoke --dry-run
# ---------------------------------------------------------------------------


def test_invoke_dry_run_does_not_call_model(tmp_path, db_path, prompt_template_path):
    output_dir = tmp_path / "out"
    tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    request_path = output_dir / "s1_request.json"

    with patch.object(subprocess, "run") as mock_run:
        rc = tailor_s1.main(
            [
                "invoke",
                "--request",
                str(request_path),
                "--output",
                str(output_dir),
                "--prompt-template",
                str(prompt_template_path),
                "--dry-run",
            ]
        )
    assert rc == 0
    mock_run.assert_not_called()


def test_invoke_dry_run_creates_no_trace_or_artifact(tmp_path, db_path, prompt_template_path):
    output_dir = tmp_path / "out"
    trace_dir = tmp_path / "traces"
    tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    request_path = output_dir / "s1_request.json"

    rc = tailor_s1.main(
        [
            "invoke",
            "--request",
            str(request_path),
            "--output",
            str(output_dir),
            "--prompt-template",
            str(prompt_template_path),
            "--trace-dir",
            str(trace_dir),
            "--dry-run",
        ]
    )
    assert rc == 0
    assert not (output_dir / "s1.json").exists()
    assert not trace_dir.exists()


def test_invoke_dry_run_does_not_print_full_jd_or_prompt(tmp_path, db_path, prompt_template_path, capsys):
    output_dir = tmp_path / "out"
    tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    request_path = output_dir / "s1_request.json"

    tailor_s1.main(
        [
            "invoke",
            "--request",
            str(request_path),
            "--output",
            str(output_dir),
            "--prompt-template",
            str(prompt_template_path),
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()
    assert "3+ years of Python experience" not in captured.out
    assert "S1_REQUEST_JSON" not in captured.out


# ---------------------------------------------------------------------------
# invoke (mocked success / failure)
# ---------------------------------------------------------------------------


def test_invoke_mocked_success_publishes_s1_json_and_trace(tmp_path, db_path, prompt_template_path):
    output_dir = tmp_path / "out"
    trace_dir = tmp_path / "traces"
    tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    request_path = output_dir / "s1_request.json"

    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout=VALID_RESPONSE_JSON, stderr="")
    ):
        rc = tailor_s1.main(
            [
                "invoke",
                "--request",
                str(request_path),
                "--output",
                str(output_dir),
                "--prompt-template",
                str(prompt_template_path),
                "--trace-dir",
                str(trace_dir),
            ]
        )
    assert rc == 0
    artifact_path = output_dir / "s1.json"
    assert artifact_path.exists()
    published = json.loads(artifact_path.read_text())
    assert published["must_have"] == [{"term": "Python", "quote": "3+ years of Python experience"}]
    assert len(list(trace_dir.glob("**/*.json"))) == 1


def test_invoke_parse_failure_never_publishes_artifact(tmp_path, db_path, prompt_template_path):
    output_dir = tmp_path / "out"
    trace_dir = tmp_path / "traces"
    tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    request_path = output_dir / "s1_request.json"

    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout="not json", stderr="")):
        rc = tailor_s1.main(
            [
                "invoke",
                "--request",
                str(request_path),
                "--output",
                str(output_dir),
                "--prompt-template",
                str(prompt_template_path),
                "--trace-dir",
                str(trace_dir),
            ]
        )
    assert rc != 0
    assert not (output_dir / "s1.json").exists()
    # A trace is still written for the malformed attempt.
    assert len(list(trace_dir.glob("**/*.json"))) == 1


def test_invoke_injection_blocked_never_publishes_artifact(tmp_path, db_path, prompt_template_path):
    output_dir = tmp_path / "out"
    trace_dir = tmp_path / "traces"
    tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    request_path = output_dir / "s1_request.json"

    injection_json = json.dumps(
        {
            "must_have": [],
            "nice_to_have": [],
            "responsibilities_summary": [],
            "seniority_signals": [],
            "disqualifiers": [],
            "company_context": None,
            "suspected_injection": [
                {"quote": "3+ years of Python experience", "reason": "looks like a directive"}
            ],
        }
    )
    with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=injection_json, stderr="")):
        rc = tailor_s1.main(
            [
                "invoke",
                "--request",
                str(request_path),
                "--output",
                str(output_dir),
                "--prompt-template",
                str(prompt_template_path),
                "--trace-dir",
                str(trace_dir),
            ]
        )
    assert rc != 0
    assert not (output_dir / "s1.json").exists()


def test_invoke_existing_artifact_survives_a_failed_rerun(tmp_path, db_path, prompt_template_path):
    output_dir = tmp_path / "out"
    trace_dir = tmp_path / "traces"
    tailor_s1.main(["prepare", "--job-id", "1", "--db", str(db_path), "--output", str(output_dir)])
    request_path = output_dir / "s1_request.json"

    with patch.object(
        subprocess, "run", return_value=MagicMock(returncode=0, stdout=VALID_RESPONSE_JSON, stderr="")
    ):
        tailor_s1.main(
            [
                "invoke",
                "--request",
                str(request_path),
                "--output",
                str(output_dir),
                "--prompt-template",
                str(prompt_template_path),
                "--trace-dir",
                str(trace_dir),
            ]
        )
    before = (output_dir / "s1.json").read_text()

    with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr="boom")):
        rc = tailor_s1.main(
            [
                "invoke",
                "--request",
                str(request_path),
                "--output",
                str(output_dir),
                "--prompt-template",
                str(prompt_template_path),
                "--trace-dir",
                str(trace_dir),
            ]
        )
    assert rc != 0
    after = (output_dir / "s1.json").read_text()
    assert before == after
