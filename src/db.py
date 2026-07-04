"""SQLite schema, connection, and query helpers. Raw sqlite3 only — no SQL
strings anywhere else in the codebase."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.models import SOURCE_PRIORITY, DiscoveredJob, Status, dedup_key

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
"""


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


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def _source_rank(source: str) -> int:
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


def insert_discovered(conn: sqlite3.Connection, discovered: list[DiscoveredJob]) -> int:
    """Insert new jobs, deduping by dedup_key. Returns the count of genuinely
    new rows. If a conflicting row already exists with a lower-priority source
    and no jd_text yet, its url/source are upgraded to the better source."""
    new_count = 0
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
                new_count += 1
            continue

        if existing["jd_text"] is None and _source_rank(job.source) < _source_rank(existing["source"]):
            conn.execute(
                "UPDATE jobs SET url = ?, source = ? WHERE dedup_key = ?",
                (job.url, job.source, key),
            )
    conn.commit()
    return new_count


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
