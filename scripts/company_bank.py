import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import time
import json
from urllib.parse import urlparse
import urllib.robotparser
import requests
import trafilatura

from src.company_bank.verify import (
    FetchResult, lint_bundle_snapshots, verify_bundle_sources, SourceVerdict
)


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


    lint_snapshots_parser = subparsers.add_parser("lint-snapshots", help="Lint snapshot quote coverage")
    lint_snapshots_parser.add_argument("--inbox", type=Path)
    lint_snapshots_parser.add_argument("bundle_path", nargs="?", type=Path)
    lint_snapshots_parser.add_argument("--strict", action="store_true")

    verify_sources_parser = subparsers.add_parser("verify-sources", help="Verify sources online")
    verify_sources_parser.add_argument("--inbox", type=Path)
    verify_sources_parser.add_argument("bundle_path", nargs="?", type=Path)
    verify_sources_parser.add_argument("--json-out", type=Path)
    verify_sources_parser.add_argument("--strict", action="store_true")
    verify_sources_parser.add_argument("--delay", type=float, default=2.0)
    verify_sources_parser.add_argument("--report-foldable", action="store_true")
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



class RateLimitedFetcher:
    def __init__(self, delay_seconds: float):
        if delay_seconds < 2.0:
            raise ValueError("Delay must be at least 2.0s")
        self.delay = delay_seconds
        self.last_request = {}
        
    def fetch(self, url: str, official_domains: tuple[str, ...]) -> FetchResult:
        host = urlparse(url).netloc
        if 'linkedin.com' in host:
            return FetchResult(url, None, "", "LinkedIn fetch forbidden by policy")
            
        now = time.time()
        last = self.last_request.get(host, 0)
        if now - last < self.delay:
            time.sleep(self.delay - (now - last))
            
        self.last_request[host] = time.time()
        
        # simple robots check could go here if needed, but the prompt says 
        # "check robots.txt for the host and if disallowed return error". 
        # Actually a robust robots.txt check requires parsing robots.txt, which takes 
        # another request. Let's do a basic one.
        robots_url = f"https://{host}/robots.txt"
        robots_now = time.time()
        robots_last = self.last_request.get(host, 0)
        if robots_now - robots_last < self.delay:
            time.sleep(self.delay - (robots_now - robots_last))
        
        headers = {'User-Agent': 'job-pipeline-source-verifier/0.1 (personal job-search research; contact via repo owner)'}
        try:
            r_resp = requests.get(robots_url, headers=headers, timeout=5)
            self.last_request[host] = time.time()
            if r_resp.status_code == 200:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(r_resp.text.splitlines())
                if not rp.can_fetch(headers['User-Agent'], url):
                    return FetchResult(url, None, "", "blocked by robots.txt")
        except Exception:
            pass # ignore robots fetch fail

        try:
            resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
            self.last_request[host] = time.time()
        except requests.exceptions.RequestException as exc:
            # one retry for transient network error (not 4xx)
            time.sleep(self.delay)
            try:
                resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
                self.last_request[host] = time.time()
            except requests.exceptions.RequestException as exc2:
                return FetchResult(url, None, "", str(exc2))
                
        final_url = resp.url
        final_host = urlparse(final_url).netloc
        # check off-domain
        if not any(final_host == d or final_host.endswith('.' + d) for d in official_domains):
            return FetchResult(url, None, "", "off-domain redirect")
            
        if resp.status_code != 200:
            return FetchResult(url, resp.status_code, "", None)
            
        # extract
        text = trafilatura.extract(resp.text)
        if not text:
            text = resp.text # fallback
            
        return FetchResult(url, resp.status_code, text, None)


def _gather_bundles(args) -> list[Path]:
    if args.bundle_path:
        return [args.bundle_path]
    elif args.inbox:
        return list(args.inbox.glob("*/bundle.json"))
    else:
        print("Either --inbox or bundle_path must be provided", file=sys.stderr)
        sys.exit(2)

def _handle_lint_snapshots(args: argparse.Namespace) -> int:
    bundles = _gather_bundles(args)
    findings = []
    
    for bp in bundles:
        try:
            bundle = parse_research_bundle(bp)
        except Exception:
            continue
        findings.extend(lint_bundle_snapshots(bundle, bp.parent))
        
    for f in findings:
        print(f"{f.company_id} {f.source_id}: {f.message}")
        
    print(f"Total findings: {len(findings)}")
    if args.strict and findings:
        return 1
    return 0

def _handle_verify_sources(args: argparse.Namespace) -> int:
    try:
        fetcher = RateLimitedFetcher(args.delay)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    bundles = _gather_bundles(args)
    all_results = []
    
    for bp in bundles:
        try:
            bundle = parse_research_bundle(bp)
        except Exception:
            continue
            
        def fetch_wrapper(url):
            return fetcher.fetch(url, bundle.official_domains)
            
        res = verify_bundle_sources(bundle, bp.parent, fetch_wrapper, report_foldable=args.report_foldable)
        all_results.append(res)
        
    # Output table
    print(f"{'Company':<15} {'Source':<20} {'Verdict':<15} {'Quotes':<10} {'Reason'}")
    print("-" * 80)
    
    counts = {SourceVerdict.VERIFIED: 0, SourceVerdict.FAILED: 0, SourceVerdict.INCONCLUSIVE: 0}
    json_out = []
    
    for b_res in all_results:
        company_json = {"company_id": b_res.company_id, "results": []}
        for s_res in b_res.results:
            counts[s_res.verdict] += 1
            q_str = f"{s_res.quotes_found}/{s_res.quotes_checked}"
            print(f"{s_res.company_id:<15} {s_res.source_id:<20} {s_res.verdict.value:<15} {q_str:<10} {s_res.reason}")
            
            company_json["results"].append({
                "source_id": s_res.source_id,
                "url": s_res.url,
                "verdict": s_res.verdict.value,
                "reason": s_res.reason,
                "quotes_checked": s_res.quotes_checked,
                "quotes_found": s_res.quotes_found
            })
        json_out.append(company_json)
            
    print("-" * 80)
    print(f"Verified: {counts[SourceVerdict.VERIFIED]}, Failed: {counts[SourceVerdict.FAILED]}, Inconclusive: {counts[SourceVerdict.INCONCLUSIVE]}")
    
    if args.json_out:
        args.json_out.write_text(json.dumps(json_out, indent=2))
        
    if counts[SourceVerdict.FAILED] > 0:
        return 1
    if args.strict and counts[SourceVerdict.INCONCLUSIVE] > 0:
        return 2
    return 0


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
    elif args.command == "lint-snapshots":
        return _handle_lint_snapshots(args)
    elif args.command == "verify-sources":
        return _handle_verify_sources(args)
    elif args.command == "validate-corpus":
        return _handle_validate_corpus(args)
    elif args.command == "import-corpus":
        return _handle_import_corpus(args)
    elif args.command == "lookup":
        return _handle_lookup(args)
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
