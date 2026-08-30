"""Offline operator for the early-career resume evidence foundation."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.resume_evidence.importer import import_corpus, validate_corpus
from src.resume_evidence.model import OutcomeTier, ResumeRepresentation, RoleFamily
from src.resume_evidence.policy import validate_doctrine_bundle, validate_outcome_bundle
from src.resume_evidence.report import (
    build_report,
    render_report_markdown,
    report_sha256,
    report_to_dict,
)
from src.resume_evidence.serde import (
    EvidenceValidationError,
    parse_doctrine_candidate,
    parse_outcome_candidate,
)
from src.resume_evidence.store import load_evidence_bank, lookup_outcomes

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _bounded(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return text[:300] if text else type(exc).__name__


def _parse_approved_at(value: str) -> datetime:
    if not _UTC_RE.fullmatch(value):
        raise EvidenceValidationError("approved-at must be YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise EvidenceValidationError(f"approved-at is invalid: {exc}") from exc


def _publish_report(output: Path, markdown: str, payload: dict[str, object]) -> None:
    json_text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".report-stage-", dir=output.parent))
    try:
        (stage / "report.md").write_text(markdown, encoding="utf-8")
        pending = stage / ".report.json.tmp"
        pending.write_text(json_text, encoding="utf-8")
        os.replace(pending, stage / "report.json")
        if output.exists():
            if not output.is_dir():
                raise EvidenceValidationError("report output conflicts with an existing file")
            actual = {
                item.name: item.read_bytes()
                for item in output.iterdir()
                if item.is_file()
            }
            expected = {
                item.name: item.read_bytes()
                for item in stage.iterdir()
                if item.is_file()
            }
            if actual != expected or len(list(output.iterdir())) != len(expected):
                raise EvidenceValidationError(
                    "report output directory conflicts with the reviewed report"
                )
            return
        os.replace(stage, output)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resume-evidence")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_bundle = sub.add_parser("validate-bundle")
    validate_bundle.add_argument("path", type=Path)

    validate_corpus_cmd = sub.add_parser("validate-corpus")
    validate_corpus_cmd.add_argument("--inbox", type=Path, required=True)
    validate_corpus_cmd.add_argument("--manifest", type=Path, required=True)

    report = sub.add_parser("report")
    report.add_argument("--inbox", type=Path, required=True)
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)

    import_cmd = sub.add_parser("import-corpus")
    import_cmd.add_argument("--inbox", type=Path, required=True)
    import_cmd.add_argument("--manifest", type=Path, required=True)
    import_cmd.add_argument("--bank-root", type=Path, required=True)
    import_cmd.add_argument("--approved-report-sha256", required=True)
    import_cmd.add_argument("--approved-at", required=True)

    stats = sub.add_parser("stats")
    stats.add_argument("--bank-root", type=Path, required=True)

    lookup = sub.add_parser("lookup")
    lookup.add_argument("--bank-root", type=Path, required=True)
    lookup.add_argument("--role-family", choices=[item.value for item in RoleFamily])
    lookup.add_argument("--max-months", type=int)
    lookup.add_argument("--outcome-tier", choices=[item.value for item in OutcomeTier])
    lookup.add_argument(
        "--representation", choices=[item.value for item in ResumeRepresentation]
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "validate-bundle":
        bundle = args.path
        if (bundle / "bundle.yaml").is_file():
            candidate = parse_outcome_candidate(bundle / "bundle.yaml")
            validate_outcome_bundle(candidate, bundle)
            print(f"OK: Valid outcome bundle for {candidate.reference_id}.")
        elif (bundle / "record.yaml").is_file():
            candidate = parse_doctrine_candidate(bundle / "record.yaml")
            validate_doctrine_bundle(candidate, bundle)
            print(f"OK: Valid doctrine bundle for {candidate.doctrine_id}.")
        else:
            raise FileNotFoundError(f"no bundle.yaml or record.yaml under {bundle}")
        return 0

    if args.command == "validate-corpus":
        corpus = validate_corpus(args.inbox, args.manifest)
        print(
            f"OK: Valid corpus with {len(corpus.outcomes)} outcomes, "
            f"{len(corpus.doctrine)} doctrine records, and {len(corpus.patterns)} patterns."
        )
        return 0

    if args.command == "report":
        report = build_report(validate_corpus(args.inbox, args.manifest))
        _publish_report(
            args.output, render_report_markdown(report), report_to_dict(report)
        )
        print(f"OK: Report SHA-256 {report_sha256(report)}.")
        return 0

    if args.command == "import-corpus":
        if not _SHA_RE.fullmatch(args.approved_report_sha256):
            raise EvidenceValidationError(
                "approved-report-sha256 must be 64 lowercase hexadecimal characters"
            )
        result = import_corpus(
            args.inbox,
            args.manifest,
            args.bank_root,
            approved_report_sha256=args.approved_report_sha256,
            approved_at=_parse_approved_at(args.approved_at),
        )
        print(
            f"OK: {result.status.value} evidence bank with {result.outcome_count} outcomes, "
            f"{result.doctrine_count} doctrine records, and {result.pattern_count} patterns."
        )
        return 0

    bank = load_evidence_bank(args.bank_root)
    if args.command == "stats":
        print(
            f"outcomes={len(bank.outcomes)} doctrine={len(bank.doctrine)} "
            f"patterns={len(bank.patterns)} corpus_version={bank.corpus_version or '-'}"
        )
        return 0

    matches = lookup_outcomes(
        bank,
        role_family=RoleFamily(args.role_family) if args.role_family else None,
        max_months=args.max_months,
        outcome_tier=OutcomeTier(args.outcome_tier) if args.outcome_tier else None,
        representation=(
            ResumeRepresentation(args.representation) if args.representation else None
        ),
    )
    if not matches:
        print("No matching outcomes.", file=sys.stderr)
        return 3
    for record in matches:
        print(
            f"{record.reference_id}\t{record.role_family.value}\t"
            f"{record.professional_experience_months}\t{record.outcome_tier.value}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(_parser().parse_args(argv))
    except EvidenceValidationError as exc:
        print(f"INVALID: {_bounded(exc)}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {_bounded(exc)}", file=sys.stderr)
        return 2
    except Exception as exc:  # fail closed at the operator boundary
        print(f"INTERNAL: {type(exc).__name__}: {_bounded(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

