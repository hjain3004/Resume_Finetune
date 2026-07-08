import json
from unittest.mock import MagicMock

from src import db, freshness
from src.models import DiscoveredJob, ResolvedJD, Status


def _conn():
    return db.get_connection(":memory:")


def _insert(conn, title, url, company="Acme", location="Remote", source="tracker_vansh"):
    db.insert_discovered(conn, [DiscoveredJob(company, title, location, url, source, None)])
    return db.get_by_url(conn, url)["id"]


# --- find_content_repost / record_content_repost ------------------------------

_BASE_JD = (
    "We are looking for a driven software engineer to design build and scale "
    "distributed backend systems handling millions of requests daily across "
    "our microservices platform"
)


def test_find_content_repost_matches_terminal_row_same_company_similar_text():
    conn = _conn()
    old_id = _insert(conn, "Backend Engineer", "https://acme.example/old")
    db.mark_resolved(conn, old_id, ResolvedJD(_BASE_JD, "greenhouse"))
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (Status.FILTERED_OUT, old_id))
    conn.commit()

    new_id = _insert(conn, "Backend Software Engineer II", "https://acme.example/new")

    match = freshness.find_content_repost(conn, "Acme", _BASE_JD + " Apply today.", exclude_row_id=new_id)

    assert match is not None
    assert match["id"] == old_id


def test_find_content_repost_ignores_non_terminal_rows():
    conn = _conn()
    other_id = _insert(conn, "Backend Engineer", "https://acme.example/old")
    db.mark_resolved(conn, other_id, ResolvedJD(_BASE_JD, "greenhouse"))
    # still RESOLVED, not terminal

    new_id = _insert(conn, "Backend Software Engineer II", "https://acme.example/new")

    match = freshness.find_content_repost(conn, "Acme", _BASE_JD, exclude_row_id=new_id)

    assert match is None


def test_find_content_repost_ignores_different_company():
    conn = _conn()
    other_id = _insert(conn, "Backend Engineer", "https://acme.example/old", company="Acme")
    db.mark_resolved(conn, other_id, ResolvedJD(_BASE_JD, "greenhouse"))
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (Status.FILTERED_OUT, other_id))
    conn.commit()

    new_id = _insert(conn, "Backend Software Engineer II", "https://beta.example/new", company="Beta")

    match = freshness.find_content_repost(conn, "Beta", _BASE_JD, exclude_row_id=new_id)

    assert match is None


def test_find_content_repost_ignores_dissimilar_text():
    conn = _conn()
    other_id = _insert(conn, "Backend Engineer", "https://acme.example/old")
    db.mark_resolved(conn, other_id, ResolvedJD("Completely unrelated warehouse logistics role.", "greenhouse"))
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (Status.FILTERED_OUT, other_id))
    conn.commit()

    new_id = _insert(conn, "Backend Software Engineer II", "https://acme.example/new")

    match = freshness.find_content_repost(conn, "Acme", _BASE_JD, exclude_row_id=new_id)

    assert match is None


def test_record_content_repost_flags_and_notes_skipped_outcome():
    conn = _conn()
    prior_id = _insert(conn, "Backend Engineer", "https://acme.example/old")
    db.mark_resolved(conn, prior_id, ResolvedJD(_BASE_JD, "greenhouse"))
    conn.execute(
        "UPDATE jobs SET status = ? WHERE id = ?", (Status.FILTERED_OUT, prior_id)
    )
    conn.commit()
    new_id = _insert(conn, "Backend Software Engineer II", "https://acme.example/new")
    prior_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (prior_id,)).fetchone()

    freshness.record_content_repost(conn, new_id, prior_row)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (new_id,)).fetchone()
    assert json.loads(row["flags"]) == ["repost"]
    assert f"you skipped job #{prior_id}" in row["notes"]


def test_record_content_repost_notes_applied_outcome():
    conn = _conn()
    prior_id = _insert(conn, "Backend Engineer", "https://acme.example/old")
    db.mark_resolved(conn, prior_id, ResolvedJD(_BASE_JD, "greenhouse"))
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (Status.APPLIED, prior_id))
    conn.commit()
    new_id = _insert(conn, "Backend Software Engineer II", "https://acme.example/new")
    prior_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (prior_id,)).fetchone()

    freshness.record_content_repost(conn, new_id, prior_row)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (new_id,)).fetchone()
    assert f"you applied job #{prior_id}" in row["notes"]


# --- run_liveness_recheck ------------------------------------------------------


def test_run_liveness_recheck_closes_404_rows():
    conn = _conn()
    job_id = _insert(conn, "Backend Engineer", "https://acme.example/job")
    conn.execute(
        "UPDATE jobs SET status = ?, last_seen_at = ? WHERE id = ?",
        (Status.SHORTLISTED, "2026-01-01T00:00:00+00:00", job_id),
    )
    conn.commit()
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=404)

    closed = freshness.run_liveness_recheck(conn, session, liveness_days=5)

    assert closed == 1
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.CLOSED


def test_run_liveness_recheck_touches_last_seen_when_still_alive():
    conn = _conn()
    job_id = _insert(conn, "Backend Engineer", "https://acme.example/job")
    conn.execute(
        "UPDATE jobs SET status = ?, last_seen_at = ? WHERE id = ?",
        (Status.SHORTLISTED, "2026-01-01T00:00:00+00:00", job_id),
    )
    conn.commit()
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200)

    closed = freshness.run_liveness_recheck(conn, session, liveness_days=5)

    assert closed == 0
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.SHORTLISTED
    assert row["last_seen_at"] > "2026-01-01T00:00:00+00:00"


def test_run_liveness_recheck_skips_recently_checked_rows():
    conn = _conn()
    job_id = _insert(conn, "Backend Engineer", "https://acme.example/job")
    conn.execute(
        "UPDATE jobs SET status = ? WHERE id = ?",
        (Status.SHORTLISTED, job_id),
    )
    conn.commit()
    db.touch_last_seen(conn, job_id)
    session = MagicMock()

    closed = freshness.run_liveness_recheck(conn, session, liveness_days=5)

    assert closed == 0
    session.get.assert_not_called()


def test_run_liveness_recheck_prefers_ats_url_over_url():
    conn = _conn()
    job_id = _insert(conn, "Backend Engineer", "https://aggregator.example/job")
    conn.execute(
        "UPDATE jobs SET status = ?, last_seen_at = ?, ats_url = ? WHERE id = ?",
        (Status.SHORTLISTED, "2026-01-01T00:00:00+00:00", "https://boards.greenhouse.io/acme/jobs/1", job_id),
    )
    conn.commit()
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=200)

    freshness.run_liveness_recheck(conn, session, liveness_days=5)

    session.get.assert_called_once_with("https://boards.greenhouse.io/acme/jobs/1")
