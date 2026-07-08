"""CLI entry point for the job-pipeline ingestion run.

Wires discovery (trackers + manual inbox), resolution, pre-filter, and digest
generation end-to-end.
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter, defaultdict

import yaml

from src import db, digest, freshness, prefilter, resolve
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
    parser.add_argument(
        "--digest-dir", metavar="DIR", default="data/digests", help="directory to write the digest markdown to"
    )
    return parser


def load_sources_config(path: str = "config/sources.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)["sources"]


def load_filters_config(path: str = "config/filters.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_browser_resolver_flag(path: str = "config/sources.yaml") -> bool:
    """M6.5: top-level `browser_resolver` toggle, sibling to `sources:`.
    Defaults to False (pre-M6.5 behavior) when absent."""
    with open(path) as f:
        return bool(yaml.safe_load(f).get("browser_resolver", False))


def load_freshness_config(path: str = "config/freshness.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


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


def run_resolution(
    conn, session, *, browser_resolver: bool = False
) -> tuple[int, int, dict[str, dict[str, int]], dict[str, int]]:
    """Resolve all DISCOVERED rows. Returns (resolved_count, failed_count,
    per_source, tiers) where per_source maps source -> {"resolved": n, "failed": n}
    and tiers maps "tier1"/"tier2"/"manual" -> count (M6.5 per-tier observability:
    tier2 = resolved via resolve/browser.py, manual = reached RESOLVE_FAILED this run)."""
    resolved_count = 0
    failed_count = 0
    per_source: dict[str, dict[str, int]] = defaultdict(lambda: {"resolved": 0, "failed": 0})
    tiers = {"tier1": 0, "tier2": 0, "manual": 0}
    for row in db.rows_by_status(conn, Status.DISCOVERED):
        result = resolve.resolve(row["url"], session, browser_resolver=browser_resolver)
        source = row["source"]
        if result is not None:
            db.mark_resolved(conn, row["id"], result)
            prior_repost = freshness.find_content_repost(
                conn, row["company"], result.jd_text, exclude_row_id=row["id"]
            )
            if prior_repost is not None:
                freshness.record_content_repost(conn, row["id"], prior_repost)
            resolved_count += 1
            per_source[source]["resolved"] += 1
            tiers["tier2" if result.resolver == "browser" else "tier1"] += 1
        else:
            status = db.record_resolve_failure(conn, row["id"])
            failed_count += 1
            per_source[source]["failed"] += 1
            if status == Status.RESOLVE_FAILED:
                tiers["manual"] += 1
    return resolved_count, failed_count, dict(per_source), tiers


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
    freshness_cfg = load_freshness_config()

    new_count = 0
    if not args.resolve_only:
        discovered = discover_all(selected, limit=args.limit, dry_run=args.dry_run)
        inserted_by_source = db.insert_discovered(
            conn,
            discovered,
            stale_days=freshness_cfg["stale_days"],
            reopen_days=freshness_cfg["reopen_days"],
        )
        new_count = sum(inserted_by_source.values())
        print(f"Discovered {len(discovered)} job(s), {new_count} new, from {len(selected)} source(s).")
        for job in discovered:
            print(f"  - {job.company}: {job.title} [{job.source}]")

        discovered_by_source = Counter(job.source for job in discovered)
        for source in selected:
            db.record_run_source(
                conn,
                run_id,
                source,
                discovered=discovered_by_source.get(source, 0),
                inserted=inserted_by_source.get(source, 0),
            )

        if args.source is None or args.source == INBOX_SOURCE_NAME:
            inbox_result = inbox_manual.ingest(conn, {"dry_run": args.dry_run})
            inbox_new = inbox_result.new_urls + inbox_result.new_pastes
            new_count += inbox_new
            print(
                f"Inbox: {inbox_result.new_urls} URL(s), {inbox_result.new_pastes} paste(s) ingested."
            )
            db.record_run_source(
                conn, run_id, INBOX_SOURCE_NAME, discovered=inbox_new, inserted=inbox_new
            )

    resolved_count = 0
    failed_count = 0
    filtered_count = 0
    tiers = {"tier1": 0, "tier2": 0, "manual": 0}
    if not args.discover_only:
        session = PoliteSession()
        browser_resolver = load_browser_resolver_flag()
        resolved_count, failed_count, resolved_by_source, tiers = run_resolution(
            conn, session, browser_resolver=browser_resolver
        )
        print(f"Resolved {resolved_count} job(s), {failed_count} failed.")

        for source, counts in resolved_by_source.items():
            db.record_run_source(
                conn, run_id, source, resolved=counts["resolved"], failed=counts["failed"]
            )

        if not args.resolve_only:
            filters_cfg = load_filters_config()
            filtered_count = prefilter.run_prefilter(conn, filters_cfg)
            print(f"Filtered out {filtered_count} job(s).")

            closed_count = freshness.run_liveness_recheck(conn, session, freshness_cfg["liveness_days"])
            print(f"Liveness recheck: {closed_count} job(s) closed.")

    db.finish_run(
        conn,
        run_id,
        new_jobs=new_count,
        resolved=resolved_count,
        failed=failed_count,
        filtered_out=filtered_count,
        tier1_resolved=tiers["tier1"],
        tier2_resolved=tiers["tier2"],
        manual_failed=tiers["manual"],
    )

    if not args.discover_only and not args.resolve_only:
        run_row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if args.dry_run:
            print(digest.build_digest(conn, run_row))
        else:
            digest_path = digest.write_digest(conn, run_row, base_dir=args.digest_dir)
            print(f"Digest written to {digest_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
