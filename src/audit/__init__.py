"""M7 self-healing audit orchestrator (docs/SELF_HEALING.md §1/§5)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.audit.types import AuditResult, Finding

from src.audit import invariants_db, invariants_export, invariants_llm, invariants_sources

_STATUS_RANK = {"PASS": 0, "SKIP": 0, "WARN": 1, "FAIL": 2}

__all__ = ["Finding", "AuditResult", "run_all", "to_json_dict"]


_CHECKS = [
    invariants_sources.check_i1,
    invariants_sources.check_i2,
    invariants_export.check_i3,
    invariants_export.check_i3b,
    invariants_export.check_i4,
    invariants_export.check_i5,
    invariants_db.check_i6a,
    invariants_db.check_i6b,
    invariants_db.check_i7,
    invariants_db.check_i8,
    invariants_db.check_i9,
    invariants_db.check_i10,
    invariants_llm.check_i11,
    invariants_llm.check_i12,
    invariants_llm.check_i13,
]


def run_all(
    conn: sqlite3.Connection,
    *,
    audit_config: dict,
    filters_config: dict,
    eligibility_config,
    freshness_config: dict,
    repo_root: Path = Path("."),
) -> AuditResult:
    findings = [
        check(conn, audit_config, filters_config, eligibility_config, freshness_config, repo_root)
        for check in _CHECKS
    ]
    overall = "PASS"
    for f in findings:
        if _STATUS_RANK[f.status] > _STATUS_RANK[overall]:
            overall = f.status
    return AuditResult(findings=findings, overall=overall)


def to_json_dict(result: AuditResult, *, date_str: str) -> dict:
    return {
        "date": date_str,
        "overall": result.overall,
        "findings": [
            {"invariant": f.invariant, "status": f.status, "evidence": f.evidence, "detail": f.detail}
            for f in result.findings
        ],
    }
