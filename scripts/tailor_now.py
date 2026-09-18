"""Apply-Now lane operator CLI (M8N-0): preflight, run, status, attest, export-jd.
A thin argparse shell around src/tailor/lane.py; it parses, validates,
and hydrates nothing itself. Database access is strictly read-only:
read-only metadata verification for State A provenance (via --db) and
the read-only export-jd helper."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import urllib.parse
import uuid
from pathlib import Path

from src import db
from src.tailor.provenance import (
    JD_PROVENANCE_SCHEMA,
    JDProvenance,
    compute_jd_sha256,
    is_aggregator_url,
)
from src.tailor.lane import (
    APPLICATIONS_MANUAL_ROOT,
    LANE_MANIFEST_NAME,
    LaneError,
    parse_lane_manifest,
    run_manual_application,
)
from src.tailor.pilot import DEFAULT_PROMPT_DIR, Stage, StageState, _discover_run_manifests
from src.tailor.preflight import run_preflight
from src.tailor.providers import Provider

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
            provider=args.provider,
            model=args.model, suffix=args.suffix,
            profile_path=Path(args.profile or DEFAULT_PROFILE),
            template_path=Path(args.template or DEFAULT_TEMPLATE),
            trace_dir=Path(args.trace_dir) if args.trace_dir else Path("data/traces"),
            prompt_dir=Path(args.prompt_dir or DEFAULT_PROMPT_DIR),
            stop_after=stop_after, only=only, dry_run=args.dry_run,
            db_path=Path(args.db) if args.db else None,
            sidecar_path=Path(args.sidecar) if args.sidecar else None,
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
                lane_m = parse_lane_manifest(json.loads(lane_path.read_text(encoding="utf-8")))
                prov = lane_m.provider or "claude"
                m_val = lane_m.model or "default"
                model = f"{prov}:{m_val}" if prov != "claude" else m_val
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
        raw_row = db.job_row_for_export(conn, args.job_id)
        if raw_row is None:
            raise LaneError(f"job {args.job_id}: no such row")
        row = dict(raw_row)

        quality = row.get("jd_quality")
        if quality != "ats":
            raise LaneError(
                f"job {args.job_id}: jd_quality is {quality!r}; only 'ats' quality jobs may be exported for tailoring"
            )

        text = row.get("jd_text") or ""
        if len(text.strip()) < 300:
            raise LaneError(
                f"job {args.job_id}: jd_text is missing or shorter than 300 characters ({len(text)} chars)"
            )

        ats_url = (row.get("ats_url") or "").strip()
        direct_url = (row.get("url") or "").strip()
        source_url = ats_url if ats_url else direct_url
        if not source_url:
            raise LaneError(f"job {args.job_id}: lacks source URL")

        parsed = urllib.parse.urlparse(source_url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise LaneError(f"job {args.job_id}: invalid source URL {source_url!r} (must use HTTPS)")

        if is_aggregator_url(source_url):
            raise LaneError(
                f"job {args.job_id}: source URL {source_url!r} is an aggregator URL; only direct ATS URLs may be exported"
            )

        if ats_url and is_aggregator_url(ats_url):
            raise LaneError(f"job {args.job_id}: ats_url {ats_url!r} is an aggregator URL")

        company = (row.get("company") or "").strip()
        title = (row.get("title") or "").strip()
        if not company or not title:
            raise LaneError(f"job {args.job_id}: missing company or title")

        sha256 = compute_jd_sha256(text.encode("utf-8"))
        prov = JDProvenance(
            schema_version=JD_PROVENANCE_SCHEMA,
            company=company,
            title=title,
            source_url=source_url,
            source_type="ats",
            jd_quality="ats",
            jd_sha256=sha256,
            job_id=int(row["id"]),
            ats_url=ats_url if ats_url else source_url,
            attestation=None,
        )

        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path = out.parent / f"{out.name}.provenance.json"

        if out.exists() or sidecar_path.exists():
            existing_dest = out if out.exists() else sidecar_path
            raise LaneError(
                f"destination {existing_dest} already exists. Refusing to overwrite. "
                "Please specify a new output path or deliberately remove both existing files."
            )

        tmp_out = out.with_name(f"{out.name}.tmp.{uuid.uuid4().hex}")
        tmp_sidecar = out.with_name(f"{out.name}.provenance.json.tmp.{uuid.uuid4().hex}")
        installed_sidecar = False

        try:
            tmp_out.write_text(text, encoding="utf-8")
            tmp_sidecar.write_text(json.dumps(prov.to_dict(), indent=2), encoding="utf-8")

            # Validate staged pair using real State A validator
            from src.tailor.provenance import validate_provenance_for_tailoring
            validate_provenance_for_tailoring(
                tmp_out,
                company=company,
                title=title,
                db_conn=conn,
                sidecar_path=tmp_sidecar,
            )

            # Install sidecar first
            tmp_sidecar.replace(sidecar_path)
            installed_sidecar = True

            # Install JD last as the commit point
            tmp_out.replace(out)
        except Exception:
            if installed_sidecar and sidecar_path.exists():
                sidecar_path.unlink()
            raise
        finally:
            if tmp_out.exists():
                tmp_out.unlink()
            if tmp_sidecar.exists():
                tmp_sidecar.unlink()

        print(f"wrote {out} ({len(text)} chars)")
        print(f"wrote provenance sidecar: {sidecar_path}")
        print(f"company: {company}")
        print(f"title: {title}")
        print(f"base_variant: {row['base_variant']}")
        print(f"jd_quality: {row['jd_quality']}")
        print(f"status: {row['status']}")
        variant = row["base_variant"] or "backend"
        cmd_argv = [
            "python", "-m", "scripts.tailor_now", "run",
            "--jd", str(out),
            "--company", company,
            "--title", title,
            "--variant", variant,
            "--db", str(Path(args.db).resolve() if args.db else "data/jobs.db"),
        ]
        print(f"\nRecommended tailoring command:\n  {shlex.join(cmd_argv)}")
        return 0
    except Exception as exc:  # noqa: BLE001
        return _fail("export-jd", exc)
    finally:
        if conn is not None:
            conn.close()


def cmd_attest(args) -> int:
    try:
        from src.tailor.provenance import create_user_attestation
        out_path = create_user_attestation(
            args.jd,
            company=args.company,
            title=args.title,
            source_url=args.source_url,
            notes=args.notes,
            out_path=args.out,
        )
        print(f"wrote provenance sidecar: {out_path}")
        print(f"company: {args.company}")
        print(f"title: {args.title}")
        print(f"source_url: {args.source_url}")
        print("jd_quality: user_attested")
        return 0
    except Exception as exc:
        return _fail("attest", exc)


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
    run.add_argument("--provider", choices=[p.value for p in Provider], default="claude")
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
    run.add_argument("--db", help="Path to database for metadata verification")
    run.add_argument("--sidecar", help="Explicit path to provenance sidecar")
    run.set_defaults(func=cmd_run)

    attest = sub.add_parser("attest", help="Record a user-attested official copy of a JD")
    attest.add_argument("--jd", required=True, help="Path to JD text file")
    attest.add_argument("--company", required=True, help="Employer company name")
    attest.add_argument("--title", required=True, help="Job title")
    attest.add_argument("--source-url", required=True, help="Official employer page or ATS URL")
    attest.add_argument("--notes", help="Optional notes")
    attest.add_argument("--out", help="Optional explicit path for provenance sidecar")
    attest.set_defaults(func=cmd_attest)

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
