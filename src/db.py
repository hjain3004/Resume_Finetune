"""SQLite schema, connection, and query helpers. Raw sqlite3 only — no SQL
strings anywhere else in the codebase."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.models import SOURCE_PRIORITY, DiscoveredJob, ResolvedJD, Status, clean_title, dedup_key

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
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    new_jobs       INTEGER DEFAULT 0,
    resolved       INTEGER DEFAULT 0,
    failed         INTEGER DEFAULT 0,
    filtered_out   INTEGER DEFAULT 0,
    tier1_resolved INTEGER NOT NULL DEFAULT 0,
    tier2_resolved INTEGER NOT NULL DEFAULT 0,
    manual_failed  INTEGER NOT NULL DEFAULT 0,
    notes          TEXT
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
    # M6.8: freshness/recycling defense.
    ("last_seen_at", "TEXT"),
    ("repost_count", "INTEGER NOT NULL DEFAULT 0"),
    # M7: I9 backfill-completeness tracking.
    ("resolved_logic_version", "INTEGER"),
)

# M6.5: per-run tier-2 (browser resolver) observability counters.
_RUNS_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("tier1_resolved", "INTEGER NOT NULL DEFAULT 0"),
    ("tier2_resolved", "INTEGER NOT NULL DEFAULT 0"),
    ("manual_failed", "INTEGER NOT NULL DEFAULT 0"),
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


def _migrate_runs_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
    for column, coltype in _RUNS_MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {coltype}")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    _migrate_jobs_columns(conn)
    _migrate_runs_columns(conn)
    conn.commit()


def _source_rank(source: str) -> int:
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


def insert_discovered(
    conn: sqlite3.Connection,
    discovered: list[DiscoveredJob],
    *,
    stale_days: int | None = None,
    reopen_days: int = 45,
) -> dict[str, int]:
    """Insert new jobs, deduping by dedup_key. Returns the count of genuinely
    new rows per source (for per-source observability).

    M6.8: new rows are flagged `stale_listing` if `date_posted` is older than
    `stale_days` (None disables the check). On a dedup-key conflict the
    posting is still being seen somewhere, so the existing row's
    `last_seen_at`/`repost_count` are always touched; additionally:
    - if a lower-priority source's row has no jd_text yet, its url/source are
      upgraded to the better source (pre-M6.8 behavior, unchanged);
    - if the existing row is RESOLVE_FAILED or CLOSED and hasn't been seen in
      `reopen_days`, it's reset to DISCOVERED with a `reopened` flag — it was
      either never actually evaluated, or died and is genuinely back. Other
      terminal statuses (FILTERED_OUT/REJECTED/APPLIED/SCORED/SHORTLISTED/...)
      stay untouched; recycled-content detection (against those) happens
      post-resolution in freshness.find_content_repost, not here."""
    new_count_by_source: dict[str, int] = defaultdict(int)
    now = _utcnow_iso()
    for job in discovered:
        key = dedup_key(job.company, job.title, job.location)
        existing = conn.execute(
            "SELECT id, source, jd_text, status, last_seen_at FROM jobs WHERE dedup_key = ?", (key,)
        ).fetchone()
        if existing is None:
            flags = None
            if (
                stale_days is not None
                and job.date_posted is not None
                and _is_older_than(job.date_posted, stale_days, now)
            ):
                flags = json.dumps(["stale_listing"])
            conn.execute(
                """
                INSERT INTO jobs (
                    dedup_key, company, title, location, url, source,
                    date_posted, discovered_at, status, flags, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    flags,
                    now,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                new_count_by_source[job.source] += 1
            continue

        prior_last_seen = existing["last_seen_at"]
        conn.execute(
            "UPDATE jobs SET last_seen_at = ?, repost_count = repost_count + 1 WHERE id = ?",
            (now, existing["id"]),
        )

        if existing["status"] in (Status.RESOLVE_FAILED, Status.CLOSED) and _is_older_than(
            prior_last_seen, reopen_days, now
        ):
            _reopen_row(conn, existing["id"], job.url, job.source, now)
        elif existing["jd_text"] is None and _source_rank(job.source) < _source_rank(existing["source"]):
            conn.execute(
                "UPDATE jobs SET url = ?, source = ? WHERE dedup_key = ?",
                (job.url, job.source, key),
            )
    conn.commit()
    return dict(new_count_by_source)


def _is_older_than(iso_ts: str | None, days: int, now_iso: str) -> bool:
    """True if `iso_ts` is missing (never confirmed) or older than `days`
    relative to `now_iso`. Both must be ISO-8601; date-only strings compare
    fine against full datetimes since they share the YYYY-MM-DD prefix."""
    if not iso_ts:
        return True
    then = datetime.fromisoformat(iso_ts)
    now = datetime.fromisoformat(now_iso)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (now - then).days >= days


def _reopen_row(conn: sqlite3.Connection, job_id: int, url: str, source: str, now: str) -> None:
    row = conn.execute("SELECT flags FROM jobs WHERE id = ?", (job_id,)).fetchone()
    flags = json.loads(row["flags"]) if row["flags"] else []
    if "reopened" not in flags:
        flags.append("reopened")
    conn.execute(
        """
        UPDATE jobs
        SET status = ?, resolve_attempts = 0, filter_reason = NULL,
            url = ?, source = ?, flags = ?
        WHERE id = ?
        """,
        (Status.DISCOVERED, url, source, json.dumps(sorted(flags)), job_id),
    )


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


def recent_run_sources_by_source(conn: sqlite3.Connection, source: str, limit: int) -> list[sqlite3.Row]:
    """Most-recent-first run_sources rows for one source, for I1's
    consecutive-zero-discoveries check."""
    return conn.execute(
        "SELECT * FROM run_sources WHERE source = ? ORDER BY run_id DESC LIMIT ?", (source, limit)
    ).fetchall()


def distinct_run_sources(conn: sqlite3.Connection) -> list[str]:
    return [row["source"] for row in conn.execute("SELECT DISTINCT source FROM run_sources ORDER BY source")]


def recent_runs(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


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
    tier1_resolved: int = 0,
    tier2_resolved: int = 0,
    manual_failed: int = 0,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE runs
        SET finished_at = ?, new_jobs = ?, resolved = ?, failed = ?,
            filtered_out = ?, tier1_resolved = ?, tier2_resolved = ?,
            manual_failed = ?, notes = ?
        WHERE id = ?
        """,
        (
            _utcnow_iso(), new_jobs, resolved, failed, filtered_out,
            tier1_resolved, tier2_resolved, manual_failed, notes, run_id,
        ),
    )
    conn.commit()


def rows_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs WHERE status = ?", (status,)).fetchall()


def get_by_url(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()


def all_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()


def reset_for_reresolution(conn: sqlite3.Connection, job_ids: list[int]) -> None:
    """M6.6 one-off: reset rows back to DISCOVERED so they're re-fetched and
    re-resolved through the current router, regardless of their prior status
    or resolve_attempts. Clears every field the resolve/prefilter steps set,
    since a re-resolve should re-derive them from scratch."""
    if not job_ids:
        return
    conn.executemany(
        """
        UPDATE jobs
        SET status = ?, jd_text = NULL, jd_resolved_at = NULL, resolver = NULL,
            resolve_attempts = 0, filter_reason = NULL, flags = NULL,
            ats_url = NULL, jd_quality = NULL, notes = NULL
        WHERE id = ?
        """,
        [(Status.DISCOVERED, job_id) for job_id in job_ids],
    )
    conn.commit()


def mark_resolved(
    conn: sqlite3.Connection, job_id: int, resolved: ResolvedJD, *, logic_version: int = 1
) -> None:
    """Set status=RESOLVED with the resolved JD text/resolver, and backfill
    title/location if they were still holding their inbox placeholder value
    (title == the URL's hostname, or location NULL).

    M6.8: merges (union) resolved.flags into whatever flags the row already
    carried, rather than overwriting — otherwise a discovery-time
    `stale_listing` or a resurfacing `reopened` flag is silently dropped the
    moment the row resolves (same class of bug as the M6.2 prefilter fix).

    M7 (I9): records `logic_version` (the resolver logic version active at
    resolve time — callers pass `resolve.LOGIC_VERSION`) and clears any
    `stale_logic_version` flag the audit previously set, since this resolve
    call is by definition re-deriving the row under the current version."""
    row = conn.execute("SELECT url, title, location, flags FROM jobs WHERE id = ?", (job_id,)).fetchone()
    title = row["title"]
    if resolved.raw_title and title == (urlparse(row["url"]).hostname or ""):
        title = clean_title(resolved.raw_title)
    location = row["location"]
    if resolved.raw_location and not location:
        location = resolved.raw_location
    existing_flags = json.loads(row["flags"]) if row["flags"] else []
    merged_flags = sorted((set(existing_flags) | set(resolved.flags or [])) - {"stale_logic_version"})

    conn.execute(
        """
        UPDATE jobs
        SET status = ?, jd_text = ?, jd_resolved_at = ?, resolver = ?,
            title = ?, location = ?, ats_url = ?, flags = ?, jd_quality = ?, notes = ?,
            resolved_logic_version = ?
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
            json.dumps(merged_flags) if merged_flags else None,
            resolved.jd_quality or "ats",
            resolved.notes,
            logic_version,
            job_id,
        ),
    )
    conn.commit()


def record_resolve_failure(conn: sqlite3.Connection, job_id: int, *, force_failed: bool = False) -> str:
    """Increment resolve_attempts; mark RESOLVE_FAILED once the limit is hit,
    or immediately when `force_failed` (M7 I2: a manual_domains hit skips the
    retry budget entirely — see resolve.is_manual_domain()). Returns the
    resulting status so callers can tally permanent failures."""
    row = conn.execute("SELECT resolve_attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
    attempts = row["resolve_attempts"] + 1
    status = Status.RESOLVE_FAILED if force_failed or attempts >= RESOLVE_FAILURE_LIMIT else Status.DISCOVERED
    conn.execute(
        "UPDATE jobs SET resolve_attempts = ?, status = ? WHERE id = ?",
        (attempts, status, job_id),
    )
    conn.commit()
    return status


def add_flag_and_note(conn: sqlite3.Connection, job_id: int, flag: str, note: str) -> None:
    """M6.8: union `flag` into the row's flags and append `note` to its notes
    (rather than overwrite — notes may already hold resolver-set text)."""
    row = conn.execute("SELECT flags, notes FROM jobs WHERE id = ?", (job_id,)).fetchone()
    flags = json.loads(row["flags"]) if row["flags"] else []
    if flag not in flags:
        flags.append(flag)
    notes = f"{row['notes']}; {note}" if row["notes"] else note
    conn.execute(
        "UPDATE jobs SET flags = ?, notes = ? WHERE id = ?",
        (json.dumps(sorted(flags)), notes, job_id),
    )
    conn.commit()


def mark_closed(conn: sqlite3.Connection, job_id: int, note: str) -> None:
    """M6.8 liveness recheck: the posting 404/410'd. Terminal; never tailor
    against a CLOSED row."""
    row = conn.execute("SELECT notes FROM jobs WHERE id = ?", (job_id,)).fetchone()
    notes = f"{row['notes']}; {note}" if row["notes"] else note
    conn.execute(
        "UPDATE jobs SET status = ?, notes = ? WHERE id = ?",
        (Status.CLOSED, notes, job_id),
    )
    conn.commit()


def touch_last_seen(conn: sqlite3.Connection, job_id: int) -> None:
    """M6.8 liveness recheck: the posting is still live — record that we just
    confirmed it, so the next recheck waits a fresh `liveness_days`."""
    conn.execute("UPDATE jobs SET last_seen_at = ? WHERE id = ?", (_utcnow_iso(), job_id))
    conn.commit()


def rows_needing_liveness_check(conn: sqlite3.Connection, cutoff_iso: str) -> list[sqlite3.Row]:
    """M6.8: SHORTLISTED/TAILORED rows never checked, or not checked since
    `cutoff_iso`."""
    return conn.execute(
        """
        SELECT * FROM jobs
        WHERE status IN (?, ?) AND (last_seen_at IS NULL OR last_seen_at < ?)
        ORDER BY id
        """,
        (Status.SHORTLISTED, Status.TAILORED, cutoff_iso),
    ).fetchall()
