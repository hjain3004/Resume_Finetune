"""Read-only source-yield and status-backlog baseline report."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src import db


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def build_baseline(conn, *, trailing_runs: int, generated_at: str | None = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    sources = []
    for row in db.source_yield_summary(conn, trailing_runs):
        discovered = int(row["discovered"] or 0)
        inserted = int(row["inserted"] or 0)
        resolved = int(row["resolved"] or 0)
        failed = int(row["failed"] or 0)
        sources.append(
            {
                "source": row["source"],
                "runs_observed": int(row["runs_observed"]),
                "discovered": discovered,
                "credited_unique_insertions": inserted,
                "credited_unique_rate": _rate(inserted, discovered),
                "resolved": resolved,
                "failed": failed,
                "resolution_rate": _rate(resolved, resolved + failed),
            }
        )
    total_fields = (
        "runs_observed",
        "discovered",
        "credited_unique_insertions",
        "resolved",
        "failed",
    )
    totals = {field: sum(row[field] for row in sources) for field in total_fields}
    status_backlog = {
        row["status"]: {
            "count": int(row["count"]),
            "oldest_discovered_at": row["oldest_discovered_at"],
        }
        for row in db.status_summary(conn)
    }
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "trailing_pipeline_runs": trailing_runs,
        "definitions": {
            "credited_unique_insertions": (
                "Rows credited to a source by current source-order attribution after "
                "deduplication; this is not causal or Shapley marginal contribution."
            ),
            "status_backlog": "Current jobs grouped by lifecycle status.",
        },
        "totals": totals,
        "sources": sources,
        "status_backlog": status_backlog,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.source_baseline",
        description="Write a read-only source-yield and backlog baseline report.",
    )
    parser.add_argument("--db", default="data/jobs.db", help="path to the SQLite database")
    parser.add_argument("--runs", type=int, default=30, help="number of finished runs to include")
    parser.add_argument(
        "--output",
        default="data/metrics/m9d-0-source-baseline.json",
        help="path for the output JSON report",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be >= 1")

    conn = db.get_readonly_connection(args.db)
    payload = build_baseline(conn, trailing_runs=args.runs)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
