from unittest.mock import MagicMock, patch

import requests

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


def test_run_resolution_treats_network_exception_as_a_resolve_failure():
    # Regression for 2026-07-15: an unhandled ConnectionError from
    # resolve.resolve() (a plain requests.get under the hood) propagated all
    # the way out of run_resolution()/main(), killing an in-progress backlog
    # clear at row 181/1047. One flaky request must be isolated to that row,
    # not abort the whole batch -- matching discover_all()'s per-adapter
    # exception isolation.
    conn = _conn()
    db.insert_discovered(
        conn,
        [
            DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None),
            DiscoveredJob("Beta", "SWE 2", "Remote", "https://example.com/job/2", "tracker_vansh", None),
        ],
    )
    session = MagicMock()

    def _side_effect(url, session, **kwargs):
        if "job/1" in url:
            raise requests.exceptions.ConnectionError("Connection aborted.")
        return ResolvedJD("jd text", "greenhouse")

    with patch.object(run_ingest.resolve, "resolve", side_effect=_side_effect):
        resolved_count, failed_count, _by_source, _tiers = run_ingest.run_resolution(conn, session)

    assert resolved_count == 1
    assert failed_count == 1
    row1 = db.get_by_url(conn, "https://example.com/job/1")
    assert row1["status"] == Status.DISCOVERED
    assert row1["resolve_attempts"] == 1
    row2 = db.get_by_url(conn, "https://example.com/job/2")
    assert row2["status"] == Status.RESOLVED


def test_run_resolution_treats_non_request_exception_as_a_resolve_failure():
    # Regression for 2026-07-15: catching only requests.exceptions.RequestException
    # still let a Playwright BrowserType.launch TimeoutError (raised from the
    # tier-2 browser resolver, which isn't a requests exception at all) crash a
    # second backlog-clear attempt at row 184/1047. resolve.resolve() can raise
    # from requests, Playwright/Crawl4AI, or any per-ATS resolver module, so the
    # catch must be broad -- proven here with a plain exception unrelated to requests.
    conn = _conn()
    db.insert_discovered(
        conn,
        [
            DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None),
            DiscoveredJob("Beta", "SWE 2", "Remote", "https://example.com/job/2", "tracker_vansh", None),
        ],
    )
    session = MagicMock()

    def _side_effect(url, session, **kwargs):
        if "job/1" in url:
            raise TimeoutError("BrowserType.launch: Timeout 180000ms exceeded.")
        return ResolvedJD("jd text", "greenhouse")

    with patch.object(run_ingest.resolve, "resolve", side_effect=_side_effect):
        resolved_count, failed_count, _by_source, _tiers = run_ingest.run_resolution(conn, session)

    assert resolved_count == 1
    assert failed_count == 1
    row1 = db.get_by_url(conn, "https://example.com/job/1")
    assert row1["status"] == Status.DISCOVERED
    assert row1["resolve_attempts"] == 1
    row2 = db.get_by_url(conn, "https://example.com/job/2")
    assert row2["status"] == Status.RESOLVED


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


def test_run_resolution_flags_content_repost_against_terminal_row():
    conn = _conn()
    base_jd = (
        "We are looking for a driven software engineer to design build and scale "
        "distributed backend systems handling millions of requests daily across "
        "our microservices platform"
    )
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "Backend Engineer", "Remote", "https://acme.example/old", "tracker_vansh", None)]
    )
    old_id = db.get_by_url(conn, "https://acme.example/old")["id"]
    db.mark_resolved(conn, old_id, ResolvedJD(base_jd, "greenhouse"))
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (Status.FILTERED_OUT, old_id))
    conn.commit()

    db.insert_discovered(
        conn,
        [DiscoveredJob("Acme", "Backend Software Engineer II", "Remote", "https://acme.example/new", "tracker_vansh", None)],
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=ResolvedJD(base_jd, "greenhouse")):
        run_ingest.run_resolution(conn, session)

    new_row = db.get_by_url(conn, "https://acme.example/new")
    import json

    assert json.loads(new_row["flags"]) == ["repost"]
    assert f"job #{old_id}" in new_row["notes"]


# --- M7 I2: manual_domains.txt routing ---------------------------------------


def test_run_resolution_calls_resolve_normally_when_manual_domains_empty():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://careers.example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with (
        patch.object(run_ingest.resolve, "load_manual_domains", return_value=set()),
        patch.object(run_ingest.resolve, "resolve", return_value=None) as mock_resolve,
    ):
        run_ingest.run_resolution(conn, session)

    mock_resolve.assert_called_once_with(
        "https://careers.example.com/job/1", session, browser_resolver=False
    )


def test_run_resolution_skips_resolve_call_for_manual_domain():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://careers.example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with (
        patch.object(run_ingest.resolve, "load_manual_domains", return_value={"careers.example.com"}),
        patch.object(run_ingest.resolve, "resolve") as mock_resolve,
    ):
        resolved_count, failed_count, per_source, tiers = run_ingest.run_resolution(conn, session)

    mock_resolve.assert_not_called()
    assert resolved_count == 0
    assert failed_count == 1
    assert per_source == {"tracker_vansh": {"resolved": 0, "failed": 1}}
    assert tiers == {"tier1": 0, "tier2": 0, "manual": 1}
    row = db.get_by_url(conn, "https://careers.example.com/job/1")
    assert row["status"] == Status.RESOLVE_FAILED
    assert row["resolve_attempts"] == 1
