import pytest
import os
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.firecrawl.budget import BudgetManager, BudgetExhaustedError, LedgerCorruptError

@pytest.fixture
def temp_ledger(tmp_path):
    return tmp_path / "usage-v1.json"

@pytest.fixture
def limits_cfg():
    return {
        "limits": {
            "monthly_credits": 100,
            "daily_credits": 50,
            "monthly_by_purpose": {
                "resolve": 100,
                "other_purpose": 50
            }
        },
        "cooldowns": {
            "failed_url_hours": 24
        }
    }

def test_budget_reserve_success(temp_ledger, limits_cfg):
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    req_id = manager.reserve("resolve", "https://example.com/job/1", 1)
    
    assert req_id is not None
    assert temp_ledger.exists()
    
    data = json.loads(temp_ledger.read_text())
    assert len(data) == 1
    assert data[0]["request_id"] == req_id
    assert data[0]["state"] == "reserved"
    assert data[0]["reserved_credits"] == 1

def test_budget_reserve_exhausts_daily(temp_ledger, limits_cfg):
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    # Fill daily
    manager.reserve("resolve", "https://example.com/job/1", 50)
    
    with pytest.raises(BudgetExhaustedError, match="daily budget exhausted"):
        manager.reserve("resolve", "https://example.com/job/2", 1)

def test_budget_reserve_exhausts_monthly(temp_ledger, limits_cfg):
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    manager.reserve("resolve", "https://example.com/job/1", 50)
    
    # Overwrite dates to simulate a different day but same month
    data = json.loads(temp_ledger.read_text())
    past_date = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    data[0]["reserved_at"] = past_date
    temp_ledger.write_text(json.dumps(data))
    
    manager.reserve("resolve", "https://example.com/job/2", 50)
    
    with pytest.raises(BudgetExhaustedError, match="monthly budget exhausted"):
        manager.reserve("resolve", "https://example.com/job/3", 2)

def test_budget_reserve_exhausts_purpose(temp_ledger, limits_cfg):
    limits_cfg["limits"]["daily_credits"] = 200
    limits_cfg["limits"]["monthly_credits"] = 200
    limits_cfg["limits"]["monthly_by_purpose"]["resolve"] = 80
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    manager.reserve("resolve", "https://example.com/job/1", 80)
    
    with pytest.raises(BudgetExhaustedError, match="monthly purpose budget for resolve exhausted"):
        manager.reserve("resolve", "https://example.com/job/2", 1)
        
    # Other purpose can still reserve
    req_id = manager.reserve("other_purpose", "https://example.com/job/3", 1)
    assert req_id is not None

def test_budget_dry_run_does_not_reserve(temp_ledger, limits_cfg):
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    req_id = manager.reserve("resolve", "https://example.com/job/1", 1, dry_run=True)
    
    assert req_id == "dry_run_id"
    if temp_ledger.exists():
        data = json.loads(temp_ledger.read_text())
        assert len(data) == 0
    else:
        assert not temp_ledger.exists()

def test_budget_reconcile(temp_ledger, limits_cfg):
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    req_id = manager.reserve("resolve", "https://example.com/job/1", 1)
    
    manager.reconcile(req_id, 1, "success", content_failed=False)
    
    data = json.loads(temp_ledger.read_text())
    assert data[0]["state"] == "reconciled"
    assert data[0]["actual_credits"] == 1
    assert data[0]["cooldown_until"] is None
    assert data[0]["outcome_class"] == "success"

def test_budget_reconcile_cooldown(temp_ledger, limits_cfg):
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    req_id = manager.reserve("resolve", "https://example.com/job/1", 1)
    
    manager.reconcile(req_id, 1, "success", content_failed=True)
    
    data = json.loads(temp_ledger.read_text())
    assert data[0]["cooldown_until"] is not None
    
    with pytest.raises(BudgetExhaustedError, match="URL is in cooldown"):
        manager.reserve("resolve", "https://example.com/job/1", 1)

def test_budget_mark_charged(temp_ledger, limits_cfg):
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    req_id = manager.reserve("resolve", "https://example.com/job/1", 1)
    
    manager.mark_charged(req_id, "ProviderTransientError")
    
    data = json.loads(temp_ledger.read_text())
    assert data[0]["state"] == "charged"
    assert data[0]["actual_credits"] is None
    assert data[0]["outcome_class"] == "ProviderTransientError"

def test_corrupt_ledger(temp_ledger, limits_cfg):
    temp_ledger.write_text("not json")
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    
    with pytest.raises(LedgerCorruptError):
        manager.reserve("resolve", "https://example.com/job/1", 1)

def test_unsupported_version_ledger(temp_ledger, limits_cfg):
    temp_ledger.write_text(json.dumps([{"version": 2}]))
    manager = BudgetManager(limits_cfg, ledger_path=str(temp_ledger))
    
    with pytest.raises(LedgerCorruptError, match="unsupported ledger version"):
        manager.reserve("resolve", "https://example.com/job/1", 1)
