from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.remediate_dead_postings import (
    REMEDIATION_NOTE,
    DeadPostingRow,
    find_dead_postings,
    main,
)
from src import db
from src.models import Status

DEAD_JD = "Sorry, this position has been filled. " + "Experience required. " * 30
LIVE_JD = "Responsibilities: build things. Qualifications: Python. " + "x" * 400
# job 1246 (D2L): careers-FAQ policy wording that M6.13 wrongly classified.
FAQ_JD = (
    "Responsibilities: build things. Qualifications: Python. "
    "When an opportunity has been filled, we will remove the job posting from "
    "the website. " + "x" * 400
)


def _conn(path: str | Path = ":memory:"):
    return db.get_connection(path)


def _insert(conn, key, status, *, jd, score=None):
    conn.execute(
        """
        INSERT INTO jobs (
            dedup_key, company, title, location, url, source, discovered_at,
            status, jd_text, fit_score, fit_rationale
        )
        VALUES (?, 'Acme', 'Software Engineer', 'Remote', ?, 'tracker_vansh',
                '2026-07-01T00:00:00+00:00', ?, ?, ?, 'old rationale')
        """,
        (key, f"https://example.com/{key}", status, jd, score),
    )
    conn.commit()
    return conn.execute("SELECT id FROM jobs WHERE dedup_key = ?", (key,)).fetchone()["id"]


def _status(conn, job_id: int) -> str:
    return conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()["status"]


# --- preview -----------------------------------------------------------------


def test_find_dead_postings_only_proposes_approved_active_states():
    conn = _conn()
    expected = {
        _insert(conn, "resolved", "RESOLVED", jd=DEAD_JD),
        _insert(conn, "scored", "SCORED", jd=DEAD_JD, score=5.0),
        _insert(conn, "shortlisted", "SHORTLISTED", jd=DEAD_JD, score=6.5),
        _insert(conn, "tailored", "TAILORED", jd=DEAD_JD, score=7.0),
    }

    rows = find_dead_postings(conn)

    assert {r.job_id for r in rows} == expected
    assert {r.from_status for r in rows} == {"RESOLVED", "SCORED", "SHORTLISTED", "TAILORED"}


@pytest.mark.parametrize(
    "status", ["FILTERED_OUT", "REJECTED", "APPLIED", "CLOSED", "RESOLVE_FAILED"]
)
def test_find_dead_postings_never_proposes_protected_terminal_states(status):
    conn = _conn()
    _insert(conn, "protected", status, jd=DEAD_JD)

    assert find_dead_postings(conn) == ()


def test_find_dead_postings_ignores_discovered_rows_with_stale_text():
    """A DISCOVERED row's leftover jd_text is not grounds for closure."""
    conn = _conn()
    _insert(conn, "discovered", "DISCOVERED", jd=DEAD_JD)

    assert find_dead_postings(conn) == ()


def test_find_dead_postings_ignores_live_jd_and_incidental_faq_wording():
    conn = _conn()
    _insert(conn, "live", "SHORTLISTED", jd=LIVE_JD, score=7.0)
    _insert(conn, "faq", "SHORTLISTED", jd=FAQ_JD, score=6.5)

    assert find_dead_postings(conn) == ()


def test_preview_row_carries_audit_fields():
    conn = _conn()
    job_id = _insert(conn, "d1", "SHORTLISTED", jd=DEAD_JD, score=6.5)

    (row,) = find_dead_postings(conn)

    assert row.job_id == job_id
    assert row.from_status == "SHORTLISTED"
    assert row.company == "Acme"
    assert row.title == "Software Engineer"
    assert row.jd_text_len == len(DEAD_JD)
    assert "this position has been filled" in row.evidence.lower()


# --- transactional apply ------------------------------------------------------


def test_apply_closes_rows_and_clears_scoring_fields():
    conn = _conn()
    job_id = _insert(conn, "d1", "SHORTLISTED", jd=DEAD_JD, score=6.5)

    changed = db.apply_dead_posting_closures(conn, find_dead_postings(conn), note=REMEDIATION_NOTE)

    assert changed == 1
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.CLOSED
    assert row["fit_score"] is None
    assert row["fit_rationale"] is None
    assert row["base_variant"] is None
    assert row["missing_keywords"] is None
    assert REMEDIATION_NOTE in row["notes"]


def test_apply_preserves_earlier_notes():
    conn = _conn()
    job_id = _insert(conn, "d1", "RESOLVED", jd=DEAD_JD)
    conn.execute("UPDATE jobs SET notes = 'resolver: tier-2 fallback' WHERE id = ?", (job_id,))
    conn.commit()

    db.apply_dead_posting_closures(conn, find_dead_postings(conn), note=REMEDIATION_NOTE)

    notes = conn.execute("SELECT notes FROM jobs WHERE id = ?", (job_id,)).fetchone()["notes"]
    assert notes == f"resolver: tier-2 fallback; {REMEDIATION_NOTE}"


def test_apply_is_idempotent_on_repeat():
    conn = _conn()
    job_id = _insert(conn, "d1", "SCORED", jd=DEAD_JD, score=5.5)
    closures = find_dead_postings(conn)

    first = db.apply_dead_posting_closures(conn, closures, note=REMEDIATION_NOTE)
    second = db.apply_dead_posting_closures(conn, closures, note=REMEDIATION_NOTE)

    assert (first, second) == (1, 0)
    notes = conn.execute("SELECT notes FROM jobs WHERE id = ?", (job_id,)).fetchone()["notes"]
    assert notes.count(REMEDIATION_NOTE) == 1


def test_apply_rolls_back_entire_batch_when_a_preview_is_stale():
    conn = _conn()
    fresh = _insert(conn, "fresh", "RESOLVED", jd=DEAD_JD)
    drifted = _insert(conn, "drifted", "SCORED", jd=DEAD_JD, score=5.0)
    closures = find_dead_postings(conn)
    # Someone rejects the second row after the preview was taken.
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (Status.REJECTED, drifted))
    conn.commit()

    with pytest.raises(db.StalePreviewError):
        db.apply_dead_posting_closures(conn, closures, note=REMEDIATION_NOTE)

    assert _status(conn, fresh) == Status.RESOLVED
    assert _status(conn, drifted) == Status.REJECTED


def test_apply_rejects_a_closure_targeting_a_protected_state():
    conn = _conn()
    job_id = _insert(conn, "protected", "FILTERED_OUT", jd=DEAD_JD)
    forged = (
        DeadPostingRow(
            job_id=job_id,
            company="Acme",
            title="Software Engineer",
            from_status="FILTERED_OUT",
            jd_text_len=len(DEAD_JD),
            evidence="this position has been filled",
        ),
    )

    with pytest.raises(ValueError):
        db.apply_dead_posting_closures(conn, forged, note=REMEDIATION_NOTE)

    assert _status(conn, job_id) == Status.FILTERED_OUT


def test_apply_rolls_back_when_a_row_disappeared():
    conn = _conn()
    kept = _insert(conn, "kept", "RESOLVED", jd=DEAD_JD)
    doomed = _insert(conn, "doomed", "RESOLVED", jd=DEAD_JD)
    closures = find_dead_postings(conn)
    conn.execute("DELETE FROM jobs WHERE id = ?", (doomed,))
    conn.commit()

    with pytest.raises(db.StalePreviewError):
        db.apply_dead_posting_closures(conn, closures, note=REMEDIATION_NOTE)

    assert _status(conn, kept) == Status.RESOLVED


def test_apply_of_empty_preview_changes_nothing():
    conn = _conn()
    job_id = _insert(conn, "live", "SHORTLISTED", jd=LIVE_JD, score=7.0)

    assert db.apply_dead_posting_closures(conn, (), note=REMEDIATION_NOTE) == 0
    assert _status(conn, job_id) == Status.SHORTLISTED


# --- CLI ----------------------------------------------------------------------


def test_cli_preview_does_not_mutate(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    conn = _conn(db_path)
    _insert(conn, "d1", "SHORTLISTED", jd=DEAD_JD, score=6.5)
    conn.close()

    assert main(["--db", str(db_path)]) == 0

    check = db.get_readonly_connection(db_path)
    row = check.execute("SELECT status, fit_score FROM jobs WHERE dedup_key = 'd1'").fetchone()
    assert row["status"] == "SHORTLISTED"
    assert row["fit_score"] == 6.5


def test_cli_preview_json_records_every_proposed_transition(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    out = tmp_path / "preview.json"
    conn = _conn(db_path)
    job_id = _insert(conn, "d1", "SHORTLISTED", jd=DEAD_JD, score=6.5)
    conn.close()

    assert main(["--db", str(db_path), "--json", str(out)]) == 0

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["to_status"] == "CLOSED"
    assert payload["allowed_from_statuses"] == ["RESOLVED", "SCORED", "SHORTLISTED", "TAILORED"]
    (row,) = payload["rows"]
    assert row["job_id"] == job_id
    assert row["from_status"] == "SHORTLISTED"
    assert row["evidence"]


def test_cli_apply_requires_confirm_and_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    conn = _conn(db_path)
    _insert(conn, "d1", "SHORTLISTED", jd=DEAD_JD, score=6.5)
    conn.close()

    assert main(["--db", str(db_path), "--apply"]) == 2
    assert main(["--db", str(db_path), "--apply", "--confirm", "APPLY"]) == 2


def test_cli_apply_moves_rows_to_closed_and_clears_scoring(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    backup_path = tmp_path / "backup.db"
    conn = _conn(db_path)
    job_id = _insert(conn, "d1", "SHORTLISTED", jd=DEAD_JD, score=6.5)
    conn.close()

    exit_code = main(
        ["--db", str(db_path), "--apply", "--confirm", "APPLY", "--backup", str(backup_path)]
    )

    assert exit_code == 0
    assert backup_path.exists()
    check = db.get_readonly_connection(db_path)
    row = check.execute(
        "SELECT status, fit_score, fit_rationale, notes FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    assert row["status"] == "CLOSED"
    assert row["fit_score"] is None
    assert row["fit_rationale"] is None
    assert "dead-posting" in row["notes"]


def test_cli_apply_twice_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    conn = _conn(db_path)
    job_id = _insert(conn, "d1", "SHORTLISTED", jd=DEAD_JD, score=6.5)
    conn.close()

    argv = ["--db", str(db_path), "--apply", "--confirm", "APPLY", "--backup"]
    assert main([*argv, str(tmp_path / "b1.db")]) == 0
    assert main([*argv, str(tmp_path / "b2.db")]) == 0

    check = db.get_readonly_connection(db_path)
    notes = check.execute("SELECT notes FROM jobs WHERE id = ?", (job_id,)).fetchone()["notes"]
    assert notes.count(REMEDIATION_NOTE) == 1
