"""Resolver for boards.greenhouse.io / job-boards.greenhouse.io postings."""

from __future__ import annotations

import html
import re

from src.models import ResolvedJD
from src.resolve.base import html_to_text

RESOLVER_NAME = "greenhouse"
_URL_RE = re.compile(
    r"(?:boards|job-boards)\.greenhouse\.io/(?P<board>[^/]+)/jobs/(?P<job_id>\d+)"
)
API_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"


def resolve(url: str, session) -> ResolvedJD | None:
    match = _URL_RE.search(url)
    if not match:
        return None

    api_url = API_URL.format(board=match["board"], job_id=match["job_id"])
    response = session.get(api_url)
    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    content = data.get("content")
    title = data.get("title")
    if not content or not title:
        return None

    location = (data.get("location") or {}).get("name")
    jd_text = html_to_text(html.unescape(content))

    return ResolvedJD(
        jd_text=jd_text,
        resolver=RESOLVER_NAME,
        raw_title=title,
        raw_location=location,
    )
