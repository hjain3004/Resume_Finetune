"""Import a scored batch file and write scores back to SQLite per ARCHITECTURE §11.

Usage: python -m scripts.import_scores <scored.json> [--db PATH] [--threshold N]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src import db
from src.models import Status
from src.run_ingest import load_filters_config

REQUIRED_FIELDS = ("id", "row_ids", "fit_score", "base_variant", "missing_keywords", "rationale")
RATIONALE_MAX_LEN = 160
DEFAULT_THRESHOLD = 7.0


@dataclass(frozen=True)
class ImportResult:
    updated: int
    shortlisted: int


def _validate_entry(conn: sqlite3.Connection, entry: dict) -> None:
    if not isinstance(entry, dict):
        raise ValueError(f"scored entry must be an object, got {type(entry).__name__}")

    for field in REQUIRED_FIELDS:
        if field not in entry:
            raise ValueError(f"scored entry missing required field '{field}': {entry}")

    job_id = entry["id"]
    if not isinstance(job_id, int):
        raise ValueError(f"'id' must be an integer, got {job_id!r}")
    row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"'id' {job_id} does not match any job in the database")

    row_ids = entry["row_ids"]
    if not isinstance(row_ids, list) or not row_ids or not all(isinstance(i, int) for i in row_ids):
        raise ValueError(f"'row_ids' must be a non-empty list of integers for id {job_id}, got {row_ids!r}")
    if job_id not in row_ids:
        raise ValueError(f"'row_ids' for id {job_id} must include {job_id} itself, got {row_ids!r}")
    for rid in row_ids:
        rid_row = conn.execute("SELECT id FROM jobs WHERE id = ?", (rid,)).fetchone()
        if rid_row is None:
            raise ValueError(f"'row_ids' entry {rid} (from id {job_id}) does not match any job in the database")

    fit_score = entry["fit_score"]
    if not isinstance(fit_score, (int, float)) or isinstance(fit_score, bool):
        raise ValueError(f"'fit_score' must be a number for id {job_id}, got {fit_score!r}")
    if not (0 <= fit_score <= 10):
        raise ValueError(f"'fit_score' must be between 0 and 10 for id {job_id}, got {fit_score!r}")

    if not isinstance(entry["base_variant"], str) or not entry["base_variant"]:
        raise ValueError(f"'base_variant' must be a non-empty string for id {job_id}")

    missing_keywords = entry["missing_keywords"]
    if not isinstance(missing_keywords, list) or not all(isinstance(k, str) for k in missing_keywords):
        raise ValueError(f"'missing_keywords' must be a list of strings for id {job_id}")

    rationale = entry["rationale"]
    if not isinstance(rationale, str):
        raise ValueError(f"'rationale' must be a string for id {job_id}")
    if len(rationale) > RATIONALE_MAX_LEN:
        raise ValueError(
            f"'rationale' must be at most {RATIONALE_MAX_LEN} chars for id {job_id}, got {len(rationale)}"
        )


def import_scores(
    conn: sqlite3.Connection,
    scored: list[dict],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> ImportResult:
    """Validate every entry before writing any changes, then apply all updates.

    Raises ValueError with no DB changes if any entry is invalid.
    """
    if not isinstance(scored, list):
        raise ValueError(f"scored batch must be a list, got {type(scored).__name__}")
    for entry in scored:
        _validate_entry(conn, entry)
    _validate_row_id_coverage(scored)

    updated = 0
    shortlisted = 0
    for entry in scored:
        status = Status.SHORTLISTED if entry["fit_score"] >= threshold else Status.SCORED
        for row_id in entry["row_ids"]:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, fit_score = ?, fit_rationale = ?, base_variant = ?, missing_keywords = ?
                WHERE id = ?
                """,
                (
                    status,
                    entry["fit_score"],
                    entry["rationale"],
                    entry["base_variant"],
                    json.dumps(entry["missing_keywords"]),
                    row_id,
                ),
            )
            updated += 1
            if status == Status.SHORTLISTED:
                shortlisted += 1
    conn.commit()
    return ImportResult(updated=updated, shortlisted=shortlisted)


def _validate_row_id_coverage(scored: list[dict]) -> None:
    """Every row_id across the scored file must be covered by exactly one entry."""
    owner: dict[int, int] = {}
    for entry in scored:
        for row_id in entry["row_ids"]:
            if row_id in owner:
                raise ValueError(
                    f"row_id {row_id} is covered by both id {owner[row_id]} and id {entry['id']} "
                    "— each row_id must be covered exactly once"
                )
            owner[row_id] = entry["id"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.import_scores",
        description="Validate and import a scored batch JSON file into the database.",
    )
    parser.add_argument("scored_file", metavar="SCORED_JSON", help="path to the *.scored.json file")
    parser.add_argument("--db", metavar="PATH", default="data/jobs.db", help="path to the SQLite database")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="fit_score threshold for SHORTLISTED (default: config/filters.yaml score_threshold)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    threshold = args.threshold
    if threshold is None:
        threshold = load_filters_config().get("score_threshold", DEFAULT_THRESHOLD)
    scored = json.loads(Path(args.scored_file).read_text())
    conn = db.get_connection(args.db)
    try:
        result = import_scores(conn, scored, threshold=threshold)
    except ValueError as exc:
        print(f"Rejected scored batch: {exc}")
        return 1
    print(f"Imported {result.updated} score(s), {result.shortlisted} shortlisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
