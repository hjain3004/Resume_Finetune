"""CLI entry point for the job-pipeline ingestion run.

Wires discovery (trackers + manual inbox), resolution, pre-filter, and digest
generation end-to-end.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src import audit as audit_module, db, digest, freshness, prefilter, resolve
from src.discover import ADAPTERS, discover_all, inbox_manual
from src.discover import tracker_common
from src.discover.base import DiscoveryIssue, DiscoveryResult
from src.models import Status
from src.eligibility import EligibilityConfigError, load_eligibility_config as _load_eligibility_config
from src.resolve.base import PoliteSession
from src.resolve.browser import BrowserClient, CircuitBreakingBrowserClient, Crawl4AIBrowserClient
from src.resolve.outcomes import ResolutionOutcome, ResolutionOutcomeKind, ResolutionSummary

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

INBOX_SOURCE_NAME = inbox_manual.SOURCE_NAME


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.run_ingest",
        description="Discover, resolve, and filter job postings.",
    )
    parser.add_argument("--dry-run", action="store_true", help="run without writing to the DB or snapshots")
    parser.add_argument("--source", metavar="NAME", help="restrict to a single discovery source")
    parser.add_argument("--resolve-only", action="store_true", help="only run the resolution step")
    parser.add_argument("--discover-only", action="store_true", help="only run the discovery step")
    parser.add_argument("--limit", type=int, metavar="N", help="cap new insertions per source")
    parser.add_argument(
        "--resolve-limit",
        type=_positive_int,
        metavar="N",
        help="cap the number of DISCOVERED rows attempted this run, ordered by id "
        "(M6.10; independent of --limit, which caps discovery insertions)",
    )
    parser.add_argument("--db", metavar="PATH", default="data/jobs.db", help="path to the SQLite database")
    parser.add_argument(
        "--snapshot-dir",
        metavar="DIR",
        help="override tracker snapshot directory",
    )
    parser.add_argument(
        "--digest-dir", metavar="DIR", default="data/digests", help="directory to write the digest markdown to"
    )
    parser.add_argument(
        "--audit-dir", metavar="DIR", default="data/audit", help="directory to write the audit JSON to"
    )
    return parser


def load_sources_config(path: str = "config/sources.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)["sources"]


def load_filters_config(path: str = "config/filters.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_eligibility_config():
    return _load_eligibility_config()


def load_browser_resolver_flag(path: str = "config/sources.yaml") -> bool:
    """M6.5: top-level `browser_resolver` toggle, sibling to `sources:`.
    Defaults to False (pre-M6.5 behavior) when absent."""
    with open(path) as f:
        return bool(yaml.safe_load(f).get("browser_resolver", False))


def load_freshness_config(path: str = "config/freshness.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_audit_config(path: str = "config/audit.yaml") -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    cfg["current_logic_version"] = resolve.LOGIC_VERSION
    return cfg


def _select_sources(sources_cfg: dict, source_name: str | None) -> dict:
    if source_name:
        if source_name == INBOX_SOURCE_NAME:
            return {}
        if source_name not in ADAPTERS or source_name not in sources_cfg:
            raise ValueError(f"unknown or unimplemented source: {source_name}")
        return {source_name: sources_cfg[source_name]}
    return {
        name: cfg for name, cfg in sources_cfg.items() if cfg.get("enabled") and name in ADAPTERS
    }


def _with_snapshot_dir(selected: dict, snapshot_dir: str | None) -> dict:
    if snapshot_dir is None:
        return {name: dict(cfg) for name, cfg in selected.items()}
    return {name: dict(cfg, snapshot_dir=snapshot_dir) for name, cfg in selected.items()}


def _serialize_discovery_issues(issues: tuple[DiscoveryIssue, ...]) -> str | None:
    if not issues:
        return None
    return json.dumps(
        {"discovery_issues": [asdict(issue) for issue in issues]},
        sort_keys=True,
    )


def _resolution_summary_payload(summary: ResolutionSummary) -> dict:
    reason_codes: dict[str, int] = {}
    for issue in summary.issues:
        reason_codes[issue.reason_code] = reason_codes.get(issue.reason_code, 0) + 1
    return {
        "resolved": summary.resolved,
        "content_failed": summary.content_failed,
        "transient": summary.transient,
        "internal": summary.internal,
        "tier1": summary.tier1,
        "tier2": summary.tier2,
        "manual": summary.manual,
        "reason_codes": reason_codes,
    }


def _empty_gate_payload() -> dict:
    return {"evaluated": 0, "filtered": 0, "deferred": 0, "passed": 0, "by_reason": {}, "by_flag": {}}


def _gate_summary_payload(summary: prefilter.EligibilityGateSummary | None) -> dict:
    if summary is None:
        return _empty_gate_payload()
    return {
        "evaluated": summary.evaluated,
        "filtered": summary.filtered,
        "deferred": summary.deferred,
        "passed": summary.passed,
        "by_reason": dict(summary.by_reason),
        "by_flag": dict(summary.by_flag),
    }


def _eligibility_summary_payload(
    eligibility_summary: dict[str, prefilter.EligibilityGateSummary] | None,
) -> dict:
    eligibility_summary = eligibility_summary or {}
    return {
        "pre_resolution": _gate_summary_payload(eligibility_summary.get("pre_resolution")),
        "post_resolution": _gate_summary_payload(eligibility_summary.get("post_resolution")),
    }


def _run_notes(
    *,
    run_outcome: str,
    summary: ResolutionSummary,
    discovery_issues: tuple[DiscoveryIssue, ...] | list[DiscoveryIssue],
    fatal_error: BaseException | None,
    eligibility_summary: dict[str, prefilter.EligibilityGateSummary] | None = None,
) -> str:
    payload = {
        "run_outcome": run_outcome,
        "resolution_summary": _resolution_summary_payload(summary),
        "eligibility_summary": _eligibility_summary_payload(eligibility_summary),
    }
    if discovery_issues:
        payload["discovery_issues"] = [asdict(issue) for issue in discovery_issues]
    if fatal_error is not None:
        payload["fatal_error"] = {
            "type": type(fatal_error).__name__,
            "message": str(fatal_error)[:500],
        }
    return json.dumps(payload, sort_keys=True)


def finalize_run(
    conn,
    run_id: int,
    *,
    summary: ResolutionSummary,
    run_outcome: str,
    fatal_error: BaseException | None,
    discovery_issues: tuple[DiscoveryIssue, ...] | list[DiscoveryIssue],
    browser_client: BrowserClient | None,
    new_count: int,
    filtered_count: int,
    eligibility_summary: dict[str, prefilter.EligibilityGateSummary] | None = None,
) -> None:
    if browser_client is not None:
        try:
            browser_client.close()
        except Exception:
            logger.exception("browser client close failed during run finalization")

    for source, counts in summary.per_source.items():
        db.record_run_source(
            conn,
            run_id,
            source,
            resolved=counts["resolved"],
            failed=counts["failed"],
        )

    db.finish_run(
        conn,
        run_id,
        new_jobs=new_count,
        resolved=summary.resolved,
        failed=summary.content_failed,
        filtered_out=filtered_count,
        tier1_resolved=summary.tier1,
        tier2_resolved=summary.tier2,
        manual_failed=summary.manual,
        notes=_run_notes(
            run_outcome=run_outcome,
            summary=summary,
            discovery_issues=discovery_issues,
            fatal_error=fatal_error,
            eligibility_summary=eligibility_summary,
        ),
    )


def persist_discovery(
    conn,
    result: DiscoveryResult,
    *,
    stale_days: int,
    reopen_days: int,
    dry_run: bool,
) -> tuple[dict[str, int], tuple[DiscoveryIssue, ...]]:
    inserted = db.insert_discovered(
        conn,
        list(result.jobs),
        stale_days=stale_days,
        reopen_days=reopen_days,
    )
    if dry_run:
        return inserted, ()
    issues = []
    for checkpoint in result.checkpoints:
        try:
            tracker_common.commit_checkpoint(checkpoint)
        except OSError as exc:
            logger.exception("checkpoint commit failed for %s", checkpoint.source)
            issues.append(
                DiscoveryIssue(
                    checkpoint.source,
                    "checkpoint",
                    type(exc).__name__,
                    str(exc)[:500],
                )
            )
    return inserted, tuple(issues)


def run_resolution(
    conn,
    session,
    *,
    browser_resolver: bool = False,
    resolve_limit: int | None = None,
    browser_client=None,
    summary: ResolutionSummary | None = None,
) -> ResolutionSummary:
    """Resolve DISCOVERED rows, ordered by id, up to `resolve_limit` (M6.10;
    None means all eligible rows). Returns the `ResolutionSummary` (a fresh
    one if the caller didn't pass one) recording resolved/content-failed/
    transient/internal counts, tier1/tier2/manual tallies, per-source counts,
    and structured issues.

    M6.10 retry-budget correction: only a genuine `CONTENT_FAILURE` (the
    resolver ran and produced nothing acceptable) consumes
    `resolve_attempts`. A `TRANSIENT_FAILURE` (a `requests` transport error or
    a browser-unavailable error) or an `INTERNAL_ERROR` (an exception
    `resolve.attempt()` doesn't specifically recognize -- logged here with a
    full traceback) leaves the row's status/attempts untouched and eligible
    for the next run; neither stops the remaining rows from being attempted
    (this is the same per-row isolation `discover_all()` already applies per
    adapter, now extended past the resolve call to genuinely distinguish
    "this job's content is bad" from "something about this attempt failed")."""
    if summary is None:
        summary = ResolutionSummary()
    manual_domains = resolve.load_manual_domains()
    for row in db.rows_by_status(conn, Status.DISCOVERED, limit=resolve_limit):
        if resolve.is_manual_domain(row["url"], manual_domains):
            status = db.record_resolve_failure(conn, row["id"], force_failed=True)
            summary.record(row, ResolutionOutcome.content_failure("manual_domain"))
            if status == Status.RESOLVE_FAILED:
                summary.manual += 1
            continue

        try:
            outcome = resolve.attempt(
                row["url"], session, browser_resolver=browser_resolver, browser_client=browser_client
            )
        except Exception as exc:
            logger.exception("unexpected resolve error for row %s (%s)", row["id"], row["url"])
            outcome = ResolutionOutcome.internal("unexpected_exception", exc)

        summary.record(row, outcome)

        if outcome.kind == ResolutionOutcomeKind.RESOLVED:
            result = outcome.result
            db.mark_resolved(conn, row["id"], result, logic_version=resolve.LOGIC_VERSION)
            prior_repost = freshness.find_content_repost(
                conn, row["company"], result.jd_text, exclude_row_id=row["id"]
            )
            if prior_repost is not None:
                freshness.record_content_repost(conn, row["id"], prior_repost)
        elif outcome.kind == ResolutionOutcomeKind.CONTENT_FAILURE:
            status = db.record_resolve_failure(conn, row["id"])
            if status == Status.RESOLVE_FAILED:
                summary.manual += 1
        # TRANSIENT_FAILURE / INTERNAL_ERROR: row is left untouched -- already
        # recorded in summary.issues for visibility; eligible again next run.
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sources_cfg = load_sources_config()
    try:
        selected = _select_sources(sources_cfg, args.source)
    except ValueError as exc:
        logger.error(str(exc))
        return 1
    try:
        eligibility_config = load_eligibility_config()
    except EligibilityConfigError as exc:
        logger.error("invalid eligibility config: %s", exc)
        return 1
    freshness_cfg = load_freshness_config()
    browser_resolver = load_browser_resolver_flag()

    db_path = ":memory:" if args.dry_run else args.db
    conn = db.get_connection(db_path)
    run_id = db.start_run(conn)

    new_count = 0
    discovery_result = DiscoveryResult((), (), (), ())
    discovery_issues: tuple[DiscoveryIssue, ...] = ()
    filtered_count = 0
    eligibility_summary: dict[str, prefilter.EligibilityGateSummary] = {}
    resolution_summary = ResolutionSummary()
    audit_result = None
    browser_client: BrowserClient | None = None
    session = None
    exit_code = 0
    run_outcome = "completed"
    fatal_error: BaseException | None = None
    write_digest = False

    try:
        if not args.resolve_only:
            selected = _with_snapshot_dir(selected, args.snapshot_dir)
            discovery_result = discover_all(selected, limit=args.limit, dry_run=args.dry_run)
            inserted_by_source, checkpoint_issues = persist_discovery(
                conn,
                discovery_result,
                stale_days=freshness_cfg["stale_days"],
                reopen_days=freshness_cfg["reopen_days"],
                dry_run=args.dry_run,
            )
            discovery_issues = discovery_result.issues + checkpoint_issues
            discovered = discovery_result.jobs
            new_count = sum(inserted_by_source.values())
            print(f"Discovered {len(discovered)} job(s), {new_count} new, from {len(selected)} source(s).")
            for job in discovered:
                print(f"  - {job.company}: {job.title} [{job.source}]")

            discovered_by_source = Counter(job.source for job in discovered)
            for source in selected:
                db.record_run_source(
                    conn,
                    run_id,
                    source,
                    discovered=discovered_by_source.get(source, 0),
                    inserted=inserted_by_source.get(source, 0),
                )

            if args.source is None or args.source == INBOX_SOURCE_NAME:
                inbox_result = inbox_manual.ingest(conn, {"dry_run": args.dry_run})
                inbox_new = inbox_result.new_urls + inbox_result.new_pastes
                new_count += inbox_new
                print(
                    f"Inbox: {inbox_result.new_urls} URL(s), {inbox_result.new_pastes} paste(s) ingested."
                )
                db.record_run_source(
                    conn, run_id, INBOX_SOURCE_NAME, discovered=inbox_new, inserted=inbox_new
                )

        all_selected_failed = (
            not args.resolve_only and bool(selected) and not discovery_result.succeeded_sources
        )
        checkpoint_failed = any(issue.stage == "checkpoint" for issue in discovery_issues)

        if not args.discover_only:
            pre_summary = prefilter.run_pre_resolution_gate(conn, eligibility_config)
            eligibility_summary["pre_resolution"] = pre_summary
            filtered_count += pre_summary.filtered

            if db.eligibility_rows(conn, Status.DISCOVERED):
                session = PoliteSession()
                if browser_resolver:
                    browser_client = CircuitBreakingBrowserClient(Crawl4AIBrowserClient())
                run_resolution(
                    conn,
                    session,
                    browser_resolver=browser_resolver,
                    resolve_limit=args.resolve_limit,
                    browser_client=browser_client,
                    summary=resolution_summary,
                )
            print(f"Resolved {resolution_summary.resolved} job(s), {resolution_summary.content_failed} failed.")

            post_summary = prefilter.run_post_resolution_gate(conn, eligibility_config)
            eligibility_summary["post_resolution"] = post_summary
            filtered_count += post_summary.filtered
            print(f"Filtered out {filtered_count} job(s).")

            if not args.resolve_only:
                if session is None:
                    session = PoliteSession()
                closed_count = freshness.run_liveness_recheck(conn, session, freshness_cfg["liveness_days"])
                print(f"Liveness recheck: {closed_count} job(s) closed.")

        if not args.discover_only and not args.resolve_only:
            audit_result = audit_module.run_all(
                conn,
                audit_config=load_audit_config(),
                filters_config=load_filters_config(),
                freshness_config=freshness_cfg,
            )
            print(f"Audit: {audit_result.overall} ({len(audit_result.findings)} invariant(s) checked)")
            if not args.dry_run:
                audit_out_dir = Path(args.audit_dir)
                audit_out_dir.mkdir(parents=True, exist_ok=True)
                audit_date_str = datetime.now(timezone.utc).date().isoformat()
                (audit_out_dir / f"{audit_date_str}.json").write_text(
                    json.dumps(audit_module.to_json_dict(audit_result, date_str=audit_date_str), indent=2)
                )
            write_digest = True

        exit_code = 1 if all_selected_failed or checkpoint_failed else 0
    except BaseException as exc:
        run_outcome = "aborted"
        fatal_error = exc
        raise
    finally:
        finalize_run(
            conn,
            run_id,
            summary=resolution_summary,
            run_outcome=run_outcome,
            fatal_error=fatal_error,
            discovery_issues=discovery_issues,
            browser_client=browser_client,
            new_count=new_count,
            filtered_count=filtered_count,
            eligibility_summary=eligibility_summary,
        )

    if write_digest:
        run_row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if args.dry_run:
            print(digest.build_digest(conn, run_row, audit_result=audit_result))
        else:
            digest_path = digest.write_digest(conn, run_row, base_dir=args.digest_dir, audit_result=audit_result)
            print(f"Digest written to {digest_path}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
