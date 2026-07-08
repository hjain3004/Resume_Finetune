"""Router: dispatch a discovered URL to the right resolver by hostname,
routing on the final URL after redirects per ARCHITECTURE §6.1."""

from __future__ import annotations

from urllib.parse import urlparse

from src.models import ResolvedJD
from src.resolve import amazon_jobs, ashby, browser, generic, greenhouse, jobright, lever, workday, wrapper

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


def resolve(url: str, session, *, browser_resolver: bool = False) -> ResolvedJD | None:
    response = session.get(url)
    if response.status_code != 200:
        # A plain `requests` GET can be bot-blocked (e.g. qualtrics.com returns
        # 410) where a rendered headless browser still succeeds. Only worth a
        # tier-2 retry for hosts with no tier-1 resolver — a blocked ATS host
        # (Tesla-style Akamai block) stays tier-3 rather than masking a real
        # break.
        if browser_resolver and route(url) is generic:
            return browser.resolve(url, session)
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
        result = generic.resolve(final_url, session)
        if result is not None:
            return result
        if browser_resolver:
            return browser.resolve(final_url, session)
        return None
    if module is jobright:
        return jobright.resolve(final_url, response.text, session, browser_resolver=browser_resolver)
    return module.resolve(final_url, session)
