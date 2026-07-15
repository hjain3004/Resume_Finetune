"""I11 (LLM I/O traceability), I12 (untrusted-input hardening), I13 (freshness
audit hook) — docs/SELF_HEALING.md §1 and docs/PHASE2_KICKOFF.md M6.8 item 5."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import db
from src.audit import Finding
from src.models import Status

_SCORED_STATUSES = (Status.SCORED, Status.SHORTLISTED, Status.TAILORED, Status.APPLIED, Status.REJECTED)


def check_i11(conn, audit_config, filters_config, eligibility_config, freshness_config, repo_root) -> Finding:
    has_scored_rows = db.has_any_row_with_status(conn, _SCORED_STATUSES)
    if not has_scored_rows:
        return Finding(invariant="I11", status="PASS")

    trace_dir = Path(repo_root) / "data" / "traces"
    has_traces = trace_dir.exists() and any(trace_dir.glob("**/*.json"))
    if has_traces:
        return Finding(invariant="I11", status="PASS")
    return Finding(
        invariant="I11", status="FAIL",
        detail="scored/shortlisted/tailored rows exist but data/traces/ has no trace files",
    )


def _resolve_path(repo_root: Path, relative: str) -> Path:
    candidate = repo_root / relative
    return candidate if candidate.exists() else Path(relative)


def check_i12(conn, audit_config, filters_config, eligibility_config, freshness_config, repo_root) -> Finding:
    cfg = audit_config.get("i12", {})
    root = Path(repo_root)

    missing_phrases = []
    for prompt_file in cfg.get("prompt_files", []):
        path = _resolve_path(root, prompt_file)
        text = path.read_text() if path.exists() else ""
        for phrase in cfg.get("required_phrases", []):
            if phrase.lower() not in text.lower():
                missing_phrases.append({"prompt_file": prompt_file, "missing_phrase": phrase})

    if missing_phrases:
        return Finding(invariant="I12", status="FAIL", evidence=missing_phrases)

    artifacts = cfg.get("imperative_artifacts", [])
    scored_path_dir = root / "data" / "batch"
    warn_evidence = []
    if scored_path_dir.exists():
        scored_files = sorted(p for p in scored_path_dir.glob("*.scored.json"))
        if scored_files:
            scored = json.loads(scored_files[-1].read_text())
            for entry in scored:
                haystack = (entry.get("rationale", "") + " " + " ".join(entry.get("missing_keywords", []))).lower()
                for artifact in artifacts:
                    if artifact.lower() in haystack:
                        warn_evidence.append({"id": entry.get("id"), "artifact": artifact})
                        break

    status = "WARN" if warn_evidence else "PASS"
    return Finding(invariant="I12", status=status, evidence=warn_evidence)


def check_i13(conn, audit_config, filters_config, eligibility_config, freshness_config, repo_root) -> Finding:
    liveness_days = freshness_config.get("liveness_days", 5)
    high_threshold = audit_config.get("i13", {}).get("high_score_threshold", 9.0)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=liveness_days)).isoformat()

    evidence = []
    for row in db.rows_by_status(conn, Status.SHORTLISTED):
        if row["last_seen_at"] is None or row["last_seen_at"] < cutoff:
            evidence.append({"id": row["id"], "issue": "liveness_overdue"})

        flags = json.loads(row["flags"]) if row["flags"] else []
        if "stale_listing" in flags and row["fit_score"] is not None and row["fit_score"] >= high_threshold:
            rationale = (row["fit_rationale"] or "").lower()
            if "stale" not in rationale:
                evidence.append({"id": row["id"], "issue": "stale_rationale_silent"})

    status = "WARN" if evidence else "PASS"
    return Finding(invariant="I13", status=status, evidence=evidence)
