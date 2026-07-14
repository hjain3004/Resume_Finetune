"""Discovery adapter for jobright-ai's category repos (configured as a list in
`config/sources.yaml` since jobright publishes one repo per role category).

Verified 2026-07-04 (see docs/DECISIONS.md) against
jobright-ai/2026-Software-Engineer-New-Grad: default branch is `master`, no
`.github/scripts/listings.json` exists (404), so discovery falls back to the
README table. That table's shape differs from vansh/Simplify's: the header
is `Company | Job Title | Location | Work Model | Date Posted` with the apply
link embedded as a markdown link inside the `Job Title` cell rather than a
separate `Application/Link` column — `tracker_common.parse_readme_table`'s
default column aliases and markdown-link fallback already cover this shape.
Default branch is looked up per-repo via the GitHub API (rather than assumed)
since the user may add repos later with a different default branch.
"""

from __future__ import annotations

import requests

from src.discover import tracker_common as common
from src.discover.base import AdapterDiscovery
from src.models import DiscoveredJob

SOURCE_NAME = "tracker_jobright"
JSON_LISTINGS_PATH = ".github/scripts/listings.json"


def parse_listings_json(entries: list[dict]) -> list[DiscoveredJob]:
    return common.parse_listings_json(entries, SOURCE_NAME)


def parse_readme_table(text: str) -> list[DiscoveredJob]:
    return common.parse_readme_table(text, SOURCE_NAME)


def _discover_repo(repo: str, session: requests.Session) -> tuple[list[DiscoveredJob], str]:
    branch = common.fetch_default_branch(repo, session, fallback="master")
    json_entries = common.fetch_json_listings(repo, branch, JSON_LISTINGS_PATH, session)
    if json_entries is not None:
        return parse_listings_json(json_entries), f"{repo}:{JSON_LISTINGS_PATH}"
    readme_text = common.fetch_readme(repo, branch, session)
    return parse_readme_table(readme_text), f"{repo}:README.md"


def discover(config: dict) -> AdapterDiscovery:
    repos = config["repos"]
    snapshot_dir = config.get("snapshot_dir", "snapshots")
    session = config.get("session") or requests.Session()

    jobs: list[DiscoveredJob] = []
    source_paths = []
    for repo in repos:
        repo_jobs, source_path = _discover_repo(repo, session)
        jobs.extend(repo_jobs)
        source_paths.append(source_path)
    combined_source_path = "; ".join(source_paths)

    return common.prepare_snapshot_diff(
        jobs,
        snapshot_dir,
        combined_source_path,
        SOURCE_NAME,
        limit=config.get("limit"),
    )
