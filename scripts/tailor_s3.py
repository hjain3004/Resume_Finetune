"""Fail-closed one-job S3 preparation and invocation CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import db
from src.profile import load_profile
from src.tailor.artifacts import write_json_atomic
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.g1 import load_banned_terms
from src.tailor.s0 import build_s0_request, parse_s0_request, parse_s0_response
from src.tailor.s1 import parse_s1_request, parse_s1_response_dict
from src.tailor.s2 import build_s2_request, parse_s2_request, parse_s2_response
from src.tailor.s3 import build_s3_request, parse_s3_request, s3_request_to_dict
from src.tailor.s3_pipeline import S3OutcomeKind, run_s3_invocation, s3_bundle_to_dict

S3_PROMPT = Path("docs/prompts/tailoring_s3.md")
BANNED_WORDS = Path("config/banned_words.txt")
TRACE_DIR = Path("data/traces")


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(label: str, exc: Exception) -> int:
    print(f"tailor_s3 {label}: {exc}", file=sys.stderr)
    return 1


def cmd_prepare(args) -> int:
    conn = None
    try:
        conn = db.get_readonly_connection(args.db)
        authoritative_s1_request = db.prepare_tailoring_request(conn, args.job_id)
        variant = db.tailoring_base_variant(conn, args.job_id)
        s1_request = parse_s1_request(_read(Path(args.s1_request)))
        if s1_request != authoritative_s1_request:
            raise ValueError("persisted S1 request does not match eligible DB row")
        s1 = parse_s1_response_dict(_read(Path(args.s1)), authoritative_s1_request.jd_text)
        if s1.suspected_injection:
            raise ValueError("S1 artifact is injection-blocked")
        positioning = load_profile(args.profile).for_positioning()
        canonical_catalog = load_profile(args.profile).for_selection(variant)
        s0_request = build_s0_request(args.job_id, args.company if hasattr(args, "company") else authoritative_s1_request.company, authoritative_s1_request.title, s1, positioning)
        persisted_s0_request = parse_s0_request(_read(Path(args.s0_request)))
        if persisted_s0_request != s0_request:
            raise ValueError("persisted S0 request does not match authoritative S1 and profile")
        s0 = parse_s0_response(json.dumps(_read(Path(args.s0))), s0_request)
        persisted_s2_request = parse_s2_request(_read(Path(args.s2_request)))
        canonical_s2_request = build_s2_request(args.job_id, authoritative_s1_request.company, authoritative_s1_request.title, s1, s0, canonical_catalog)
        if persisted_s2_request != canonical_s2_request:
            raise ValueError("persisted S2 request does not match authoritative chain")
        s2 = parse_s2_response(json.dumps(_read(Path(args.s2))), canonical_s2_request)
        alignment = alignment_from_profile(load_profile(args.profile), canonical_s2_request, s2)
        request = build_s3_request(args.job_id, authoritative_s1_request.company, authoritative_s1_request.title, s1, s0, s2, alignment)
        write_json_atomic(Path(args.output) / "s3_request.json", s3_request_to_dict(request))
        print(f"Wrote S3 request for job {args.job_id}")
        return 0
    except Exception as exc:
        return _fail("prepare", exc)
    finally:
        if conn is not None:
            conn.close()


def cmd_invoke(args) -> int:
    try:
        request_path = Path(args.request)
        request = parse_s3_request(_read(request_path))
        prompt_template = Path(args.prompt_template) if args.prompt_template else S3_PROMPT
        banned_terms = load_banned_terms(Path(args.banned_words))
        from src.tailor.s3 import build_s3_prompt
        prompt = build_s3_prompt(prompt_template.read_text(encoding="utf-8"), request)
        if args.dry_run:
            print(f"[dry-run] S3 prompt validated ({len(prompt)} chars); no model call, trace, or bundle.")
            return 0
        outcome = run_s3_invocation(request, prompt_template_path=prompt_template, request_path=request_path, banned_terms=banned_terms, timeout=args.timeout, trace_dir=Path(args.trace_dir) if args.trace_dir else TRACE_DIR)
        if outcome.kind is not S3OutcomeKind.VALID:
            return _fail("invoke", ValueError(f"{outcome.kind.value}: {outcome.error}"))
        write_json_atomic(Path(args.output) / "s3_bundle.json", s3_bundle_to_dict(outcome.bundle))
        print(f"Wrote S3 bundle for job {request.job_id}")
        return 0
    except Exception as exc:
        return _fail("invoke", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.tailor_s3")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--job-id", type=int, required=True)
    prepare.add_argument("--db", required=True)
    prepare.add_argument("--profile", required=True)
    prepare.add_argument("--s1-request", required=True)
    prepare.add_argument("--s1", required=True)
    prepare.add_argument("--s0-request", required=True)
    prepare.add_argument("--s0", required=True)
    prepare.add_argument("--s2-request", required=True)
    prepare.add_argument("--s2", required=True)
    prepare.add_argument("--output", required=True)
    prepare.set_defaults(func=cmd_prepare)
    invoke = sub.add_parser("invoke")
    invoke.add_argument("--request", required=True)
    invoke.add_argument("--banned-words", required=True)
    invoke.add_argument("--output", required=True)
    invoke.add_argument("--prompt-template")
    invoke.add_argument("--trace-dir")
    invoke.add_argument("--timeout", type=float, default=300)
    invoke.add_argument("--dry-run", action="store_true")
    invoke.set_defaults(func=cmd_invoke)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
