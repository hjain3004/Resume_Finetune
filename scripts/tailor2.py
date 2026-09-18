"""Tailor2 Operator CLI: run, preflight, status.

A thin argparse shell around src.tailor2.lane; it enforces explicit provider
and model flags, validates environment invariants, and reports bounded diagnostics.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from src.profile import load_profile
from src.tailor.providers import (
    Provider,
    check_gemini_credentials,
    check_openai_credentials,
)
from src.tailor.publish import slugify
from src.tailor2.invoker import Tailor2Invoker
from src.tailor2.lane import Tailor2RunResult, run_tailor2_lane


def _fail(label: str, msg: str) -> int:
    print(f"tailor2 {label}: {msg}", file=sys.stderr)
    return 1


def cmd_preflight(args: argparse.Namespace) -> int:
    profile_path = Path(args.profile or "config/master_profile.yaml")
    template_path = Path(args.template or "profile/template.tex")
    findings: list[str] = []

    # 1. Profile check
    try:
        prof = load_profile(profile_path)
        print(f"[PASS] profile: {profile_path} ({len(prof.experience)} exp, {len(prof.projects)} proj)")
    except Exception as exc:
        msg = f"[FAIL] profile: {exc}"
        findings.append(msg)
        print(msg)

    # 2. LaTeX Template check
    if template_path.exists():
        print(f"[PASS] template: {template_path}")
    else:
        msg = f"[FAIL] template: {template_path} not found"
        findings.append(msg)
        print(msg)

    # 3. pdflatex check
    pdflatex = shutil.which("pdflatex")
    if pdflatex:
        print(f"[PASS] pdflatex: {pdflatex}")
    else:
        if not args.skip_render:
            msg = "[FAIL] pdflatex: not found on PATH"
            findings.append(msg)
            print(msg)
        else:
            print("[SKIP] pdflatex: skipped (--skip-render)")

    # 4. Provider credentials
    if args.provider:
        prov = args.provider.lower()
        if prov == Provider.OPENAI.value:
            err = check_openai_credentials()
            if err:
                findings.append(f"[FAIL] openai: {err}")
                print(findings[-1])
            else:
                print("[PASS] openai: OPENAI_API_KEY set")
        elif prov == Provider.GEMINI.value:
            err = check_gemini_credentials()
            if err:
                findings.append(f"[FAIL] gemini: {err}")
                print(findings[-1])
            else:
                print("[PASS] gemini: GEMINI_API_KEY set")
        elif prov == Provider.CLAUDE.value:
            if shutil.which("claude") is None:
                findings.append("[FAIL] claude: claude CLI not found on PATH")
                print(findings[-1])
            else:
                print("[PASS] claude: CLI found on PATH")
    else:
        # Check and display status of all available providers without failing
        openai_err = check_openai_credentials()
        gemini_err = check_gemini_credentials()
        claude_found = shutil.which("claude") is not None
        print(f"[INFO] openai: {'OPENAI_API_KEY set' if not openai_err else 'OPENAI_API_KEY missing'}")
        print(f"[INFO] gemini: {'GEMINI_API_KEY set' if not gemini_err else 'GEMINI_API_KEY missing'}")
        print(f"[INFO] claude: {'claude CLI on PATH' if claude_found else 'claude CLI missing'}")

    passed = len(findings) == 0
    print(f"preflight: {'PASS' if passed else 'FAIL'} ({len(findings)} finding(s))")
    return 0 if passed else 1


def cmd_run(args: argparse.Namespace) -> int:
    jd_path = Path(args.jd)
    if not jd_path.exists():
        return _fail("run", f"JD file not found: {jd_path}")

    jd_text = jd_path.read_text(encoding="utf-8")
    if len(jd_text.strip()) < 50:
        return _fail("run", f"JD text is too short ({len(jd_text)} chars); minimum 50 chars required.")

    profile_path = Path(args.profile or "config/master_profile.yaml")
    if not profile_path.exists():
        return _fail("run", f"profile not found: {profile_path}")

    template_path = Path(args.template or "profile/template.tex")
    if not template_path.exists():
        return _fail("run", f"LaTeX template not found: {template_path}")

    # Enforce explicit provider and model for live runs
    if not args.dry_run and not args.fake_responses:
        if not args.provider:
            return _fail("run", "--provider is required for live execution (choices: claude, openai, gemini).")
        if not args.model or not str(args.model).strip():
            return _fail("run", "explicit --model name is required for live execution; defaulting is disabled.")

        prov = args.provider.lower()
        if prov == Provider.OPENAI.value:
            err = check_openai_credentials()
            if err:
                return _fail("run", err)
        elif prov == Provider.GEMINI.value:
            err = check_gemini_credentials()
            if err:
                return _fail("run", err)
        elif prov == Provider.CLAUDE.value:
            if shutil.which("claude") is None:
                return _fail("run", "claude CLI not found on PATH.")

        if args.auditor_provider:
            aud_prov = args.auditor_provider.lower()
            if aud_prov == Provider.OPENAI.value:
                err = check_openai_credentials()
                if err:
                    return _fail("run", f"auditor: {err}")
            elif aud_prov == Provider.GEMINI.value:
                err = check_gemini_credentials()
                if err:
                    return _fail("run", f"auditor: {err}")
            elif aud_prov == Provider.CLAUDE.value:
                if shutil.which("claude") is None:
                    return _fail("run", "auditor: claude CLI not found on PATH.")

    if args.dry_run:
        try:
            load_profile(profile_path)
        except Exception as exc:
            return _fail("run", f"profile validation failed: {exc}")
        print(f"[dry-run] tailor2: preflight validated for {args.company} - {args.title} ({args.variant}); no model calls made.")
        return 0

    fake_resp_dict = None
    if args.fake_responses:
        fake_resp_path = Path(args.fake_responses)
        if not fake_resp_path.exists():
            return _fail("run", f"fake responses file not found: {fake_resp_path}")
        try:
            fake_resp_dict = json.loads(fake_resp_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return _fail("run", f"failed to parse fake responses JSON: {exc}")

    # Determine out_dir
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        root = Path(args.root or "applications_manual")
        slug = f"{slugify(args.company)}-{slugify(args.title)}"
        if args.suffix:
            slug = f"{slug}-{slugify(args.suffix)}"
        slug = f"{slug}-tailor2"
        out_dir = root / slug

    try:
        invoker = Tailor2Invoker(
            provider=args.provider or "claude",
            model=args.model,
            timeout_seconds=args.timeout or 300,
            dry_run=args.dry_run,
            fake_responses=fake_resp_dict,
            trace_dir=Path(args.trace_dir or "data/traces"),
        )
        auditor_invoker = None
        if args.auditor_provider or args.auditor_model:
            auditor_invoker = Tailor2Invoker(
                provider=args.auditor_provider or (args.provider or "claude"),
                model=args.auditor_model or args.model,
                timeout_seconds=args.timeout or 300,
                dry_run=args.dry_run,
                fake_responses=fake_resp_dict,
                trace_dir=Path(args.trace_dir or "data/traces"),
            )
        outcome = run_tailor2_lane(
            jd_path=jd_path,
            company=args.company,
            title=args.title,
            variant=args.variant,
            invoker=invoker,
            out_dir=out_dir,
            profile_path=profile_path,
            template_path=template_path,
            auditor_invoker=auditor_invoker,
            acknowledge_same_model=args.acknowledge_same_model,
            repair_budget=args.repair_budget,
        )
    except Exception as exc:
        return _fail("run", str(exc))

    status_label = outcome.status or ("ACCEPTED" if outcome.success else "REJECTED_FATAL")
    if not outcome.success:
        print(
            f"tailor2 run: {status_label} ({outcome.call_count} model calls, repair_performed={outcome.repair_performed})",
            file=sys.stderr,
        )
        for reason in outcome.rejection_reasons:
            print(f"  - {reason}", file=sys.stderr)
        print(f"manifest: {outcome.manifest_path}", file=sys.stderr)
        return 1

    print(f"tailor2 run: {status_label} ({outcome.call_count} model calls, repair_performed={outcome.repair_performed})")
    for warning in outcome.warnings:
        print(f"  [warning] {warning}")
    print(f"pdf: {outcome.out_pdf}")
    print(f"manifest: {outcome.manifest_path}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.root or "applications_manual")
    if not root.exists():
        print(f"0 tailor2 application(s) found under {root}")
        return 0

    rows = []
    for manifest_file in sorted(root.rglob("run_manifest.json")):
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            run_id = data.get("run_id", "-")
            company = data.get("company", "-")
            title = data.get("title", "-")
            variant = data.get("variant", "-")
            status_val = data.get("status", "-")
            prov = data.get("provider", "-")
            model = data.get("model", "-")
            calls = data.get("call_count", 0)
            repair = data.get("repair_performed", False)
            dir_name = manifest_file.parent.name
            rows.append((dir_name, company, title, variant, f"{prov}:{model}", status_val, calls, repair))
        except Exception:
            continue

    for dir_name, company, title, variant, model_str, status_val, calls, repair in rows:
        print(
            f"{dir_name}  {company} — {title} ({variant})  model={model_str}  status={status_val}  calls={calls}  repair={repair}"
        )
    print(f"{len(rows)} tailor2 application(s) found under {root}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.tailor2")
    sub = parser.add_subparsers(dest="command", required=True)

    # preflight
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--profile")
    preflight.add_argument("--template")
    preflight.add_argument("--provider", choices=[p.value for p in Provider])
    preflight.add_argument("--skip-render", action="store_true")
    preflight.set_defaults(func=cmd_preflight)

    # run
    run = sub.add_parser("run")
    run.add_argument("--jd", required=True, help="Path to job description text file")
    run.add_argument("--company", required=True, help="Target company name")
    run.add_argument("--title", required=True, help="Target job title")
    run.add_argument("--variant", required=True, choices=["backend", "ml"], help="Resume variant")
    run.add_argument("--provider", choices=[p.value for p in Provider], help="Drafter model provider")
    run.add_argument("--model", help="Drafter explicit model identifier")
    run.add_argument(
        "--auditor-provider",
        choices=[p.value for p in Provider],
        help="Auditor model provider (independent of --provider). Also used for repair/re-audit unless overridden. "
        "Omit to reuse --provider (same-model audit; a disclosure is logged and recorded in the manifest).",
    )
    run.add_argument(
        "--auditor-model",
        help="Auditor explicit model identifier (independent of --model). Omit to reuse --model.",
    )
    run.add_argument(
        "--acknowledge-same-model",
        action="store_true",
        help="Suppress the same-model warning log line when --auditor-provider/--auditor-model are omitted or "
        "identical to --provider/--model. The manifest's same_model_draft_and_audit field is still recorded "
        "either way -- this flag only silences the console warning for a deliberate same-model run.",
    )
    run.add_argument(
        "--repair-budget",
        type=int,
        default=1,
        help="Maximum repair+re-audit cycles attempted before an unresolved REPAIRABLE_QUALITY finding falls "
        "through to NEEDS_HUMAN_REVIEW (default: 1).",
    )
    run.add_argument("--root", help="Root directory for manual applications (default: applications_manual)")
    run.add_argument("--out-dir", help="Explicit output directory override")
    run.add_argument("--suffix", help="Optional suffix for the application directory slug")
    run.add_argument("--profile", help="Path to master_profile.yaml")
    run.add_argument("--template", help="Path to template.tex")
    run.add_argument("--trace-dir", help="Path to trace logging directory")
    run.add_argument("--timeout", type=int, default=300, help="Per-invocation timeout in seconds")
    run.add_argument("--dry-run", action="store_true", help="Validate preflight and inputs without making model calls")
    run.add_argument("--fake-responses", help="Path to JSON file with fake model responses (for offline replay/testing)")
    run.set_defaults(func=cmd_run)

    # status
    status = sub.add_parser("status")
    status.add_argument("--root", help="Root directory for manual applications (default: applications_manual)")
    status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
