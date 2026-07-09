"""I6 (prefilter integrity), I7 (idempotency — see Task 10), I8 (state
machine legality), I9 (backfill completeness), I10 (DB referential sanity) —
docs/SELF_HEALING.md §1."""

from __future__ import annotations

import json

from src import db, prefilter
from src.audit import Finding
from src.models import Status

_ACTIVE_LOGIC_VERSION_STATUSES = (
    Status.RESOLVED, Status.SCORED, Status.SHORTLISTED, Status.TAILORED,
)


def check_i6a(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    leak_statuses = (Status.RESOLVED, Status.SCORED, Status.SHORTLISTED, Status.TAILORED, Status.APPLIED)
    evidence = []
    for row in db.all_rows(conn):
        if row["status"] not in leak_statuses:
            continue
        result = prefilter.evaluate(row["title"], row["location"], row["jd_text"], filters_config)
        if result.filtered:
            evidence.append({"id": row["id"], "title": row["title"], "reason": result.reason})
    status = "FAIL" if evidence else "PASS"
    return Finding(invariant="I6a", status=status, evidence=evidence)


def check_i6b(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    cfg = audit_config.get("i6", {})
    high = cfg.get("warn_filtered_pct_above", 0.90)
    low = cfg.get("warn_filtered_pct_below", 0.20)
    latest = db.recent_runs(conn, 1)
    if not latest:
        return Finding(invariant="I6b", status="PASS")
    run = latest[0]
    denom = run["resolved"] + run["filtered_out"]
    if denom == 0:
        return Finding(invariant="I6b", status="PASS")
    pct = run["filtered_out"] / denom
    if pct > high or pct < low:
        return Finding(invariant="I6b", status="WARN", evidence=[{"run_id": run["id"], "filtered_pct": pct}])
    return Finding(invariant="I6b", status="PASS")


def check_i7(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    """I7 (docs/SELF_HEALING.md §1/§3): a full double-pipeline-run idempotency
    check is a weekly/after-src-change action (tests/test_idempotency.py
    already covers it in CI), not a per-run DB-state check — it can't fit the
    <10s/10k-row automatic-audit budget alongside a real second pipeline run.
    Always SKIP here; diff_permitted_drift() below is the reusable piece,
    invoked by `python -m scripts.audit --db-before X --db-after Y`."""
    return Finding(
        invariant="I7", status="SKIP",
        detail="run via tests/test_idempotency.py or `scripts.audit --db-before/--db-after` (weekly cadence, SELF_HEALING §3)",
    )


def diff_permitted_drift(
    rows_before: list[dict],
    rows_after: list[dict],
    *,
    permitted_drift: frozenset[str] = frozenset({"last_seen_at", "repost_count"}),
) -> list[dict]:
    by_id_before = {r["id"]: r for r in rows_before}
    by_id_after = {r["id"]: r for r in rows_after}
    diffs = []
    for row_id, after in by_id_after.items():
        before = by_id_before.get(row_id)
        if before is None:
            diffs.append({"id": row_id, "issue": "row appeared that wasn't in the before snapshot"})
            continue
        changed = [
            field for field in after
            if field not in permitted_drift and before.get(field) != after.get(field)
        ]
        if changed:
            diffs.append({"id": row_id, "changed_fields": changed})
    return diffs


def check_i8(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    evidence = []
    known_statuses = {s.value for s in Status}
    threshold = filters_config.get("score_threshold", 7.0)
    for row in db.all_rows(conn):
        if row["status"] not in known_statuses:
            evidence.append({"id": row["id"], "issue": f"undefined status {row['status']!r}"})
        if row["status"] == Status.DISCOVERED and row["resolve_attempts"] >= 3:
            evidence.append({"id": row["id"], "issue": "DISCOVERED with resolve_attempts >= 3"})
        if row["status"] == Status.SCORED and row["fit_score"] is None:
            evidence.append({"id": row["id"], "issue": "SCORED without fit_score"})
        if row["status"] == Status.SHORTLISTED and (row["fit_score"] is None or row["fit_score"] < threshold):
            evidence.append({"id": row["id"], "issue": "SHORTLISTED below score_threshold"})
    status = "FAIL" if evidence else "PASS"
    return Finding(invariant="I8", status=status, evidence=evidence)


def check_i9(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    stale_flag = audit_config.get("i9", {}).get("stale_flag", "stale_logic_version")
    current_version = audit_config.get("current_logic_version", 1)

    warn_evidence = []
    fail_evidence = []
    for row in db.all_rows(conn):
        if row["status"] not in _ACTIVE_LOGIC_VERSION_STATUSES:
            continue
        version = row["resolved_logic_version"]
        if version is None or version >= current_version:
            continue
        flags = json.loads(row["flags"]) if row["flags"] else []
        if stale_flag in flags:
            fail_evidence.append({"id": row["id"], "resolved_logic_version": version})
        else:
            flags = sorted(set(flags) | {stale_flag})
            conn.execute("UPDATE jobs SET flags = ? WHERE id = ?", (json.dumps(flags), row["id"]))
            conn.commit()
            warn_evidence.append({"id": row["id"], "resolved_logic_version": version})

    if fail_evidence:
        return Finding(invariant="I9", status="FAIL", evidence=fail_evidence)
    if warn_evidence:
        return Finding(invariant="I9", status="WARN", evidence=warn_evidence)
    return Finding(invariant="I9", status="PASS")


def check_i10(conn, audit_config, filters_config, freshness_config, repo_root) -> Finding:
    evidence = []

    dup_keys = conn.execute(
        "SELECT dedup_key, COUNT(*) c FROM jobs GROUP BY dedup_key HAVING c > 1"
    ).fetchall()
    for row in dup_keys:
        evidence.append({"issue": "duplicate dedup_key", "dedup_key": row["dedup_key"]})

    orphaned = conn.execute(
        "SELECT rs.run_id, rs.source FROM run_sources rs LEFT JOIN runs r ON rs.run_id = r.id WHERE r.id IS NULL"
    ).fetchall()
    for row in orphaned:
        evidence.append({"issue": "orphaned run_sources row", "run_id": row["run_id"], "source": row["source"]})

    status = "FAIL" if evidence else "PASS"
    return Finding(invariant="I10", status=status, evidence=evidence)
