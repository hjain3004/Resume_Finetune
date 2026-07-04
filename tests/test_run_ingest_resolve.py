from unittest.mock import MagicMock, patch

from src import db, run_ingest
from src.models import DiscoveredJob, ResolvedJD, Status


def _conn():
    connection = db.get_connection(":memory:")
    return connection


def test_run_resolution_marks_resolved_rows_resolved():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://boards.greenhouse.io/acme/jobs/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=ResolvedJD("jd text", "greenhouse")):
        resolved_count, failed_count = run_ingest.run_resolution(conn, session)

    assert resolved_count == 1
    assert failed_count == 0
    row = db.get_by_url(conn, "https://boards.greenhouse.io/acme/jobs/1")
    assert row["status"] == Status.RESOLVED
    assert row["jd_text"] == "jd text"


def test_run_resolution_records_failure_and_leaves_discovered_under_limit():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=None):
        resolved_count, failed_count = run_ingest.run_resolution(conn, session)

    assert resolved_count == 0
    assert failed_count == 1
    row = db.get_by_url(conn, "https://example.com/job/1")
    assert row["status"] == Status.DISCOVERED
    assert row["resolve_attempts"] == 1


def test_run_resolution_sets_resolve_failed_after_three_runs():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=None):
        run_ingest.run_resolution(conn, session)
        run_ingest.run_resolution(conn, session)
        run_ingest.run_resolution(conn, session)

    row = db.get_by_url(conn, "https://example.com/job/1")
    assert row["status"] == Status.RESOLVE_FAILED
    assert row["resolve_attempts"] == 3


def test_run_resolution_only_processes_discovered_rows():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None)]
    )
    row_id = db.get_by_url(conn, "https://example.com/job/1")["id"]
    db.mark_resolved(conn, row_id, ResolvedJD("already resolved", "greenhouse"))
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve") as mock_resolve:
        run_ingest.run_resolution(conn, session)

    mock_resolve.assert_not_called()
