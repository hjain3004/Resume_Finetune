"""M6.13 one-off: find rows whose stored jd_text is a closed/expired-posting
notice (rather than real JD content) and move them to CLOSED, clearing their
scoring fields. Same dry-run/--apply/--backup shape as scripts/eligibility_impact.py.

Usage:
    python -m scripts.remediate_dead_postings --db PATH [--json OUT]
    python -m scripts.remediate_dead_postings --db PATH --apply --confirm APPLY --backup PATH
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src import db
from src.models import Status
from src.resolve.generic import is_dead_posting_text

_EXCLUDED_STATUSES = {Status.RESOLVE_FAILED, Status.REJECTED, Status.CLOSED}


@dataclass(frozen=True)
class DeadPostingRow:
    job_id: int
    company: str
    title: str
    from_status: str
    jd_text_len: int


def find_dead_postings(conn: sqlite3.Connection) -> tuple[DeadPostingRow, ...]:
    rows = []
    for row in db.all_rows(conn):
        if row["status"] in _EXCLUDED_STATUSES:
            continue
        jd_text = row["jd_text"]
        if not jd_text or not is_dead_posting_text(jd_text):
            continue
        rows.append(
            DeadPostingRow(
                job_id=row["id"],
                company=row["company"],
                title=row["title"],
                from_status=row["status"],
                jd_text_len=len(jd_text),
            )
        )
    return tuple(sorted(rows, key=lambda r: r.job_id))


def report_payload(rows: tuple[DeadPostingRow, ...]) -> dict:
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "rows": [asdict(r) for r in rows],
    }


def _backup_database(conn: sqlite3.Connection, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(str(backup_path))
    try:
        conn.backup(dest)
    finally:
        dest.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--backup")
    args = parser.parse_args(argv)

    try:
        if args.apply:
            if args.confirm != "APPLY" or not args.backup:
                return 2
            backup_path = Path(args.backup)
            if backup_path.exists():
                return 2
            conn = db.get_connection(args.db)
            rows = find_dead_postings(conn)
            _backup_database(conn, backup_path)
            for row in rows:
                db.mark_dead_posting(
                    conn, row.job_id, "M6.13: content matched dead-posting phrase list"
                )
            print(json.dumps({"changed": len(rows)}, sort_keys=True))
            return 0

        conn = db.get_readonly_connection(args.db)
        rows = find_dead_postings(conn)
        payload = report_payload(rows)
        if args.json:
            path = Path(args.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"count": payload["count"]}, sort_keys=True))
        return 0
    except (OSError, sqlite3.Error) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
