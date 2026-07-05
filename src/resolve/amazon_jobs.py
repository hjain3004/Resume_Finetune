"""Resolver for amazon.jobs postings, per PHASE2_KICKOFF.md M6.0(d).

The obvious per-job endpoint (`{job_path}.json`) is bot-gated (406 without a
browser session/cookie dance we won't do, per CLAUDE.md etiquette). The public
search endpoint is not: `search.json?base_query={job_id}` returns the exact
posting when queried by its numeric id, defensively matched by `job_path`
rather than trusting order/uniqueness of the search results.
"""

from __future__ import annotations

import re

from src.models import ResolvedJD
from src.resolve.base import html_to_text

RESOLVER_NAME = "amazon_jobs"
SEARCH_URL = "https://www.amazon.jobs/en/search.json"
_URL_RE = re.compile(r"amazon\.jobs/[a-z]{2}/jobs/(?P<job_id>\d+)")


def resolve(url: str, session) -> ResolvedJD | None:
    match = _URL_RE.search(url)
    if not match:
        return None
    job_id = match["job_id"]

    response = session.get(SEARCH_URL, params={"base_query": job_id})
    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    needle = f"/jobs/{job_id}/"
    job = next(
        (j for j in data.get("jobs") or [] if needle in (j.get("job_path") or "")), None
    )
    if job is None:
        return None

    title = job.get("title")
    description = job.get("description")
    if not title or not description:
        return None

    parts = [html_to_text(description)]
    for heading, field in (
        ("Basic Qualifications", "basic_qualifications"),
        ("Preferred Qualifications", "preferred_qualifications"),
    ):
        section = job.get(field)
        if section:
            parts.append(f"{heading}:\n{html_to_text(section)}")

    return ResolvedJD(
        jd_text="\n\n".join(parts),
        resolver=RESOLVER_NAME,
        raw_title=title,
        raw_location=job.get("normalized_location") or job.get("location"),
    )
