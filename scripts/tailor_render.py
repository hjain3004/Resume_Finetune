"""Fail-closed one-job bundle-driven render CLI. Rebuilds the authoritative
S3Request from the upstream chain exactly as scripts/tailor_s3.py prepare
does (never trusting a persisted bundle without revalidating it against the
current profile), reparses the accepted bundle via the three-argument
parse_s3_bundle, refuses unless static G1 already passed, and publishes
through render_and_publish."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import db
from src.profile import load_profile
from src.tailor.alignment_view import alignment_from_profile
from src.tailor.g1 import load_banned_terms
from src.tailor.publish import RenderOutcomeKind, render_and_publish
from src.tailor.s0 import build_s0_request, parse_s0_request, parse_s0_response
from src.tailor.s1 import parse_s1_request, parse_s1_response_dict
from src.tailor.s2 import build_s2_request, parse_s2_request, parse_s2_response
from src.tailor.s3 import build_s3_request
from src.tailor.s3_pipeline import parse_s3_bundle


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(label: str, exc: Exception) -> int:
    print(f"tailor_render {label}: {exc}", file=sys.stderr)
    return 1


def _rebuild_s3_request(args):
    """Revalidate the full S1->S0->S2->alignment chain exactly as
    scripts/tailor_s3.py prepare does, returning the authoritative
    S3Request. A stale bundle can never be rendered against a profile it
    was not derived from."""
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


def cmd_render(args) -> int:
    try:
        s3_request = _rebuild_s3_request(args)
        banned_terms = load_banned_terms(Path(args.banned_words))
        raw_bundle = _read(Path(args.bundle))
        bundle = parse_s3_bundle(raw_bundle, s3_request, banned_terms)

        if bundle.g1.status.value != "static_pass":
            raise ValueError(f"static G1 status is {bundle.g1.status.value!r}, not static_pass")

        if args.dry_run:
            print(
                f"[dry-run] render validated for job {s3_request.job_id} "
                f"({s3_request.company} — {s3_request.title}); no pdflatex call, no publication."
            )
            return 0

        profile = load_profile(args.profile)
        canonical_text_by_id = {bullet.bullet_id: bullet.plain_text for bullet in s3_request.alignment.bullets}
        outcome = render_and_publish(
            profile, bundle.draft, root=Path(args.root), template_path=Path(args.template),
            canonical_text_by_id=canonical_text_by_id, s3_bundle_schema_version=bundle.schema_version,
        )
        if outcome.kind not in (RenderOutcomeKind.VALID, RenderOutcomeKind.ALREADY_PUBLISHED):
            return _fail("render", ValueError(f"{outcome.kind.value}: {outcome.error or list(outcome.violations)}"))

        print(f"render {outcome.kind.value}: job {s3_request.job_id} ({s3_request.company} — {s3_request.title})")
        return 0
    except Exception as exc:
        return _fail("render", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.tailor_render")
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render")
    render.add_argument("--job-id", type=int, default=1)
    render.add_argument("--db", required=True)
    render.add_argument("--profile", required=True)
    render.add_argument("--template", required=True)
    render.add_argument("--s1-request", required=True)
    render.add_argument("--s1", required=True)
    render.add_argument("--s0-request", required=True)
    render.add_argument("--s0", required=True)
    render.add_argument("--s2-request", required=True)
    render.add_argument("--s2", required=True)
    render.add_argument("--bundle", required=True)
    render.add_argument("--banned-words", default="config/banned_words.txt")
    render.add_argument("--root", required=True)
    render.add_argument("--dry-run", action="store_true")
    render.set_defaults(func=cmd_render)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
