import json
import sqlite3

import pytest

from scripts import source_baseline
from src import db
from src.models import DiscoveredJob, Status


def _job(dedup_suffix, status):
    return DiscoveredJob(
        f"Company {dedup_suffix}",
        f"SWE {dedup_suffix}",
        "Remote",
        f"https://example.com/{dedup_suffix}",
        "tracker_vansh",
        None,
    ), status


def _insert_job(conn, dedup_suffix, status):
    job, wanted_status = _job(dedup_suffix, status)
    db.insert_discovered(conn, [job])
    conn.execute(
        "UPDATE jobs SET status = ? WHERE url = ?",
        (wanted_status, job.url),
    )
    conn.commit()


def _seed_baseline(conn):
    run1 = db.start_run(conn)
    db.record_run_source(
        conn,
        run1,
        "tracker_vansh",
        discovered=15,
        inserted=5,
        resolved=3,
        failed=2,
    )
    db.record_run_source(
        conn,
        run1,
        "tracker_simplify",
        discovered=8,
        inserted=2,
        resolved=2,
        failed=0,
    )
    db.finish_run(conn, run1)

    unfinished = db.start_run(conn)
    db.record_run_source(
        conn,
        unfinished,
        "tracker_vansh",
        discovered=100,
        inserted=100,
        resolved=100,
        failed=100,
    )

    _insert_job(conn, "discovered", Status.DISCOVERED)
    _insert_job(conn, "failed", Status.RESOLVE_FAILED)
    _insert_job(conn, "resolved", Status.RESOLVED)


def test_build_baseline_reports_source_yields_and_status_backlog():
    conn = db.get_connection(":memory:")
    _seed_baseline(conn)

    payload = source_baseline.build_baseline(
        conn, trailing_runs=30, generated_at="2026-07-14T00:00:00+00:00"
    )

    by_source = {row["source"]: row for row in payload["sources"]}
    assert by_source["tracker_vansh"]["credited_unique_rate"] == 5 / 15
    assert by_source["tracker_vansh"]["resolution_rate"] == 3 / 5
    assert by_source["tracker_simplify"]["credited_unique_rate"] == 2 / 8
    assert by_source["tracker_simplify"]["resolution_rate"] == 1.0
    assert payload["status_backlog"]["DISCOVERED"]["count"] == 1
    assert payload["status_backlog"]["RESOLVE_FAILED"]["count"] == 1
    assert payload["status_backlog"]["RESOLVED"]["count"] == 1
    assert "source-order attribution" in payload["definitions"]["credited_unique_insertions"]


def test_build_baseline_zero_denominators_return_none():
    conn = db.get_connection(":memory:")
    run_id = db.start_run(conn)
    db.record_run_source(conn, run_id, "tracker_vansh")
    db.finish_run(conn, run_id)

    payload = source_baseline.build_baseline(
        conn, trailing_runs=30, generated_at="2026-07-14T00:00:00+00:00"
    )

    source = payload["sources"][0]
    assert source["credited_unique_rate"] is None
    assert source["resolution_rate"] is None


def test_build_baseline_only_finished_trailing_runs_participate():
    conn = db.get_connection(":memory:")
    _seed_baseline(conn)
    latest = db.start_run(conn)
    db.record_run_source(conn, latest, "tracker_vansh", discovered=1, inserted=1)
    db.finish_run(conn, latest)

    payload = source_baseline.build_baseline(
        conn, trailing_runs=1, generated_at="2026-07-14T00:00:00+00:00"
    )

    assert payload["sources"] == [
        {
            "source": "tracker_vansh",
            "runs_observed": 1,
            "discovered": 1,
            "credited_unique_insertions": 1,
            "credited_unique_rate": 1.0,
            "resolved": 0,
            "failed": 0,
            "resolution_rate": None,
        }
    ]


def test_get_readonly_connection_uses_sqlite_mode_ro(monkeypatch, tmp_path):
    calls = []

    def fake_connect(database, *, uri=False):
        calls.append((database, uri))
        raise sqlite3.OperationalError("stop")

    monkeypatch.setattr(db.sqlite3, "connect", fake_connect)

    with pytest.raises(sqlite3.OperationalError, match="stop"):
        db.get_readonly_connection(tmp_path / "jobs.db")

    assert calls
    assert calls[0][1] is True
    assert calls[0][0].startswith("file:")
    assert calls[0][0].endswith("?mode=ro")


def test_cli_uses_readonly_connection_and_preserves_db_bytes(monkeypatch, tmp_path):
    db_path = tmp_path / "jobs.db"
    output_path = tmp_path / "baseline.json"
    conn = db.get_connection(db_path)
    _seed_baseline(conn)
    conn.close()
    before = db_path.read_bytes()
    opened = []
    real_get_readonly = db.get_readonly_connection

    def tracked_get_readonly(path):
        opened.append(path)
        return real_get_readonly(path)

    monkeypatch.setattr(source_baseline.db, "get_readonly_connection", tracked_get_readonly)

    assert (
        source_baseline.main(
            ["--db", str(db_path), "--runs", "30", "--output", str(output_path)]
        )
        == 0
    )

    assert opened == [str(db_path)]
    assert db_path.read_bytes() == before
    payload = json.loads(output_path.read_text())
    assert payload["schema_version"] == 1


def test_cli_rejects_non_positive_runs(tmp_path):
    with pytest.raises(SystemExit):
        source_baseline.main(["--runs", "0", "--output", str(tmp_path / "out.json")])
