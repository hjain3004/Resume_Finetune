"""Eligibility gate orchestration.

Business policy lives in src.eligibility and config/eligibility.yaml. This
module only adapts pure decisions to idempotent DB helper calls.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass

from src import db
from src.eligibility import (
    EligibilityConfig,
    EligibilityDisposition,
    EligibilityStage,
    evaluate,
)
from src.models import Status


@dataclass(frozen=True)
class EligibilityGateSummary:
    evaluated: int = 0
    filtered: int = 0
    deferred: int = 0
    passed: int = 0
    by_reason: tuple[tuple[str, int], ...] = ()
    by_flag: tuple[tuple[str, int], ...] = ()


def run_pre_resolution_gate(conn: sqlite3.Connection, config: EligibilityConfig) -> EligibilityGateSummary:
    return _run_gate(conn, config, stage=EligibilityStage.PRE_RESOLUTION, status=Status.DISCOVERED)


def run_post_resolution_gate(conn: sqlite3.Connection, config: EligibilityConfig) -> EligibilityGateSummary:
    return _run_gate(conn, config, stage=EligibilityStage.POST_RESOLUTION, status=Status.RESOLVED)


def _run_gate(
    conn: sqlite3.Connection,
    config: EligibilityConfig,
    *,
    stage: EligibilityStage,
    status: Status,
) -> EligibilityGateSummary:
    evaluated = filtered = deferred = passed = 0
    by_reason: Counter[str] = Counter()
    by_flag: Counter[str] = Counter()

    for row in db.eligibility_rows(conn, status):
        evaluated += 1
        existing_flags = _flags_tuple(row["flags"])
        decision = evaluate(
            stage=stage,
            title=row["title"],
            location=row["location"],
            jd_text=row["jd_text"],
            existing_flags=existing_flags,
            config=config,
        )
        if decision.disposition is EligibilityDisposition.FILTER:
            reason = decision.reason_code or "eligibility:unknown"
            if db.mark_eligibility_filtered(conn, row["id"], expected_status=status, reason=reason):
                filtered += 1
                by_reason[reason] += 1
        elif decision.disposition is EligibilityDisposition.DEFER:
            deferred += 1
        else:
            passed += 1
            added_flags = tuple(flag for flag in decision.flags if flag not in existing_flags)
            if added_flags and db.merge_job_flags(conn, row["id"], added_flags):
                for flag in added_flags:
                    by_flag[flag] += 1

    conn.commit()
    return EligibilityGateSummary(
        evaluated=evaluated,
        filtered=filtered,
        deferred=deferred,
        passed=passed,
        by_reason=tuple(sorted(by_reason.items())),
        by_flag=tuple(sorted(by_flag.items())),
    )


def _flags_tuple(raw_flags: str | None) -> tuple[str, ...]:
    if not raw_flags:
        return ()
    return tuple(json.loads(raw_flags))
