"""Apply-Now lane operator CLI (M8N-0): preflight, run, status, export-jd.
A thin argparse shell around src/tailor/lane.py; it parses, validates,
and hydrates nothing itself. The only DB access in this file is the
read-only export-jd helper used for the spec §11 benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import db
from src.tailor.lane import (
    APPLICATIONS_MANUAL_ROOT,
    LANE_MANIFEST_NAME,
    LaneError,
    parse_lane_manifest,
    run_manual_application,
)
from src.tailor.pilot import DEFAULT_PROMPT_DIR, Stage, StageState, _discover_run_manifests
from src.tailor.preflight import run_preflight

DEFAULT_PROFILE = Path("config/master_profile.yaml")
DEFAULT_TEMPLATE = Path("profile/template.tex")


def _fail(label: str, exc: Exception) -> int:
    print(f"tailor_now {label}: {exc}", file=sys.stderr)
    return 1


def cmd_preflight(args) -> int:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="apply-now-preflight-") as workdir:
        report = run_preflight(
            Path(args.profile or DEFAULT_PROFILE), Path(args.template or DEFAULT_TEMPLATE),
            Path(args.prompt_dir or DEFAULT_PROMPT_DIR), Path(workdir), skip_render=args.skip_render,
        )
    for finding in report.findings:
        print(f"{finding.check} [{finding.surface}]: {finding.message}")
    print(f"preflight: {'PASS' if report.passed else 'FAIL'} ({len(report.findings)} finding(s))")
    return 0 if report.passed else 1


def cmd_run(args) -> int:
    try:
        stop_after = Stage(args.stop_after) if args.stop_after else None
        only = Stage(args.only) if args.only else None
        outcome = run_manual_application(
            Path(args.jd), company=args.company, title=args.title, variant=args.variant,
            root=Path(args.root) if args.root else APPLICATIONS_MANUAL_ROOT,
            model=args.model, suffix=args.suffix,
            profile_path=Path(args.profile or DEFAULT_PROFILE),
            template_path=Path(args.template or DEFAULT_TEMPLATE),
            trace_dir=Path(args.trace_dir) if args.trace_dir else Path("data/traces"),
            prompt_dir=Path(args.prompt_dir or DEFAULT_PROMPT_DIR),
            stop_after=stop_after, only=only, dry_run=args.dry_run,
        )
    except LaneError as exc:
        return _fail("run", exc)
    except Exception as exc:  # noqa: BLE001 - operator CLI reports, never crashes
        return _fail("run", exc)

    if outcome.failed_stage is not None:
        record = next((r for r in outcome.manifest.stages if r.stage is outcome.failed_stage), None)
        error_text = record.error if record is not None else "unknown failure"
        print(f"tailor_now run: job {outcome.manifest.job_id} failed at stage "
              f"{outcome.failed_stage.value}: {error_text}", file=sys.stderr)
        if outcome.retry_command:
            print(f"retry with: {outcome.retry_command}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"[dry-run] job {outcome.manifest.job_id}: chain composes; no model call, no write.")
        return 0
    render_record = next((r for r in outcome.manifest.stages if r.stage is Stage.RENDER), None)
    pdf_path = ""
    if render_record is not None and render_record.artifact_path:
        try:
            pdf_path = json.loads(Path(render_record.artifact_path).read_text(encoding="utf-8")).get("pdf_path", "")
        except (OSError, ValueError):
            pdf_path = ""
    print(f"job {outcome.manifest.job_id}: completed ({outcome.manifest.total_model_calls} model calls)")
    if pdf_path:
        print(f"pdf: {pdf_path}")
    return 0


def cmd_status(args) -> int:
    root = Path(args.root) if args.root else APPLICATIONS_MANUAL_ROOT
    rows = []
    for directory, manifest in _discover_run_manifests(root):
        model = ""
        lane_path = directory / LANE_MANIFEST_NAME
        if lane_path.exists():
            try:
                model = parse_lane_manifest(json.loads(lane_path.read_text(encoding="utf-8"))).model or "default"
            except (OSError, ValueError):
                model = "?"
        reached = [r.stage.value for r in manifest.stages
                   if r.state in (StageState.COMPLETE, StageState.SKIPPED_COMPLETE)]
        last = reached[-1] if reached else "-"
        rows.append((directory.name, manifest.company, manifest.title, last, model, manifest.total_model_calls))
    for name, company, title, last, model, calls in sorted(rows):
        print(f"{name}  {company} — {title}  last_complete={last}  model={model}  calls={calls}")
    print(f"{len(rows)} application(s) under {root}")
    return 0


def cmd_export_jd(args) -> int:
    conn = None
    try:
        conn = db.get_readonly_connection(args.db)
        row = db.job_row_for_export(conn, args.job_id)
        if row is None:
            raise LaneError(f"job {args.job_id}: no such row")
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(row["jd_text"] or "", encoding="utf-8")
        print(f"wrote {out} ({len(row['jd_text'] or '')} chars)")
        print(f"company: {row['company']}")
        print(f"title: {row['title']}")
        print(f"base_variant: {row['base_variant']}")
        print(f"jd_quality: {row['jd_quality']}")
        print(f"status: {row['status']}")
        return 0
    except Exception as exc:  # noqa: BLE001
        return _fail("export-jd", exc)
    finally:
        if conn is not None:
            conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.tailor_now")
    sub = parser.add_subparsers(dest="command", required=True)
    stage_choices = [stage.value for stage in Stage]

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--profile")
    preflight.add_argument("--template")
    preflight.add_argument("--prompt-dir")
    preflight.add_argument("--skip-render", action="store_true")
    preflight.set_defaults(func=cmd_preflight)

    run = sub.add_parser("run")
    run.add_argument("--jd", required=True)
    run.add_argument("--company", required=True)
    run.add_argument("--title", required=True)
    run.add_argument("--variant", required=True)
    run.add_argument("--model")
    run.add_argument("--suffix")
    run.add_argument("--root")
    run.add_argument("--profile")
    run.add_argument("--template")
    run.add_argument("--prompt-dir")
    run.add_argument("--trace-dir")
    run.add_argument("--stop-after", choices=stage_choices)
    run.add_argument("--only", choices=stage_choices)
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status")
    status.add_argument("--root")
    status.set_defaults(func=cmd_status)

    export = sub.add_parser("export-jd")
    export.add_argument("--db", default="data/jobs.db")
    export.add_argument("--job-id", type=int, required=True)
    export.add_argument("--out", required=True)
    export.set_defaults(func=cmd_export_jd)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
