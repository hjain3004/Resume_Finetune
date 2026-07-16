"""Report Calibration Contract v2 score-vs-fit-call agreement.

Preferred usage:
    python -m scripts.calibration_report data/calibration/2026-07-16.fit.md \
      --scored-file data/calibration/2026-07-16.scored.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src import calibration, db
from src.calibration import CalibrationContractError, ComparisonKind, RoundMetadata
from src.run_ingest import load_filters_config

DEFAULT_THRESHOLD = 7.0


def _jobs_from_fit(worksheet: calibration.CalibrationWorksheet) -> tuple[calibration.BatchJob, ...]:
    return tuple(label.job for label in worksheet.labels)


def _scores_from_db(db_path: str | Path, jobs: tuple[calibration.BatchJob, ...]) -> tuple[calibration.ScoredCall, ...]:
    conn = db.get_readonly_connection(db_path)
    rows = db.calibration_scores_by_ids(conn, tuple(job.job_id for job in jobs))
    score_by_id = {row["id"]: row["fit_score"] for row in rows}
    scores: list[calibration.ScoredCall] = []
    for job in jobs:
        score = score_by_id.get(job.job_id)
        if score is None:
            continue
        scores.append(calibration.ScoredCall(job_id=job.job_id, row_ids=job.row_ids, fit_score=float(score)))
    return tuple(scores)


def _count_fit_labels(worksheet: calibration.CalibrationWorksheet) -> dict[str, int]:
    return {call: sum(1 for label in worksheet.labels if label.fit_call == call) for call in ("APPLY", "MAYBE", "SKIP")}


def _print_report(
    worksheet_path: Path,
    worksheet: calibration.CalibrationWorksheet,
    report: calibration.CalibrationReport,
    *,
    threshold: float,
    scored_source: str,
) -> None:
    metadata = worksheet.metadata
    assert isinstance(metadata, RoundMetadata)
    fit_counts = _count_fit_labels(worksheet)
    agreements = sum(1 for comparison in report.comparisons if comparison.kind == ComparisonKind.AGREEMENT)
    false_negatives = [c for c in report.comparisons if c.kind == ComparisonKind.FALSE_NEGATIVE]
    false_positives = [c for c in report.comparisons if c.kind == ComparisonKind.FALSE_POSITIVE]
    unscored = [c for c in report.comparisons if c.kind == ComparisonKind.UNSCORED]

    print(f"Worksheet: {worksheet_path}")
    print(f"Contract: v{metadata.contract_version} {metadata.stage.value}")
    print(f"Round: {metadata.round_name}")
    print(f"Batch: {metadata.batch_path}")
    print(f"Batch SHA-256: {metadata.batch_sha256}")
    print(f"Score source: {scored_source}")
    print(f"Threshold: {threshold}")
    print(f"Canonical jobs: {len(worksheet.labels)}")
    print(f"Interest-labeled: {sum(1 for label in worksheet.labels if label.interest_call is not None)}")
    print(f"Fit-labeled: {sum(1 for label in worksheet.labels if label.fit_call is not None)}")
    print(f"Scored: {len(worksheet.labels) - len(unscored)}")
    print(f"Unscored: {len(unscored)}")
    print(f"Fit labels: APPLY={fit_counts['APPLY']}, MAYBE={fit_counts['MAYBE']}, SKIP={fit_counts['SKIP']}")
    print(f"Agreements: {agreements}/{len(report.comparisons)}")
    print(f"False negatives: {len(false_negatives)}")
    print(f"False positives: {len(false_positives)}")

    if false_negatives or false_positives:
        print("Disagreements:")
        for comparison in [*false_negatives, *false_positives]:
            label = comparison.label
            print(
                f"  id={label.job.job_id} {label.job.company} — {label.job.title}: "
                f"interest={label.interest_call}, fit={label.fit_call}, score={comparison.score}, "
                f"kind={comparison.kind.value}, notes={label.notes}"
            )

    if unscored:
        print("Unscored:")
        for comparison in unscored:
            label = comparison.label
            print(f"  id={label.job.job_id} {label.job.company} — {label.job.title}: fit={label.fit_call}")

    print("Transition matrix:")
    for interest_call, fit_call, count in report.transition_counts:
        print(f"  {interest_call} -> {fit_call}: {count}")

    changed = [label for label in worksheet.labels if label.interest_call != label.fit_call]
    print(f"Changed after JD: {len(changed)}")
    for label in changed:
        print(
            f"  id={label.job.job_id} {label.job.company} — {label.job.title}: "
            f"{label.interest_call} -> {label.fit_call}; notes={label.notes}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.calibration_report",
        description="Compare a v2 full-JD fit worksheet against scored output.",
    )
    parser.add_argument("worksheet", metavar="FIT_WORKSHEET")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--scored-file", metavar="SCORED_JSON")
    source.add_argument("--db", metavar="PATH", default=None)
    parser.add_argument("--threshold", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    threshold = args.threshold
    if threshold is None:
        threshold = load_filters_config().get("score_threshold", DEFAULT_THRESHOLD)
    worksheet_path = Path(args.worksheet)
    try:
        worksheet = calibration.parse_calibration_worksheet(worksheet_path, require_complete=True)
        jobs = _jobs_from_fit(worksheet)
        if args.scored_file:
            scores = calibration.load_scored_file(args.scored_file, jobs)
            scored_source = str(args.scored_file)
        else:
            db_path = args.db or "data/jobs.db"
            scores = _scores_from_db(db_path, jobs)
            scored_source = str(db_path)
        report = calibration.compare_fit_calls(worksheet, scores, threshold=float(threshold))
        _print_report(worksheet_path, worksheet, report, threshold=float(threshold), scored_source=scored_source)
        return 0
    except (CalibrationContractError, OSError, ValueError) as exc:
        print(f"Calibration report rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
