"""Discovery adapter for vanshb03/New-Grad-2027.

Verified 2026-07-04 (see docs/DECISIONS.md): default branch is `dev`, and a
machine-readable `.github/scripts/listings.json` exists and is preferred over
the README table per ARCHITECTURE §5.2. The README parser is kept as a
defensive fallback.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.models import DiscoveredJob, dedup_key

SOURCE_NAME = "tracker_vansh"
BRANCH = "dev"
JSON_LISTINGS_PATH = ".github/scripts/listings.json"
USER_AGENT = "job-pipeline (personal use)"
REQUEST_TIMEOUT = 15

_HREF_RE = re.compile(r'href="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"</?br\s*/?>", re.IGNORECASE)
_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")


def _headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _fetch_json(repo: str, session: requests.Session) -> list[dict] | None:
    url = f"https://raw.githubusercontent.com/{repo}/{BRANCH}/{JSON_LISTINGS_PATH}"
    response = session.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _fetch_readme(repo: str, session: requests.Session) -> str:
    url = f"https://raw.githubusercontent.com/{repo}/{BRANCH}/README.md"
    response = session.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def parse_listings_json(entries: list[dict]) -> list[DiscoveredJob]:
    jobs: list[DiscoveredJob] = []
    for entry in entries:
        if not entry.get("active", True) or not entry.get("is_visible", True):
            continue
        url = entry.get("url")
        company = entry.get("company_name")
        title = entry.get("title")
        if not url or not company or not title:
            continue
        locations = entry.get("locations") or []
        location = "; ".join(locations) if locations else None
        date_posted = None
        ts = entry.get("date_posted")
        if isinstance(ts, (int, float)):
            date_posted = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        jobs.append(
            DiscoveredJob(
                company=company,
                title=title,
                location=location,
                url=url,
                source=SOURCE_NAME,
                date_posted=date_posted,
            )
        )
    return jobs


def _strip_html(cell: str) -> str:
    cell = _BR_RE.sub("; ", cell)
    cell = _TAG_RE.sub("", cell)
    return cell.strip()


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-+:?", cell) for cell in cells if cell)


def parse_readme_table(text: str) -> list[DiscoveredJob]:
    lines = text.splitlines()
    header_idx = None
    columns: dict[str, int] = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and "Company" in stripped:
            cells = _split_row(stripped)
            columns = {name: idx for idx, name in enumerate(cells)}
            if "Company" in columns:
                header_idx = i
                break
    if header_idx is None:
        return []

    def col(cells: list[str], name: str) -> str:
        idx = columns.get(name)
        if idx is None or idx >= len(cells):
            return ""
        return cells[idx]

    jobs: list[DiscoveredJob] = []
    last_company: str | None = None
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = _split_row(stripped)
        if _is_separator_row(cells):
            continue

        raw_company = col(cells, "Company")
        company_match = _BOLD_RE.search(raw_company)
        company = (company_match.group(1) if company_match else raw_company).strip()
        company = company.lstrip("↳").strip()
        if not company:
            company = last_company or ""
        last_company = company or last_company

        title = _strip_html(col(cells, "Role"))
        location_raw = col(cells, "Location")
        location = _strip_html(location_raw) or None

        link_cell = col(cells, "Application/Link")
        href_match = _HREF_RE.search(link_cell)
        if not href_match or not company or not title:
            continue
        url = href_match.group(1)

        jobs.append(
            DiscoveredJob(
                company=company,
                title=title,
                location=location,
                url=url,
                source=SOURCE_NAME,
                date_posted=None,
            )
        )
    return jobs


def _snapshot_path(snapshot_dir: str | Path) -> Path:
    return Path(snapshot_dir) / f"{SOURCE_NAME}.json"


def _load_snapshot_keys(snapshot_dir: str | Path) -> set[str]:
    path = _snapshot_path(snapshot_dir)
    if not path.exists():
        return set()
    return set(json.loads(path.read_text()).get("keys", []))


def _save_snapshot_keys(snapshot_dir: str | Path, keys: set[str], source_path: str) -> None:
    path = _snapshot_path(snapshot_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"keys": sorted(keys), "source_path": source_path}, indent=2))


def diff_new_jobs(
    jobs: list[DiscoveredJob], snapshot_dir: str | Path, source_path: str
) -> list[DiscoveredJob]:
    """Compare parsed jobs against the previous snapshot's dedup_key set,
    return only the new ones, then overwrite the snapshot with the full set."""
    previous_keys = _load_snapshot_keys(snapshot_dir)
    current_keys = {dedup_key(j.company, j.title, j.location) for j in jobs}
    new_jobs = [
        j for j in jobs if dedup_key(j.company, j.title, j.location) not in previous_keys
    ]
    _save_snapshot_keys(snapshot_dir, current_keys, source_path)
    return new_jobs


def discover(config: dict) -> list[DiscoveredJob]:
    repo = config["repo"]
    snapshot_dir = config.get("snapshot_dir", "snapshots")
    session = config.get("session") or requests.Session()
    dry_run = config.get("dry_run", False)

    json_entries = _fetch_json(repo, session)
    if json_entries is not None:
        jobs = parse_listings_json(json_entries)
        source_path = JSON_LISTINGS_PATH
    else:
        readme_text = _fetch_readme(repo, session)
        jobs = parse_readme_table(readme_text)
        source_path = "README.md"

    if dry_run:
        previous_keys = _load_snapshot_keys(snapshot_dir)
        return [
            j for j in jobs if dedup_key(j.company, j.title, j.location) not in previous_keys
        ]
    return diff_new_jobs(jobs, snapshot_dir, source_path)
