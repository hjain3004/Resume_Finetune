"""Manual inbox adapter per ARCHITECTURE §5.3 (inbox/urls.txt + inbox/*.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from src import db, resolve
from src.models import (
    DiscoveredJob,
    ManualUrlError,
    ResolvedJD,
    canonical_job_url,
    manual_url_dedup_key,
)

SOURCE_NAME = "inbox"

_SPLIT_RE = re.compile(r"\s*(?:—|--|\|)\s*")


class InboxInputError(ValueError):
    """Raised when an inbox manual URL is invalid or contains sensitive credentials."""


@dataclass(frozen=True)
class InboxResult:
    new_urls: int
    new_pastes: int
    url_job_ids: tuple[int, ...] = ()


def _parse_urls_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    urls = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            urls.append(stripped)
    return urls


def _parse_paste_file(path: Path) -> tuple[str, str, str, str | None, str] | None:
    """Returns (url, company, title, location, jd_text), or None if the file
    doesn't match the documented format (line 1: URL, line 2: Company —
    Title — Location, rest: JD text)."""
    lines = path.read_text().splitlines()
    if len(lines) < 3:
        return None
    url = lines[0].strip()
    if not url:
        return None
    parts = [p.strip() for p in _SPLIT_RE.split(lines[1].strip()) if p.strip()]
    if len(parts) < 2:
        return None
    company, title = parts[0], parts[1]
    location = parts[2] if len(parts) > 2 else None
    jd_text = "\n".join(lines[2:]).strip()
    if not jd_text:
        return None
    return url, company, title, location, jd_text


def ingest(conn, config: dict) -> InboxResult:
    inbox_dir = Path(config.get("inbox_dir", "inbox"))
    processed_dir = inbox_dir / "processed"
    urls_path = inbox_dir / "urls.txt"
    dry_run = config.get("dry_run", False)

    raw_urls = _parse_urls_file(urls_path)
    canonical_urls: list[str] = []
    for raw in raw_urls:
        try:
            c_url = canonical_job_url(raw)
            canonical_urls.append(c_url)
        except ManualUrlError as exc:
            raise InboxInputError(f"invalid manual URL in {urls_path.name}: {exc}") from exc

    new_urls = 0
    url_job_ids: list[int] = []
    seen_keys: set[str] = set()

    for c_url in canonical_urls:
        id_key = manual_url_dedup_key(c_url)
        if id_key in seen_keys:
            continue
        seen_keys.add(id_key)

        hostname = urlsplit(c_url).hostname or "unknown"
        job = DiscoveredJob(
            company="unknown",
            title=hostname,
            location=None,
            url=c_url,
            source=SOURCE_NAME,
            date_posted=None,
            identity_key=id_key,
        )
        if dry_run:
            new_urls += 1
            continue

        new_urls += sum(db.insert_discovered(conn, [job]).values())
        row = db.get_by_dedup_key(conn, id_key)
        if row is not None:
            url_job_ids.append(row["id"])

    new_pastes = 0
    for md_path in sorted(inbox_dir.glob("*.md")):
        parsed = _parse_paste_file(md_path)
        if parsed is None:
            continue
        url, company, title, location, jd_text = parsed
        job = DiscoveredJob(
            company=company,
            title=title,
            location=location,
            url=url,
            source=SOURCE_NAME,
            date_posted=None,
        )
        if dry_run:
            new_pastes += 1
            continue
        db.insert_discovered(conn, [job])
        row = db.get_by_url(conn, url)
        if row is not None:
            db.mark_resolved(
                conn,
                row["id"],
                ResolvedJD(
                    jd_text=jd_text, resolver="manual", raw_title=title, raw_location=location
                ),
                logic_version=resolve.LOGIC_VERSION,
            )
            new_pastes += 1
        processed_dir.mkdir(parents=True, exist_ok=True)
        md_path.rename(processed_dir / md_path.name)

    if not dry_run and raw_urls:
        urls_path.write_text("")

    return InboxResult(new_urls=new_urls, new_pastes=new_pastes, url_job_ids=tuple(url_job_ids))
