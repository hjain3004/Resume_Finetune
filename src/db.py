"""SQLite schema, connection, and query helpers. Raw sqlite3 only — no SQL
strings anywhere else in the codebase."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.models import SOURCE_PRIORITY, DiscoveredJob, ResolvedJD, Status, dedup_key

RESOLVE_FAILURE_LIMIT = 3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key       TEXT UNIQUE NOT NULL,
    company         TEXT NOT NULL,
    title           TEXT NOT NULL,
    location        TEXT,
    url             TEXT NOT NULL,
    source          TEXT NOT NULL,
    date_posted     TEXT,
    discovered_at   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'DISCOVERED',
    jd_text         TEXT,
    jd_resolved_at  TEXT,
    resolver        TEXT,
    resolve_attempts INTEGER NOT NULL DEFAULT 0,
    filter_reason   TEXT,
    flags           TEXT,
    fit_score       REAL,
    fit_rationale   TEXT,
    base_variant    TEXT,
    missing_keywords TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    new_jobs     INTEGER DEFAULT 0,
    resolved     INTEGER DEFAULT 0,
    failed       INTEGER DEFAULT 0,
    filtered_out INTEGER DEFAULT 0,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS run_sources (
    run_id      INTEGER NOT NULL,
    source      TEXT NOT NULL,
    discovered  INTEGER NOT NULL DEFAULT 0,
    inserted    INTEGER NOT NULL DEFAULT 0,
    resolved    INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, source)
);
"""

# Columns added after the initial schema. Applied via idempotent ALTER TABLE so
# existing databases pick them up without data loss; new tables (run_sources)
# are already covered by CREATE TABLE IF NOT EXISTS above.
_JOBS_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("ats_url", "TEXT"),
    ("jd_quality", "TEXT"),
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _migrate_jobs_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    for column, coltype in _JOBS_MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {coltype}")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    _migrate_jobs_columns(conn)
    conn.commit()


def _source_rank(source: str) -> int:
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


def insert_discovered(conn: sqlite3.Connection, discovered: list[DiscoveredJob]) -> dict[str, int]:
    """Insert new jobs, deduping by dedup_key. Returns the count of genuinely
    new rows per source (for per-source observability). If a conflicting row
    already exists with a lower-priority source and no jd_text yet, its
    url/source are upgraded to the better source."""
    new_count_by_source: dict[str, int] = defaultdict(int)
    now = _utcnow_iso()
    for job in discovered:
        key = dedup_key(job.company, job.title, job.location)
        existing = conn.execute(
            "SELECT id, source, jd_text FROM jobs WHERE dedup_key = ?", (key,)
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO jobs (
                    dedup_key, company, title, location, url, source,
                    date_posted, discovered_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedup_key) DO NOTHING
                """,
                (
                    key,
                    job.company,
                    job.title,
                    job.location,
                    job.url,
                    job.source,
                    job.date_posted,
                    now,
                    Status.DISCOVERED,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                new_count_by_source[job.source] += 1
            continue

        if existing["jd_text"] is None and _source_rank(job.source) < _source_rank(existing["source"]):
            conn.execute(
                "UPDATE jobs SET url = ?, source = ? WHERE dedup_key = ?",
                (job.url, job.source, key),
            )
    conn.commit()
    return dict(new_count_by_source)


def record_run_source(
    conn: sqlite3.Connection,
    run_id: int,
    source: str,
    *,
    discovered: int = 0,
    inserted: int = 0,
    resolved: int = 0,
    failed: int = 0,
) -> None:
    """Upsert one source's counters for a run. Called once after discovery
    (discovered/inserted) and once after resolution (resolved/failed) per
    source, so a source contributing zero is a visible row, not a silent gap."""
    conn.execute(
        """
        INSERT INTO run_sources (run_id, source, discovered, inserted, resolved, failed)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, source) DO UPDATE SET
            discovered = discovered + excluded.discovered,
            inserted = inserted + excluded.inserted,
            resolved = resolved + excluded.resolved,
            failed = failed + excluded.failed
        """,
        (run_id, source, discovered, inserted, resolved, failed),
    )
    conn.commit()


def run_sources_for_run(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM run_sources WHERE run_id = ? ORDER BY source", (run_id,)
    ).fetchall()


def start_run(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "INSERT INTO runs (started_at) VALUES (?)", (_utcnow_iso(),)
    )
    conn.commit()
    return cursor.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    new_jobs: int = 0,
    resolved: int = 0,
    failed: int = 0,
    filtered_out: int = 0,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE runs
        SET finished_at = ?, new_jobs = ?, resolved = ?, failed = ?,
            filtered_out = ?, notes = ?
        WHERE id = ?
        """,
        (_utcnow_iso(), new_jobs, resolved, failed, filtered_out, notes, run_id),
    )
    conn.commit()


def rows_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs WHERE status = ?", (status,)).fetchall()


def get_by_url(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()


def mark_resolved(conn: sqlite3.Connection, job_id: int, resolved: ResolvedJD) -> None:
    """Set status=RESOLVED with the resolved JD text/resolver, and backfill
    title/location if they were still holding their inbox placeholder value
    (title == the URL's hostname, or location NULL)."""
    row = conn.execute("SELECT url, title, location FROM jobs WHERE id = ?", (job_id,)).fetchone()
    title = row["title"]
    if resolved.raw_title and title == (urlparse(row["url"]).hostname or ""):
        title = resolved.raw_title
    location = row["location"]
    if resolved.raw_location and not location:
        location = resolved.raw_location

    conn.execute(
        """
        UPDATE jobs
        SET status = ?, jd_text = ?, jd_resolved_at = ?, resolver = ?,
            title = ?, location = ?, ats_url = ?, flags = ?, jd_quality = ?, notes = ?
        WHERE id = ?
        """,
        (
            Status.RESOLVED,
            resolved.jd_text,
            _utcnow_iso(),
            resolved.resolver,
            title,
            location,
            resolved.ats_url,
            json.dumps(resolved.flags) if resolved.flags else None,
            resolved.jd_quality or "ats",
            resolved.notes,
            job_id,
        ),
    )
    conn.commit()


def record_resolve_failure(conn: sqlite3.Connection, job_id: int) -> None:
    """Increment resolve_attempts; mark RESOLVE_FAILED once the limit is hit."""
    row = conn.execute("SELECT resolve_attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
    attempts = row["resolve_attempts"] + 1
    status = Status.RESOLVE_FAILED if attempts >= RESOLVE_FAILURE_LIMIT else Status.DISCOVERED
    conn.execute(
        "UPDATE jobs SET resolve_attempts = ?, status = ? WHERE id = ?",
        (attempts, status, job_id),
    )
    conn.commit()
