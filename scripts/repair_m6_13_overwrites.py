"""M6.13R: undo the terminal-state overwrites the M6.13 remediation applied.

M6.13 moved every content-matched row to CLOSED, including 35 rows that were
already FILTERED_OUT — a terminal eligibility decision it had no business
replacing. This tool diffs the live DB against the pre-remediation backup and
proposes restoring exactly those rows.

It is deliberately narrow. A row is only proposed when all of the following
hold, so nothing that changed for any other reason can be caught up in it:

  - the backup row is FILTERED_OUT and the live row is CLOSED;
  - the live notes are the backup notes with the M6.13 note appended.

`filter_reason` and the scoring columns are never written: M6.13 did not
change them, and reconstructing values that were legitimately absent would be
fabrication rather than repair.

Usage:
    python -m scripts.repair_m6_13_overwrites --db PATH --from-backup PATH [--json OUT]
    python -m scripts.repair_m6_13_overwrites --db PATH --from-backup PATH \
        --apply --confirm APPLY --backup PATH
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

# The note M6.13 appended. Distinct from M6.13R's REMEDIATION_NOTE.
LEGACY_NOTE = "M6.13: content matched dead-posting phrase list"

# Only this overwrite is authorized for repair. RESOLVED/SCORED/SHORTLISTED
# rows that M6.13 closed are left alone here — they are re-evaluated by the
# corrected detector through scripts.remediate_dead_postings instead.
REPAIRABLE_FROM_STATUS = Status.FILTERED_OUT


@dataclass(frozen=True)
class Restoration:
    job_id: int
    company: str
    title: str
    expected_status: str
    expected_notes: str | None
    restored_status: str
    restored_notes: str | None
    filter_reason: str | None


def _strip_legacy_note(notes: str) -> str | None:
    """The backup's notes, recovered by removing only the appended M6.13 note."""
    if notes == LEGACY_NOTE:
        return None
    suffix = f"; {LEGACY_NOTE}"
    return notes[: -len(suffix)] if notes.endswith(suffix) else notes


def build_restorations(
    conn: sqlite3.Connection, backup: sqlite3.Connection
) -> tuple[Restoration, ...]:
    backup_rows = {row["id"]: row for row in db.all_rows(backup)}
    out = []
    for row in db.all_rows(conn):
        prior = backup_rows.get(row["id"])
        if prior is None:
            continue
        if row["status"] != Status.CLOSED or prior["status"] != REPAIRABLE_FROM_STATUS:
            continue
        notes = row["notes"] or ""
        if LEGACY_NOTE not in notes:
            continue
        restored_notes = _strip_legacy_note(notes)
        # The overwrite is only attributable to M6.13 if stripping its note
        # reproduces the backup exactly. Anything else changed for other
        # reasons and is out of scope.
        if restored_notes != prior["notes"]:
            continue
        out.append(
            Restoration(
                job_id=row["id"],
                company=row["company"],
                title=row["title"],
                expected_status=str(row["status"]),
                expected_notes=row["notes"],
                restored_status=str(prior["status"]),
                restored_notes=restored_notes,
                filter_reason=row["filter_reason"],
            )
        )
    return tuple(sorted(out, key=lambda r: r.job_id))


def report_payload(rows: tuple[Restoration, ...]) -> dict:
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "legacy_note": LEGACY_NOTE,
        "count": len(rows),
        "counts_by_restored_status": dict(
            sorted(Counter(r.restored_status for r in rows).items())
        ),
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
    parser.add_argument("--from-backup", required=True)
    parser.add_argument("--json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--backup")
    args = parser.parse_args(argv)

    try:
        prior = db.get_readonly_connection(args.from_backup)
        if args.apply:
            if args.confirm != "APPLY" or not args.backup:
                return 2
            backup_path = Path(args.backup)
            if backup_path.exists():
                return 2
            conn = db.get_connection(args.db)
            rows = build_restorations(conn, prior)
            _backup_database(conn, backup_path)
            changed = db.apply_terminal_state_restorations(conn, rows)
            print(json.dumps({"changed": changed, "previewed": len(rows)}, sort_keys=True))
            return 0

        conn = db.get_readonly_connection(args.db)
        payload = report_payload(build_restorations(conn, prior))
        if args.json:
            path = Path(args.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(
            json.dumps(
                {
                    "count": payload["count"],
                    "counts_by_restored_status": payload["counts_by_restored_status"],
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
