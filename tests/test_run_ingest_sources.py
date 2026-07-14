"""Per-source observability (PHASE2_KICKOFF.md M6.0(3)): a source that
contributes zero rows must still show up as a visible zero in run_sources,
not silently vanish — this is the exact shape of the tracker_simplify bug."""

import json
from unittest.mock import patch

import pytest

from src import db, run_ingest
from src.discover.base import DiscoveryIssue, DiscoveryResult, PendingCheckpoint
from src.discover.inbox_manual import InboxResult
from src.models import DiscoveredJob, ResolvedJD


def _discovery_result(jobs=(), checkpoints=(), succeeded_sources=("tracker_vansh",), issues=()):
    return DiscoveryResult(tuple(jobs), tuple(checkpoints), tuple(succeeded_sources), tuple(issues))


def _run(db_path, jobs, *, resolve_result=None, digest_dir=None, audit_dir=None):
    with (
        patch.object(run_ingest, "discover_all", return_value=_discovery_result(jobs)),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(
            run_ingest.resolve, "resolve", return_value=resolve_result or ResolvedJD("jd", "fixture")
        ),
    ):
        args = ["--db", db_path]
        if digest_dir is not None:
            args += ["--digest-dir", digest_dir]
        if audit_dir is not None:
            args += ["--audit-dir", audit_dir]
        run_ingest.main(args)


def _job(source="tracker_vansh"):
    return DiscoveredJob(
        "Acme",
        "SWE",
        "Remote",
        "https://boards.greenhouse.io/acme/jobs/1",
        source,
        None,
    )


def _checkpoint(tmp_path, source="tracker_vansh"):
    return PendingCheckpoint(
        source,
        tmp_path / f"{source}.json",
        "listings.json",
        frozenset({"k1"}),
        frozenset(),
    )


def test_db_failure_never_calls_checkpoint_commit(tmp_path):
    conn = db.get_connection(":memory:")
    result = _discovery_result([_job()], [_checkpoint(tmp_path)])

    with patch.object(db, "insert_discovered", side_effect=RuntimeError("db")):
        with patch.object(run_ingest.tracker_common, "commit_checkpoint") as commit:
            with pytest.raises(RuntimeError, match="db"):
                run_ingest.persist_discovery(
                    conn, result, stale_days=21, reopen_days=45, dry_run=False
                )
    commit.assert_not_called()


def test_checkpoint_failure_keeps_inserted_row_and_returns_issue(tmp_path):
    conn = db.get_connection(":memory:")
    result = _discovery_result([_job()], [_checkpoint(tmp_path)])

    with patch.object(run_ingest.tracker_common, "commit_checkpoint", side_effect=OSError("disk")):
        inserted, issues = run_ingest.persist_discovery(
            conn, result, stale_days=21, reopen_days=45, dry_run=False
        )

    assert inserted == {"tracker_vansh": 1}
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert issues[0].stage == "checkpoint"


def test_dry_run_never_commits_checkpoint(tmp_path):
    conn = db.get_connection(":memory:")
    result = _discovery_result([_job()], [_checkpoint(tmp_path)])

    with patch.object(run_ingest.tracker_common, "commit_checkpoint") as commit:
        run_ingest.persist_discovery(conn, result, stale_days=21, reopen_days=45, dry_run=True)

    commit.assert_not_called()


def test_all_selected_adapters_fail_returns_one_and_finishes_run_with_notes(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    issue = DiscoveryIssue("tracker_vansh", "fetch", "RuntimeError", "boom")

    with (
        patch.object(run_ingest, "load_sources_config", return_value={"tracker_vansh": {"enabled": True}}),
        patch.object(run_ingest, "discover_all", return_value=_discovery_result(issues=[issue], succeeded_sources=())),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
    ):
        code = run_ingest.main(["--db", db_path, "--discover-only"])

    conn = db.get_connection(db_path)
    run_row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    notes = json.loads(run_row["notes"])
    assert code == 1
    assert run_row["finished_at"] is not None
    assert notes["discovery_issues"] == [
        {"source": "tracker_vansh", "stage": "fetch", "error_type": "RuntimeError", "message": "boom"}
    ]


def test_partial_source_failure_returns_zero_and_keeps_issue_in_notes(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    issue = DiscoveryIssue("tracker_simplify", "fetch", "RuntimeError", "boom")

    with (
        patch.object(
            run_ingest,
            "load_sources_config",
            return_value={
                "tracker_vansh": {"enabled": True},
                "tracker_simplify": {"enabled": True},
            },
        ),
        patch.object(
            run_ingest,
            "discover_all",
            return_value=_discovery_result([_job()], succeeded_sources=("tracker_vansh",), issues=[issue]),
        ),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
    ):
        code = run_ingest.main(["--db", db_path, "--discover-only"])

    conn = db.get_connection(db_path)
    run_row = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    notes = json.loads(run_row["notes"])
    assert code == 0
    assert notes["discovery_issues"][0]["source"] == "tracker_simplify"


def test_resolve_only_does_not_return_one_when_no_discovery_sources_succeed(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    code = run_ingest.main(["--db", db_path, "--resolve-only"])
    assert code == 0


def test_snapshot_dir_reaches_each_selected_adapter_config(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    snapshot_dir = str(tmp_path / "snapshots")
    seen = {}

    def fake_discover_all(selected, **kwargs):
        seen.update(selected)
        return _discovery_result()

    with (
        patch.object(
            run_ingest,
            "load_sources_config",
            return_value={
                "tracker_vansh": {"enabled": True},
                "tracker_simplify": {"enabled": True},
            },
        ),
        patch.object(run_ingest, "discover_all", side_effect=fake_discover_all),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
    ):
        run_ingest.main(
            ["--db", db_path, "--discover-only", "--snapshot-dir", snapshot_dir]
        )

    assert seen["tracker_vansh"]["snapshot_dir"] == snapshot_dir
    assert seen["tracker_simplify"]["snapshot_dir"] == snapshot_dir


def test_zero_discovery_source_is_recorded_not_silently_absent(tmp_path):
    db_path = str(tmp_path / "jobs.db")
    jobs = [
        DiscoveredJob(
            "Acme", "SWE", "Remote", "https://boards.greenhouse.io/acme/jobs/1",
            "tracker_vansh", None,
        )
    ]
    with patch(
        "src.run_ingest.load_sources_config",
        return_value={
            "tracker_vansh": {"enabled": True},
            "tracker_simplify": {"enabled": True},
        },
    ):
        _run(db_path, jobs, digest_dir=str(tmp_path / "digests"), audit_dir=str(tmp_path / "audit"))

    conn = db.get_connection(db_path)
    run_id = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()["id"]
    rows = {row["source"]: dict(row) for row in db.run_sources_for_run(conn, run_id)}

    assert rows["tracker_vansh"]["discovered"] == 1
    assert rows["tracker_vansh"]["resolved"] == 1
    assert "tracker_simplify" in rows
    assert rows["tracker_simplify"]["discovered"] == 0
    assert rows["tracker_simplify"]["inserted"] == 0


def test_full_run_writes_audit_json(tmp_path):
    """docs/SELF_HEALING.md §1: the audit runs automatically at the end of
    every pipeline run and writes data/audit/YYYY-MM-DD.json. Uses a
    tmp_path-scoped --audit-dir so the test never touches the real
    data/audit/ directory."""
    from datetime import datetime, timezone

    db_path = str(tmp_path / "jobs.db")
    audit_dir = tmp_path / "audit"
    jobs = [
        DiscoveredJob(
            "Acme", "SWE", "Remote", "https://boards.greenhouse.io/acme/jobs/1",
            "tracker_vansh", None,
        )
    ]
    with patch(
        "src.run_ingest.load_sources_config",
        return_value={"tracker_vansh": {"enabled": True}},
    ):
        _run(
            db_path, jobs,
            digest_dir=str(tmp_path / "digests"),
            audit_dir=str(audit_dir),
        )

    today = datetime.now(timezone.utc).date().isoformat()
    audit_path = audit_dir / f"{today}.json"
    assert audit_path.exists()
    payload = json.loads(audit_path.read_text())
    assert set(payload.keys()) >= {"date", "overall", "findings"}
    assert payload["date"] == today
    assert payload["overall"] in {"PASS", "WARN", "FAIL"}
    assert isinstance(payload["findings"], list)
