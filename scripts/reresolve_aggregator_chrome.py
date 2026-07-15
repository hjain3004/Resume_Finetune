"""One-off (M6.6 punch-list item 2): re-resolve every row whose jd_text still
contains aggregator chrome (leftover from before src/resolve/jobright.py
existed), regardless of status or resolve_attempts.

Resets matching rows to DISCOVERED (clearing jd_text/resolver/flags/etc, per
db.reset_for_reresolution) and re-runs resolution, so they go through the
current router — jobright.com/jobright.ai URLs now hit src/resolve/jobright.py
instead of falling through to the generic resolver. Idempotent: rows that
resolve clean won't match these patterns again on a second run.

Usage: python -m scripts.reresolve_aggregator_chrome [--db PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import re

from src import db
from src.resolve.base import PoliteSession
from src.run_ingest import load_browser_resolver_flag, run_resolution

_CHROME_PATTERNS = (
    re.compile(r"h1b sponsor(?:ship)? likely", re.IGNORECASE),
    re.compile(r"^\s*trends of total sponsorships", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*funding\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*recent news", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*company data provided by", re.IGNORECASE | re.MULTILINE),
    re.compile(r"·\s*\d+\s*(?:minutes?|hours?|days?)\s+ago", re.IGNORECASE),
)


def matches_aggregator_chrome(jd_text: str | None) -> bool:
    if not jd_text:
        return False
    return any(pattern.search(jd_text) for pattern in _CHROME_PATTERNS)


def select_rows_to_reresolve(conn) -> list[int]:
    return [row["id"] for row in db.all_rows(conn) if matches_aggregator_chrome(row["jd_text"])]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.reresolve_aggregator_chrome",
        description="Reset and re-resolve every row whose jd_text still has aggregator chrome.",
    )
    parser.add_argument("--db", metavar="PATH", default="data/jobs.db", help="path to the SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="report matching rows without changing the DB")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = db.get_connection(args.db)

    job_ids = select_rows_to_reresolve(conn)
    print(f"{len(job_ids)} row(s) match aggregator-chrome patterns.")
    if args.dry_run or not job_ids:
        return 0

    db.reset_for_reresolution(conn, job_ids)
    session = PoliteSession()
    browser_resolver = load_browser_resolver_flag()
    summary = run_resolution(conn, session, browser_resolver=browser_resolver)
    print(f"Re-resolved {summary.resolved} job(s), {summary.content_failed} failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
