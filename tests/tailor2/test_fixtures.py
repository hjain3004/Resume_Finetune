"""Class 2: Immutable recorded model fixtures integration tests for tailor2.

Verifies end-to-end determinism against byte-exact, frozen model responses
without making live network or model calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.profile import load_profile
from src.render.lines import parse_rendered_lines
from src.tailor2.invoker import Tailor2Invoker
from src.tailor2.lane import run_tailor2_lane
from src.tailor2.models import (
    parse_audit_response,
    parse_draft_response,
    parse_re_audit_response,
    parse_repair_response,
)
from src.tailor2.validators import (
    validate_audit_response,
    validate_draft_response,
    validate_re_audit_response,
    validate_repair_response,
)

FIXTURES_DIR = Path("tests/fixtures/tailor2")


def test_immutable_fixtures_parse_cleanly() -> None:
    assert (FIXTURES_DIR / "job_description.txt").exists()
    assert (FIXTURES_DIR / "draft_response.json").exists()
    assert (FIXTURES_DIR / "audit_response_pass.json").exists()
    assert (FIXTURES_DIR / "audit_response_reject_one.json").exists()
    assert (FIXTURES_DIR / "repair_response.json").exists()
    assert (FIXTURES_DIR / "re_audit_response_pass.json").exists()

    draft_raw = (FIXTURES_DIR / "draft_response.json").read_text(encoding="utf-8")
    draft = parse_draft_response(draft_raw)
    assert len(draft.bullets) == 15

    audit_pass_raw = (FIXTURES_DIR / "audit_response_pass.json").read_text(encoding="utf-8")
    audit_pass = parse_audit_response(audit_pass_raw)
    assert audit_pass.overall_verdict == "PASS"

    audit_rej_raw = (FIXTURES_DIR / "audit_response_reject_one.json").read_text(encoding="utf-8")
    audit_rej = parse_audit_response(audit_rej_raw)
    assert audit_rej.overall_verdict == "REPAIR_REQUIRED"

    repair_raw = (FIXTURES_DIR / "repair_response.json").read_text(encoding="utf-8")
    repair = parse_repair_response(repair_raw)
    assert len(repair.repaired_bullets) == 1

    re_audit_raw = (FIXTURES_DIR / "re_audit_response_pass.json").read_text(encoding="utf-8")
    re_audit = parse_re_audit_response(re_audit_raw)
    assert re_audit.overall_verdict == "PASS"


def test_immutable_draft_passes_deterministic_validation() -> None:
    jd_text = (FIXTURES_DIR / "job_description.txt").read_text(encoding="utf-8")
    draft_raw = (FIXTURES_DIR / "draft_response.json").read_text(encoding="utf-8")
    draft = parse_draft_response(draft_raw)
    profile = load_profile(Path("config/master_profile.yaml"))

    # Must pass all invariants without raising
    validate_draft_response(draft, jd_text, profile, "backend")


def test_immutable_e2e_happy_path_determinism(tmp_path: Path) -> None:
    jd_path = FIXTURES_DIR / "job_description.txt"
    draft_raw = (FIXTURES_DIR / "draft_response.json").read_text(encoding="utf-8")
    audit_raw = (FIXTURES_DIR / "audit_response_pass.json").read_text(encoding="utf-8")

    fake_responses = {
        "draft": draft_raw,
        "audit": audit_raw,
    }

    invoker = Tailor2Invoker(
        provider="openai",
        model="gpt-4o-frozen-fixture",
        fake_responses=fake_responses,
        trace_dir=tmp_path / "traces",
    )

    out_dir = tmp_path / "immutable_app_happy"
    result = run_tailor2_lane(
        jd_path=jd_path,
        company="Datacenter Corp",
        title="Backend Software Engineer",
        variant="backend",
        invoker=invoker,
        out_dir=out_dir,
    )

    assert result.success is True
    assert result.call_count == 2
    assert result.repair_performed is False
    assert result.out_pdf is not None
    assert result.out_pdf.exists()

    # Verify exactly 1 page
    pages = parse_rendered_lines(result.out_pdf)
    assert len(pages) == 1

    # Verify atomic manifest
    manifest_data = json.loads((out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest_data["status"] == "ACCEPTED"
    assert manifest_data["call_count"] == 2
    assert manifest_data["repair_performed"] is False


def test_immutable_e2e_repair_path_determinism(tmp_path: Path) -> None:
    jd_path = FIXTURES_DIR / "job_description.txt"
    draft_raw = (FIXTURES_DIR / "draft_response.json").read_text(encoding="utf-8")
    audit_raw = (FIXTURES_DIR / "audit_response_reject_one.json").read_text(encoding="utf-8")
    repair_raw = (FIXTURES_DIR / "repair_response.json").read_text(encoding="utf-8")
    re_audit_raw = (FIXTURES_DIR / "re_audit_response_pass.json").read_text(encoding="utf-8")

    fake_responses = {
        "draft": draft_raw,
        "audit": audit_raw,
        "repair": repair_raw,
        "re_audit": re_audit_raw,
    }

    invoker = Tailor2Invoker(
        provider="claude",
        model="claude-3-5-sonnet-frozen-fixture",
        fake_responses=fake_responses,
        trace_dir=tmp_path / "traces",
    )

    out_dir = tmp_path / "immutable_app_repair"
    result = run_tailor2_lane(
        jd_path=jd_path,
        company="Datacenter Corp",
        title="Backend Software Engineer",
        variant="backend",
        invoker=invoker,
        out_dir=out_dir,
    )

    assert result.success is True
    assert result.call_count == 4
    assert result.repair_performed is True
    assert result.out_pdf is not None
    assert result.out_pdf.exists()

    # Verify exactly 1 page
    pages = parse_rendered_lines(result.out_pdf)
    assert len(pages) == 1

    # Verify spliced repaired draft written
    assert (out_dir / "draft_repaired.json").exists()
    assert (out_dir / "repair.json").exists()
    assert (out_dir / "re_audit.json").exists()

    # Verify atomic manifest
    manifest_data = json.loads((out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest_data["status"] == "ACCEPTED"
    assert manifest_data["call_count"] == 4
    assert manifest_data["repair_performed"] is True
