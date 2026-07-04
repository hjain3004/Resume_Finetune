"""Polite HTTP session and shared HTML->text helper for resolvers."""

from __future__ import annotations

import html
import re
import time
from urllib.parse import urlparse

import requests

USER_AGENT = "Mozilla/5.0 (compatible; job-pipeline personal use)"
REQUEST_TIMEOUT = 15
MIN_HOST_INTERVAL = 2.0


class PoliteSession:
    """Wraps a requests.Session with a per-hostname rate limit, timeout,
    redirect-following, and an honest User-Agent. Never retries within a run."""

    def __init__(
        self,
        session: requests.Session | None = None,
        time_func=time.monotonic,
        sleep_func=time.sleep,
    ) -> None:
        self._session = session or requests.Session()
        self._time_func = time_func
        self._sleep_func = sleep_func
        self._last_request_at: dict[str, float] = {}

    def _wait_for_host(self, host: str) -> None:
        last = self._last_request_at.get(host)
        now = self._time_func()
        if last is not None:
            elapsed = now - last
            if elapsed < MIN_HOST_INTERVAL:
                self._sleep_func(MIN_HOST_INTERVAL - elapsed)
        self._last_request_at[host] = now

    def get(self, url: str, **kwargs) -> requests.Response:
        host = urlparse(url).hostname or ""
        self._wait_for_host(host)
        headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        kwargs.setdefault("allow_redirects", True)
        return self._session.get(url, headers=headers, **kwargs)


_TAG_RE = re.compile(r"<[^>]+>")
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_BLOCK_BREAK_RE = re.compile(
    r"</(p|div|h[1-6]|ul|ol|br)\s*>|<br\s*/?>", re.IGNORECASE
)
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def html_to_text(raw_html: str) -> str:
    """Minimal HTML->text: unescape entities, strip tags, preserve list items
    as '- ' lines and paragraph breaks as blank lines."""
    text = _LI_RE.sub(lambda m: f"- {_TAG_RE.sub('', m.group(1)).strip()}\n", raw_html)
    text = _BLOCK_BREAK_RE.sub("\n\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()
