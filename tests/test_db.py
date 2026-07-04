import sqlite3

import pytest

from src import db
from src.models import DiscoveredJob, Status


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    db.init_db(connection)
    return connection


def _job(**overrides) -> DiscoveredJob:
    defaults = dict(
        company="Acme",
        title="Software Engineer",
        location="Remote",
        url="https://example.com/job/1",
        source="tracker_vansh",
        date_posted=None,
    )
    defaults.update(overrides)
    return DiscoveredJob(**defaults)


def test_insert_discovered_inserts_new_rows(conn):
    jobs = [_job(), _job(company="Other Co", title="Backend Engineer")]
    count = db.insert_discovered(conn, jobs)
    assert count == 2
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 2
    assert rows[0]["status"] == Status.DISCOVERED


def test_insert_discovered_twice_is_idempotent(conn):
    jobs = [_job()]
    first = db.insert_discovered(conn, jobs)
    second = db.insert_discovered(conn, jobs)
    assert first == 1
    assert second == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_insert_discovered_upgrades_source_by_priority(conn):
    low_priority = _job(source="tracker_jobright", url="https://jobright.example/1")
    db.insert_discovered(conn, [low_priority])

    high_priority = _job(source="tracker_simplify", url="https://simplify.example/1")
    count = db.insert_discovered(conn, [high_priority])

    assert count == 0
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["source"] == "tracker_simplify"
    assert row["url"] == "https://simplify.example/1"


def test_insert_discovered_does_not_downgrade_source(conn):
    high_priority = _job(source="tracker_simplify", url="https://simplify.example/1")
    db.insert_discovered(conn, [high_priority])

    low_priority = _job(source="tracker_jobright", url="https://jobright.example/1")
    db.insert_discovered(conn, [low_priority])

    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["source"] == "tracker_simplify"


def test_start_and_finish_run(conn):
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_jobs=3, resolved=1)
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["new_jobs"] == 3
    assert row["resolved"] == 1
    assert row["finished_at"] is not None


def test_rows_by_status_and_get_by_url(conn):
    db.insert_discovered(conn, [_job(url="https://example.com/job/42")])
    rows = db.rows_by_status(conn, Status.DISCOVERED)
    assert len(rows) == 1
    fetched = db.get_by_url(conn, "https://example.com/job/42")
    assert fetched is not None
    assert fetched["company"] == "Acme"
