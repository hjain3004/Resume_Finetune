"""Discovery adapter registry per ARCHITECTURE §5.1.

`discover_all()` iterates enabled, implemented adapters, concatenates their
results, and isolates each adapter's exceptions so one broken source never
kills the run. The manual inbox adapter is intentionally not part of this
registry — see `inbox_manual.py`'s module docstring for why.
"""

from __future__ import annotations

import logging

from src.discover import tracker_jobright, tracker_simplify, tracker_vansh
from src.models import DiscoveredJob

logger = logging.getLogger(__name__)

ADAPTERS = {
    tracker_vansh.SOURCE_NAME: tracker_vansh,
    tracker_simplify.SOURCE_NAME: tracker_simplify,
    tracker_jobright.SOURCE_NAME: tracker_jobright,
}


def discover_all(
    sources_cfg: dict, *, limit: int | None = None, dry_run: bool = False
) -> list[DiscoveredJob]:
    """Run every enabled adapter named in `sources_cfg` that's implemented in
    ADAPTERS. An adapter raising an exception is logged and skipped; it does
    not prevent the other adapters from contributing their jobs."""
    all_jobs: list[DiscoveredJob] = []
    for name, cfg in sources_cfg.items():
        if not cfg.get("enabled") or name not in ADAPTERS:
            continue
        adapter = ADAPTERS[name]
        adapter_cfg = dict(cfg, dry_run=dry_run)
        try:
            jobs = adapter.discover(adapter_cfg)
        except Exception:
            logger.exception("discovery failed for source %s", name)
            continue
        if limit is not None:
            jobs = jobs[:limit]
        all_jobs.extend(jobs)
    return all_jobs
