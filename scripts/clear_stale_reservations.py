import json
import logging
from datetime import datetime, timezone, timedelta
from src.firecrawl.budget import UsageRecord, BudgetManager
from src.run_ingest import load_sources_config
import yaml
import argparse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

def main():
    parser = argparse.ArgumentParser(description="Clear stale Firecrawl reservations.")
    parser.add_argument("--threshold-hours", type=float, default=2.0, help="Clear reservations older than this many hours")
    parser.add_argument("--ledger", default="data/firecrawl/usage-v1.json", help="Path to usage ledger")
    args = parser.parse_args()
    
    with open("config/firecrawl.yaml") as f:
        cfg = yaml.safe_load(f)
        
    budget = BudgetManager(cfg, ledger_path=args.ledger)
    
    with budget._advisory_lock():
        records = budget._read_ledger()
        
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(hours=args.threshold_hours)
        
        stale = []
        for i, r in enumerate(records):
            if r.state == "reserved":
                r_time = datetime.fromisoformat(r.reserved_at)
                if r_time < threshold:
                    stale.append(i)
                    
        if not stale:
            print("No stale reservations found.")
            return
            
        print(f"Found {len(stale)} stale reservation(s):")
        for i in stale:
            r = records[i]
            print(f"  Request ID: {r.request_id}, Reserved At: {r.reserved_at}, Purpose: {r.purpose}")
            
        confirm = input(f"Clear these {len(stale)} reservation(s)? [y/N] ")
        if confirm.lower().strip() == 'y':
            # Remove from ledger to release budget
            # Or mark them as 'cleared'. Deleting them is cleaner so they don't count towards limits.
            # Actually, to maintain history, we can mark them state="cleared" and they won't be counted since _check_limits counts 'reserved', 'charged', 'reconciled'.
            for i in stale:
                records[i].state = "cleared"
                records[i].completed_at = now.isoformat()
            budget._write_ledger(records)
            print("Stale reservations cleared.")
        else:
            print("Aborted.")

if __name__ == "__main__":
    main()
