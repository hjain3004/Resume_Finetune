"""M9F-0 defect 3: operator cleanup of stale reservations.

The script must use a public typed API (not BudgetManager privates), require
explicit confirmation, leave the ledger byte-identical when aborted, and clear
only eligible stale `reserved` records while preserving audit history.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.firecrawl.budget import (
    STATE_CHARGED,
    STATE_CLEARED,
    STATE_RECONCILED,
    STATE_RESERVED,
    BudgetManager,
)


@pytest.fixture
def cfg():
    return {
        "limits": {
            "monthly_credits": 800,
            "daily_credits": 500,
            "per_run_credits": 10,
            "monthly_by_purpose": {"resolution": 500},
        },
        "cooldowns": {"failed_url_hours": 24},
    }


def _row(request_id, state, *, age_hours, run_ref="run-1"):
    ts = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {
        "version": 1,
        "request_id": request_id,
        "run_ref": run_ref,
        "reserved_at": ts.isoformat(),
        "completed_at": None,
        "purpose": "resolution",
        "job_ref": None,
        "url_sha256": "a" * 64,
        "reserved_credits": 1,
        "actual_credits": None,
        "state": state,
        "outcome_class": None,
        "provider_id": None,
        "cooldown_until": None,
    }


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "usage-v1.json"
    path.write_text(
        json.dumps(
            [
                _row("stale-a", STATE_RESERVED, age_hours=5),
                _row("stale-b", STATE_RESERVED, age_hours=9),
                _row("recent", STATE_RESERVED, age_hours=0.5),
                _row("done", STATE_RECONCILED, age_hours=8),
                _row("billed", STATE_CHARGED, age_hours=8),
            ]
        )
    )
    return path


def test_list_stale_reservations_is_public_and_selects_only_old_reserved(cfg, ledger):
    mgr = BudgetManager(cfg, ledger_path=str(ledger), run_ref="run-1")
    stale = mgr.list_stale_reservations(older_than_hours=2.0)

    assert sorted(s.request_id for s in stale) == ["stale-a", "stale-b"]


def test_clear_reservations_releases_allowance(cfg, ledger):
    mgr = BudgetManager(cfg, ledger_path=str(ledger), run_ref="run-1")
    # reserved(3) + reconciled(1) + charged(1) = 5 of the per-run 10 consumed.
    cleared = mgr.clear_reservations(["stale-a", "stale-b"])
    assert cleared == 2

    rows = {r["request_id"]: r for r in json.loads(ledger.read_text())}
    assert rows["stale-a"]["state"] == STATE_CLEARED
    assert rows["stale-b"]["state"] == STATE_CLEARED
    assert rows["recent"]["state"] == STATE_RESERVED
    assert rows["done"]["state"] == STATE_RECONCILED
    assert rows["billed"]["state"] == STATE_CHARGED


def test_clear_reservations_preserves_reserved_at_timestamps(cfg, ledger):
    before = {r["request_id"]: r["reserved_at"] for r in json.loads(ledger.read_text())}
    mgr = BudgetManager(cfg, ledger_path=str(ledger), run_ref="run-1")
    mgr.clear_reservations(["stale-a"])

    after = {r["request_id"]: r["reserved_at"] for r in json.loads(ledger.read_text())}
    assert after == before


def test_clear_reservations_refuses_a_finalized_record(cfg, ledger):
    mgr = BudgetManager(cfg, ledger_path=str(ledger), run_ref="run-1")
    with pytest.raises(ValueError):
        mgr.clear_reservations(["billed"])


def test_clear_reservations_refuses_an_unknown_request_id(cfg, ledger):
    mgr = BudgetManager(cfg, ledger_path=str(ledger), run_ref="run-1")
    with pytest.raises(KeyError):
        mgr.clear_reservations(["no-such-id"])


def test_cli_abort_leaves_ledger_byte_identical(cfg, ledger, monkeypatch, capsys):
    from scripts import clear_stale_reservations as cli

    original = ledger.read_bytes()
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    monkeypatch.setattr(cli, "load_firecrawl_config", lambda: cfg)

    rc = cli.main(["--ledger", str(ledger), "--threshold-hours", "2"])

    assert rc == 0
    assert ledger.read_bytes() == original
    assert "Aborted" in capsys.readouterr().out


def test_cli_confirm_clears_only_eligible_stale_reserved(cfg, ledger, monkeypatch):
    from scripts import clear_stale_reservations as cli

    monkeypatch.setattr("builtins.input", lambda *_: "y")
    monkeypatch.setattr(cli, "load_firecrawl_config", lambda: cfg)

    rc = cli.main(["--ledger", str(ledger), "--threshold-hours", "2"])

    assert rc == 0
    rows = {r["request_id"]: r["state"] for r in json.loads(ledger.read_text())}
    assert rows == {
        "stale-a": STATE_CLEARED,
        "stale-b": STATE_CLEARED,
        "recent": STATE_RESERVED,
        "done": STATE_RECONCILED,
        "billed": STATE_CHARGED,
    }


def test_cli_does_not_use_budget_manager_privates():
    import inspect

    from scripts import clear_stale_reservations as cli

    source = inspect.getsource(cli)
    assert "_advisory_lock" not in source
    assert "_read_ledger" not in source
    assert "_write_ledger" not in source
