"""Create and reveal Calibration Contract v2 packets.

Task 3 implements the blind interest-stage packet creation. Reveal is added in
the next task per the milestone plan.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from src import calibration
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
    now: datetime | None = None,
) -> tuple[Path, Path]:
    jobs = calibration.select_round_jobs(calibration.load_batch(source_batch), limit=limit)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.calibration_packet")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="create a blind interest-stage calibration packet")
    start.add_argument("source_batch", metavar="SOURCE_BATCH")
    start.add_argument("--out-dir", default="data/calibration")
    start.add_argument("--round", dest="round_name", default=None)
    start.add_argument("--limit", type=int, default=DEFAULT_ROUND_LIMIT)
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
            )
            print(f"Wrote calibration batch: {batch_path}")
            print(f"Wrote interest worksheet: {interest_path}")
            print(f"Canonical jobs: {len(calibration.load_batch(batch_path))}")
            return 0
    except (CalibrationContractError, FileExistsError, OSError) as exc:
        print(f"Calibration packet rejected: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
