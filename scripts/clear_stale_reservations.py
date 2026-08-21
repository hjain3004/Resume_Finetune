"""Operator command: release stale Firecrawl credit reservations (M9F-0, A4).

A reservation is written before paid network I/O and finalized afterwards. If a
run crashes in between, the record stays `reserved` and keeps consuming the
monthly/daily/per-run allowance -- fail-closed by design, since the request may
genuinely have been billed.

This command never runs automatically and never clears anything without an
explicit `y`. Cleared records are retained for audit history (state `cleared`)
rather than deleted, and every other recorded field, including `reserved_at`,
is preserved.
"""

from __future__ import annotations

import argparse
import logging
import sys

import yaml

from src.firecrawl.budget import BudgetManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

FIRECRAWL_CONFIG_PATH = "config/firecrawl.yaml"


def load_firecrawl_config(path: str = FIRECRAWL_CONFIG_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clear stale Firecrawl reservations.")
    parser.add_argument(
        "--threshold-hours",
        type=float,
        default=2.0,
        help="Clear reservations older than this many hours",
    )
    parser.add_argument(
        "--ledger",
        default="data/firecrawl/usage-v1.json",
        help="Path to usage ledger",
    )
    args = parser.parse_args(argv)

    budget = BudgetManager(load_firecrawl_config(), ledger_path=args.ledger)

    stale = budget.list_stale_reservations(older_than_hours=args.threshold_hours)
    if not stale:
        print("No stale reservations found.")
        return 0

    print(f"Found {len(stale)} stale reservation(s):")
    for record in stale:
        print(
            f"  request_id={record.request_id} run_ref={record.run_ref} "
            f"reserved_at={record.reserved_at} purpose={record.purpose} "
            f"credits={record.reserved_credits}"
        )

    confirm = input(f"Clear these {len(stale)} reservation(s)? [y/N] ")
    if confirm.lower().strip() != "y":
        print("Aborted. Ledger unchanged.")
        return 0

    cleared = budget.clear_reservations([record.request_id for record in stale])
    print(f"Cleared {cleared} stale reservation(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
