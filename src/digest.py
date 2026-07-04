"""Markdown digest generation per ARCHITECTURE §8."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.models import Status

_RESOLVE_FAILURE_LIMIT = 3


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _new_and_resolved_table(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT company, title, location, flags, source, url FROM jobs WHERE status = ? ORDER BY company",
        (Status.RESOLVED,),
    ).fetchall()
    lines = [
        "| Company | Title | Location | Flags | Source | Link |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        flags = ", ".join(json.loads(row["flags"])) if row["flags"] else ""
        lines.append(
            f"| {row['company']} | {row['title']} | {row['location'] or ''} | {flags} | "
            f"{row['source']} | [link]({row['url']}) |"
        )
    return "\n".join(lines)


def _needs_help_table(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        """
        SELECT company, title, url, status, resolve_attempts FROM jobs
        WHERE status = ? OR (status = ? AND resolve_attempts > 0)
        ORDER BY company
        """,
        (Status.RESOLVE_FAILED, Status.DISCOVERED),
    ).fetchall()
    lines = [
        "Paste the job description into `inbox/<name>.md` using the format in "
        "ARCHITECTURE.md §5.3 to resolve these manually.",
        "",
        "| Company | Title | URL | Status |",
        "|---|---|---|---|",
    ]
    for row in rows:
        attempts = row["resolve_attempts"]
        if row["status"] == Status.RESOLVE_FAILED:
            state = f"failed ({attempts}/{_RESOLVE_FAILURE_LIMIT} attempts)"
        else:
            state = f"retrying ({attempts}/{_RESOLVE_FAILURE_LIMIT} attempts)"
        lines.append(f"| {row['company']} | {row['title']} | {row['url']} | {state} |")
    return "\n".join(lines)


def _filtered_out_list(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT company, title, filter_reason FROM jobs WHERE status = ? ORDER BY company",
        (Status.FILTERED_OUT,),
    ).fetchall()
    return "\n".join(f"- {row['company']} — {row['title']} ({row['filter_reason']})" for row in rows)


def build_digest(conn: sqlite3.Connection, run_row: sqlite3.Row, *, date_str: str | None = None) -> str:
    date_str = date_str or _today_iso()
    return (
        f"# Job Digest — {date_str}\n"
        "\n"
        "## Run summary\n"
        f"- Discovered: {run_row['new_jobs']}\n"
        f"- Resolved: {run_row['resolved']}\n"
        f"- Failed: {run_row['failed']}\n"
        f"- Filtered out: {run_row['filtered_out']}\n"
        "\n"
        "## New & resolved\n"
        f"{_new_and_resolved_table(conn)}\n"
        "\n"
        "## Needs your help\n"
        f"{_needs_help_table(conn)}\n"
        "\n"
        "## Filtered out\n"
        f"{_filtered_out_list(conn)}\n"
    )


def write_digest(
    conn: sqlite3.Connection,
    run_row: sqlite3.Row,
    *,
    base_dir: str | Path = "data/digests",
    date_str: str | None = None,
) -> Path:
    date_str = date_str or _today_iso()
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{date_str}.md"
    path.write_text(build_digest(conn, run_row, date_str=date_str))
    return path
