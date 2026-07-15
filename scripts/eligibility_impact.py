from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from src import db
from src.eligibility import (
    EligibilityConfig,
    EligibilityConfigError,
    EligibilityDisposition,
    EligibilityStage,
    evaluate,
    load_eligibility_config,
)
from src.models import Status


class ImpactAction(str, Enum):
    FILTER_DISCOVERED = "filter_discovered"
    FILTER_ACTIVE = "filter_active"
    RESTORE_LEGACY = "restore_legacy"
    REPORT_TERMINAL = "report_terminal"


@dataclass(frozen=True)
class ImpactTransition:
    job_id: int
    action: ImpactAction
    from_status: str
    to_status: str | None
    reason_code: str | None
    evidence: tuple[str, ...]


_ACTIVE_STATUSES = {Status.RESOLVED, Status.SCORED, Status.SHORTLISTED}
_TERMINAL_STATUSES = {Status.APPLIED, Status.REJECTED, Status.TAILORED, Status.CLOSED}
_LEGACY_REASONS = {"location", "title_include", "title_exclude"}


def build_impact(conn: sqlite3.Connection, config: EligibilityConfig) -> tuple[ImpactTransition, ...]:
    transitions: list[ImpactTransition] = []
    for row in db.all_rows(conn):
        flags = tuple(json.loads(row["flags"])) if row["flags"] else ()
        status = row["status"]
        if status == Status.DISCOVERED:
            decision = evaluate(
                stage=EligibilityStage.PRE_RESOLUTION,
                title=row["title"],
                location=row["location"],
                jd_text=row["jd_text"],
                existing_flags=flags,
                config=config,
            )
            if decision.disposition is EligibilityDisposition.FILTER:
                transitions.append(
                    ImpactTransition(row["id"], ImpactAction.FILTER_DISCOVERED, status, Status.FILTERED_OUT, decision.reason_code, decision.evidence)
                )
        elif status in _ACTIVE_STATUSES:
            decision = _post_decision(row, flags, config)
            if decision.disposition is EligibilityDisposition.FILTER:
                transitions.append(
                    ImpactTransition(row["id"], ImpactAction.FILTER_ACTIVE, status, Status.FILTERED_OUT, decision.reason_code, decision.evidence)
                )
        elif status == Status.FILTERED_OUT:
            reason = row["filter_reason"]
            if reason in _LEGACY_REASONS or (reason or "").startswith("yoe:"):
                decision = _post_decision(row, flags, config)
                if decision.disposition is EligibilityDisposition.PASS:
                    transitions.append(
                        ImpactTransition(row["id"], ImpactAction.RESTORE_LEGACY, status, Status.RESOLVED, reason, decision.evidence)
                    )
        elif status in _TERMINAL_STATUSES:
            decision = _post_decision(row, flags, config)
            if decision.disposition is EligibilityDisposition.FILTER:
                transitions.append(
                    ImpactTransition(row["id"], ImpactAction.REPORT_TERMINAL, status, None, decision.reason_code, decision.evidence)
                )
    return tuple(sorted(transitions, key=lambda item: (item.action.value, item.job_id)))


def _post_decision(row, flags: tuple[str, ...], config: EligibilityConfig):
    return evaluate(
        stage=EligibilityStage.POST_RESOLUTION,
        title=row["title"],
        location=row["location"],
        jd_text=row["jd_text"],
        existing_flags=flags,
        config=config,
    )


def report_payload(transitions: tuple[ImpactTransition, ...], config: EligibilityConfig) -> dict:
    by_action = Counter(t.action.value for t in transitions)
    by_reason = Counter(t.reason_code for t in transitions if t.reason_code)
    return {
        "version": 1,
        "policy_version": config.version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts_by_action": dict(sorted(by_action.items())),
        "counts_by_reason": dict(sorted(by_reason.items())),
        "transitions": [
            {
                **asdict(t),
                "action": t.action.value,
                "evidence": list(t.evidence),
            }
            for t in transitions
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--backup")
    args = parser.parse_args(argv)

    try:
        config = load_eligibility_config()
        if args.apply:
            if args.confirm != "APPLY" or not args.backup:
                return 2
            backup_path = Path(args.backup)
            if backup_path.exists():
                return 2
            conn = db.get_connection(args.db)
            transitions = build_impact(conn, config)
            _backup_database(conn, backup_path)
            changed = db.apply_eligibility_transitions(conn, tuple(t for t in transitions if t.action is not ImpactAction.REPORT_TERMINAL))
            print(json.dumps({"changed": changed, "previewed": len([t for t in transitions if t.action is not ImpactAction.REPORT_TERMINAL])}, sort_keys=True))
            return 0
        conn = db.get_readonly_connection(args.db)
        transitions = build_impact(conn, config)
        payload = report_payload(transitions, config)
        if args.json:
            path = Path(args.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"counts_by_action": payload["counts_by_action"], "counts_by_reason": payload["counts_by_reason"]}, sort_keys=True))
        return 0
    except (EligibilityConfigError, OSError, sqlite3.Error) as exc:
        print(str(exc))
        return 2


def _backup_database(conn: sqlite3.Connection, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(str(backup_path))
    try:
        conn.backup(dest)
    finally:
        dest.close()


if __name__ == "__main__":
    raise SystemExit(main())
