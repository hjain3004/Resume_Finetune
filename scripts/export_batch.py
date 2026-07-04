"""Export RESOLVED jobs to a scoring batch file per ARCHITECTURE §11.

Usage: python -m scripts.export_batch [--db PATH] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src import db
from src.models import Status

JD_TEXT_TRUNCATE_LEN = 6000


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def export_batch(
    conn: sqlite3.Connection,
    *,
    base_dir: str | Path = "data/batch",
    date_str: str | None = None,
) -> Path:
    date_str = date_str or _today_iso()
    rows = conn.execute(
        "SELECT id, company, title, jd_text FROM jobs WHERE status = ? ORDER BY id",
        (Status.RESOLVED,),
    ).fetchall()
    batch = [
        {
            "id": row["id"],
            "company": row["company"],
            "title": row["title"],
            "jd_text": (row["jd_text"] or "")[:JD_TEXT_TRUNCATE_LEN],
        }
        for row in rows
    ]

    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{date_str}.json"
    path.write_text(json.dumps(batch, indent=2))
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.export_batch",
        description="Export RESOLVED jobs to a scoring batch JSON file.",
    )
    parser.add_argument("--db", metavar="PATH", default="data/jobs.db", help="path to the SQLite database")
    parser.add_argument("--out-dir", metavar="DIR", default="data/batch", help="directory to write the batch file to")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = db.get_connection(args.db)
    path = export_batch(conn, base_dir=args.out_dir)
    print(f"Exported batch to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
