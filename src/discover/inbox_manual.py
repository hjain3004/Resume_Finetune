"""Manual inbox adapter per ARCHITECTURE §5.3 (inbox/urls.txt + inbox/*.md).

Deviation from the plain `discover(config) -> list[DiscoveredJob]` adapter
protocol (see docs/DECISIONS.md): MD paste files must be inserted AND
immediately marked RESOLVED in the same step, and "move processed files" /
"rewrite urls.txt keeping only unprocessed lines" both require knowing which
lines actually became job rows in the DB. A pure discover()->list function
can't express that, so `ingest()` takes the DB connection directly and is
called from run_ingest.py's discovery step alongside (not through)
`discover.discover_all()`.

Known gap: a URL-only inbox line gets placeholder `company="unknown"`,
`title=<hostname>` (per §5.3) until resolution backfills the title. Two
pending URLs on the same hostname therefore produce the same dedup_key and
the second collapses into the first (dedup_key ignores url) — acceptable for
a single-user manual inbox where such collisions should be rare, but noted
here rather than silently worked around.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from src import db
from src.models import DiscoveredJob, ResolvedJD

SOURCE_NAME = "inbox"

_SPLIT_RE = re.compile(r"\s*(?:—|--|\|)\s*")


@dataclass(frozen=True)
class InboxResult:
    new_urls: int
    new_pastes: int


def _parse_urls_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    urls = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            urls.append(line)
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

    new_urls = 0
    processed_url_lines: set[str] = set()
    for url in _parse_urls_file(urls_path):
        hostname = urlparse(url).hostname or "unknown"
        job = DiscoveredJob(
            company="unknown",
            title=hostname,
            location=None,
            url=url,
            source=SOURCE_NAME,
            date_posted=None,
        )
        if dry_run:
            new_urls += 1
            continue
        new_urls += db.insert_discovered(conn, [job])
        processed_url_lines.add(url)

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
            )
            new_pastes += 1
        processed_dir.mkdir(parents=True, exist_ok=True)
        md_path.rename(processed_dir / md_path.name)

    if not dry_run and processed_url_lines:
        remaining = [u for u in _parse_urls_file(urls_path) if u not in processed_url_lines]
        urls_path.write_text("\n".join(remaining) + ("\n" if remaining else ""))

    return InboxResult(new_urls=new_urls, new_pastes=new_pastes)
