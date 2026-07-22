from __future__ import annotations

from pathlib import Path

from scripts.remediate_dead_postings import find_dead_postings, main
from src import db


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


def test_find_dead_postings_matches_closure_text_and_skips_terminal_statuses() -> None:
    conn = _conn()
    dead_shortlisted = _insert(
        conn, "d1", "SHORTLISTED", jd="Sorry, this job is no longer available. " + "x" * 400, score=6.5
    )
    _insert(conn, "d2", "RESOLVE_FAILED", jd="Sorry, this job is no longer available. " + "x" * 400)
    _insert(conn, "d3", "REJECTED", jd="Sorry, this job is no longer available. " + "x" * 400)
    _insert(conn, "live", "SHORTLISTED", jd="Responsibilities: build things. " + "x" * 400, score=7.0)

    rows = find_dead_postings(conn)

    assert [r.job_id for r in rows] == [dead_shortlisted]


def test_cli_preview_does_not_mutate(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    conn = _conn(db_path)
    _insert(conn, "d1", "SHORTLISTED", jd="This position has been filled. " + "x" * 400, score=6.5)
    conn.close()

    assert main(["--db", str(db_path)]) == 0

    check = db.get_readonly_connection(db_path)
    row = check.execute("SELECT status, fit_score FROM jobs WHERE dedup_key = 'd1'").fetchone()
    assert row["status"] == "SHORTLISTED"
    assert row["fit_score"] == 6.5


def test_cli_apply_requires_confirm_and_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    conn = _conn(db_path)
    _insert(conn, "d1", "SHORTLISTED", jd="This position has been filled. " + "x" * 400, score=6.5)
    conn.close()

    assert main(["--db", str(db_path), "--apply"]) == 2
    assert main(["--db", str(db_path), "--apply", "--confirm", "APPLY"]) == 2


def test_cli_apply_moves_rows_to_closed_and_clears_scoring(tmp_path: Path) -> None:
    db_path = tmp_path / "jobs.db"
    backup_path = tmp_path / "backup.db"
    conn = _conn(db_path)
    job_id = _insert(conn, "d1", "SHORTLISTED", jd="This position has been filled. " + "x" * 400, score=6.5)
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
