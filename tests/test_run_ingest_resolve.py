import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from src import db, run_ingest
from src.models import DiscoveredJob, ResolvedJD, Status
from src.resolve.browser import BrowserUnavailableError
from src.resolve.outcomes import ResolutionSummary


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
        summary = run_ingest.run_resolution(conn, session)

    assert summary.resolved == 1
    assert summary.content_failed == 0
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
        summary = run_ingest.run_resolution(conn, session)

    assert summary.per_source == {
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
        summary = run_ingest.run_resolution(conn, session)

    assert summary.resolved == 0
    assert summary.content_failed == 1
    row = db.get_by_url(conn, "https://example.com/job/1")
    assert row["status"] == Status.DISCOVERED
    assert row["resolve_attempts"] == 1
    assert (summary.tier1, summary.tier2, summary.manual) == (0, 0, 0)


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


# --- M6.10: transient vs content vs internal retry-budget semantics ---------


def test_run_resolution_treats_network_exception_as_transient_not_content_failure():
    # M6.10 regression: a requests.ConnectionError from resolve.resolve() must
    # NOT consume resolve_attempts (the pre-M6.10 behavior crashed a live
    # backlog clear at row 181/1047 by treating this as an unhandled
    # exception; the intermediate fix on 2026-07-15 caught it but still
    # spent a content-failure attempt on it, which is also wrong -- a
    # transient infrastructure error tells us nothing about the job's
    # content). One flaky request must be isolated to that row, not abort
    # the whole batch, and must leave the row fully untouched.
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
        summary = run_ingest.run_resolution(conn, session)

    assert summary.resolved == 1
    assert summary.content_failed == 0
    assert summary.transient == 1
    row1 = db.get_by_url(conn, "https://example.com/job/1")
    assert row1["status"] == Status.DISCOVERED
    assert row1["resolve_attempts"] == 0
    row2 = db.get_by_url(conn, "https://example.com/job/2")
    assert row2["status"] == Status.RESOLVED


def test_run_resolution_treats_browser_unavailable_as_transient():
    # M6.10: the real-world case this whole design targets -- a Playwright
    # BrowserType.launch timeout, surfaced by Crawl4AIBrowserClient as
    # BrowserUnavailableError, must be transient, not a content failure.
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
            raise BrowserUnavailableError("Timeout 180000ms exceeded")
        return ResolvedJD("jd text", "greenhouse")

    with patch.object(run_ingest.resolve, "resolve", side_effect=_side_effect):
        summary = run_ingest.run_resolution(conn, session)

    assert summary.transient == 1
    assert summary.content_failed == 0
    row1 = db.get_by_url(conn, "https://example.com/job/1")
    assert row1["status"] == Status.DISCOVERED
    assert row1["resolve_attempts"] == 0
    row2 = db.get_by_url(conn, "https://example.com/job/2")
    assert row2["status"] == Status.RESOLVED


def test_run_resolution_treats_unexpected_exception_as_internal_not_content_failure(caplog):
    # An exception attempt() doesn't specifically recognize (not a requests
    # exception, not BrowserUnavailableError -- e.g. a genuine programming
    # defect in some resolver module) must still not consume resolve_attempts,
    # must be logged with a traceback, and must not stop the next row.
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
            raise RuntimeError("some unrecognized resolver defect")
        return ResolvedJD("jd text", "greenhouse")

    with patch.object(run_ingest.resolve, "resolve", side_effect=_side_effect):
        with caplog.at_level(logging.ERROR, logger="src.run_ingest"):
            summary = run_ingest.run_resolution(conn, session)

    assert summary.internal == 1
    assert summary.content_failed == 0
    row1 = db.get_by_url(conn, "https://example.com/job/1")
    assert row1["status"] == Status.DISCOVERED
    assert row1["resolve_attempts"] == 0
    row2 = db.get_by_url(conn, "https://example.com/job/2")
    assert row2["status"] == Status.RESOLVED

    assert any("unexpected" in record.message.lower() for record in caplog.records)
    assert any(record.exc_info for record in caplog.records)


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
        summary = run_ingest.run_resolution(conn, session)

    assert (summary.tier1, summary.tier2, summary.manual) == (1, 1, 0)


def test_run_resolution_counts_manual_only_on_permanent_failure():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=None):
        summary_1 = run_ingest.run_resolution(conn, session)
        summary_2 = run_ingest.run_resolution(conn, session)
        summary_3 = run_ingest.run_resolution(conn, session)

    assert (summary_1.tier1, summary_1.tier2, summary_1.manual) == (0, 0, 0)
    assert (summary_2.tier1, summary_2.tier2, summary_2.manual) == (0, 0, 0)
    assert (summary_3.tier1, summary_3.tier2, summary_3.manual) == (0, 0, 1)


def test_run_resolution_passes_browser_resolver_toggle_through():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=None) as mock_resolve:
        run_ingest.run_resolution(conn, session, browser_resolver=True)

    mock_resolve.assert_called_once_with(
        "https://example.com/job/1", session, browser_resolver=True, browser_client=None
    )


def test_run_resolution_passes_browser_client_through():
    conn = _conn()
    db.insert_discovered(
        conn, [DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None)]
    )
    session = MagicMock()
    browser_client = object()

    with patch.object(run_ingest.resolve, "resolve", return_value=None) as mock_resolve:
        run_ingest.run_resolution(conn, session, browser_resolver=True, browser_client=browser_client)

    mock_resolve.assert_called_once_with(
        "https://example.com/job/1", session, browser_resolver=True, browser_client=browser_client
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


# --- M6.10: --resolve-limit behavior -----------------------------------------


def test_run_resolution_resolve_limit_processes_only_the_lowest_id_rows():
    conn = _conn()
    db.insert_discovered(
        conn,
        [
            DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/job/1", "tracker_vansh", None),
            DiscoveredJob("Beta", "SWE 2", "Remote", "https://example.com/job/2", "tracker_vansh", None),
            DiscoveredJob("Gamma", "SWE 3", "Remote", "https://example.com/job/3", "tracker_vansh", None),
        ],
    )
    session = MagicMock()

    with patch.object(run_ingest.resolve, "resolve", return_value=None) as mock_resolve:
        summary = run_ingest.run_resolution(conn, session, resolve_limit=2)

    assert mock_resolve.call_count == 2
    assert summary.content_failed == 2
    row3 = db.get_by_url(conn, "https://example.com/job/3")
    assert row3["status"] == Status.DISCOVERED
    assert row3["resolve_attempts"] == 0


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
        "https://careers.example.com/job/1", session, browser_resolver=False, browser_client=None
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
        summary = run_ingest.run_resolution(conn, session)

    mock_resolve.assert_not_called()
    assert summary.resolved == 0
    assert summary.content_failed == 1
    assert summary.per_source == {"tracker_vansh": {"resolved": 0, "failed": 1}}
    assert (summary.tier1, summary.tier2, summary.manual) == (0, 0, 1)
    row = db.get_by_url(conn, "https://careers.example.com/job/1")
    assert row["status"] == Status.RESOLVE_FAILED
    assert row["resolve_attempts"] == 1


# --- M6.10: --resolve-limit CLI flag ----------------------------------------


def test_build_parser_accepts_resolve_limit_of_one():
    parser = run_ingest.build_parser()
    args = parser.parse_args(["--resolve-only", "--resolve-limit", "1"])
    assert args.resolve_limit == 1


def test_build_parser_rejects_resolve_limit_of_zero():
    parser = run_ingest.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--resolve-only", "--resolve-limit", "0"])


def test_build_parser_resolve_limit_defaults_to_none():
    parser = run_ingest.build_parser()
    args = parser.parse_args(["--resolve-only"])
    assert args.resolve_limit is None
