from unittest.mock import patch

from scripts import reresolve_aggregator_chrome as reresolve
from src import db
from src.models import DiscoveredJob, ResolvedJD, Status


def _conn():
    return db.get_connection(":memory:")


def test_matches_aggregator_chrome_detects_known_patterns():
    assert reresolve.matches_aggregator_chrome("...H1B Sponsor Likely...")
    assert reresolve.matches_aggregator_chrome("Amazon · 3 hours ago\nSDE")
    assert reresolve.matches_aggregator_chrome("Intro\nTrends of Total Sponsorships\nmore")
    assert reresolve.matches_aggregator_chrome("Intro\nFunding\nSeries B")
    assert reresolve.matches_aggregator_chrome("Intro\nRecent News\nsome article")
    assert reresolve.matches_aggregator_chrome("Intro\nCompany data provided by Crunchbase")


def test_matches_aggregator_chrome_false_for_clean_text():
    assert not reresolve.matches_aggregator_chrome("A clean job description with no chrome.")
    assert not reresolve.matches_aggregator_chrome(None)
    assert not reresolve.matches_aggregator_chrome("")


def _insert(conn, title, url, jd_text, status=Status.RESOLVED, source="tracker_jobright"):
    db.insert_discovered(conn, [DiscoveredJob("Acme", title, "Remote", url, source, None)])
    row_id = db.get_by_url(conn, url)["id"]
    if status == Status.RESOLVED:
        db.mark_resolved(conn, row_id, ResolvedJD(jd_text, "generic"))
    return row_id


def test_select_rows_to_reresolve_finds_only_chrome_matches():
    conn = _conn()
    dirty_id = _insert(conn, "Software Engineer", "https://jobright.ai/jobs/1", "Acme · 3 hours ago\nWe build things.")
    clean_id = _insert(conn, "Data Engineer", "https://boards.greenhouse.io/acme/jobs/2", "A clean posting.")

    matched = reresolve.select_rows_to_reresolve(conn)

    assert matched == [dirty_id]
    assert clean_id not in matched


def test_select_rows_to_reresolve_ignores_status_and_attempts():
    conn = _conn()
    dirty_id = _insert(
        conn, "k1", "https://jobright.ai/jobs/1", "H1B Sponsor Likely\nfull posting text", status=Status.RESOLVED
    )
    conn.execute(
        "UPDATE jobs SET status = ?, filter_reason = ?, resolve_attempts = ? WHERE id = ?",
        (Status.FILTERED_OUT, "title_exclude", 2, dirty_id),
    )
    conn.commit()

    matched = reresolve.select_rows_to_reresolve(conn)

    assert matched == [dirty_id]


def test_main_resets_and_reresolves_matching_rows():
    conn = _conn()
    dirty_id = _insert(conn, "Software Engineer", "https://jobright.ai/jobs/1", "Acme · 3 hours ago\nold aggregator text")
    clean_id = _insert(conn, "Data Engineer", "https://boards.greenhouse.io/acme/jobs/2", "A clean posting.")

    with patch("src.run_ingest.resolve.resolve") as mock_resolve:
        mock_resolve.return_value = ResolvedJD("clean re-resolved jd text", "jobright", jd_quality="aggregator")
        with patch("src.db.get_connection", return_value=conn):
            reresolve.main(["--db", "ignored.db"])

    dirty_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (dirty_id,)).fetchone()
    clean_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (clean_id,)).fetchone()

    assert dirty_row["status"] == Status.RESOLVED
    assert dirty_row["jd_text"] == "clean re-resolved jd text"
    assert dirty_row["resolver"] == "jobright"
    assert not reresolve.matches_aggregator_chrome(dirty_row["jd_text"])
    # untouched row: resolve() was never called for it because it wasn't reset to DISCOVERED
    assert clean_row["jd_text"] == "A clean posting."


def test_main_dry_run_does_not_modify_db():
    conn = _conn()
    dirty_id = _insert(conn, "Software Engineer", "https://jobright.ai/jobs/1", "Acme · 3 hours ago\nold aggregator text")

    with patch("src.db.get_connection", return_value=conn):
        reresolve.main(["--db", "ignored.db", "--dry-run"])

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (dirty_id,)).fetchone()
    assert row["status"] == Status.RESOLVED
    assert "hours ago" in row["jd_text"]
