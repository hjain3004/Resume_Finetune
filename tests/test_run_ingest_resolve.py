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
        resolved_count, failed_count, _by_source, _tiers = run_ingest.run_resolution(conn, session)

    assert resolved_count == 1
    assert failed_count == 0
    row = db.get_by_url(conn, "https://boards.greenhouse.io/acme/jobs/1")
    assert row["status"] == Status.RESOLVED
    assert row["jd_text"] == "jd text"


def test_run_resolution_breaks_down_counts_by_source():
    conn = _conn()
    db.insert_discovered(
        conn,
        [
            DiscoveredJob(
                "Acme", "SWE", "Remote",
                "https://boards.greenhouse.io/acme/jobs/1", "tracker_vansh", None,
            ),
            DiscoveredJob(
                "Beta", "SWE 2", "Remote", "https://example.com/job/2", "tracker_simplify", None,
            ),
        ],
    )
    session = MagicMock()

    def _side_effect(url, session, **kwargs):
        return ResolvedJD("jd text", "greenhouse") if "greenhouse" in url else None

    with patch.object(run_ingest.resolve, "resolve", side_effect=_side_effect):
        _, _, by_source, _tiers = run_ingest.run_resolution(conn, session)

    assert by_source == {
        "tracker_vansh": {"resolved": 1, "failed": 0},
        "tracker_simplify": {"resolved": 0, "failed": 1},
    }


def test_run_resolution_records_failure_and_leaves_discovered_under_limit():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=None):
        resolved_count, failed_count, _by_source, tiers = run_ingest.run_resolution(conn, session)

    assert resolved_count == 0
    assert failed_count == 1
    row = db.get_by_url(conn, "https://example.com/job/1")
    assert row["status"] == Status.DISCOVERED
    assert row["resolve_attempts"] == 1
    assert tiers == {"tier1": 0, "tier2": 0, "manual": 0}


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


def test_run_resolution_tallies_tier1_tier2_and_manual():
    conn = _conn()
    db.insert_discovered(
        conn,
        [
            DiscoveredJob("Acme", "SWE", "Remote", "https://boards.greenhouse.io/acme/jobs/1", "tracker_vansh", None),
            DiscoveredJob("Beta", "SWE 2", "Remote", "https://example.com/job/2", "tracker_simplify", None),
            DiscoveredJob("Gamma", "SWE 3", "Remote", "https://example.com/job/3", "tracker_simplify", None),
        ],
    )

    def _side_effect(url, session, **kwargs):
        if "greenhouse" in url:
            return ResolvedJD("jd text", "greenhouse")
        if "job/2" in url:
            return ResolvedJD("rendered jd", "browser")
        return None

    session = MagicMock()
    with patch.object(run_ingest.resolve, "resolve", side_effect=_side_effect):
        _, _, _by_source, tiers = run_ingest.run_resolution(conn, session)

    assert tiers == {"tier1": 1, "tier2": 1, "manual": 0}


def test_run_resolution_counts_manual_only_on_permanent_failure():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=None):
        _, _, _by_source, tiers_1 = run_ingest.run_resolution(conn, session)
        _, _, _by_source, tiers_2 = run_ingest.run_resolution(conn, session)
        _, _, _by_source, tiers_3 = run_ingest.run_resolution(conn, session)

    assert tiers_1 == {"tier1": 0, "tier2": 0, "manual": 0}
    assert tiers_2 == {"tier1": 0, "tier2": 0, "manual": 0}
    assert tiers_3 == {"tier1": 0, "tier2": 0, "manual": 1}


def test_run_resolution_passes_browser_resolver_toggle_through():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=None) as mock_resolve:
        run_ingest.run_resolution(conn, session, browser_resolver=True)

    mock_resolve.assert_called_once_with(
        "https://example.com/job/1", session, browser_resolver=True
    )
