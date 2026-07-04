"""CLI entry point for the job-pipeline ingestion run.

Wires discovery (trackers + manual inbox), resolution, and run accounting
end-to-end. Pre-filter and digest steps are implemented in a later milestone.
"""

from __future__ import annotations

import argparse
import logging

import yaml

from src import db, resolve
from src.discover import ADAPTERS, discover_all, inbox_manual
from src.models import Status
from src.resolve.base import PoliteSession

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

INBOX_SOURCE_NAME = inbox_manual.SOURCE_NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.run_ingest",
        description="Discover, resolve, and filter job postings.",
    )
    parser.add_argument("--dry-run", action="store_true", help="run without writing to the DB or snapshots")
    parser.add_argument("--source", metavar="NAME", help="restrict to a single discovery source")
    parser.add_argument("--resolve-only", action="store_true", help="only run the resolution step")
    parser.add_argument("--discover-only", action="store_true", help="only run the discovery step")
    parser.add_argument("--limit", type=int, metavar="N", help="cap new insertions per source")
    parser.add_argument("--db", metavar="PATH", default="data/jobs.db", help="path to the SQLite database")
    return parser


def load_sources_config(path: str = "config/sources.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)["sources"]


def _select_sources(sources_cfg: dict, source_name: str | None) -> dict:
    if source_name:
        if source_name == INBOX_SOURCE_NAME:
            return {}
        if source_name not in ADAPTERS or source_name not in sources_cfg:
            raise ValueError(f"unknown or unimplemented source: {source_name}")
        return {source_name: sources_cfg[source_name]}
    return {
        name: cfg for name, cfg in sources_cfg.items() if cfg.get("enabled") and name in ADAPTERS
    }


def run_resolution(conn, session) -> tuple[int, int]:
    """Resolve all DISCOVERED rows. Returns (resolved_count, failed_count)."""
    resolved_count = 0
    failed_count = 0
    for row in db.rows_by_status(conn, Status.DISCOVERED):
        result = resolve.resolve(row["url"], session)
        if result is not None:
            db.mark_resolved(conn, row["id"], result)
            resolved_count += 1
        else:
            db.record_resolve_failure(conn, row["id"])
            failed_count += 1
    return resolved_count, failed_count


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sources_cfg = load_sources_config()
    try:
        selected = _select_sources(sources_cfg, args.source)
    except ValueError as exc:
        logger.error(str(exc))
        return 1

    db_path = ":memory:" if args.dry_run else args.db
    conn = db.get_connection(db_path)
    run_id = db.start_run(conn)

    new_count = 0
    if not args.resolve_only:
        discovered = discover_all(selected, limit=args.limit, dry_run=args.dry_run)
        new_count = db.insert_discovered(conn, discovered)
        print(f"Discovered {len(discovered)} job(s), {new_count} new, from {len(selected)} source(s).")
        for job in discovered:
            print(f"  - {job.company}: {job.title} [{job.source}]")

        if args.source is None or args.source == INBOX_SOURCE_NAME:
            inbox_result = inbox_manual.ingest(conn, {"dry_run": args.dry_run})
            new_count += inbox_result.new_urls + inbox_result.new_pastes
            print(
                f"Inbox: {inbox_result.new_urls} URL(s), {inbox_result.new_pastes} paste(s) ingested."
            )

    resolved_count = 0
    failed_count = 0
    if not args.discover_only:
        session = PoliteSession()
        resolved_count, failed_count = run_resolution(conn, session)
        print(f"Resolved {resolved_count} job(s), {failed_count} failed.")
        logger.info("prefilter/digest steps are not implemented yet (later milestones)")

    db.finish_run(conn, run_id, new_jobs=new_count, resolved=resolved_count, failed=failed_count)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
