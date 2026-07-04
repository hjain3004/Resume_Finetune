"""Resolver for {tenant}.wd{N}.myworkdayjobs.com postings.

Unofficial JSON endpoint: wrap in defensive parsing and treat any schema
surprise (missing keys, unexpected shape) as a soft failure -> None.
"""

from __future__ import annotations

import re

from src.models import ResolvedJD
from src.resolve.base import html_to_text

RESOLVER_NAME = "workday"
_URL_RE = re.compile(
    r"(?P<tenant>[^./]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com/"
    r"(?:[a-z]{2}-[A-Z]{2}/)?"
    r"(?P<site>[^/]+)/job/(?P<rest>.+)"
)
JSON_URL = "https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{rest}"


def resolve(url: str, session) -> ResolvedJD | None:
    match = _URL_RE.search(url)
    if not match:
        return None

    json_url = JSON_URL.format(**match.groupdict())
    response = session.get(json_url, headers={"Accept": "application/json"})
    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    try:
        info = data["jobPostingInfo"]
        title = info["title"]
        description = info["jobDescription"]
    except (KeyError, TypeError):
        return None

    if not title or not description:
        return None

    return ResolvedJD(
        jd_text=html_to_text(description),
        resolver=RESOLVER_NAME,
        raw_title=title,
        raw_location=info.get("location"),
    )
