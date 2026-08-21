"""M9F-0 repair regressions: per-run credit enforcement (defect 1) and
ledger-state-aware budget accounting (defect 3).

Offline only. No network, no real ledger path, no credentials.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.firecrawl.budget import (
    BudgetExhaustedError,
    BudgetManager,
    LedgerCorruptError,
)


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "usage-v1.json"


@pytest.fixture
def cfg():
    """Per-run cap of 10 is the binding limit; daily/monthly/purpose are slack."""
    return {
        "limits": {
            "monthly_credits": 800,
            "daily_credits": 500,
            "per_run_credits": 10,
            "monthly_by_purpose": {"resolution": 500, "discovery": 250, "research": 50},
        },
        "cooldowns": {"failed_url_hours": 24},
    }


def _mgr(cfg, ledger, run_ref):
    return BudgetManager(cfg, ledger_path=str(ledger), run_ref=run_ref)


# ---------------------------------------------------------------- defect 1


def test_first_ten_reservations_in_a_run_succeed(cfg, ledger):
    mgr = _mgr(cfg, ledger, "run-1")
    for i in range(10):
        assert mgr.reserve("resolution", f"https://e.com/{i}", 1) is not None


def test_eleventh_reservation_in_one_run_exceeds_per_run_cap(cfg, ledger):
    mgr = _mgr(cfg, ledger, "run-1")
    for i in range(10):
        mgr.reserve("resolution", f"https://e.com/{i}", 1)

    with pytest.raises(BudgetExhaustedError, match="per-run"):
        mgr.reserve("resolution", "https://e.com/11", 1)


def test_second_run_gets_an_independent_per_run_allowance(cfg, ledger):
    first = _mgr(cfg, ledger, "run-1")
    for i in range(10):
        first.reserve("resolution", f"https://e.com/{i}", 1)

    second = _mgr(cfg, ledger, "run-2")
    assert second.reserve("resolution", "https://e.com/next", 1) is not None


def test_both_runs_still_contribute_to_daily_and_monthly_and_purpose(cfg, ledger):
    cfg["limits"]["daily_credits"] = 12
    first = _mgr(cfg, ledger, "run-1")
    for i in range(10):
        first.reserve("resolution", f"https://e.com/a{i}", 1)

    second = _mgr(cfg, ledger, "run-2")
    second.reserve("resolution", "https://e.com/b0", 1)
    second.reserve("resolution", "https://e.com/b1", 1)

    with pytest.raises(BudgetExhaustedError, match="daily"):
        second.reserve("resolution", "https://e.com/b2", 1)


def test_per_run_cap_survives_a_ledger_reload(cfg, ledger):
    for i in range(10):
        _mgr(cfg, ledger, "run-1").reserve("resolution", f"https://e.com/{i}", 1)

    reloaded = _mgr(cfg, ledger, "run-1")
    with pytest.raises(BudgetExhaustedError, match="per-run"):
        reloaded.reserve("resolution", "https://e.com/11", 1)


def test_dry_run_checks_per_run_cap_but_writes_no_record(cfg, ledger):
    mgr = _mgr(cfg, ledger, "run-1")
    for i in range(10):
        mgr.reserve("resolution", f"https://e.com/{i}", 1)

    with pytest.raises(BudgetExhaustedError, match="per-run"):
        mgr.reserve("resolution", "https://e.com/11", 1, dry_run=True)

    assert len(json.loads(ledger.read_text())) == 10


def test_legacy_record_without_run_ref_does_not_consume_current_run_allowance(cfg, ledger):
    """A schema-v1 record predating run_ref belongs to a past run. It must still
    count toward daily/monthly/purpose, but never against this run's allowance."""
    legacy = [
        {
            "version": 1,
            "request_id": f"legacy-{i}",
            "reserved_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "purpose": "resolution",
            "job_ref": None,
            "url_sha256": "0" * 64,
            "reserved_credits": 1,
            "actual_credits": None,
            "state": "reserved",
            "outcome_class": None,
            "provider_id": None,
            "cooldown_until": None,
        }
        for i in range(10)
    ]
    ledger.write_text(json.dumps(legacy))

    mgr = _mgr(cfg, ledger, "run-1")
    assert mgr.reserve("resolution", "https://e.com/new", 1) is not None


# ---------------------------------------------------------------- defect 3


def _seed(ledger, *, state, count, run_ref="run-1", credits=1):
    rows = [
        {
            "version": 1,
            "request_id": f"{state}-{i}",
            "run_ref": run_ref,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "purpose": "resolution",
            "job_ref": None,
            "url_sha256": f"{i:064d}",
            "reserved_credits": credits,
            "actual_credits": None,
            "state": state,
            "outcome_class": None,
            "provider_id": None,
            "cooldown_until": None,
        }
        for i in range(count)
    ]
    ledger.write_text(json.dumps(rows))


def test_cleared_records_release_per_run_allowance(cfg, ledger):
    _seed(ledger, state="cleared", count=10)
    mgr = _mgr(cfg, ledger, "run-1")
    assert mgr.reserve("resolution", "https://e.com/new", 1) is not None


def test_cleared_records_release_daily_monthly_and_purpose(cfg, ledger):
    cfg["limits"]["daily_credits"] = 10
    cfg["limits"]["monthly_by_purpose"]["resolution"] = 10
    _seed(ledger, state="cleared", count=10, run_ref="old-run")
    mgr = _mgr(cfg, ledger, "run-new")
    assert mgr.reserve("resolution", "https://e.com/new", 1) is not None


def test_charged_records_do_not_release_allowance(cfg, ledger):
    _seed(ledger, state="charged", count=10)
    mgr = _mgr(cfg, ledger, "run-1")
    with pytest.raises(BudgetExhaustedError, match="per-run"):
        mgr.reserve("resolution", "https://e.com/new", 1)


def test_unknown_ledger_state_fails_closed(cfg, ledger):
    _seed(ledger, state="banana", count=1)
    mgr = _mgr(cfg, ledger, "run-1")
    with pytest.raises(LedgerCorruptError):
        mgr.reserve("resolution", "https://e.com/new", 1)


def test_reconciled_record_counts_at_actual_cost(cfg, ledger):
    mgr = _mgr(cfg, ledger, "run-1")
    req = mgr.reserve("resolution", "https://e.com/a", 5)
    mgr.reconcile(req, 1, "accepted")

    # 5 reserved but only 1 actually charged -> 9 of the per-run 10 remain.
    for i in range(9):
        assert mgr.reserve("resolution", f"https://e.com/b{i}", 1) is not None
    with pytest.raises(BudgetExhaustedError, match="per-run"):
        mgr.reserve("resolution", "https://e.com/over", 1)


def test_reconciling_unknown_request_id_is_an_error(cfg, ledger):
    mgr = _mgr(cfg, ledger, "run-1")
    with pytest.raises(KeyError):
        mgr.reconcile("no-such-id", 1, "accepted")


def test_conflicting_reconciliation_fails_visibly(cfg, ledger):
    mgr = _mgr(cfg, ledger, "run-1")
    req = mgr.reserve("resolution", "https://e.com/a", 1)
    mgr.reconcile(req, 1, "accepted")
    mgr.reconcile(req, 1, "accepted")  # identical repeat is idempotent

    with pytest.raises(ValueError):
        mgr.reconcile(req, 1, "content_failed")
