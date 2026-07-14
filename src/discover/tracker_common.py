"""Shared machinery for the GitHub-tracker discovery adapters (vansh, simplify,
jobright) per ARCHITECTURE §5.2: JSON-listings probe, README-table fallback,
and snapshot diffing. Each tracker module wraps these with its own SOURCE_NAME,
repo config, and (for README parsing) its own column-name aliases, since the
three repos don't share identical table shapes.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.discover.base import AdapterDiscovery, PendingCheckpoint, SnapshotState
from src.models import DiscoveredJob, dedup_key

USER_AGENT = "job-pipeline (personal use)"
REQUEST_TIMEOUT = 15

_HREF_RE = re.compile(r'href="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"</?br\s*/?>", re.IGNORECASE)
_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def headers() -> dict[str, str]:
    result = {"User-Agent": USER_AGENT}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        result["Authorization"] = f"token {token}"
    return result


def fetch_default_branch(repo: str, session: requests.Session, *, fallback: str = "main") -> str:
    """Look up a repo's default branch via the GitHub API. Falls back to
    `fallback` on any error (rate limit, network failure) rather than raising,
    since branch drift shouldn't take down a whole discovery run."""
    try:
        response = session.get(
            f"https://api.github.com/repos/{repo}", headers=headers(), timeout=REQUEST_TIMEOUT
        )
        if response.status_code != 200:
            return fallback
        return response.json().get("default_branch") or fallback
    except (requests.RequestException, ValueError):
        return fallback


def fetch_json_listings(
    repo: str, branch: str, path: str, session: requests.Session
) -> list[dict] | None:
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    response = session.get(url, headers=headers(), timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def fetch_readme(repo: str, branch: str, session: requests.Session) -> str:
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/README.md"
    response = session.get(url, headers=headers(), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def parse_listings_json(entries: list[dict], source_name: str) -> list[DiscoveredJob]:
    """Parse the `.github/scripts/listings.json` schema shared by vansh and
    Simplify (both are Simplify-maintained trackers using the same format)."""
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
                source=source_name,
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


def _first_present(columns: dict[str, int], names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in columns:
            return name
    return None


def parse_readme_table(
    text: str,
    source_name: str,
    *,
    company_col: tuple[str, ...] = ("Company",),
    role_col: tuple[str, ...] = ("Role", "Job Title"),
    location_col: tuple[str, ...] = ("Location",),
    link_col: tuple[str, ...] = ("Application/Link",),
) -> list[DiscoveredJob]:
    """Parse a tracker README's main table. Column names vary by repo (vansh
    uses a dedicated `Application/Link` column with an `<a href>`; jobright
    embeds the apply link as a markdown link in the `Job Title` cell instead),
    so the caller supplies aliases and both link shapes are tried."""
    lines = text.splitlines()
    header_idx = None
    columns: dict[str, int] = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("|") and any(name in stripped for name in company_col):
            cells = _split_row(stripped)
            candidate_columns = {name: idx for idx, name in enumerate(cells)}
            if _first_present(candidate_columns, company_col):
                columns = candidate_columns
                header_idx = i
                break
    if header_idx is None:
        return []

    company_name = _first_present(columns, company_col)
    role_name = _first_present(columns, role_col)
    location_name = _first_present(columns, location_col)
    link_name = _first_present(columns, link_col)

    def col(cells: list[str], name: str | None) -> str:
        if name is None:
            return ""
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

        raw_company = col(cells, company_name)
        company_md = _MD_LINK_RE.search(raw_company)
        if company_md:
            company = company_md.group(1).strip()
        else:
            bold_match = _BOLD_RE.search(raw_company)
            company = (bold_match.group(1) if bold_match else raw_company).strip()
        company = company.lstrip("↳").strip()
        if not company:
            company = last_company or ""
        last_company = company or last_company

        raw_role = col(cells, role_name)
        role_md = _MD_LINK_RE.search(raw_role)
        title = role_md.group(1).strip() if role_md else _strip_html(raw_role)

        location_raw = col(cells, location_name)
        location = _strip_html(location_raw) or None

        url = None
        link_cell = col(cells, link_name)
        href_match = _HREF_RE.search(link_cell)
        if href_match:
            url = href_match.group(1)
        elif role_md:
            url = role_md.group(2).strip()

        if not url or not company or not title:
            continue

        jobs.append(
            DiscoveredJob(
                company=company,
                title=title,
                location=location,
                url=url,
                source=source_name,
                date_posted=None,
            )
        )
    return jobs


def _snapshot_path(snapshot_dir: str | Path, source_name: str) -> Path:
    return Path(snapshot_dir) / f"{source_name}.json"


def load_snapshot_state(snapshot_dir: str | Path, source_name: str) -> SnapshotState:
    path = _snapshot_path(snapshot_dir, source_name)
    if not path.exists():
        return SnapshotState(frozenset(), frozenset())
    payload = json.loads(path.read_text())
    return SnapshotState(
        frozenset(payload.get("keys", [])),
        frozenset(payload.get("pending_keys", [])),
    )


def load_snapshot_keys(snapshot_dir: str | Path, source_name: str) -> set[str]:
    return set(load_snapshot_state(snapshot_dir, source_name).keys)


def prepare_snapshot_diff(
    jobs: list[DiscoveredJob],
    snapshot_dir: str | Path,
    source_path: str,
    source_name: str,
    *,
    limit: int | None = None,
) -> AdapterDiscovery:
    previous = load_snapshot_state(snapshot_dir, source_name)
    current_keys: set[str] = set()
    candidate_keys: set[str] = set()
    candidates: list[DiscoveredJob] = []
    for item in jobs:
        item_key = dedup_key(item.company, item.title, item.location)
        current_keys.add(item_key)
        if item_key in candidate_keys:
            continue
        if item_key not in previous.keys or item_key in previous.pending_keys:
            candidate_keys.add(item_key)
            candidates.append(item)
    selected = candidates if limit is None else candidates[:limit]
    deferred = candidates[len(selected) :]
    checkpoint = PendingCheckpoint(
        source_name,
        _snapshot_path(snapshot_dir, source_name),
        source_path,
        frozenset(current_keys),
        frozenset(dedup_key(j.company, j.title, j.location) for j in deferred),
    )
    return AdapterDiscovery(source_name, tuple(selected), checkpoint)


def commit_checkpoint(checkpoint: PendingCheckpoint) -> None:
    path = checkpoint.path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = {
        "keys": sorted(checkpoint.keys),
        "pending_keys": sorted(checkpoint.pending_keys),
        "source_path": checkpoint.source_path,
    }
    try:
        temporary.write_text(json.dumps(payload, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

