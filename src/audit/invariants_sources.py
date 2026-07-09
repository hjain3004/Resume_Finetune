"""I1 (source liveness) and I2 (resolution health) — docs/SELF_HEALING.md §1."""

from __future__ import annotations

from urllib.parse import urlparse

from src import db, prefilter
from src.audit import Finding
from src.models import Status


def check_i1(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    cfg = audit_config.get("i1", {})
    warn_n = cfg.get("warn_consecutive_zero_runs", 3)
    fail_n = cfg.get("fail_consecutive_zero_runs", 7)
    limit = cfg.get("trailing_runs_considered", 7)

    worst = "PASS"
    evidence = []
    for source in db.distinct_run_sources(conn):
        rows = db.recent_run_sources_by_source(conn, source, limit)
        streak = 0
        for row in rows:
            if row["discovered"] == 0:
                streak += 1
            else:
                break
        if streak >= fail_n:
            worst = "FAIL"
            evidence.append({"source": source, "consecutive_zero_runs": streak})
        elif streak >= warn_n and worst != "FAIL":
            worst = "WARN"
            evidence.append({"source": source, "consecutive_zero_runs": streak})
    return Finding(invariant="I1", status=worst, evidence=evidence)


def check_i2(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    cfg = audit_config.get("i2", {})
    fail_rate_below = cfg.get("fail_resolve_rate_below", 0.5)
    trailing = cfg.get("trailing_runs_considered", 3)
    warn_domain_count = cfg.get("warn_domain_failure_count", 3)

    status = "PASS"
    evidence = []

    runs = db.recent_runs(conn, trailing)
    total_resolved = sum(r["resolved"] for r in runs)
    total_failed = sum(r["failed"] for r in runs)
    attempted = total_resolved + total_failed
    if attempted > 0 and (total_resolved / attempted) < fail_rate_below:
        status = "FAIL"
        evidence.append({"resolved": total_resolved, "failed": total_failed, "rate": total_resolved / attempted})

    failing_rows = [
        row
        for row in db.all_rows(conn)
        if row["status"] == Status.RESOLVE_FAILED
        and not prefilter.evaluate(row["title"], row["location"], row["jd_text"], filters_config).filtered
    ]
    by_domain: dict[str, list[int]] = {}
    for row in failing_rows:
        hostname = urlparse(row["url"]).hostname or ""
        by_domain.setdefault(hostname, []).append(row["id"])
    for domain, ids in by_domain.items():
        if len(ids) >= warn_domain_count:
            if status != "FAIL":
                status = "WARN"
            evidence.append({"domain": domain, "row_ids": ids, "resolver_gap": True})

    return Finding(invariant="I2", status=status, evidence=evidence)
