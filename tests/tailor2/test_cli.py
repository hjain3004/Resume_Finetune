"""Unit tests for tailor2 CLI (scripts/tailor2.py)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.tailor2 import main


def test_cli_preflight_pass(tmp_path: Path) -> None:
    code = main(["preflight", "--skip-render"])
    assert code == 0


def test_cli_preflight_missing_profile(tmp_path: Path) -> None:
    code = main(["preflight", "--profile", str(tmp_path / "nonexistent.yaml")])
    assert code == 1


def test_cli_preflight_provider_openai_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = main(["preflight", "--provider", "openai", "--skip-render"])
    assert code == 1


def test_cli_status_empty(tmp_path: Path) -> None:
    code = main(["status", "--root", str(tmp_path)])
    assert code == 0


def test_cli_status_with_manifest(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    app_dir = tmp_path / "acme-corp-swe-tailor2"
    app_dir.mkdir(parents=True)
    manifest_data = {
        "run_id": "20260917T120000Z",
        "created_at": "2026-09-17T12:00:00Z",
        "provider": "claude",
        "model": "claude-3-5-sonnet-20241022",
        "company": "Acme Corp",
        "title": "Software Engineer",
        "variant": "backend",
        "call_count": 2,
        "repair_performed": False,
        "status": "ACCEPTED",
        "rejection_details": [],
    }
    (app_dir / "run_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    code = main(["status", "--root", str(tmp_path)])
    assert code == 0
    captured = capsys.readouterr()
    assert "Acme Corp" in captured.out
    assert "Software Engineer" in captured.out
    assert "1 tailor2 application(s) found" in captured.out


def test_cli_run_fails_missing_jd(tmp_path: Path) -> None:
    code = main([
        "run",
        "--jd", str(tmp_path / "nonexistent.txt"),
        "--company", "Acme",
        "--title", "Engineer",
        "--variant", "backend",
        "--dry-run",
    ])
    assert code == 1


def test_cli_run_fails_short_jd(tmp_path: Path) -> None:
    jd = tmp_path / "short_jd.txt"
    jd.write_text("Too short JD", encoding="utf-8")
    code = main([
        "run",
        "--jd", str(jd),
        "--company", "Acme",
        "--title", "Engineer",
        "--variant", "backend",
        "--dry-run",
    ])
    assert code == 1


def test_cli_run_dry_run_success(tmp_path: Path, sample_jd_text: str) -> None:
    jd = tmp_path / "jd.txt"
    jd.write_text(sample_jd_text, encoding="utf-8")
    code = main([
        "run",
        "--jd", str(jd),
        "--company", "Acme Corp",
        "--title", "Senior Systems Engineer",
        "--variant", "backend",
        "--dry-run",
    ])
    assert code == 0


def test_cli_run_requires_provider_and_model_for_live(tmp_path: Path, sample_jd_text: str) -> None:
    jd = tmp_path / "jd.txt"
    jd.write_text(sample_jd_text, encoding="utf-8")
    # Missing provider
    code1 = main([
        "run",
        "--jd", str(jd),
        "--company", "Acme Corp",
        "--title", "Engineer",
        "--variant", "backend",
    ])
    assert code1 == 1

    # Missing model
    code2 = main([
        "run",
        "--jd", str(jd),
        "--company", "Acme Corp",
        "--title", "Engineer",
        "--variant", "backend",
        "--provider", "openai",
    ])
    assert code2 == 1


def test_cli_run_with_fake_responses_e2e(
    tmp_path: Path,
    sample_jd_text: str,
    fake_draft_response_backend: dict,
    fake_audit_response_pass: dict,
    capsys: pytest.CaptureFixture,
) -> None:
    jd = tmp_path / "jd.txt"
    jd.write_text(sample_jd_text, encoding="utf-8")

    fake_responses = {
        "draft": json.dumps(fake_draft_response_backend),
        "audit": json.dumps(fake_audit_response_pass),
    }
    fake_resp_file = tmp_path / "fake_responses.json"
    fake_resp_file.write_text(json.dumps(fake_responses), encoding="utf-8")

    out_dir = tmp_path / "apps" / "acme-tailor2"
    trace_dir = tmp_path / "traces"

    code = main([
        "run",
        "--jd", str(jd),
        "--company", "Acme Corp",
        "--title", "Senior Systems Engineer",
        "--variant", "backend",
        "--out-dir", str(out_dir),
        "--fake-responses", str(fake_resp_file),
        "--trace-dir", str(trace_dir),
    ])
    assert code == 0
    captured = capsys.readouterr()
    assert "COMPLETED" in captured.out

    # Verify generated artifacts
    assert (out_dir / "job_description.txt").exists()
    assert (out_dir / "draft.json").exists()
    assert (out_dir / "audit.json").exists()
    assert (out_dir / "resume.tex").exists()
    assert (out_dir / "resume.pdf").exists()
    assert (out_dir / "run_manifest.json").exists()
