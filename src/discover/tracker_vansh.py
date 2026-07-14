"""Discovery adapter for vanshb03/New-Grad-2027.

Verified 2026-07-04 (see docs/DECISIONS.md): default branch is `dev`, and a
machine-readable `.github/scripts/listings.json` exists and is preferred over
the README table per ARCHITECTURE §5.2. The README parser is kept as a
defensive fallback. Shared tracker machinery lives in `tracker_common.py`.
"""

from __future__ import annotations

import requests

from src.discover import tracker_common as common
from src.discover.base import AdapterDiscovery
from src.models import DiscoveredJob

SOURCE_NAME = "tracker_vansh"
BRANCH = "dev"
JSON_LISTINGS_PATH = ".github/scripts/listings.json"


def parse_listings_json(entries: list[dict]) -> list[DiscoveredJob]:
    return common.parse_listings_json(entries, SOURCE_NAME)


def parse_readme_table(text: str) -> list[DiscoveredJob]:
    return common.parse_readme_table(text, SOURCE_NAME)


def discover(config: dict) -> AdapterDiscovery:
    repo = config["repo"]
    snapshot_dir = config.get("snapshot_dir", "snapshots")
    session = config.get("session") or requests.Session()

    json_entries = common.fetch_json_listings(repo, BRANCH, JSON_LISTINGS_PATH, session)
    if json_entries is not None:
        jobs = parse_listings_json(json_entries)
        source_path = JSON_LISTINGS_PATH
    else:
        readme_text = common.fetch_readme(repo, BRANCH, session)
        jobs = parse_readme_table(readme_text)
        source_path = "README.md"

    return common.prepare_snapshot_diff(
        jobs,
        snapshot_dir,
        source_path,
        SOURCE_NAME,
        limit=config.get("limit"),
    )
