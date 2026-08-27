"""The one-job pilot operator CLI: select, run, cost, gate, index.

Mirrors scripts/tailor_s3.py's structure. This CLI is a thin argument-
parsing and printing shell around src/tailor/pilot.py -- it re-implements
no parsing, validation, hydration, or selection logic of its own.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from src import db
from src.tailor.pilot import (
    APPLICATIONS_ROOT,
    STAGE_ARTIFACT,
    Stage,
    _discover_run_manifests,
    _read_json_or_none,
    acceptance_gate,
    bounded,
    cost_report,
    eligible_candidates,
    select_pilot_jobs,
)
from src.tailor.pilot import run_application
from src.tailor.publish import parse_render_result

DEFAULT_PROFILE = Path("config/master_profile.yaml")
DEFAULT_FEEDBACK_DIR = Path("data/feedback")


def _fail(label: str, exc: Exception) -> int:
    print(f"tailor_pilot {label}: {bounded(exc)}", file=sys.stderr)
    return 1


def cmd_select(args) -> int:
    conn = None
    try:
        conn = db.get_readonly_connection(args.db)
        candidates = eligible_candidates(conn)
        picks = select_pilot_jobs(candidates, count=args.count)
        for candidate in picks:
            print(f"{candidate.job_id}  {candidate.company} — {candidate.title} "
                  f"({candidate.base_variant}, {candidate.jd_length}B)")
            print(f"    reason: {'; '.join(candidate.reasons)}")
        return 0
    except Exception as exc:
        return _fail("select", exc)
    finally:
        if conn is not None:
            conn.close()


def cmd_run(args) -> int:
    try:
        stop_after = Stage(args.stop_after) if args.stop_after else None
        only = Stage(args.only) if args.only else None
        outcome = run_application(
            args.job_id, db_path=args.db, profile_path=args.profile or DEFAULT_PROFILE,
            root=Path(args.root) if args.root else APPLICATIONS_ROOT,
            trace_dir=Path(args.trace_dir) if args.trace_dir else Path("data/traces"),
            feedback_dir=Path(args.feedback_dir) if args.feedback_dir else DEFAULT_FEEDBACK_DIR,
            stop_after=stop_after, only=only, dry_run=args.dry_run,
            allow_rerun_after_feedback=args.allow_rerun_after_feedback,
        )
        if outcome.failed_stage is not None:
            failed_record = next(
                (record for record in outcome.manifest.stages if record.stage is outcome.failed_stage), None
            )
            error_text = failed_record.error if failed_record is not None else "unknown failure"
            print(f"tailor_pilot run: job {args.job_id} failed at stage "
                  f"{outcome.failed_stage.value}: {error_text}", file=sys.stderr)
            if outcome.retry_command:
                print(f"retry with: {outcome.retry_command}", file=sys.stderr)
            return 1
        if args.dry_run:
            print(f"[dry-run] job {args.job_id}: chain composes; no model call, no write.")
            return 0
        print(f"job {args.job_id}: completed ({outcome.manifest.total_model_calls} model calls)")
        return 0
    except Exception as exc:
        return _fail("run", exc)


def cmd_cost(args) -> int:
    try:
        report = cost_report(Path(args.root) if args.root else APPLICATIONS_ROOT)
        print(f"applications: {report.applications}")
        print(f"total_model_calls: {report.total_model_calls}")
        print(f"mean_calls_per_application: {report.mean_calls_per_application:.2f}")
        print("calls_by_stage:")
        for stage_name, calls in report.calls_by_stage:
            print(f"  {stage_name}: {calls}")
        print("g2_round_distribution:")
        for rounds_used, count in report.g2_round_distribution:
            print(f"  {rounds_used} round(s): {count}")
        return 0
    except Exception as exc:
        return _fail("cost", exc)


def cmd_gate(args) -> int:
    try:
        report = acceptance_gate(
            Path(args.root) if args.root else APPLICATIONS_ROOT,
            Path(args.feedback_dir) if args.feedback_dir else DEFAULT_FEEDBACK_DIR,
            expected_runs=args.expected_runs,
        )
        for condition in report.conditions:
            status = "PASS" if condition.passed else "FAIL"
            print(f"{condition.name}: {status} (threshold {condition.threshold}, observed {condition.observed})")
        print(f"gate: {'PASS' if report.passed else 'FAIL'}")
        return 0 if report.passed else 1
    except Exception as exc:
        return _fail("gate", exc)


def _index_row(directory: Path, manifest) -> tuple[str, str, str, str, str, str, str]:
    manifest_path = directory / "run_manifest.json"
    mtime = manifest_path.stat().st_mtime if manifest_path.exists() else 0.0
    date = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).date().isoformat() if mtime else ""

    g3_record = next((r for r in manifest.stages if r.stage is Stage.G3), None)
    g3_status = "reached" if g3_record is not None and g3_record.outcome_kind not in ("pending", "failed") else "pending"

    l7_status = "n/a"
    pdf_path = ""
    raw_render = _read_json_or_none(directory / STAGE_ARTIFACT[Stage.RENDER])
    if raw_render is not None:
        try:
            render_result = parse_render_result(raw_render)
            l7_status = "pass" if not render_result.l7_violations else "fail"
            pdf_path = render_result.pdf_path
        except (KeyError, TypeError, ValueError):
            pass

    return (date, manifest.company, manifest.title, g3_status, l7_status,
            str(manifest.total_model_calls), pdf_path)


def cmd_index(args) -> int:
    try:
        root = Path(args.root) if args.root else APPLICATIONS_ROOT
        runs = _discover_run_manifests(root)
        rows = sorted((_index_row(directory, manifest) for directory, manifest in runs), key=lambda row: (row[1], row[2]))

        lines = [
            "# Applications index",
            "",
            "| Date | Company | Role | G3 | L7 | Model calls | PDF |",
            "|---|---|---|---|---|---|---|",
        ]
        for date, company, title, g3_status, l7_status, model_calls, pdf_path in rows:
            lines.append(f"| {date} | {company} | {title} | {g3_status} | {l7_status} | {model_calls} | {pdf_path} |")
        lines.append("")

        root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)
        (root_path / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"wrote {root_path / 'INDEX.md'} ({len(rows)} application(s))")
        return 0
    except Exception as exc:
        return _fail("index", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.tailor_pilot")
    sub = parser.add_subparsers(dest="command", required=True)
    stage_choices = [stage.value for stage in Stage]

    select = sub.add_parser("select")
    select.add_argument("--db", required=True)
    select.add_argument("--count", type=int, default=3)
    select.set_defaults(func=cmd_select)

    run = sub.add_parser("run")
    run.add_argument("--job-id", type=int, required=True)
    run.add_argument("--db", required=True)
    run.add_argument("--profile")
    run.add_argument("--root")
    run.add_argument("--trace-dir")
    run.add_argument("--feedback-dir")
    run.add_argument("--stop-after", choices=stage_choices)
    run.add_argument("--only", choices=stage_choices)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--allow-rerun-after-feedback", action="store_true")
    run.set_defaults(func=cmd_run)

    cost = sub.add_parser("cost")
    cost.add_argument("--root")
    cost.set_defaults(func=cmd_cost)

    gate = sub.add_parser("gate")
    gate.add_argument("--root")
    gate.add_argument("--feedback-dir")
    gate.add_argument("--expected-runs", type=int, default=3)
    gate.set_defaults(func=cmd_gate)

    index = sub.add_parser("index")
    index.add_argument("--root")
    index.set_defaults(func=cmd_index)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
