"""Resolver for jobs.ashbyhq.com postings."""

from __future__ import annotations

import re

from src.models import ResolvedJD
from src.resolve.base import html_to_text

RESOLVER_NAME = "ashby"
_URL_RE = re.compile(r"jobs\.ashbyhq\.com/(?P<org>[^/]+)/(?P<job_id>[^/?#]+)")
API_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"


def resolve(url: str, session) -> ResolvedJD | None:
    match = _URL_RE.search(url)
    if not match:
        return None

    response = session.get(API_URL.format(org=match["org"]))
    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    job = next((j for j in data.get("jobs") or [] if j.get("id") == match["job_id"]), None)
    if job is None:
        return None

    title = job.get("title")
    description_html = job.get("descriptionHtml")
    if not title or not description_html:
        return None

    return ResolvedJD(
        jd_text=html_to_text(description_html),
        resolver=RESOLVER_NAME,
        raw_title=title,
        raw_location=job.get("location"),
    )
