"""Router: dispatch a discovered URL to the right resolver by hostname,
routing on the final URL after redirects per ARCHITECTURE §6.1."""

from __future__ import annotations

from urllib.parse import urlparse

from src.models import ResolvedJD
from src.resolve import ashby, generic, greenhouse, lever, workday

_HOSTNAME_ROUTES = (
    ("greenhouse.io", greenhouse),
    ("lever.co", lever),
    ("ashbyhq.com", ashby),
    ("myworkdayjobs.com", workday),
)


def route(url: str):
    hostname = urlparse(url).hostname or ""
    for needle, module in _HOSTNAME_ROUTES:
        if needle in hostname:
            return module
    return generic


def resolve(url: str, session) -> ResolvedJD | None:
    response = session.get(url)
    if response.status_code != 200:
        return None

    final_url = response.url
    module = route(final_url)
    return module.resolve(final_url, session)
