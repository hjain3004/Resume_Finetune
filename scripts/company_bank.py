import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.company_bank.importer import import_corpus, validate_corpus
from src.company_bank.model import LookupStatus, PermittedUse
from src.company_bank.policy import to_company_dossier
from src.company_bank.serde import (
    CompanyBankValidationError,
    parse_research_bundle,
    parse_utc_timestamp,
)
from src.company_bank.store import load_company_bank


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Company Bank CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_bundle_parser = subparsers.add_parser("validate-bundle", help="Validate a research bundle")
    validate_bundle_parser.add_argument("bundle_path", type=Path)

    validate_corpus_parser = subparsers.add_parser("validate-corpus", help="Validate a corpus inbox")
    validate_corpus_parser.add_argument("--inbox", type=Path, required=True)
    validate_corpus_parser.add_argument("--seeds", type=Path, required=True)
    validate_corpus_parser.add_argument("--now", type=str)

    import_corpus_parser = subparsers.add_parser("import-corpus", help="Import a corpus inbox")
    import_corpus_parser.add_argument("--inbox", type=Path, required=True)
    import_corpus_parser.add_argument("--bank-root", type=Path, required=True)
    import_corpus_parser.add_argument("--seeds", type=Path, required=True)
    import_corpus_parser.add_argument("--now", type=str)

    lookup_parser = subparsers.add_parser("lookup", help="Lookup a company")
    lookup_parser.add_argument("query", type=str)
    lookup_parser.add_argument("--bank-root", type=Path, required=True)
    lookup_parser.add_argument("--business-unit", "-b", type=str)
    lookup_parser.add_argument("--role-family", "-r", type=str)
    lookup_parser.add_argument(
        "--use", type=str,
        choices=[u.value for u in PermittedUse],
        default=PermittedUse.S0.value
    )
    lookup_parser.add_argument("--now", type=str)

    return parser


def _parse_now(now_str: str | None) -> datetime:
    if now_str:
        return parse_utc_timestamp(now_str, "now")
    return datetime.now(timezone.utc)


def _handle_validate_bundle(args: argparse.Namespace) -> int:
    try:
        if not args.bundle_path.is_file():
            print(f"UNREADABLE: {args.bundle_path}", file=sys.stderr)
            return 2
        
        bundle = parse_research_bundle(args.bundle_path)
        dossier = to_company_dossier(bundle, args.bundle_path.parent)
        print(f"OK: Valid bundle for {dossier.company_id}")
        return 0
    except CompanyBankValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return 2


def _handle_validate_corpus(args: argparse.Namespace) -> int:
    try:
        now = _parse_now(args.now)
        dossiers = validate_corpus(args.inbox, args.seeds, now=now)
        print(f"Valid corpus with {len(dossiers)} companies")
        return 0
    except CompanyBankValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return 2


def _handle_import_corpus(args: argparse.Namespace) -> int:
    try:
        now = _parse_now(args.now)
        res = import_corpus(args.inbox, args.bank_root, args.seeds, now=now)
        print(f"Import {res.status.value}: {res.company_count} companies at {res.target}")
        return 0
    except CompanyBankValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return 2


def _handle_lookup(args: argparse.Namespace) -> int:
    try:
        bank = load_company_bank(args.bank_root)
    except CompanyBankValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return 2

    try:
        now = _parse_now(args.now)
    except Exception as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    permitted_use = PermittedUse(args.use)
    
    from src.company_bank.store import lookup_company
    res = lookup_company(
        bank,
        args.query,
        now=now,
        business_unit=args.business_unit,
        role_family=args.role_family,
        permitted_use=permitted_use,
    )

    if res.status == LookupStatus.FRESH:
        print(f"FRESH: {res.company_id}")
        return 0
    else:
        print(f"{res.status.name}: {res.message}", file=sys.stderr)
        return 3


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-bundle":
        return _handle_validate_bundle(args)
    elif args.command == "validate-corpus":
        return _handle_validate_corpus(args)
    elif args.command == "import-corpus":
        return _handle_import_corpus(args)
    elif args.command == "lookup":
        return _handle_lookup(args)
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
