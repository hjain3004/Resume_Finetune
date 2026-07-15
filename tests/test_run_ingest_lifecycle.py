"""M6.10 Task 6: reliable partial/aborted run finalization.

`finalize_run()` is the single call site for `db.finish_run()` -- called
exactly once, from `main()`'s `finally` block, so a mid-run exception still
leaves a finished `runs` row with partial counters instead of stuck at
`started_at`/no `finished_at` forever (found 2026-07-15: runs 12 and 13 from
two crashed live backlog-clear attempts are exactly this failure mode).
"""

import json
from unittest.mock import patch

import pytest

from src import db, run_ingest
from src.discover.base import DiscoveryIssue, DiscoveryResult
from src.discover.inbox_manual import InboxResult
from src.models import DiscoveredJob, ResolvedJD, Status
from src.resolve.outcomes import ResolutionOutcome, ResolutionSummary


def _conn():
    return db.get_connection(":memory:")


# --- finalize_run() unit tests -----------------------------------------------


def test_finalize_run_writes_completed_notes_and_counters():
    conn = _conn()
    run_id = db.start_run(conn)
    summary = ResolutionSummary(resolved=2, content_failed=1, tier1=2, manual=0)
    summary.per_source["tracker_vansh"] = {"resolved": 2, "failed": 1}

    run_ingest.finalize_run(
        conn,
        run_id,
        summary=summary,
        run_outcome="completed",
        fatal_error=None,
        discovery_issues=[],
        browser_client=None,
        new_count=5,
        filtered_count=1,
    )

    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["finished_at"] is not None
    assert row["new_jobs"] == 5
    assert row["resolved"] == 2
    assert row["failed"] == 1
    assert row["filtered_out"] == 1
    assert row["tier1_resolved"] == 2

    notes = json.loads(row["notes"])
    assert notes["run_outcome"] == "completed"
    assert "fatal_error" not in notes
    assert "discovery_issues" not in notes
    assert notes["resolution_summary"]["transient"] == 0
    assert notes["resolution_summary"]["internal"] == 0
    assert notes["eligibility_summary"] == {
        "pre_resolution": {"evaluated": 0, "filtered": 0, "deferred": 0, "passed": 0, "by_reason": {}, "by_flag": {}},
        "post_resolution": {"evaluated": 0, "filtered": 0, "deferred": 0, "passed": 0, "by_reason": {}, "by_flag": {}},
    }

    source_row = conn.execute(
        "SELECT * FROM run_sources WHERE run_id = ? AND source = ?", (run_id, "tracker_vansh")
    ).fetchone()
    assert source_row["resolved"] == 2
    assert source_row["failed"] == 1


def test_finalize_run_writes_aborted_notes_with_fatal_error():
    conn = _conn()
    run_id = db.start_run(conn)
    summary = ResolutionSummary(resolved=1)

    run_ingest.finalize_run(
        conn,
        run_id,
        summary=summary,
        run_outcome="aborted",
        fatal_error=KeyboardInterrupt(),
        discovery_issues=[],
        browser_client=None,
        new_count=0,
        filtered_count=0,
    )

    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["finished_at"] is not None
    assert row["resolved"] == 1
    notes = json.loads(row["notes"])
    assert notes["run_outcome"] == "aborted"
    assert notes["fatal_error"]["type"] == "KeyboardInterrupt"


def test_finalize_run_merges_discovery_issues_into_notes():
    conn = _conn()
    run_id = db.start_run(conn)
    issue = DiscoveryIssue("tracker_vansh", "fetch", "ConnectionError", "boom")

    run_ingest.finalize_run(
        conn,
        run_id,
        summary=ResolutionSummary(),
        run_outcome="completed",
        fatal_error=None,
        discovery_issues=[issue],
        browser_client=None,
        new_count=0,
        filtered_count=0,
    )

    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    notes = json.loads(row["notes"])
    assert notes["discovery_issues"] == [
        {"source": "tracker_vansh", "stage": "fetch", "error_type": "ConnectionError", "message": "boom"}
    ]


def test_finalize_run_includes_reason_code_counts_from_summary_issues():
    conn = _conn()
    run_id = db.start_run(conn)
    summary = ResolutionSummary()
    summary.record(
        {"id": 1, "url": "https://example.com/1", "source": "tracker_vansh"},
        ResolutionOutcome.transient("http_transport", ConnectionError("reset")),
    )
    summary.record(
        {"id": 2, "url": "https://example.com/2", "source": "tracker_vansh"},
        ResolutionOutcome.transient("http_transport", ConnectionError("reset again")),
    )
    summary.record(
        {"id": 3, "url": "https://example.com/3", "source": "tracker_vansh"},
        ResolutionOutcome.internal("unexpected_exception", RuntimeError("boom")),
    )

    run_ingest.finalize_run(
        conn,
        run_id,
        summary=summary,
        run_outcome="completed",
        fatal_error=None,
        discovery_issues=[],
        browser_client=None,
        new_count=0,
        filtered_count=0,
    )

    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    notes = json.loads(row["notes"])
    assert notes["resolution_summary"]["transient"] == 2
    assert notes["resolution_summary"]["internal"] == 1
    assert notes["resolution_summary"]["reason_codes"] == {
        "http_transport": 2,
        "unexpected_exception": 1,
    }


def test_finalize_run_closes_browser_client():
    conn = _conn()
    run_id = db.start_run(conn)

    class _FakeClient:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    client = _FakeClient()
    run_ingest.finalize_run(
        conn,
        run_id,
        summary=ResolutionSummary(),
        run_outcome="completed",
        fatal_error=None,
        discovery_issues=[],
        browser_client=client,
        new_count=0,
        filtered_count=0,
    )

    assert client.closed is True


def test_finalize_run_logs_but_does_not_raise_if_browser_close_fails(caplog):
    conn = _conn()
    run_id = db.start_run(conn)

    class _FailingClient:
        def close(self):
            raise RuntimeError("already closed")

    run_ingest.finalize_run(
        conn,
        run_id,
        summary=ResolutionSummary(),
        run_outcome="completed",
        fatal_error=None,
        discovery_issues=[],
        browser_client=_FailingClient(),
        new_count=0,
        filtered_count=0,
    )

    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["finished_at"] is not None  # finalization still completed


# --- main() integration: interrupted vs completed run ------------------------


def test_main_finalizes_run_as_aborted_when_resolution_is_interrupted(tmp_path):
    db_path = str(tmp_path / "jobs.db")

    def _fake_run_resolution(conn, session, *, browser_resolver, resolve_limit, browser_client, summary):
        summary.record(
            {"id": 1, "url": "https://boards.greenhouse.io/acme/jobs/1", "source": "tracker_vansh"},
            ResolutionOutcome.resolved(ResolvedJD("jd", "greenhouse")),
        )
        raise KeyboardInterrupt()

    with (
        patch.object(
            run_ingest,
            "discover_all",
            return_value=DiscoveryResult(
                (
                    DiscoveredJob(
                        "Acme",
                        "Software Engineer",
                        "New York, NY",
                        "https://boards.greenhouse.io/acme/jobs/1",
                        "tracker_vansh",
                        None,
                    ),
                ),
                (),
                ("tracker_vansh", "tracker_simplify", "tracker_jobright"),
                (),
            ),
        ),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(run_ingest, "run_resolution", side_effect=_fake_run_resolution),
    ):
        with pytest.raises(KeyboardInterrupt):
            run_ingest.main(
                ["--db", db_path, "--digest-dir", str(tmp_path / "digests"), "--audit-dir", str(tmp_path / "audit")]
            )

    conn = db.get_connection(db_path)
    run_row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert run_row["finished_at"] is not None
    assert run_row["resolved"] == 1

    source_row = conn.execute(
        "SELECT * FROM run_sources WHERE run_id = ? AND source = ?", (run_row["id"], "tracker_vansh")
    ).fetchone()
    assert source_row["resolved"] == 1

    notes = json.loads(run_row["notes"])
    assert notes["run_outcome"] == "aborted"
    assert notes["fatal_error"]["type"] == "KeyboardInterrupt"
    assert "eligibility_summary" in notes


def test_resolve_only_filters_explicit_non_us_before_session_or_resolution(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    conn = db.get_connection(db_path)
    db.insert_discovered(
        conn,
        [DiscoveredJob("Acme", "Software Engineer", "Remote - Canada", "https://example.com/ca", "tracker_vansh", None)],
    )

    with (
        patch.object(run_ingest, "PoliteSession", side_effect=AssertionError("session should not be created")),
        patch.object(run_ingest, "run_resolution", side_effect=AssertionError("resolution should not run")),
    ):
        result = run_ingest.main(["--resolve-only", "--db", db_path])

    row = db.get_connection(db_path).execute("SELECT status, filter_reason FROM jobs").fetchone()
    assert result == 0
    assert row["status"] == Status.FILTERED_OUT
    assert row["filter_reason"] == "eligibility:country"


def test_resolve_only_unknown_location_reaches_resolver(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    conn = db.get_connection(db_path)
    db.insert_discovered(
        conn,
        [DiscoveredJob("Acme", "Software Engineer", "Remote", "https://example.com/remote", "tracker_vansh", None)],
    )

    called = {"resolution": False}

    def _fake_resolution(conn, session, *, browser_resolver, resolve_limit, browser_client, summary):
        called["resolution"] = True
        return summary

    with patch.object(run_ingest, "run_resolution", side_effect=_fake_resolution):
        result = run_ingest.main(["--resolve-only", "--db", db_path])

    assert result == 0
    assert called["resolution"] is True


def test_discover_only_does_not_run_eligibility_gates(tmp_path):
    db_path = str(tmp_path / "jobs.db")

    with (
        patch.object(
            run_ingest,
            "discover_all",
            return_value=DiscoveryResult((), (), ("tracker_vansh",), ()),
        ),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(run_ingest.prefilter, "run_pre_resolution_gate", side_effect=AssertionError("no pre gate")),
        patch.object(run_ingest.prefilter, "run_post_resolution_gate", side_effect=AssertionError("no post gate")),
    ):
        result = run_ingest.main(["--discover-only", "--db", db_path])

    assert result == 0


def test_invalid_eligibility_config_exits_before_database_creation(tmp_path):
    db_path = tmp_path / "jobs.db"

    with patch.object(run_ingest, "load_eligibility_config", side_effect=run_ingest.EligibilityConfigError("bad config")):
        result = run_ingest.main(["--db", str(db_path)])

    assert result == 1
    assert not db_path.exists()


def test_main_completed_run_has_run_outcome_completed_without_discovery_issues_key(tmp_path):
    db_path = str(tmp_path / "jobs.db")

    with (
        patch.object(
            run_ingest,
            "discover_all",
            return_value=DiscoveryResult((), (), ("tracker_vansh", "tracker_simplify", "tracker_jobright"), ()),
        ),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
    ):
        exit_code = run_ingest.main(
            ["--db", db_path, "--digest-dir", str(tmp_path / "digests"), "--audit-dir", str(tmp_path / "audit")]
        )

    assert exit_code == 0
    conn = db.get_connection(db_path)
    run_row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert run_row["finished_at"] is not None
    notes = json.loads(run_row["notes"])
    assert notes["run_outcome"] == "completed"
    assert "discovery_issues" not in notes
    assert "fatal_error" not in notes
