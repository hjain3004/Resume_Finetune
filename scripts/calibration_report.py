"""Report threshold-crossing disagreements between a blind calibration baseline
and imported AI scores, per PHASE2_KICKOFF.md Phase 2 Step 3.

A disagreement is a job where the user's blind call and the AI's fit_score
land on opposite sides of the shortlist threshold: user said APPLY but the
score fell below threshold, or user said SKIP but the score met or exceeded
it. MAYBE calls are never disagreements — they're the ambiguous middle the
protocol doesn't ask the model to resolve.

Usage: python -m scripts.calibration_report data/calibration/2026-07-12.user.md
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src import db
from src.run_ingest import load_filters_config

VALID_CALLS = {"APPLY", "MAYBE", "SKIP"}
DEFAULT_THRESHOLD = 7.0


@dataclass(frozen=True)
class CalibrationRow:
    job_id: int
    company: str
    title: str
    call: str


@dataclass(frozen=True)
class Disagreement:
    job_id: int
    company: str
    title: str
    call: str
    fit_score: float


def parse_worksheet(text: str) -> tuple[list[CalibrationRow], int]:
    """Return (rated rows, total job rows listed) from a calibration worksheet.

    Rows without a your-call value (blank, or anything other than
    APPLY/MAYBE/SKIP) are counted in the total but excluded from the rated list.
    """
    rated: list[CalibrationRow] = []
    total = 0
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        total += 1
        call = cells[5].strip().upper()
        if call in VALID_CALLS:
            rated.append(
                CalibrationRow(job_id=int(cells[0]), company=cells[1], title=cells[2], call=call)
            )
    return rated, total


def find_disagreements(
    conn: sqlite3.Connection, rows: list[CalibrationRow], threshold: float
) -> tuple[list[Disagreement], list[CalibrationRow]]:
    """Split rated rows into (threshold-crossing disagreements, rows with no fit_score yet)."""
    disagreements: list[Disagreement] = []
    unscored: list[CalibrationRow] = []
    for row in rows:
        result = conn.execute("SELECT fit_score FROM jobs WHERE id = ?", (row.job_id,)).fetchone()
        fit_score = result["fit_score"] if result is not None else None
        if fit_score is None:
            unscored.append(row)
            continue
        crosses = (row.call == "APPLY" and fit_score < threshold) or (
            row.call == "SKIP" and fit_score >= threshold
        )
        if crosses:
            disagreements.append(
                Disagreement(
                    job_id=row.job_id, company=row.company, title=row.title, call=row.call, fit_score=fit_score
                )
            )
    return disagreements, unscored


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.calibration_report",
        description="Compare a blind calibration worksheet against imported AI scores.",
    )
    parser.add_argument("worksheet", metavar="WORKSHEET_MD", help="path to data/calibration/YYYY-MM-DD.user.md")
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

    worksheet_path = Path(args.worksheet)
    rows, total = parse_worksheet(worksheet_path.read_text())
    conn = db.get_connection(args.db)
    disagreements, unscored = find_disagreements(conn, rows, threshold)

    print(f"Worksheet: {worksheet_path}")
    print(f"Threshold: {threshold}")
    print(f"Jobs listed: {total}, rated: {len(rows)}, unscored: {len(unscored)}")
    if unscored:
        print(f"WARNING: {len(unscored)} rated job(s) have no fit_score yet — run scoring before drawing conclusions.")
        for row in unscored:
            print(f"  id={row.job_id} {row.company} — {row.title}: you said {row.call}, no score yet")
    print(f"Disagreements: {len(disagreements)}")
    for d in disagreements:
        print(f"  id={d.job_id} {d.company} — {d.title}: you said {d.call}, score={d.fit_score}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
