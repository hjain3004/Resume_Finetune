"""Narrow CLI for M8P-1 S1 requirement extraction.

Two modes only, one job at a time (deliberate -- the eventual three-job
pilot reviews one job at a time):

    python -m scripts.tailor_s1 prepare --job-id ID --db PATH --output DIR
    python -m scripts.tailor_s1 invoke --request PATH --output DIR [--dry-run]

`prepare` uses a read-only DB connection, validates the job via
`src.db.prepare_tailoring_request`, and writes a deterministic
`s1_request.json`. It never calls the model.

`invoke` reads and strictly validates `s1_request.json`, builds the
self-contained S1 prompt, invokes the tool-disabled model wrapper exactly
once, writes the I11 trace, and atomically publishes `s1.json` only after
every structural and semantic check passes. `--dry-run` builds and
validates the request/prompt without ever calling the model, tracing, or
publishing, and never prints the full JD or prompt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import db
from src.tailor.invoke import DEFAULT_TIMEOUT_SECONDS
from src.tailor.artifacts import write_json_atomic
from src.tailor.s1 import S1ParseError, build_s1_prompt, parse_s1_request, s1_request_to_dict, s1_response_to_dict
from src.tailor.s1_pipeline import S1OutcomeKind, run_s1_invocation

PROMPT_TEMPLATE_PATH = Path("docs/prompts/tailoring_s1.md")
TRACE_DIR = Path("data/traces")
REQUEST_FILENAME = "s1_request.json"
ARTIFACT_FILENAME = "s1.json"


def cmd_prepare(args: argparse.Namespace) -> int:
    try:
        conn = db.get_readonly_connection(args.db)
    except Exception as exc:  # sqlite3.Error, OSError: DB missing/unreadable
        print(f"tailor_s1 prepare: cannot open {args.db!r} read-only: {exc}", file=sys.stderr)
        return 1
    try:
        request = db.prepare_tailoring_request(conn, args.job_id)
    except db.TailoringPrepError as exc:
        print(f"tailor_s1 prepare: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    request_path = Path(args.output) / REQUEST_FILENAME
    write_json_atomic(request_path, s1_request_to_dict(request))
    print(f"Wrote {request_path} for job {request.job_id} ({request.company} — {request.title})")
    return 0


def cmd_invoke(args: argparse.Namespace) -> int:
    request_path = Path(args.request)
    try:
        raw = json.loads(request_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"tailor_s1 invoke: cannot read request {request_path}: {exc}", file=sys.stderr)
        return 1
    try:
        request = parse_s1_request(raw)
    except S1ParseError as exc:
        print(f"tailor_s1 invoke: invalid request: {exc}", file=sys.stderr)
        return 1

    prompt_template_path = Path(args.prompt_template) if args.prompt_template else PROMPT_TEMPLATE_PATH
    try:
        prompt = build_s1_prompt(prompt_template_path.read_text(), request)
    except (OSError, ValueError) as exc:
        print(f"tailor_s1 invoke: cannot build prompt: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(
            f"[dry-run] would invoke S1 for job {request.job_id} "
            f"({request.company} — {request.title}); prompt validated "
            f"({len(prompt)} chars). No model call, no trace, no s1.json."
        )
        return 0

    trace_dir = Path(args.trace_dir) if args.trace_dir else TRACE_DIR
    outcome = run_s1_invocation(
        request,
        prompt_template_path=prompt_template_path,
        request_path=request_path,
        timeout=args.timeout,
        trace_dir=trace_dir,
    )

    if outcome.trace_path is not None:
        print(f"trace: {outcome.trace_path}", file=sys.stderr)

    if outcome.kind != S1OutcomeKind.VALID:
        print(f"tailor_s1 invoke: {outcome.kind.value}: {outcome.error}", file=sys.stderr)
        return 1

    artifact_path = Path(args.output) / ARTIFACT_FILENAME
    write_json_atomic(artifact_path, s1_response_to_dict(outcome.response))
    print(f"Wrote {artifact_path} for job {request.job_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.tailor_s1",
        description="M8P-1 S1 requirement-extraction CLI: prepare a validated request, then invoke the model once.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="Read one SHORTLISTED, ats-quality job and write s1_request.json")
    prepare_parser.add_argument("--job-id", type=int, required=True, metavar="ID")
    prepare_parser.add_argument("--db", default="data/jobs.db", metavar="PATH")
    prepare_parser.add_argument("--output", required=True, metavar="DIR")
    prepare_parser.set_defaults(func=cmd_prepare)

    invoke_parser = subparsers.add_parser("invoke", help="Invoke the tool-disabled S1 model once and publish s1.json")
    invoke_parser.add_argument("--request", required=True, metavar="PATH", help="path to a prepared s1_request.json")
    invoke_parser.add_argument("--output", required=True, metavar="DIR")
    invoke_parser.add_argument("--prompt-template", default=None, metavar="PATH")
    invoke_parser.add_argument("--trace-dir", default=None, metavar="DIR")
    invoke_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    invoke_parser.add_argument("--dry-run", action="store_true")
    invoke_parser.set_defaults(func=cmd_invoke)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
