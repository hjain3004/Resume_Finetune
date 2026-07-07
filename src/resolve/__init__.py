"""Router: dispatch a discovered URL to the right resolver by hostname,
routing on the final URL after redirects per ARCHITECTURE §6.1."""

from __future__ import annotations

from urllib.parse import urlparse

from src.models import ResolvedJD
from src.resolve import amazon_jobs, ashby, generic, greenhouse, jobright, lever, workday, wrapper

_HOSTNAME_ROUTES = (
    ("greenhouse.io", greenhouse),
    ("lever.co", lever),
    ("ashbyhq.com", ashby),
    ("myworkdayjobs.com", workday),
    ("amazon.jobs", amazon_jobs),
    ("jobright.com", jobright),
    ("jobright.ai", jobright),
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
    if module is generic:
        wrapped = wrapper.resolve_wrapper_map(final_url, session)
        if wrapped is not None:
            return wrapped
        unwrapped = wrapper.resolve_gh_jid(final_url, response.text, session)
        if unwrapped is not None:
            return unwrapped
    if module is jobright:
        return jobright.resolve(final_url, response.text, session)
    return module.resolve(final_url, session)
