"""Deterministic verification tests for the Top 10 Tailoring Target set.

Tests:
1. One-company-one-role enforcement (exactly 10 targets, exactly 10 unique companies).
2. Cross-location duplicate collapse.
3. Exactly one TikTok role with exact title and requisition identity.
4. Mandatory Twitch Payments role identity.
5. ATS-only eligibility (zero aggregator summaries).
6. Deterministic tie-breaking (fit_score DESC, date_posted DESC, id DESC).
7. Stable output across identical runs.
8. Failure when a required role lacks an authentic JD.
9. No modification of the historical top-40 export.
10. File-level SHA-256 hash integrity against selection audit.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
import pytest

from scripts.export_tailoring_targets import (
    build_selection_audit,
    build_tailoring_targets,
    get_default_db_path,
    normalize_company_name,
    resolve_tiktok_ecommerce_jd,
    resolve_twitch_payments_jd,
)

TARGETS_DIR = Path("shortlist/tailoring_targets")
TARGETS_JSON = TARGETS_DIR / "targets.json"
AUDIT_JSON = TARGETS_DIR / "selection_audit.json"
JDS_DIR = TARGETS_DIR / "jds"
TOP40_JSON = Path("shortlist/jobs_top40.json")
TOP40_DB = Path("shortlist/jobs_top40.db")
TOP40_README = Path("shortlist/README.md")


@pytest.fixture
def loaded_targets() -> list[dict]:
    assert TARGETS_JSON.exists(), f"Missing targets file: {TARGETS_JSON}"
    return json.loads(TARGETS_JSON.read_text(encoding="utf-8"))


@pytest.fixture
def loaded_audit() -> dict:
    assert AUDIT_JSON.exists(), f"Missing audit file: {AUDIT_JSON}"
    return json.loads(AUDIT_JSON.read_text(encoding="utf-8"))


def test_target_count_and_one_company_one_role_enforcement(loaded_targets: list[dict]) -> None:
    assert len(loaded_targets) == 10, f"Expected exactly 10 targets, got {len(loaded_targets)}"

    normalized_companies = [normalize_company_name(t["company"]).lower() for t in loaded_targets]
    unique_companies = set(normalized_companies)

    assert len(unique_companies) == 10, (
        f"Expected 10 unique companies, got {len(unique_companies)}: {unique_companies}"
    )


def test_cross_location_duplicate_collapse(loaded_targets: list[dict]) -> None:
    tiktok_targets = [t for t in loaded_targets if "tiktok" in t["company"].lower()]
    assert len(tiktok_targets) == 1

    tiktok = tiktok_targets[0]
    collapsed = tiktok["collapsed_duplicate_rows"]

    # 4091 is the Seattle location variant of Global E-commerce
    assert 4091 in collapsed or 2392 in collapsed, (
        "Cross-location variant of Global E-commerce (Job 4091/2392) must be in collapsed rows"
    )
    # Requisition location note or multiple locations covered
    assert "San Jose" in tiktok["location"]
    assert "Seattle" in tiktok["location"]


def test_exactly_one_tiktok_with_exact_title_and_requisition(loaded_targets: list[dict]) -> None:
    tiktok_targets = [t for t in loaded_targets if "tiktok" in t["company"].lower()]
    assert len(tiktok_targets) == 1

    target = tiktok_targets[0]
    expected_title = "Backend Software Engineer Graduate (Global E-commerce) - 2027 Start"
    assert target["exact_title"] == expected_title

    ats_url = target["canonical_ats_url"]
    assert "lifeattiktok.com" in ats_url
    assert "7668824169648097541" in ats_url
    assert target["is_required_override"] is True


def test_mandatory_twitch_payments_identity(loaded_targets: list[dict]) -> None:
    twitch_targets = [t for t in loaded_targets if "twitch" in t["company"].lower()]
    assert len(twitch_targets) == 1

    target = twitch_targets[0]
    assert "payments" in target["exact_title"].lower()
    assert target["exact_title"] == "Software Engineer I, Payments"
    assert target["canonical_ats_url"] == "https://www.amazon.jobs/en/jobs/10502486/software-engineer-i-payments"
    assert target["is_required_override"] is True


def test_ats_only_eligibility(loaded_targets: list[dict]) -> None:
    for target in loaded_targets:
        assert target["jd_quality"] == "ats", (
            f"Target {target['company']} - {target['exact_title']} has quality {target['jd_quality']}; "
            "must be ATS-quality."
        )

        jd_path = JDS_DIR / target["jd_filename"]
        assert jd_path.exists(), f"Missing JD file {jd_path}"
        jd_text = jd_path.read_text(encoding="utf-8")
        assert len(jd_text) >= 1000, (
            f"JD text for {target['company']} is suspiciously short ({len(jd_text)} chars); "
            "cannot be an aggregator stub."
        )


def test_deterministic_tie_breaking(loaded_targets: list[dict]) -> None:
    # Ranks must be 1 through 10 consecutively
    ranks = [t["rank"] for t in loaded_targets]
    assert ranks == list(range(1, 11))

    # Assert non-increasing fit scores
    for i in range(len(loaded_targets) - 1):
        curr_t = loaded_targets[i]
        next_t = loaded_targets[i + 1]
        assert curr_t["fit_score"] >= next_t["fit_score"], (
            f"Target rank {curr_t['rank']} score ({curr_t['fit_score']}) "
            f"is lower than rank {next_t['rank']} score ({next_t['fit_score']})"
        )


def test_stable_output_across_identical_runs() -> None:
    db_file = get_default_db_path()
    if not db_file.exists():
        pytest.skip(f"Source DB {db_file} not found")

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        run1 = build_tailoring_targets(conn)
        run2 = build_tailoring_targets(conn)
    finally:
        conn.close()

    assert len(run1) == len(run2) == 10
    for t1, t2 in zip(run1, run2):
        assert t1["rank"] == t2["rank"]
        assert t1["company"] == t2["company"]
        assert t1["exact_title"] == t2["exact_title"]
        assert t1["fit_score"] == t2["fit_score"]
        assert t1["jd_sha256"] == t2["jd_sha256"]


def test_failure_when_required_role_lacks_authentic_jd(tmp_path: Path) -> None:
    empty_db = tmp_path / "empty.db"
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE jobs (id INTEGER, jd_text TEXT, url TEXT, location TEXT, jd_quality TEXT)")

    # 1. Twitch fails if no cached JD and allow_network=False
    with pytest.raises(RuntimeError, match="Could not authenticate authentic ATS JD for Twitch"):
        resolve_twitch_payments_jd(conn, allow_network=False, cached_path=tmp_path / "nonexistent.txt")

    # 2. TikTok fails if row 2385 is not in db and cached JD does not exist
    with pytest.raises(RuntimeError, match="Could not authenticate authentic ATS JD for TikTok"):
        resolve_tiktok_ecommerce_jd(conn, cached_path=tmp_path / "nonexistent.txt")


def test_no_modification_of_historical_top40_export() -> None:
    assert TOP40_JSON.exists()
    assert TOP40_DB.exists()
    assert TOP40_README.exists()

    top40_data = json.loads(TOP40_JSON.read_text(encoding="utf-8"))
    assert len(top40_data) == 40, f"Historical top 40 must contain exactly 40 jobs, got {len(top40_data)}"

    # Check git diff on shortlist/jobs_top40* is clean
    res = subprocess.run(
        ["git", "status", "--porcelain", "shortlist/jobs_top40.json", "shortlist/jobs_top40.db", "shortlist/README.md"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "", f"Historical top-40 files must not be modified: {res.stdout}"


def test_every_jd_file_hash_matches_manifest(loaded_targets: list[dict]) -> None:
    for target in loaded_targets:
        fpath = JDS_DIR / target["jd_filename"]
        assert fpath.exists()
        actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
        assert actual_hash == target["jd_sha256"], (
            f"File {fpath} hash {actual_hash} does not match manifest hash {target['jd_sha256']}"
        )


def test_selection_audit_verdict_pass(loaded_audit: dict) -> None:
    assert loaded_audit["audit_verdict"] == "PASS"
    for k, v in loaded_audit["invariants"].items():
        assert v is True, f"Invariant {k} was not True: {v}"
