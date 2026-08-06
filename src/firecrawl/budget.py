import json
import os
import time
import uuid
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

# Spec limits
# Limits are loaded from config/firecrawl.yaml in the application, but we pass them to the budget manager.

class BudgetExhaustedError(RuntimeError):
    pass

class LedgerCorruptError(RuntimeError):
    pass

@dataclass
class UsageRecord:
    version: int
    request_id: str
    reserved_at: str
    completed_at: str | None
    purpose: str
    job_ref: str | None
    url_sha256: str
    reserved_credits: int
    actual_credits: int | None
    state: str  # 'reserved', 'charged', 'reconciled'
    outcome_class: str | None
    provider_id: str | None
    cooldown_until: str | None

def hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()

class BudgetManager:
    def __init__(self, limits_cfg: dict, ledger_path: str = "data/firecrawl/usage-v1.json"):
        self.limits = limits_cfg
        self.ledger_path = Path(ledger_path)
        self.lock_path = self.ledger_path.with_name(self.ledger_path.name + ".lock")
        
    @contextmanager
    def _advisory_lock(self, timeout: float = 10.0):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        start = time.time()
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                os.close(fd)
                break
            except FileExistsError:
                if time.time() - start > timeout:
                    raise TimeoutError("failed to acquire budget lock")
                time.sleep(0.1)
        try:
            yield
        finally:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def _read_ledger(self) -> list[UsageRecord]:
        if not self.ledger_path.exists():
            return []
        try:
            data = json.loads(self.ledger_path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            raise LedgerCorruptError("ledger json invalid") from exc
        
        if not isinstance(data, list):
            raise LedgerCorruptError("ledger must be a list")
            
        records = []
        for d in data:
            if d.get("version") != 1:
                raise LedgerCorruptError("unsupported ledger version")
            records.append(UsageRecord(**d))
        return records

    def _write_ledger(self, records: list[UsageRecord]):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.ledger_path.with_name(f".{self.ledger_path.name}.{uuid.uuid4().hex}.tmp")
        data = [asdict(r) for r in records]
        try:
            temp_path.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
            os.replace(temp_path, self.ledger_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _check_cooldown(self, url: str, records: list[UsageRecord]):
        url_hash = hash_url(url)
        now = datetime.now(timezone.utc)
        for r in records:
            if r.url_sha256 == url_hash and r.cooldown_until:
                cd = datetime.fromisoformat(r.cooldown_until)
                if now < cd:
                    raise BudgetExhaustedError("URL is in cooldown")

    def _check_limits(self, purpose: str, cost: int, records: list[UsageRecord]):
        now = datetime.now(timezone.utc)
        current_month = now.strftime("%Y-%m")
        current_day = now.strftime("%Y-%m-%d")
        
        month_total = 0
        day_total = 0
        purpose_total = 0
        
        for r in records:
            # We count reserved credits if state == 'reserved' or 'charged', actual if 'reconciled'
            credits_spent = r.actual_credits if r.state == "reconciled" and r.actual_credits is not None else r.reserved_credits
            
            r_time = datetime.fromisoformat(r.reserved_at)
            if r_time.strftime("%Y-%m") == current_month:
                month_total += credits_spent
                if r.purpose == purpose:
                    purpose_total += credits_spent
            if r_time.strftime("%Y-%m-%d") == current_day:
                day_total += credits_spent

        limits = self.limits["limits"]
        if month_total + cost > limits["monthly_credits"]:
            raise BudgetExhaustedError("monthly budget exhausted")
        if day_total + cost > limits["daily_credits"]:
            raise BudgetExhaustedError("daily budget exhausted")
        purpose_cap = limits["monthly_by_purpose"].get(purpose, 0)
        if purpose_total + cost > purpose_cap:
            raise BudgetExhaustedError(f"monthly purpose budget for {purpose} exhausted")

    def reserve(self, purpose: str, url: str, cost: int, job_ref: str | None = None, dry_run: bool = False) -> str:
        """Reserve credits for an operation. Returns a request ID. Raises BudgetExhaustedError."""
        if dry_run:
            # Check limits but don't reserve
            with self._advisory_lock():
                records = self._read_ledger()
                self._check_cooldown(url, records)
                self._check_limits(purpose, cost, records)
            return "dry_run_id"
            
        with self._advisory_lock():
            records = self._read_ledger()
            self._check_cooldown(url, records)
            self._check_limits(purpose, cost, records)
            
            req_id = uuid.uuid4().hex
            records.append(UsageRecord(
                version=1,
                request_id=req_id,
                reserved_at=datetime.now(timezone.utc).isoformat(),
                completed_at=None,
                purpose=purpose,
                job_ref=job_ref,
                url_sha256=hash_url(url),
                reserved_credits=cost,
                actual_credits=None,
                state="reserved",
                outcome_class=None,
                provider_id=None,
                cooldown_until=None
            ))
            self._write_ledger(records)
            return req_id

    def reconcile(self, req_id: str, actual_cost: int, outcome_class: str, provider_id: str | None = None, content_failed: bool = False):
        """Finalize a reservation with actual cost and outcome. If content_failed, sets 24h cooldown."""
        with self._advisory_lock():
            records = self._read_ledger()
            for r in records:
                if r.request_id == req_id:
                    r.state = "reconciled"
                    r.completed_at = datetime.now(timezone.utc).isoformat()
                    r.actual_credits = actual_cost
                    r.outcome_class = outcome_class
                    r.provider_id = provider_id
                    if content_failed:
                        cd_hours = self.limits["cooldowns"]["failed_url_hours"]
                        from datetime import timedelta
                        r.cooldown_until = (datetime.now(timezone.utc) + timedelta(hours=cd_hours)).isoformat()
                    self._write_ledger(records)
                    return
            # Should not happen unless manually messed up
            pass

    def mark_charged(self, req_id: str, outcome_class: str, provider_id: str | None = None):
        """Mark as charged (fail closed). Leaves reserved_credits as the cost."""
        with self._advisory_lock():
            records = self._read_ledger()
            for r in records:
                if r.request_id == req_id:
                    r.state = "charged"
                    r.completed_at = datetime.now(timezone.utc).isoformat()
                    r.outcome_class = outcome_class
                    r.provider_id = provider_id
                    self._write_ledger(records)
                    return
