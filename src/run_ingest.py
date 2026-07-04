"""CLI entry point for the job-pipeline ingestion run.

Discovery (this milestone) wires the tracker_vansh adapter end-to-end.
Resolution, pre-filter, and digest steps are implemented in later milestones.
"""

from __future__ import annotations

import argparse
import logging

import yaml

from src import db
from src.discover import tracker_vansh
from src.models import DiscoveredJob

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SOURCE_ADAPTERS = {
    "tracker_vansh": tracker_vansh,
}


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
        if source_name not in SOURCE_ADAPTERS or source_name not in sources_cfg:
            raise ValueError(f"unknown or unimplemented source: {source_name}")
        return {source_name: sources_cfg[source_name]}
    return {
        name: cfg
        for name, cfg in sources_cfg.items()
        if cfg.get("enabled") and name in SOURCE_ADAPTERS
    }


def run_discovery(
    sources_cfg: dict, *, limit: int | None = None, dry_run: bool = False
) -> list[DiscoveredJob]:
    all_jobs: list[DiscoveredJob] = []
    for name, cfg in sources_cfg.items():
        adapter = SOURCE_ADAPTERS[name]
        adapter_cfg = dict(cfg, dry_run=dry_run)
        try:
            jobs = adapter.discover(adapter_cfg)
        except Exception:
            logger.exception("discovery failed for source %s", name)
            continue
        if limit is not None:
            jobs = jobs[:limit]
        all_jobs.extend(jobs)
    return all_jobs


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

    discovered = run_discovery(selected, limit=args.limit, dry_run=args.dry_run)
    new_count = db.insert_discovered(conn, discovered)
    db.finish_run(conn, run_id, new_jobs=new_count)

    print(f"Discovered {len(discovered)} job(s), {new_count} new, from {len(selected)} source(s).")
    for job in discovered:
        print(f"  - {job.company}: {job.title} [{job.source}]")

    if not args.discover_only:
        logger.info("resolve/prefilter/digest steps are not implemented yet (later milestones)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
