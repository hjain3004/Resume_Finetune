"""Fail-closed one-job G2 critic + bounded revision CLI. Mirrors
scripts/tailor_s3.py exactly: prepare revalidates the entire upstream
chain plus the accepted S3 bundle; invoke never trusts a persisted file
without rebuilding the authoritative context it must match.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import db
from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.artifacts import write_json_atomic
from src.tailor.g1 import load_banned_terms
from src.tailor.g2 import load_taste_lessons
from src.tailor.g2_pipeline import G2OutcomeKind, g2_bundle_to_dict, run_g2_loop
from src.tailor.s0 import build_s0_request, parse_s0_request, parse_s0_response
from src.tailor.s1 import parse_s1_request, parse_s1_response_dict
from src.tailor.s2 import build_s2_request, parse_s2_request, parse_s2_response
from src.tailor.s3 import build_s3_request, parse_s3_request, s3_request_to_dict
from src.tailor.s3_pipeline import parse_s3_bundle

G2_PROMPT = Path("docs/prompts/tailoring_g2.md")
S3_REVISION_PROMPT = Path("docs/prompts/tailoring_s3.md")
BANNED_WORDS = Path("config/banned_words.txt")
TASTE = Path("config/taste.md")
TRACE_DIR = Path("data/traces")


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(label: str, exc: Exception) -> int:
    print(f"tailor_g2 {label}: {exc}", file=sys.stderr)
    return 1


def _rebuild_s3_request(args):
    """Revalidate the full S1->S0->S2->alignment chain exactly as
    scripts/tailor_s3.py prepare does, returning the authoritative
    S3Request. Never trusts a persisted upstream artifact merely because
    it exists on disk."""
    conn = db.get_readonly_connection(args.db)
    try:
        authoritative_s1_request = db.prepare_tailoring_request(conn, args.job_id)
        variant = db.tailoring_base_variant(conn, args.job_id)
        s1_request = parse_s1_request(_read(Path(args.s1_request)))
        if s1_request != authoritative_s1_request:
            raise ValueError("persisted S1 request does not match eligible DB row")
        s1 = parse_s1_response_dict(_read(Path(args.s1)), authoritative_s1_request.jd_text)
        if s1.suspected_injection:
            raise ValueError("S1 artifact is injection-blocked")
        profile = load_profile(args.profile)
        positioning = profile.for_positioning()
        canonical_catalog = profile.for_selection(variant)
        s0_request = build_s0_request(args.job_id, authoritative_s1_request.company, authoritative_s1_request.title, s1, positioning)
        persisted_s0_request = parse_s0_request(_read(Path(args.s0_request)))
        if persisted_s0_request != s0_request:
            raise ValueError("persisted S0 request does not match authoritative S1 and profile")
        s0 = parse_s0_response(json.dumps(_read(Path(args.s0))), s0_request)
        persisted_s2_request = parse_s2_request(_read(Path(args.s2_request)))
        canonical_s2_request = build_s2_request(args.job_id, authoritative_s1_request.company, authoritative_s1_request.title, s1, s0, canonical_catalog)
        if persisted_s2_request != canonical_s2_request:
            raise ValueError("persisted S2 request does not match authoritative chain")
        s2 = parse_s2_response(json.dumps(_read(Path(args.s2))), canonical_s2_request)
        alignment = alignment_from_profile(profile, canonical_s2_request, s2)
        return build_s3_request(args.job_id, authoritative_s1_request.company, authoritative_s1_request.title, s1, s0, s2, alignment)
    finally:
        conn.close()


def cmd_prepare(args) -> int:
    try:
        s3_request = _rebuild_s3_request(args)
        banned_terms = load_banned_terms(Path(args.banned_words))
        raw_bundle = _read(Path(args.bundle))
        # Revalidate the accepted S3 bundle against the freshly rebuilt
        # authoritative request -- a persisted bundle is never trusted
        # merely because it exists.
        parse_s3_bundle(raw_bundle, s3_request, banned_terms)

        write_json_atomic(Path(args.output) / "s3_request.json", s3_request_to_dict(s3_request))
        write_json_atomic(Path(args.output) / "g2_request.json", raw_bundle)
        print(f"Wrote G2 preparation artifacts for job {args.job_id}")
        return 0
    except Exception as exc:
        return _fail("prepare", exc)


def cmd_invoke(args) -> int:
    try:
        s3_request_path = Path(args.s3_request)
        s3_request = parse_s3_request(_read(s3_request_path))
        banned_terms = load_banned_terms(Path(args.banned_words))
        raw_bundle = _read(Path(args.request))
        s3_bundle = parse_s3_bundle(raw_bundle, s3_request, banned_terms)

        g2_prompt_template = Path(args.prompt_template) if args.prompt_template else G2_PROMPT
        s3_prompt_template = Path(args.s3_prompt_template) if args.s3_prompt_template else S3_REVISION_PROMPT
        taste_path = Path(args.taste) if getattr(args, "taste", None) else TASTE
        taste_lessons = load_taste_lessons(taste_path) if taste_path.exists() else ()

        if args.dry_run:
            print(
                f"[dry-run] G2 review validated for job {s3_request.job_id} "
                f"({s3_request.company} — {s3_request.title}); no model call, trace, or bundle."
            )
            return 0

        trace_dir = Path(args.trace_dir) if args.trace_dir else TRACE_DIR
        outcome = run_g2_loop(
            s3_request, s3_bundle,
            prompt_template_path=g2_prompt_template,
            s3_prompt_template_path=s3_prompt_template,
            request_path=s3_request_path,
            banned_terms=banned_terms,
            taste_lessons=taste_lessons,
            timeout=args.timeout,
            trace_dir=trace_dir,
            max_rounds=args.max_rounds,
        )
        for trace_path in outcome.trace_paths:
            print(f"trace: {trace_path}", file=sys.stderr)

        if outcome.kind not in (G2OutcomeKind.PASSED_ROUND_1, G2OutcomeKind.PASSED_ROUND_2, G2OutcomeKind.OPEN_FLAGS):
            return _fail("invoke", ValueError(f"{outcome.kind.value}: {outcome.error}"))

        write_json_atomic(Path(args.output) / "g2_bundle.json", g2_bundle_to_dict(outcome.bundle))
        print(f"Wrote G2 bundle for job {s3_request.job_id} ({outcome.kind.value})")
        return 0
    except Exception as exc:
        return _fail("invoke", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.tailor_g2")
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
    prepare.add_argument("--bundle", required=True, help="path to the accepted s3_bundle.json to review")
    prepare.add_argument("--banned-words", default=str(BANNED_WORDS))
    prepare.add_argument("--taste", default=str(TASTE))
    prepare.add_argument("--output", required=True)
    prepare.set_defaults(func=cmd_prepare)

    invoke = sub.add_parser("invoke")
    invoke.add_argument("--request", required=True, help="path to the (revalidated) accepted s3_bundle.json")
    invoke.add_argument("--s3-request", required=True, help="path to the prepared, authoritative s3_request.json")
    invoke.add_argument("--banned-words", default=str(BANNED_WORDS))
    invoke.add_argument("--taste", default=str(TASTE))
    invoke.add_argument("--output", required=True)
    invoke.add_argument("--prompt-template")
    invoke.add_argument("--s3-prompt-template")
    invoke.add_argument("--trace-dir")
    invoke.add_argument("--timeout", type=float, default=300)
    invoke.add_argument("--max-rounds", type=int, default=2)
    invoke.add_argument("--dry-run", action="store_true")
    invoke.set_defaults(func=cmd_invoke)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
