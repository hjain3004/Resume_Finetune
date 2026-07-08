import json
import sqlite3

import pytest

from src import db
from src.models import DiscoveredJob, ResolvedJD, Status


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
    by_source = db.insert_discovered(conn, jobs)
    assert sum(by_source.values()) == 2
    assert by_source == {"tracker_vansh": 2}
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 2
    assert rows[0]["status"] == Status.DISCOVERED


def test_insert_discovered_twice_is_idempotent(conn):
    jobs = [_job()]
    first = db.insert_discovered(conn, jobs)
    second = db.insert_discovered(conn, jobs)
    assert sum(first.values()) == 1
    assert sum(second.values()) == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_insert_discovered_upgrades_source_by_priority(conn):
    low_priority = _job(source="tracker_jobright", url="https://jobright.example/1")
    db.insert_discovered(conn, [low_priority])

    high_priority = _job(source="tracker_simplify", url="https://simplify.example/1")
    by_source = db.insert_discovered(conn, [high_priority])

    assert sum(by_source.values()) == 0
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


def test_finish_run_defaults_tier_counts_to_zero(conn):
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, new_jobs=3, resolved=1)
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["tier1_resolved"] == 0
    assert row["tier2_resolved"] == 0
    assert row["manual_failed"] == 0


def test_finish_run_records_tier_counts(conn):
    run_id = db.start_run(conn)
    db.finish_run(conn, run_id, tier1_resolved=4, tier2_resolved=2, manual_failed=1)
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["tier1_resolved"] == 4
    assert row["tier2_resolved"] == 2
    assert row["manual_failed"] == 1


def test_rows_by_status_and_get_by_url(conn):
    db.insert_discovered(conn, [_job(url="https://example.com/job/42")])
    rows = db.rows_by_status(conn, Status.DISCOVERED)
    assert len(rows) == 1
    fetched = db.get_by_url(conn, "https://example.com/job/42")
    assert fetched is not None
    assert fetched["company"] == "Acme"


def test_mark_resolved_sets_status_and_jd_fields(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    resolved = ResolvedJD(jd_text="full jd text", resolver="greenhouse")

    db.mark_resolved(conn, job_id, resolved)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.RESOLVED
    assert row["jd_text"] == "full jd text"
    assert row["resolver"] == "greenhouse"
    assert row["jd_resolved_at"] is not None


def test_mark_resolved_backfills_placeholder_title_and_location_for_inbox(conn):
    db.insert_discovered(
        conn,
        [_job(source="inbox", company="unknown", title="example.com", location=None)],
    )
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    resolved = ResolvedJD(
        jd_text="full jd text",
        resolver="greenhouse",
        raw_title="Software Engineer",
        raw_location="Remote",
    )

    db.mark_resolved(conn, job_id, resolved)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["title"] == "Software Engineer"
    assert row["location"] == "Remote"


def test_mark_resolved_does_not_overwrite_non_placeholder_fields(conn):
    db.insert_discovered(
        conn,
        [_job(source="inbox", company="unknown", title="Real Title", location="Real Loc")],
    )
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    resolved = ResolvedJD(
        jd_text="full jd text",
        resolver="greenhouse",
        raw_title="Other Title",
        raw_location="Other Loc",
    )

    db.mark_resolved(conn, job_id, resolved)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["title"] == "Real Title"
    assert row["location"] == "Real Loc"


def test_record_resolve_failure_increments_attempts_and_stays_discovered(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]

    status = db.record_resolve_failure(conn, job_id)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["resolve_attempts"] == 1
    assert row["status"] == Status.DISCOVERED
    assert status == Status.DISCOVERED


def test_record_resolve_failure_sets_resolve_failed_at_three_attempts(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]

    db.record_resolve_failure(conn, job_id)
    db.record_resolve_failure(conn, job_id)
    status = db.record_resolve_failure(conn, job_id)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["resolve_attempts"] == 3
    assert status == Status.RESOLVE_FAILED
    assert row["status"] == Status.RESOLVE_FAILED


def test_mark_resolved_persists_ats_url(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    resolved = ResolvedJD(
        jd_text="full jd text",
        resolver="greenhouse",
        ats_url="https://boards.greenhouse.io/amperity/jobs/8040043",
    )

    db.mark_resolved(conn, job_id, resolved)

    row = conn.execute("SELECT ats_url FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["ats_url"] == "https://boards.greenhouse.io/amperity/jobs/8040043"


def test_init_db_migration_adds_ats_url_to_pre_existing_db(tmp_path):
    path = tmp_path / "old.db"
    legacy = sqlite3.connect(str(path))
    legacy.executescript(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dedup_key TEXT UNIQUE NOT NULL,
            company TEXT NOT NULL,
            title TEXT NOT NULL,
            location TEXT,
            url TEXT NOT NULL,
            source TEXT NOT NULL,
            date_posted TEXT,
            discovered_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DISCOVERED',
            jd_text TEXT,
            jd_resolved_at TEXT,
            resolver TEXT,
            resolve_attempts INTEGER NOT NULL DEFAULT 0,
            filter_reason TEXT,
            flags TEXT,
            fit_score REAL,
            fit_rationale TEXT,
            base_variant TEXT,
            missing_keywords TEXT,
            notes TEXT
        );
        """
    )
    legacy.execute(
        "INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at) "
        "VALUES ('k', 'Acme', 'SWE', 'https://x/1', 'tracker_vansh', '2026-01-01')"
    )
    legacy.commit()
    legacy.close()

    migrated = sqlite3.connect(str(path))
    migrated.row_factory = sqlite3.Row
    db.init_db(migrated)

    row = migrated.execute("SELECT * FROM jobs").fetchone()
    assert row["ats_url"] is None
    assert row["company"] == "Acme"


def test_mark_resolved_persists_flags_and_jd_quality(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    resolved = ResolvedJD(
        jd_text="full jd text",
        resolver="jobright",
        jd_quality="aggregator",
        flags=["sponsor_likely"],
        notes="jobright aggregator: https://jobright.ai/jobs/info/1",
    )

    db.mark_resolved(conn, job_id, resolved)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["jd_quality"] == "aggregator"
    assert json.loads(row["flags"]) == ["sponsor_likely"]
    assert row["notes"] == "jobright aggregator: https://jobright.ai/jobs/info/1"


def test_mark_resolved_defaults_jd_quality_to_ats_when_unset(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    resolved = ResolvedJD(jd_text="full jd text", resolver="greenhouse")

    db.mark_resolved(conn, job_id, resolved)

    row = conn.execute("SELECT jd_quality, flags FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["jd_quality"] == "ats"
    assert row["flags"] is None


def test_init_db_migration_adds_jd_quality_to_pre_existing_db(tmp_path):
    path = tmp_path / "old.db"
    legacy = sqlite3.connect(str(path))
    legacy.executescript(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dedup_key TEXT UNIQUE NOT NULL,
            company TEXT NOT NULL,
            title TEXT NOT NULL,
            location TEXT,
            url TEXT NOT NULL,
            source TEXT NOT NULL,
            date_posted TEXT,
            discovered_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'DISCOVERED',
            jd_text TEXT,
            jd_resolved_at TEXT,
            resolver TEXT,
            resolve_attempts INTEGER NOT NULL DEFAULT 0,
            filter_reason TEXT,
            flags TEXT,
            fit_score REAL,
            fit_rationale TEXT,
            base_variant TEXT,
            missing_keywords TEXT,
            notes TEXT,
            ats_url TEXT
        );
        """
    )
    legacy.execute(
        "INSERT INTO jobs (dedup_key, company, title, url, source, discovered_at) "
        "VALUES ('k', 'Acme', 'SWE', 'https://x/1', 'tracker_vansh', '2026-01-01')"
    )
    legacy.commit()
    legacy.close()

    migrated = sqlite3.connect(str(path))
    migrated.row_factory = sqlite3.Row
    db.init_db(migrated)

    row = migrated.execute("SELECT * FROM jobs").fetchone()
    assert row["jd_quality"] is None

    # Second init on an already-migrated DB must not error or duplicate the column.
    db.init_db(migrated)


def test_record_run_source_upserts_and_accumulates(conn):
    run_id = db.start_run(conn)
    db.record_run_source(conn, run_id, "tracker_vansh", discovered=5, inserted=3)
    db.record_run_source(conn, run_id, "tracker_vansh", resolved=2, failed=1)

    rows = db.run_sources_for_run(conn, run_id)
    assert len(rows) == 1
    assert rows[0]["discovered"] == 5
    assert rows[0]["inserted"] == 3
    assert rows[0]["resolved"] == 2
    assert rows[0]["failed"] == 1


def test_run_sources_for_run_lists_all_sources_including_zero(conn):
    run_id = db.start_run(conn)
    db.record_run_source(conn, run_id, "tracker_simplify", discovered=0, inserted=0)
    db.record_run_source(conn, run_id, "tracker_vansh", discovered=4, inserted=4)

    rows = db.run_sources_for_run(conn, run_id)
    sources = {row["source"]: row["discovered"] for row in rows}
    assert sources == {"tracker_simplify": 0, "tracker_vansh": 4}
