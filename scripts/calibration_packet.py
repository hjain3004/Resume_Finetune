"""Create and reveal Calibration Contract v2 packets.

Task 3 implements the blind interest-stage packet creation. Reveal is added in
the next task per the milestone plan.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from src import calibration, db
from src.calibration import DEFAULT_ROUND_LIMIT, CalibrationContractError, CalibrationStage, RoundMetadata


def _utc_round_name(now: datetime | None) -> str:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).date().isoformat()


def start_round(
    source_batch: str | Path,
    *,
    out_dir: str | Path = "data/calibration",
    round_name: str | None = None,
    limit: int = DEFAULT_ROUND_LIMIT,
    exclude_rounds: Sequence[str | Path] = (),
    now: datetime | None = None,
) -> tuple[Path, Path]:
    exclude_ids = frozenset(
        job.job_id for prior in exclude_rounds for job in calibration.load_batch(prior)
    )
    jobs = calibration.select_round_jobs(
        calibration.load_batch(source_batch), limit=limit, exclude_ids=exclude_ids
    )
    round_id = round_name or _utc_round_name(now)
    base = Path(out_dir)
    batch_path = base / f"{round_id}.batch.json"
    interest_path = base / f"{round_id}.interest.md"
    if batch_path.exists():
        raise FileExistsError(batch_path)
    if interest_path.exists():
        raise FileExistsError(interest_path)

    batch_text = calibration.batch_jobs_to_json(jobs)
    created_batch = False
    try:
        calibration.atomic_write_text(batch_path, batch_text)
        created_batch = True
        metadata = RoundMetadata(
            contract_version=calibration.CONTRACT_VERSION,
            stage=CalibrationStage.INTEREST,
            round_name=round_id,
            batch_path=batch_path,
            batch_sha256=calibration.sha256_file(batch_path),
            canonical_job_count=len(jobs),
            created_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        )
        calibration.atomic_write_text(interest_path, calibration.render_interest_worksheet(metadata, jobs))
    except Exception:
        if created_batch:
            try:
                batch_path.unlink()
            except FileNotFoundError:
                pass
        raise
    return batch_path, interest_path


def _default_fit_path(interest_path: Path) -> Path:
    if interest_path.name.endswith(".interest.md"):
        return interest_path.with_name(interest_path.name.removesuffix(".interest.md") + ".fit.md")
    return interest_path.with_suffix(".fit.md")


def reveal_fit(
    interest_path: str | Path,
    *,
    db_path: str | Path = "data/jobs.db",
    out_path: str | Path | None = None,
    now: datetime | None = None,
) -> Path:
    interest_artifact = Path(interest_path)
    output_path = Path(out_path) if out_path is not None else _default_fit_path(interest_artifact)
    if output_path.exists():
        raise FileExistsError(output_path)
    interest = calibration.parse_interest_worksheet(interest_artifact, require_complete=True)
    if not isinstance(interest.metadata, RoundMetadata):
        raise CalibrationContractError("reveal requires a v2 interest worksheet")
    job_ids = tuple(label.job.job_id for label in interest.labels)
    conn = db.get_readonly_connection(db_path)
    rows = db.calibration_jobs_by_ids(conn, job_ids)
    by_id = {row["id"]: row for row in rows}
    missing = [job_id for job_id in job_ids if job_id not in by_id]
    if missing:
        raise CalibrationContractError(f"missing complete JD rows for job ids {missing}")
    full_jds: list[calibration.FullJD] = []
    for label in interest.labels:
        row = by_id[label.job.job_id]
        if row["company"] != label.job.company or row["title"] != label.job.title:
            raise CalibrationContractError(f"job {label.job.job_id}: database company/title no longer matches batch")
        if not row["jd_text"]:
            raise CalibrationContractError(f"job {label.job.job_id}: database jd_text is missing")
        full_jds.append(
            calibration.FullJD(
                job_id=row["id"],
                company=row["company"],
                title=row["title"],
                jd_text=row["jd_text"],
            )
        )
    metadata = RoundMetadata(
        contract_version=calibration.CONTRACT_VERSION,
        stage=CalibrationStage.FIT,
        round_name=interest.metadata.round_name,
        batch_path=interest.metadata.batch_path,
        batch_sha256=interest.metadata.batch_sha256,
        canonical_job_count=len(interest.labels),
        created_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        interest_path=interest_artifact,
        interest_sha256=calibration.sha256_file(interest_artifact),
    )
    calibration.atomic_write_text(output_path, calibration.render_fit_worksheet(metadata, interest, tuple(full_jds)))
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.calibration_packet")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="create a blind interest-stage calibration packet")
    start.add_argument("source_batch", metavar="SOURCE_BATCH")
    start.add_argument("--out-dir", default="data/calibration")
    start.add_argument("--round", dest="round_name", default=None)
    start.add_argument("--limit", type=int, default=DEFAULT_ROUND_LIMIT)
    start.add_argument(
        "--exclude-round",
        dest="exclude_rounds",
        action="append",
        default=[],
        metavar="PRIOR_BATCH",
        help="path to a previous round's .batch.json whose jobs must not be drawn again "
        "(repeatable); keeps successive rounds blind and additive",
    )
    reveal = subparsers.add_parser("reveal", help="reveal a locked full-JD fit worksheet")
    reveal.add_argument("interest_path", metavar="INTEREST")
    reveal.add_argument("--db", default="data/jobs.db")
    reveal.add_argument("--out", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            batch_path, interest_path = start_round(
                args.source_batch,
                out_dir=args.out_dir,
                round_name=args.round_name,
                limit=args.limit,
                exclude_rounds=args.exclude_rounds,
            )
            print(f"Wrote calibration batch: {batch_path}")
            print(f"Wrote interest worksheet: {interest_path}")
            print(f"Canonical jobs: {len(calibration.load_batch(batch_path))}")
            return 0
        if args.command == "reveal":
            fit_path = reveal_fit(args.interest_path, db_path=args.db, out_path=args.out)
            print(f"Wrote fit worksheet: {fit_path}")
            return 0
    except (CalibrationContractError, FileExistsError, OSError) as exc:
        print(f"Calibration packet rejected: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
