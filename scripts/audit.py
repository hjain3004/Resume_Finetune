"""M7 self-healing audit CLI (docs/SELF_HEALING.md §5).

Usage:
    python -m scripts.audit [--db PATH] [--out-dir DIR] [--repo-root DIR]
    python -m scripts.audit --db-before PATH --db-after PATH
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src import audit, db, resolve
from src.audit.invariants_db import diff_permitted_drift
from src.run_ingest import load_filters_config, load_freshness_config

_STATUS_ICON = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗", "SKIP": "–"}


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _rows_as_dicts(conn: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in db.all_rows(conn)]


def _load_audit_config(path: str = "config/audit.yaml") -> dict:
    import yaml

    with open(path) as f:
        return yaml.safe_load(f) or {}


def run_diff_mode(db_before: str, db_after: str) -> int:
    conn_before = sqlite3.connect(db_before)
    conn_before.row_factory = sqlite3.Row
    conn_after = sqlite3.connect(db_after)
    conn_after.row_factory = sqlite3.Row

    diffs = diff_permitted_drift(_rows_as_dicts(conn_before), _rows_as_dicts(conn_after))
    if diffs:
        print(f"I7 FAIL: {len(diffs)} row(s) diverged beyond permitted drift")
        for d in diffs:
            print(f"  - {d}")
        return 1
    print("I7 PASS: no unpermitted drift between the two DB snapshots")
    return 0


def run_audit(db_path: str, out_dir: str, repo_root: str) -> audit.AuditResult:
    conn = db.get_connection(db_path)
    audit_config = _load_audit_config()
    audit_config["current_logic_version"] = resolve.LOGIC_VERSION
    filters_config = load_filters_config()
    freshness_config = load_freshness_config()

    result = audit.run_all(
        conn,
        audit_config=audit_config,
        filters_config=filters_config,
        freshness_config=freshness_config,
        repo_root=Path(repo_root),
    )

    date_str = _today_iso()
    out_path = Path(out_dir) / f"{date_str}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(audit.to_json_dict(result, date_str=date_str), indent=2))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.audit",
        description="Evaluate the M7 self-healing invariant suite (docs/SELF_HEALING.md).",
    )
    parser.add_argument("--db", metavar="PATH", default="data/jobs.db")
    parser.add_argument("--out-dir", metavar="DIR", default="data/audit")
    parser.add_argument("--repo-root", metavar="DIR", default=".")
    parser.add_argument("--db-before", metavar="PATH")
    parser.add_argument("--db-after", metavar="PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.db_before or args.db_after:
        if not (args.db_before and args.db_after):
            print("--db-before and --db-after must be given together")
            return 1
        return run_diff_mode(args.db_before, args.db_after)

    result = run_audit(args.db, args.out_dir, args.repo_root)
    for finding in result.findings:
        icon = _STATUS_ICON[finding.status]
        print(f"{icon} {finding.invariant}: {finding.status} ({len(finding.evidence)} evidence row(s))")
    print(f"Overall: {result.overall}")
    return 1 if result.overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
