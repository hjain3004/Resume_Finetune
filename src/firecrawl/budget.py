import json
import os
import time
import uuid
import hashlib
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Spec limits
# Limits are loaded from config/firecrawl.yaml in the application, but we pass them to the budget manager.

class BudgetExhaustedError(RuntimeError):
    pass

class LedgerCorruptError(RuntimeError):
    pass


# Ledger states, defined centrally so the budget calculation, the operator
# cleanup command, and the tests cannot drift apart (M9F-0 defect 3).
STATE_RESERVED = "reserved"
STATE_CHARGED = "charged"
STATE_RECONCILED = "reconciled"
STATE_CLEARED = "cleared"

#: States that consume budget. `cleared` is deliberately absent: a cleared
#: record is retained for audit history but releases its allowance.
ACTIVE_STATES = frozenset({STATE_RESERVED, STATE_CHARGED, STATE_RECONCILED})
KNOWN_STATES = ACTIVE_STATES | {STATE_CLEARED}


def record_cost(record: "UsageRecord") -> int:
    """Credits a ledger record currently consumes.

    `reserved` and `charged` count at the reserved (maximum) cost because
    billing is not yet known to be lower. `reconciled` counts at the
    trustworthy actual cost. `cleared` counts nothing."""
    if record.state == STATE_CLEARED:
        return 0
    if record.state == STATE_RECONCILED and record.actual_credits is not None:
        return record.actual_credits
    return record.reserved_credits

@dataclass
class UsageRecord:
    version: int
    request_id: str
    run_ref: str | None
    reserved_at: str
    completed_at: str | None
    purpose: str
    job_ref: str | None
    url_sha256: str
    reserved_credits: int
    actual_credits: int | None
    state: str  # one of KNOWN_STATES
    outcome_class: str | None
    provider_id: str | None
    cooldown_until: str | None

def hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StaleReservation:
    """Audit-safe view of a non-final reservation, for the operator command.

    Deliberately carries no URL and no credentials -- only the hash-free
    bookkeeping an operator needs to decide whether to release it."""

    request_id: str
    run_ref: str | None
    reserved_at: str
    purpose: str
    reserved_credits: int

class BudgetManager:
    def __init__(
        self,
        limits_cfg: dict,
        ledger_path: str = "data/firecrawl/usage-v1.json",
        run_ref: str | None = None,
    ):
        self.limits = limits_cfg
        self.ledger_path = Path(ledger_path)
        self.lock_path = self.ledger_path.with_name(self.ledger_path.name + ".lock")
        self.run_ref = run_ref or uuid.uuid4().hex
        
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
            # `run_ref` was introduced after the first schema-v1 records were
            # written. A record without it predates per-run accounting and is
            # therefore attributed to no run: it still counts toward daily,
            # monthly, and purpose totals, but can never consume a *current*
            # run's allowance (see `_check_limits`). Unknown/extra keys fail
            # closed rather than being silently dropped.
            d = {"run_ref": None, **d}
            try:
                record = UsageRecord(**d)
            except TypeError as exc:
                raise LedgerCorruptError(f"unusable ledger record: {exc}") from exc
            if record.state not in KNOWN_STATES:
                raise LedgerCorruptError(f"unknown ledger state: {record.state!r}")
            records.append(record)
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
        run_total = 0

        for r in records:
            credits_spent = record_cost(r)
            if not credits_spent:
                continue

            # Per-run accounting is independent of the calendar window: a run
            # that straddles UTC midnight keeps one allowance. Legacy records
            # carry run_ref=None and so never match a real run token.
            if r.run_ref is not None and r.run_ref == self.run_ref:
                run_total += credits_spent

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
        per_run_cap = limits.get("per_run_credits")
        if per_run_cap is not None and run_total + cost > per_run_cap:
            raise BudgetExhaustedError("per-run budget exhausted")
        purpose_cap = limits["monthly_by_purpose"].get(purpose, 0)
        if purpose_total + cost > purpose_cap:
            raise BudgetExhaustedError(f"monthly purpose budget for {purpose} exhausted")

    def remaining_allowances(self, purpose: str) -> dict[str, int]:
        """Credits still available under each cap, for run notes and the digest.

        Read-only and never raises on an empty ledger; a corrupt ledger still
        fails closed via `_read_ledger`."""
        with self._advisory_lock():
            records = self._read_ledger()

        now = datetime.now(timezone.utc)
        current_month = now.strftime("%Y-%m")
        current_day = now.strftime("%Y-%m-%d")
        month_total = day_total = purpose_total = run_total = 0

        for r in records:
            spent = record_cost(r)
            if not spent:
                continue
            if r.run_ref is not None and r.run_ref == self.run_ref:
                run_total += spent
            r_time = datetime.fromisoformat(r.reserved_at)
            if r_time.strftime("%Y-%m") == current_month:
                month_total += spent
                if r.purpose == purpose:
                    purpose_total += spent
            if r_time.strftime("%Y-%m-%d") == current_day:
                day_total += spent

        limits = self.limits["limits"]
        per_run_cap = limits.get("per_run_credits")
        purpose_cap = limits["monthly_by_purpose"].get(purpose, 0)
        return {
            "monthly": max(0, limits["monthly_credits"] - month_total),
            "daily": max(0, limits["daily_credits"] - day_total),
            "run": max(0, per_run_cap - run_total) if per_run_cap is not None else -1,
            f"purpose_{purpose}": max(0, purpose_cap - purpose_total),
        }

    def list_stale_reservations(self, older_than_hours: float) -> list[StaleReservation]:
        """Reservations still in `reserved` state and older than the threshold.

        Read-only: this never mutates the ledger. Public so the operator
        command does not reach into BudgetManager privates (M9F-0 defect 3)."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
        with self._advisory_lock():
            records = self._read_ledger()
        return [
            StaleReservation(
                request_id=r.request_id,
                run_ref=r.run_ref,
                reserved_at=r.reserved_at,
                purpose=r.purpose,
                reserved_credits=r.reserved_credits,
            )
            for r in records
            if r.state == STATE_RESERVED
            and datetime.fromisoformat(r.reserved_at) < cutoff
        ]

    def clear_reservations(self, request_ids: Sequence[str]) -> int:
        """Release the named `reserved` records, keeping them for audit history.

        Returns the number cleared. Refuses unknown ids (KeyError) and already
        finalized records (ValueError) rather than rewriting billing history.
        `reserved_at` and every other recorded field are preserved; only
        `state` and `completed_at` change."""
        wanted = list(request_ids)
        if not wanted:
            return 0
        with self._advisory_lock():
            records = self._read_ledger()
            by_id = {r.request_id: r for r in records}

            missing = [rid for rid in wanted if rid not in by_id]
            if missing:
                raise KeyError(f"unknown reservation(s): {', '.join(sorted(missing))}")

            not_reserved = [rid for rid in wanted if by_id[rid].state != STATE_RESERVED]
            if not_reserved:
                raise ValueError(
                    "refusing to clear finalized record(s): "
                    f"{', '.join(sorted(not_reserved))}"
                )

            now = datetime.now(timezone.utc).isoformat()
            for rid in wanted:
                by_id[rid].state = STATE_CLEARED
                by_id[rid].completed_at = now
            self._write_ledger(records)
            return len(wanted)

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
                run_ref=self.run_ref,
                reserved_at=datetime.now(timezone.utc).isoformat(),
                completed_at=None,
                purpose=purpose,
                job_ref=job_ref,
                url_sha256=hash_url(url),
                reserved_credits=cost,
                actual_credits=None,
                state=STATE_RESERVED,
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
                if r.request_id != req_id:
                    continue

                if r.state == STATE_RECONCILED:
                    # Idempotent only when the repeat agrees with the recorded
                    # final result. A conflicting reconciliation must fail
                    # visibly rather than silently rewrite billing history.
                    if r.actual_credits == actual_cost and r.outcome_class == outcome_class:
                        return
                    raise ValueError(
                        f"conflicting reconciliation for {req_id}: "
                        f"recorded {r.outcome_class}/{r.actual_credits}, "
                        f"got {outcome_class}/{actual_cost}"
                    )

                r.state = STATE_RECONCILED
                r.completed_at = datetime.now(timezone.utc).isoformat()
                r.actual_credits = actual_cost
                r.outcome_class = outcome_class
                r.provider_id = provider_id
                if content_failed:
                    cd_hours = self.limits["cooldowns"]["failed_url_hours"]
                    r.cooldown_until = (
                        datetime.now(timezone.utc) + timedelta(hours=cd_hours)
                    ).isoformat()
                self._write_ledger(records)
                return

            raise KeyError(f"unknown reservation: {req_id}")

    def mark_charged(self, req_id: str, outcome_class: str, provider_id: str | None = None):
        """Mark as charged (fail closed). Leaves reserved_credits as the cost."""
        with self._advisory_lock():
            records = self._read_ledger()
            for r in records:
                if r.request_id == req_id:
                    r.state = STATE_CHARGED
                    r.completed_at = datetime.now(timezone.utc).isoformat()
                    r.outcome_class = outcome_class
                    r.provider_id = provider_id
                    self._write_ledger(records)
                    return
            raise KeyError(f"unknown reservation: {req_id}")
