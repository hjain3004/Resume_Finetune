from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.eligibility_impact import ImpactAction, build_impact, main
from src import db
from src.eligibility import load_eligibility_config


def _conn(path: str | Path = ":memory:"):
    return db.get_connection(path)


def _insert(conn, key, status, *, title="Software Engineer", location="New York, NY", jd="Starts in 2027.", reason=None, score=None):
    conn.execute(
        """
        INSERT INTO jobs (
            dedup_key, company, title, location, url, source, discovered_at,
            status, jd_text, filter_reason, fit_score, fit_rationale,
            base_variant, missing_keywords, borderline
        )
        VALUES (?, 'Acme', ?, ?, ?, 'tracker_vansh', '2026-07-01T00:00:00+00:00',
                ?, ?, ?, ?, 'old rationale', 'S0', '["x"]', 1)
        """,
        (key, title, location, f"https://example.com/{key}", status, jd, reason, score),
    )
    conn.commit()
    return conn.execute("SELECT id FROM jobs WHERE dedup_key = ?", (key,)).fetchone()["id"]


def test_preview_reports_exact_transitions_and_does_not_mutate() -> None:
    conn = _conn()
    discovered = _insert(conn, "d1", "DISCOVERED", location="Remote - Canada")
    active = _insert(conn, "a1", "SHORTLISTED", jd="Starts in 2027. Unable to sponsor visas.", score=8.0)
    legacy = _insert(conn, "l1", "FILTERED_OUT", reason="location")
    terminal = _insert(conn, "t1", "APPLIED", location="Toronto, Canada")
    before = [dict(row) for row in db.all_rows(conn)]

    transitions = build_impact(conn, load_eligibility_config())

    assert [(t.job_id, t.action, t.to_status, t.reason_code) for t in transitions] == [
        (active, ImpactAction.FILTER_ACTIVE, "FILTERED_OUT", "eligibility:work_authorization"),
        (discovered, ImpactAction.FILTER_DISCOVERED, "FILTERED_OUT", "eligibility:country"),
        (terminal, ImpactAction.REPORT_TERMINAL, None, "eligibility:country"),
        (legacy, ImpactAction.RESTORE_LEGACY, "RESOLVED", "location"),
    ]
    assert [dict(row) for row in db.all_rows(conn)] == before


def test_cli_preview_does_not_create_json_unless_requested(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    conn = _conn(db_path)
    _insert(conn, "d1", "DISCOVERED", location="Remote - Canada")
    conn.close()

    assert main(["--db", str(db_path)]) == 0
    assert list(tmp_path.glob("*.json")) == []

    out = tmp_path / "impact.json"
    assert main(["--db", str(db_path), "--json", str(out)]) == 0
    payload = json.loads(out.read_text())
    assert payload["counts_by_action"]["filter_discovered"] == 1


def test_apply_requires_confirmation_and_new_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    backup = tmp_path / "backup.db"
    conn = _conn(db_path)
    _insert(conn, "d1", "DISCOVERED", location="Remote - Canada")
    conn.close()
    backup.write_text("exists")

    assert main(["--db", str(db_path), "--apply", "--backup", str(tmp_path / "new.db")]) == 2
    assert main(["--db", str(db_path), "--apply", "--confirm", "APPLY", "--backup", str(backup)]) == 2


def test_apply_creates_backup_applies_preview_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    backup = tmp_path / "backup.db"
    conn = _conn(db_path)
    active = _insert(conn, "a1", "SHORTLISTED", jd="Starts in 2027. Unable to sponsor visas.", score=8.0)
    legacy = _insert(conn, "l1", "FILTERED_OUT", reason="location", score=6.0)
    terminal = _insert(conn, "t1", "APPLIED", location="Toronto, Canada", score=9.0)
    conn.close()

    assert main(["--db", str(db_path), "--apply", "--confirm", "APPLY", "--backup", str(backup)]) == 0
    assert backup.exists()
    applied = _conn(db_path)
    active_row = applied.execute("SELECT * FROM jobs WHERE id = ?", (active,)).fetchone()
    legacy_row = applied.execute("SELECT * FROM jobs WHERE id = ?", (legacy,)).fetchone()
    terminal_row = applied.execute("SELECT * FROM jobs WHERE id = ?", (terminal,)).fetchone()
    assert active_row["status"] == "FILTERED_OUT"
    assert active_row["fit_score"] == 8.0
    assert legacy_row["status"] == "RESOLVED"
    assert legacy_row["filter_reason"] is None
    assert legacy_row["fit_score"] is None
    assert legacy_row["fit_rationale"] is None
    assert legacy_row["base_variant"] is None
    assert legacy_row["missing_keywords"] is None
    assert legacy_row["borderline"] == 0
    assert terminal_row["status"] == "APPLIED"

    remaining = build_impact(applied, load_eligibility_config())
    assert [t.action for t in remaining] == [ImpactAction.REPORT_TERMINAL]
    assert db.apply_eligibility_transitions(applied, ()) == 0


def test_apply_rolls_back_on_mid_transaction_error(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _conn()
    row_id = _insert(conn, "d1", "DISCOVERED", location="Remote - Canada")
    good = build_impact(conn, load_eligibility_config())[0]
    bad = type("BadTransition", (), {
        "action": "unknown_action",
        "job_id": row_id,
        "from_status": "DISCOVERED",
        "reason_code": "eligibility:country",
    })()

    with pytest.raises(RuntimeError):
        try:
            db.apply_eligibility_transitions(conn, (good, bad))
        except ValueError as exc:
            raise RuntimeError("boom") from exc
    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (row_id,)).fetchone()
    assert row["status"] == "DISCOVERED"
