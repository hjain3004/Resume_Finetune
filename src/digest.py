"""Markdown digest generation per ARCHITECTURE §8."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src import db
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


def _needs_original_posting_table(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT company, title, url FROM jobs WHERE status = ? AND jd_quality = ? ORDER BY company",
        (Status.SHORTLISTED, "aggregator"),
    ).fetchall()
    if not rows:
        return ""
    lines = [
        "",
        "### Needs the original posting",
        "",
        "These shortlisted rows only have an aggregator's summary, not the employer's literal",
        "wording. Drop the real posting URL into `inbox/urls.txt` before tailoring.",
        "",
        "| Company | Title | Aggregator URL |",
        "|---|---|---|",
    ]
    lines.extend(f"| {row['company']} | {row['title']} | {row['url']} |" for row in rows)
    return "\n".join(lines)


def _recycled_table(conn: sqlite3.Connection) -> str:
    """M6.8: RESOLVED rows carrying `repost` (content-matched a prior
    terminal decision) or `reopened` (resurfaced after RESOLVE_FAILED/CLOSED)
    — the friendly "recycled: you skipped/applied..." message was composed
    at detection time and lives directly in `notes` (see freshness.py)."""
    rows = conn.execute(
        "SELECT company, title, flags, notes FROM jobs WHERE status = ? ORDER BY company",
        (Status.RESOLVED,),
    ).fetchall()
    recycled = [row for row in rows if row["flags"] and set(json.loads(row["flags"])) & {"repost", "reopened"}]
    if not recycled:
        return ""
    lines = [
        "",
        "## Recycled & reopened",
        "",
        "| Company | Title | Note |",
        "|---|---|---|",
    ]
    lines.extend(f"| {row['company']} | {row['title']} | {row['notes'] or ''} |" for row in recycled)
    return "\n".join(lines)


def _closed_table(conn: sqlite3.Connection) -> str:
    """M6.8: rows a liveness recheck confirmed dead (404/410). Terminal —
    never tailor against these."""
    rows = conn.execute(
        "SELECT company, title, notes FROM jobs WHERE status = ? ORDER BY company",
        (Status.CLOSED,),
    ).fetchall()
    if not rows:
        return ""
    lines = [
        "",
        "## Closed (dead links)",
        "",
        "| Company | Title | Note |",
        "|---|---|---|",
    ]
    lines.extend(f"| {row['company']} | {row['title']} | {row['notes'] or ''} |" for row in rows)
    return "\n".join(lines)


def _filtered_out_list(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT company, title, filter_reason FROM jobs WHERE status = ? ORDER BY company",
        (Status.FILTERED_OUT,),
    ).fetchall()
    return "\n".join(f"- {row['company']} — {row['title']} ({row['filter_reason']})" for row in rows)


def _per_source_table(conn: sqlite3.Connection, run_id: int) -> str:
    rows = db.run_sources_for_run(conn, run_id)
    lines = [
        "| Source | Discovered | Inserted | Resolved | Failed |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['source']} | {row['discovered']} | {row['inserted']} | "
            f"{row['resolved']} | {row['failed']} |"
        )
    if not rows:
        lines.append("| _(no sources ran this run)_ | | | | |")
    return "\n".join(lines)


def _audit_section(audit_result) -> str:
    if audit_result is None:
        return ""
    lines = [
        "",
        "## Audit",
        "",
        "| Invariant | Status | Evidence |",
        "|---|---|---|",
    ]
    for finding in audit_result.findings:
        lines.append(f"| {finding.invariant} | {finding.status} | {len(finding.evidence)} |")
    return "\n".join(lines)


_FAIL_BANNER = (
    "**⚠️ AUDIT FAILURES — see the Audit section below. The New & resolved section is "
    "suppressed until the FAIL is cleared (docs/SELF_HEALING.md §3).**"
)


def build_digest(
    conn: sqlite3.Connection, run_row: sqlite3.Row, *, date_str: str | None = None, audit_result=None
) -> str:
    date_str = date_str or _today_iso()
    needs_help = _needs_help_table(conn)
    needs_original = _needs_original_posting_table(conn)
    recycled = _recycled_table(conn)
    closed = _closed_table(conn)
    needs_section = needs_help + ("\n" + needs_original if needs_original else "")
    needs_section += ("\n" + recycled if recycled else "") + ("\n" + closed if closed else "")

    audit_failed = audit_result is not None and audit_result.overall == "FAIL"
    new_and_resolved_body = _FAIL_BANNER if audit_failed else _new_and_resolved_table(conn)

    return (
        f"# Job Digest — {date_str}\n"
        "\n"
        "## Run summary\n"
        f"- Discovered: {run_row['new_jobs']}\n"
        f"- Resolved: {run_row['resolved']}\n"
        f"- Failed: {run_row['failed']}\n"
        f"- Filtered out: {run_row['filtered_out']}\n"
        f"- Resolution tiers — t1: {run_row['tier1_resolved']}, t2: {run_row['tier2_resolved']}, "
        f"manual: {run_row['manual_failed']}\n"
        "\n"
        "### Per-source\n"
        f"{_per_source_table(conn, run_row['id'])}\n"
        "\n"
        "## New & resolved\n"
        f"{new_and_resolved_body}\n"
        "\n"
        "## Needs your help\n"
        f"{needs_section}\n"
        "\n"
        "## Filtered out\n"
        f"{_filtered_out_list(conn)}\n"
        f"{_audit_section(audit_result)}"
    )


def write_digest(
    conn: sqlite3.Connection,
    run_row: sqlite3.Row,
    *,
    base_dir: str | Path = "data/digests",
    date_str: str | None = None,
    audit_result=None,
) -> Path:
    date_str = date_str or _today_iso()
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{date_str}.md"
    path.write_text(build_digest(conn, run_row, date_str=date_str, audit_result=audit_result))
    return path
