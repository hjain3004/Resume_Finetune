"""M6.13R: find rows whose stored jd_text is a closed/expired-posting notice
(rather than real JD content) and move them to CLOSED, clearing their scoring
fields. Same dry-run/--apply/--confirm/--backup shape as
scripts/eligibility_impact.py.

Only the approved active statuses in `db.CONTENT_CLOSURE_SOURCE_STATUSES` may
be transitioned. Terminal states (FILTERED_OUT, REJECTED, APPLIED, CLOSED,
RESOLVE_FAILED) are never proposed and never overwritten; M6.13 did overwrite
35 FILTERED_OUT rows and that is what this version prevents.

Usage:
    python -m scripts.remediate_dead_postings --db PATH [--json OUT]
    python -m scripts.remediate_dead_postings --db PATH --apply --confirm APPLY --backup PATH
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src import db
from src.models import Status
from src.resolve.generic import dead_posting_evidence

REMEDIATION_NOTE = "M6.13R: content matched dead-posting notice"

_EVIDENCE_MAX_CHARS = 200


@dataclass(frozen=True)
class DeadPostingRow:
    """One proposed transition. `from_status` is the compare-and-set predicate
    the apply step guards on, so a stale preview cannot silently overwrite
    state that changed after the preview was taken."""

    job_id: int
    company: str
    title: str
    from_status: str
    jd_text_len: int
    evidence: str


def find_dead_postings(conn: sqlite3.Connection) -> tuple[DeadPostingRow, ...]:
    allowed = {str(s) for s in db.CONTENT_CLOSURE_SOURCE_STATUSES}
    rows = []
    for row in db.all_rows(conn):
        if row["status"] not in allowed:
            continue
        jd_text = row["jd_text"]
        if not jd_text:
            continue
        evidence = dead_posting_evidence(jd_text)
        if evidence is None:
            continue
        rows.append(
            DeadPostingRow(
                job_id=row["id"],
                company=row["company"],
                title=row["title"],
                from_status=row["status"],
                jd_text_len=len(jd_text),
                evidence=evidence[:_EVIDENCE_MAX_CHARS],
            )
        )
    return tuple(sorted(rows, key=lambda r: r.job_id))


def report_payload(rows: tuple[DeadPostingRow, ...]) -> dict:
    return {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": REMEDIATION_NOTE,
        "to_status": str(Status.CLOSED),
        "allowed_from_statuses": sorted(str(s) for s in db.CONTENT_CLOSURE_SOURCE_STATUSES),
        "count": len(rows),
        "counts_by_from_status": dict(sorted(Counter(r.from_status for r in rows).items())),
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
            changed = db.apply_dead_posting_closures(conn, rows, note=REMEDIATION_NOTE)
            print(json.dumps({"changed": changed, "previewed": len(rows)}, sort_keys=True))
            return 0

        conn = db.get_readonly_connection(args.db)
        payload = report_payload(find_dead_postings(conn))
        if args.json:
            path = Path(args.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(
            json.dumps(
                {
                    "count": payload["count"],
                    "counts_by_from_status": payload["counts_by_from_status"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, sqlite3.Error, db.StalePreviewError, ValueError) as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
