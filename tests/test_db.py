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


def test_rows_by_status_returns_rows_ordered_by_id_regardless_of_insertion_order(conn):
    # M6.10: --resolve-limit must select a deterministic, repeatable subset.
    db.insert_discovered(
        conn,
        [
            _job(url="https://example.com/job/c", company="C Corp"),
            _job(url="https://example.com/job/a", company="A Corp"),
            _job(url="https://example.com/job/b", company="B Corp"),
        ],
    )
    rows = db.rows_by_status(conn, Status.DISCOVERED)
    ids = [row["id"] for row in rows]
    assert ids == sorted(ids)


def test_rows_by_status_limit_returns_exactly_n_lowest_id_rows(conn):
    db.insert_discovered(
        conn,
        [
            _job(url="https://example.com/job/1", company="A"),
            _job(url="https://example.com/job/2", company="B"),
            _job(url="https://example.com/job/3", company="C"),
        ],
    )
    all_rows = db.rows_by_status(conn, Status.DISCOVERED)
    assert len(all_rows) == 3

    limited = db.rows_by_status(conn, Status.DISCOVERED, limit=2)
    assert len(limited) == 2
    assert [row["id"] for row in limited] == sorted(row["id"] for row in all_rows)[:2]


def test_rows_by_status_limit_none_returns_all_rows(conn):
    db.insert_discovered(
        conn,
        [_job(url="https://example.com/job/1"), _job(url="https://example.com/job/2", company="B")],
    )
    rows = db.rows_by_status(conn, Status.DISCOVERED, limit=None)
    assert len(rows) == 2


def test_eligibility_rows_returns_status_rows_ordered_by_id(conn):
    db.insert_discovered(
        conn,
        [
            _job(url="https://example.com/c", company="C"),
            _job(url="https://example.com/a", company="A"),
            _job(url="https://example.com/b", company="B"),
        ],
    )

    rows = db.eligibility_rows(conn, Status.DISCOVERED)

    assert [row["id"] for row in rows] == sorted(row["id"] for row in rows)


def test_merge_job_flags_preserves_existing_sorts_and_is_idempotent(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute("UPDATE jobs SET flags = ? WHERE id = ?", (json.dumps(["z_existing"]), job_id))
    conn.commit()

    assert db.merge_job_flags(conn, job_id, ("country_unknown", "z_existing")) is True
    row = conn.execute("SELECT flags FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert json.loads(row["flags"]) == ["country_unknown", "z_existing"]
    assert db.merge_job_flags(conn, job_id, ("z_existing", "country_unknown")) is False


def test_mark_eligibility_filtered_compare_and_set_and_idempotent(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]

    assert db.mark_eligibility_filtered(
        conn, job_id, expected_status=Status.DISCOVERED, reason="eligibility:country"
    ) is True
    row = conn.execute("SELECT status, filter_reason FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.FILTERED_OUT
    assert row["filter_reason"] == "eligibility:country"
    assert db.mark_eligibility_filtered(
        conn, job_id, expected_status=Status.DISCOVERED, reason="eligibility:country"
    ) is False


def test_mark_eligibility_filtered_preserves_terminal_or_unexpected_status(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute("UPDATE jobs SET status = ?, filter_reason = ? WHERE id = ?", (Status.APPLIED, None, job_id))
    conn.commit()

    assert db.mark_eligibility_filtered(
        conn, job_id, expected_status=Status.DISCOVERED, reason="eligibility:country"
    ) is False
    row = conn.execute("SELECT status, filter_reason FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.APPLIED
    assert row["filter_reason"] is None


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


def test_mark_resolved_strips_boilerplate_from_backfilled_title(conn):
    # M6.9 item 2: live example, id 52 — resolver raw_title carried page
    # furniture ("Job Details" + requisition id) into the backfilled title.
    db.insert_discovered(
        conn,
        [_job(source="inbox", company="unknown", title="example.com", location=None)],
    )
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    resolved = ResolvedJD(
        jd_text="full jd text",
        resolver="generic",
        raw_title="Front End Developer (Hybrid) - 28751 Job Details",
    )

    db.mark_resolved(conn, job_id, resolved)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["title"] == "Front End Developer (Hybrid)"


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


# --- M6.8 freshness & recycling defense --------------------------------------


def test_insert_discovered_flags_stale_listing_when_date_posted_old(conn):
    old_job = _job(date_posted="2026-01-01")
    db.insert_discovered(conn, [old_job], stale_days=21)

    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert json.loads(row["flags"]) == ["stale_listing"]


def test_insert_discovered_does_not_flag_recent_posting(conn):
    recent_job = _job(date_posted="2026-07-01")
    db.insert_discovered(conn, [recent_job], stale_days=21)

    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["flags"] is None


def test_insert_discovered_does_not_flag_when_date_posted_missing(conn):
    job = _job(date_posted=None)
    db.insert_discovered(conn, [job], stale_days=21)

    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["flags"] is None


def test_insert_discovered_stale_check_disabled_when_stale_days_none(conn):
    old_job = _job(date_posted="2020-01-01")
    db.insert_discovered(conn, [old_job], stale_days=None)

    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["flags"] is None


def test_insert_discovered_sets_last_seen_at_on_first_insert(conn):
    db.insert_discovered(conn, [_job()])
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["last_seen_at"] is not None
    assert row["repost_count"] == 0


def test_insert_discovered_bumps_last_seen_and_repost_count_on_conflict(conn):
    db.insert_discovered(conn, [_job()])
    row = conn.execute("SELECT * FROM jobs").fetchone()
    first_seen = row["last_seen_at"]

    db.insert_discovered(conn, [_job()])
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["repost_count"] == 1
    assert row["last_seen_at"] >= first_seen


def test_insert_discovered_reopens_stale_resolve_failed_row(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute(
        "UPDATE jobs SET status = ?, resolve_attempts = 3, last_seen_at = ? WHERE id = ?",
        (Status.RESOLVE_FAILED, "2026-01-01T00:00:00+00:00", job_id),
    )
    conn.commit()

    db.insert_discovered(conn, [_job(url="https://example.com/job/1-refreshed")], reopen_days=45)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.DISCOVERED
    assert row["resolve_attempts"] == 0
    assert json.loads(row["flags"]) == ["reopened"]
    assert row["url"] == "https://example.com/job/1-refreshed"


def test_insert_discovered_reopens_stale_closed_row(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute(
        "UPDATE jobs SET status = ?, last_seen_at = ? WHERE id = ?",
        (Status.CLOSED, "2026-01-01T00:00:00+00:00", job_id),
    )
    conn.commit()

    db.insert_discovered(conn, [_job()], reopen_days=45)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.DISCOVERED
    assert json.loads(row["flags"]) == ["reopened"]


def test_insert_discovered_does_not_reopen_recently_seen_resolve_failed_row(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute(
        "UPDATE jobs SET status = ?, resolve_attempts = 3, last_seen_at = ? WHERE id = ?",
        (Status.RESOLVE_FAILED, db._utcnow_iso(), job_id),
    )
    conn.commit()

    db.insert_discovered(conn, [_job()], reopen_days=45)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.RESOLVE_FAILED


def test_insert_discovered_does_not_reopen_resolve_failed_row_with_null_last_seen_at(conn):
    # Regression for the bug found 2026-07-15: rows inserted before last_seen_at
    # existed (pre-M6.8) have last_seen_at = NULL. _is_older_than() treated that
    # as "definitely old enough", reopening on the very first re-sighting instead
    # of after reopen_days. This is exactly what happened to 21 real tracker_vansh
    # rows on 2026-07-12.
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute(
        "UPDATE jobs SET status = ?, resolve_attempts = 3, last_seen_at = NULL WHERE id = ?",
        (Status.RESOLVE_FAILED, job_id),
    )
    conn.commit()

    db.insert_discovered(conn, [_job()], reopen_days=45)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.RESOLVE_FAILED
    assert row["last_seen_at"] is not None  # backfilled for next time


def test_insert_discovered_does_not_reopen_other_terminal_statuses(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute(
        "UPDATE jobs SET status = ?, last_seen_at = ? WHERE id = ?",
        (Status.FILTERED_OUT, "2026-01-01T00:00:00+00:00", job_id),
    )
    conn.commit()

    db.insert_discovered(conn, [_job()], reopen_days=45)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.FILTERED_OUT


def test_mark_resolved_merges_flags_instead_of_overwriting(conn):
    db.insert_discovered(conn, [_job(date_posted="2026-01-01")], stale_days=21)
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    assert json.loads(conn.execute("SELECT flags FROM jobs WHERE id = ?", (job_id,)).fetchone()["flags"]) == [
        "stale_listing"
    ]

    db.mark_resolved(conn, job_id, ResolvedJD(jd_text="jd", resolver="greenhouse", flags=["sponsor_likely"]))

    row = conn.execute("SELECT flags FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert set(json.loads(row["flags"])) == {"stale_listing", "sponsor_likely"}


def test_add_flag_and_note_unions_flag_and_appends_note(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute("UPDATE jobs SET notes = ? WHERE id = ?", ("existing note", job_id))
    conn.commit()

    db.add_flag_and_note(conn, job_id, "repost", "recycled: you skipped job #7 on 2026-06-01")

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert json.loads(row["flags"]) == ["repost"]
    assert row["notes"] == "existing note; recycled: you skipped job #7 on 2026-06-01"


def test_mark_closed_sets_status_and_appends_note(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]

    db.mark_closed(conn, job_id, "liveness recheck: 404")

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.CLOSED
    assert row["notes"] == "liveness recheck: 404"


def test_touch_last_seen_updates_timestamp(conn):
    db.insert_discovered(conn, [_job()])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute("UPDATE jobs SET last_seen_at = NULL WHERE id = ?", (job_id,))
    conn.commit()

    db.touch_last_seen(conn, job_id)

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["last_seen_at"] is not None


def test_rows_needing_liveness_check_only_shortlisted_and_tailored_and_stale(conn):
    db.insert_discovered(conn, [_job(url="https://example.com/1")])
    db.insert_discovered(conn, [_job(url="https://example.com/2", title="Other")])
    db.insert_discovered(conn, [_job(url="https://example.com/3", title="Third")])
    ids = [r["id"] for r in conn.execute("SELECT id FROM jobs ORDER BY id").fetchall()]

    conn.execute(
        "UPDATE jobs SET status = ?, last_seen_at = ? WHERE id = ?",
        (Status.SHORTLISTED, "2026-01-01T00:00:00+00:00", ids[0]),
    )
    conn.execute(
        "UPDATE jobs SET status = ?, last_seen_at = ? WHERE id = ?",
        (Status.TAILORED, db._utcnow_iso(), ids[1]),
    )
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (Status.RESOLVED, ids[2]))
    conn.commit()

    rows = db.rows_needing_liveness_check(conn, "2026-06-01T00:00:00+00:00")

    assert [r["id"] for r in rows] == [ids[0]]


def test_mark_resolved_writes_logic_version(conn):
    job = _job()
    db.insert_discovered(conn, [job])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    resolved = ResolvedJD(jd_text="jd text", resolver="greenhouse")

    db.mark_resolved(conn, job_id, resolved, logic_version=3)

    row = conn.execute("SELECT resolved_logic_version FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["resolved_logic_version"] == 3


def test_mark_resolved_defaults_logic_version_to_one(conn):
    job = _job()
    db.insert_discovered(conn, [job])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]

    db.mark_resolved(conn, job_id, ResolvedJD(jd_text="jd text", resolver="greenhouse"))

    row = conn.execute("SELECT resolved_logic_version FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["resolved_logic_version"] == 1


def test_mark_resolved_clears_stale_logic_version_flag(conn):
    job = _job()
    db.insert_discovered(conn, [job])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]
    conn.execute(
        "UPDATE jobs SET flags = ? WHERE id = ?", (json.dumps(["stale_logic_version", "reopened"]), job_id)
    )
    conn.commit()

    db.mark_resolved(conn, job_id, ResolvedJD(jd_text="jd text", resolver="greenhouse"), logic_version=2)

    row = conn.execute("SELECT flags FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert json.loads(row["flags"]) == ["reopened"]


def test_record_resolve_failure_force_failed_sets_resolve_failed_immediately(conn):
    job = _job()
    db.insert_discovered(conn, [job])
    job_id = conn.execute("SELECT id FROM jobs").fetchone()["id"]

    status = db.record_resolve_failure(conn, job_id, force_failed=True)

    assert status == Status.RESOLVE_FAILED
    row = conn.execute("SELECT status, resolve_attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == Status.RESOLVE_FAILED
    assert row["resolve_attempts"] == 1
