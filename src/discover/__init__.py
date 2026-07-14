"""Discovery adapter registry per ARCHITECTURE §5.1.

`discover_all()` iterates enabled, implemented adapters, concatenates their
prepared results, and isolates each adapter's exceptions so one broken source
never kills the run. The manual inbox adapter is intentionally not part of this
registry — see `inbox_manual.py`'s module docstring for why.
"""

from __future__ import annotations

import logging

from src.discover import tracker_jobright, tracker_simplify, tracker_vansh
from src.discover.base import DiscoveryIssue, DiscoveryResult

logger = logging.getLogger(__name__)

ADAPTERS = {
    tracker_vansh.SOURCE_NAME: tracker_vansh,
    tracker_simplify.SOURCE_NAME: tracker_simplify,
    tracker_jobright.SOURCE_NAME: tracker_jobright,
}


def discover_all(
    sources_cfg: dict,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    adapters=None,
) -> DiscoveryResult:
    """Run every enabled adapter named in `sources_cfg` that's implemented in
    ADAPTERS. An adapter raising an exception is logged and skipped; it does
    not prevent the other adapters from contributing their jobs."""
    registry = ADAPTERS if adapters is None else adapters
    jobs = []
    checkpoints = []
    succeeded = []
    issues = []
    for name, cfg in sources_cfg.items():
        if not cfg.get("enabled") or name not in registry:
            continue
        adapter = registry[name]
        adapter_cfg = dict(cfg, dry_run=dry_run, limit=limit)
        try:
            prepared = adapter.discover(adapter_cfg)
        except Exception as exc:
            logger.exception("discovery failed for source %s", name)
            issues.append(DiscoveryIssue(name, "fetch", type(exc).__name__, str(exc)[:500]))
            continue
        jobs.extend(prepared.jobs)
        if prepared.checkpoint is not None:
            checkpoints.append(prepared.checkpoint)
        succeeded.append(name)
    return DiscoveryResult(tuple(jobs), tuple(checkpoints), tuple(succeeded), tuple(issues))
