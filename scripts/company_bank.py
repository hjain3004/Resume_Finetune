import argparse
import os
import sys
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import json
import time
from urllib.parse import urljoin, urlparse
import urllib.robotparser
import requests
import trafilatura

from src.company_bank.verify import (
    FetchResult,
    SourceVerdict,
    lint_bundle_snapshots,
    verify_bundle_sources,
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - exercised only when Playwright is absent
    sync_playwright = None

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
    verify_sources_parser.add_argument("--render", action="store_true", help="Use Playwright to render JS-heavy pages")
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



# AGENTS.md prime directive 6 forbids LinkedIn scraping. LinkedIn is also one of the
# 31 seed companies, so its own public corporate pages must remain verifiable. These
# three hosts serve corporate/engineering/careers content with no member data.
#
# This allowlist is deliberately a fixed constant and is NOT derived from the bundle's
# official_domains. A guard that consults the data it is guarding can be switched off
# by that data: declaring "linkedin.com" official would otherwise unblock member
# profiles, the job-search product, the feed, and messaging.
LINKEDIN_PUBLIC_HOSTS = frozenset({
    "about.linkedin.com",
    "engineering.linkedin.com",
    "careers.linkedin.com",
})

USER_AGENT = "job-pipeline-source-verifier/0.1 (personal job-search research; contact via repo owner)"
MAX_REDIRECTS = 5


def _linkedin_blocked(host: str) -> bool:
    """True when `host` is a LinkedIn host outside the public-corporate allowlist."""
    host = host.lower().split(":")[0]
    if host.endswith(".linkedin.com") or host == "linkedin.com":
        return host not in LINKEDIN_PUBLIC_HOSTS
    return False


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _domain_allowed(host: str, official_domains: tuple[str, ...]) -> bool:
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in official_domains)


def _url_policy_error(url: str, official_domains: tuple[str, ...]) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return "non-HTTPS URL forbidden by policy"
    if not host:
        return "missing host"
    if _linkedin_blocked(host):
        return "LinkedIn fetch forbidden by policy"
    if not _domain_allowed(host, official_domains):
        return "off-domain redirect"
    return None


class RateLimitedFetcher:
    def __init__(self, delay_seconds: float, page=None):
        if delay_seconds < 2.0:
            raise ValueError("Delay must be at least 2.0s")
        self.delay = delay_seconds
        self.page = page
        self.last_request = {}

    def _sleep_for_host(self, host: str) -> None:
        now = time.time()
        last = self.last_request.get(host, 0)
        if now - last < self.delay:
            time.sleep(self.delay - (now - last))
        self.last_request[host] = time.time()

    def _robots_allowed(self, url: str, host: str, headers: dict[str, str]) -> bool:
        robots_url = f"https://{host}/robots.txt"
        self._sleep_for_host(host)
        try:
            r_resp = requests.get(robots_url, headers=headers, timeout=5, allow_redirects=False)
            if r_resp.status_code == 200:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(r_resp.text.splitlines())
                return rp.can_fetch(headers["User-Agent"], url)
        except Exception:
            pass
        return True

    def _get_once(self, url: str, host: str, headers: dict[str, str]):
        self._sleep_for_host(host)
        return requests.get(url, headers=headers, timeout=20, allow_redirects=False)

    def _render_text(
        self,
        url: str,
        official_domains: tuple[str, ...],
        host: str,
    ) -> tuple[int, str] | None:
        if not self.page:
            return None

        route_handler = None
        if hasattr(self.page, "route"):
            page = self.page

            def route_handler(route):
                request = route.request
                is_main_nav = False
                with suppress(Exception):
                    is_main_nav = (
                        request.is_navigation_request()
                        and getattr(request, "frame", None) == page.main_frame
                    )
                if is_main_nav and _url_policy_error(request.url, official_domains):
                    route.abort()
                    return
                route.continue_()

            self.page.route("**/*", route_handler)

        try:
            self._sleep_for_host(host)
            pw_resp = self.page.goto(url, wait_until="networkidle", timeout=20000)
            self.page.wait_for_timeout(2000)

            final_url = self.page.url
            if _url_policy_error(final_url, official_domains):
                return None

            pw_status = pw_resp.status if pw_resp else 200
            if pw_status == 200:
                pw_text = self.page.evaluate("document.body.innerText")
                if pw_text:
                    return pw_status, pw_text
        finally:
            if route_handler and hasattr(self.page, "unroute"):
                with suppress(Exception):
                    self.page.unroute("**/*", route_handler)
        return None

    def fetch(self, url: str, official_domains: tuple[str, ...]) -> FetchResult:
        headers = {"User-Agent": USER_AGENT}
        current_url = url
        resp = None

        for redirect_count in range(MAX_REDIRECTS + 1):
            error = _url_policy_error(current_url, official_domains)
            if error:
                return FetchResult(url, None, "", error)

            host = _hostname(current_url)
            if not self._robots_allowed(current_url, host, headers):
                return FetchResult(url, None, "", "blocked by robots.txt")

            try:
                resp = self._get_once(current_url, host, headers)
            except requests.exceptions.RequestException:
                time.sleep(self.delay)
                try:
                    resp = self._get_once(current_url, host, headers)
                except requests.exceptions.RequestException as exc2:
                    return FetchResult(url, None, "", str(exc2))

            if resp.status_code not in {301, 302, 303, 307, 308}:
                break
            if redirect_count == MAX_REDIRECTS:
                return FetchResult(url, None, "", "too many redirects")

            location = resp.headers.get("Location")
            if not location:
                return FetchResult(url, None, "", "redirect missing Location")

            next_url = urljoin(current_url, location)
            error = _url_policy_error(next_url, official_domains)
            if error:
                return FetchResult(url, None, "", error)
            current_url = next_url

        if resp is None:
            return FetchResult(url, None, "", "no response")

        if resp.status_code != 200:
            return FetchResult(url, resp.status_code, "", None)

        text = trafilatura.extract(resp.text)
        if not text:
            text = resp.text

        if self.page and len(text) < 500:
            try:
                rendered = self._render_text(current_url, official_domains, _hostname(current_url))
                if rendered:
                    pw_status, pw_text = rendered
                    return FetchResult(url, pw_status, pw_text, None)
            except Exception:
                pass

        return FetchResult(url, resp.status_code, text, None)


class _CliInputError(Exception):
    def __init__(self, code: int, prefix: str, path: Path | None, message: str):
        super().__init__(message)
        self.code = code
        self.prefix = prefix
        self.path = path


def _print_cli_input_error(exc: _CliInputError) -> None:
    if exc.path:
        print(f"{exc.prefix}: {exc.path}: {exc}", file=sys.stderr)
    else:
        print(f"{exc.prefix}: {exc}", file=sys.stderr)


def _gather_bundles(args) -> list[Path]:
    if args.bundle_path and args.inbox:
        raise _CliInputError(2, "UNREADABLE", None, "provide either --inbox or bundle_path, not both")
    if args.bundle_path:
        if not args.bundle_path.is_file():
            raise _CliInputError(2, "UNREADABLE", args.bundle_path, "bundle file does not exist")
        return [args.bundle_path]
    if args.inbox:
        if not args.inbox.is_dir():
            raise _CliInputError(2, "UNREADABLE", args.inbox, "inbox directory does not exist")
        bundles = sorted(args.inbox.glob("*/bundle.json"))
        if not bundles:
            raise _CliInputError(2, "UNREADABLE", args.inbox, "empty inbox")
        return bundles
    raise _CliInputError(2, "UNREADABLE", None, "either --inbox or bundle_path must be provided")


def _load_selected_bundles(args) -> list[tuple[Path, object]]:
    selected = []
    for bp in _gather_bundles(args):
        try:
            bundle = parse_research_bundle(bp)
            to_company_dossier(bundle, bp.parent)
        except CompanyBankValidationError as exc:
            raise _CliInputError(1, "INVALID", bp, str(exc)) from exc
        except Exception as exc:
            raise _CliInputError(2, "UNREADABLE", bp, str(exc)) from exc
        selected.append((bp, bundle))
    return selected


def _resolved_nonexistent_path(path: Path) -> Path:
    parent = path.parent.resolve()
    return parent / path.name


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_json_out_path(json_out: Path | None, bundle_paths: list[Path]) -> None:
    if json_out is None:
        return
    out = _resolved_nonexistent_path(json_out)
    if json_out.exists() and json_out.is_dir():
        raise _CliInputError(2, "UNREADABLE", json_out, "json-out path is a directory")
    for bundle_path in bundle_paths:
        bundle_file = bundle_path.resolve()
        bundle_dir = bundle_path.parent.resolve()
        sources_dir = (bundle_dir / "sources").resolve()
        if out == bundle_file:
            raise _CliInputError(2, "UNREADABLE", json_out, "json-out may not overwrite bundle.json")
        if out == bundle_dir:
            raise _CliInputError(2, "UNREADABLE", json_out, "json-out may not target a bundle directory")
        if _is_relative_to(out, sources_dir):
            raise _CliInputError(2, "UNREADABLE", json_out, "json-out may not be written under sources/")


def _write_json_atomic(path: Path, data: object) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise


def _handle_lint_snapshots(args: argparse.Namespace) -> int:
    try:
        bundles = _load_selected_bundles(args)
    except _CliInputError as exc:
        _print_cli_input_error(exc)
        return exc.code

    findings = []
    for bp, bundle in bundles:
        findings.extend(lint_bundle_snapshots(bundle, bp.parent))

    for f in findings:
        print(f"{f.company_id} {f.source_id}: {f.message}")

    print(f"Total findings: {len(findings)}")
    if args.strict and findings:
        return 1
    return 0

def _handle_verify_sources(args: argparse.Namespace) -> int:
    page = None
    playwright = None
    browser = None

    try:
        bundles = _load_selected_bundles(args)
        _validate_json_out_path(args.json_out, [bp for bp, _ in bundles])
        fetcher = RateLimitedFetcher(args.delay, page=page)

        if args.render:
            if sync_playwright is None:
                print("UNREADABLE: Playwright is unavailable", file=sys.stderr)
                return 2
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch()
            page = browser.new_page(
                viewport={"width": 1280, "height": 720},
                user_agent=USER_AGENT,
                locale="en-US",
            )
            fetcher = RateLimitedFetcher(args.delay, page=page)

        all_results = []
        for bp, bundle in bundles:
            def fetch_wrapper(url):
                return fetcher.fetch(url, bundle.official_domains)

            res = verify_bundle_sources(
                bundle,
                bp.parent,
                fetch_wrapper,
                report_foldable=args.report_foldable,
            )
            all_results.append(res)

        print(f"{'Company':<15} {'Source':<20} {'Verdict':<15} {'Quotes':<10} {'Reason'}")
        print("-" * 80)

        counts = {
            SourceVerdict.VERIFIED: 0,
            SourceVerdict.FAILED: 0,
            SourceVerdict.INCONCLUSIVE: 0,
        }
        json_out = []

        for b_res in all_results:
            company_json = {"company_id": b_res.company_id, "results": []}
            for s_res in b_res.results:
                counts[s_res.verdict] += 1
                q_str = f"{s_res.quotes_found}/{s_res.quotes_checked}"
                print(
                    f"{s_res.company_id:<15} {s_res.source_id:<20} "
                    f"{s_res.verdict.value:<15} {q_str:<10} {s_res.reason}"
                )

                company_json["results"].append({
                    "source_id": s_res.source_id,
                    "url": s_res.url,
                    "verdict": s_res.verdict.value,
                    "reason": s_res.reason,
                    "quotes_checked": s_res.quotes_checked,
                    "quotes_found": s_res.quotes_found,
                })
            json_out.append(company_json)

        print("-" * 80)
        print(
            "Verified: "
            f"{counts[SourceVerdict.VERIFIED]}, "
            f"Failed: {counts[SourceVerdict.FAILED]}, "
            f"Inconclusive: {counts[SourceVerdict.INCONCLUSIVE]}"
        )

        if args.json_out:
            try:
                _write_json_atomic(args.json_out, json_out)
            except OSError as exc:
                print(f"UNREADABLE: json-out {args.json_out}: {exc}", file=sys.stderr)
                return 2

        if counts[SourceVerdict.FAILED] > 0:
            return 1
        if args.strict and counts[SourceVerdict.INCONCLUSIVE] > 0:
            return 2
        return 0
    except _CliInputError as exc:
        _print_cli_input_error(exc)
        return exc.code
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        if browser:
            with suppress(Exception):
                browser.close()
        if playwright:
            with suppress(Exception):
                playwright.stop()


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
