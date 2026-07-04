"""Resolver for jobs.lever.co postings."""

from __future__ import annotations

import re

from src.models import ResolvedJD
from src.resolve.base import html_to_text

RESOLVER_NAME = "lever"
_URL_RE = re.compile(r"jobs\.lever\.co/(?P<company>[^/]+)/(?P<posting_id>[^/?#]+)")
API_URL = "https://api.lever.co/v0/postings/{company}/{posting_id}"


def resolve(url: str, session) -> ResolvedJD | None:
    match = _URL_RE.search(url)
    if not match:
        return None

    api_url = API_URL.format(company=match["company"], posting_id=match["posting_id"])
    response = session.get(api_url)
    if response.status_code != 200:
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    title = data.get("text")
    description = data.get("description")
    if not title or not description:
        return None

    sections = [description]
    for item in data.get("lists") or []:
        heading = item.get("text")
        content = item.get("content")
        if heading:
            sections.append(f"<h3>{heading}</h3>")
        if content:
            sections.append(content)

    jd_text = html_to_text("\n".join(sections))
    location = (data.get("categories") or {}).get("location")

    return ResolvedJD(
        jd_text=jd_text,
        resolver=RESOLVER_NAME,
        raw_title=title,
        raw_location=location,
    )
