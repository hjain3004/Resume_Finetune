"""Discovery adapter for SimplifyJobs/New-Grad-Positions.

Verified 2026-07-04 (see docs/DECISIONS.md): default branch is `dev`, same as
vansh's fork of this tracker, and `.github/scripts/listings.json` exists with
the identical schema. The README parser is kept as a defensive fallback.
"""

from __future__ import annotations

from pathlib import Path

import requests

from src.discover import tracker_common as common
from src.models import DiscoveredJob, dedup_key

SOURCE_NAME = "tracker_simplify"
BRANCH = "dev"
JSON_LISTINGS_PATH = ".github/scripts/listings.json"


def parse_listings_json(entries: list[dict]) -> list[DiscoveredJob]:
    return common.parse_listings_json(entries, SOURCE_NAME)


def parse_readme_table(text: str) -> list[DiscoveredJob]:
    return common.parse_readme_table(text, SOURCE_NAME)


def diff_new_jobs(
    jobs: list[DiscoveredJob], snapshot_dir: str | Path, source_path: str
) -> list[DiscoveredJob]:
    return common.diff_new_jobs(jobs, snapshot_dir, source_path, SOURCE_NAME)


def discover(config: dict) -> list[DiscoveredJob]:
    repo = config["repo"]
    snapshot_dir = config.get("snapshot_dir", "snapshots")
    session = config.get("session") or requests.Session()
    dry_run = config.get("dry_run", False)

    json_entries = common.fetch_json_listings(repo, BRANCH, JSON_LISTINGS_PATH, session)
    if json_entries is not None:
        jobs = parse_listings_json(json_entries)
        source_path = JSON_LISTINGS_PATH
    else:
        readme_text = common.fetch_readme(repo, BRANCH, session)
        jobs = parse_readme_table(readme_text)
        source_path = "README.md"

    if dry_run:
        previous_keys = common.load_snapshot_keys(snapshot_dir, SOURCE_NAME)
        return [
            j for j in jobs if dedup_key(j.company, j.title, j.location) not in previous_keys
        ]
    return diff_new_jobs(jobs, snapshot_dir, source_path)
