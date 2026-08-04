import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.company_bank.model import LookupStatus, PermittedUse
from src.company_bank.serde import CompanyBankValidationError, parse_research_bundle
from src.company_bank.policy import to_company_dossier
from src.company_bank.store import load_company_bank, lookup_company


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Company Bank CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-bundle", help="Validate a research bundle")
    validate_parser.add_argument("bundle_path", type=Path)
    validate_parser.add_argument("bundle_dir", type=Path)

    lookup_parser = subparsers.add_parser("lookup", help="Lookup a company")
    lookup_parser.add_argument("db_path", type=Path)
    lookup_parser.add_argument("query", type=str)
    lookup_parser.add_argument("--business-unit", "-b", type=str)
    lookup_parser.add_argument("--role-family", "-r", type=str)
    lookup_parser.add_argument(
        "--permitted-use", "-u", type=str,
        choices=[u.value for u in PermittedUse],
        default=PermittedUse.S0.value
    )
    lookup_parser.add_argument(
        "--now", type=str,
        help="ISO 8601 UTC timestamp for simulated time"
    )

    args = parser.parse_args(argv)

    if args.command == "validate-bundle":
        return _handle_validate(args)
    elif args.command == "lookup":
        return _handle_lookup(args)
    return 1


def _handle_validate(args: argparse.Namespace) -> int:
    try:
        if not args.bundle_path.is_file():
            print(f"UNREADABLE: {args.bundle_path}", file=sys.stderr)
            return 2
        
        bundle = parse_research_bundle(args.bundle_path)
        dossier = to_company_dossier(bundle, args.bundle_dir)
        print(f"Valid bundle for {dossier.company_id}")
        return 0
    except CompanyBankValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1


def _handle_lookup(args: argparse.Namespace) -> int:
    try:
        bank = load_company_bank(args.db_path)
    except CompanyBankValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return 2

    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if not now.tzinfo:
            now = now.replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    permitted_use = PermittedUse(args.permitted_use)
    
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


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
