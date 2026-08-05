import pytest
from unittest.mock import patch
from scripts.company_bank import RateLimitedFetcher

class MockResponse:
    def __init__(self, status_code, text, url=None):
        self.status_code = status_code
        self.text = text
        self.url = url or "http://example.com"

def mock_get(url, **kwargs):
    if url.endswith("robots.txt"):
        if "notion.com" in url:
            return MockResponse(200, """User-Agent: *
Allow: /
Disallow: /invite/
Disallow: /*/invite/
Disallow: /templates/search?query=*
Disallow: /embed/*
User-Agent: BLEXBot
Disallow: /""")
        elif "amazon.jobs" in url:
            return MockResponse(200, """User-agent: AhrefsBot
Disallow: /

User-agent: *
Disallow: /internal
Disallow: /en/internal""")
        else:
            return MockResponse(404, "")
    
    return MockResponse(200, "foo bar", url)

@patch("scripts.company_bank.requests.get", side_effect=mock_get)
@patch("scripts.company_bank.time.sleep")
def test_robots_parser(mock_sleep, mock_req):
    fetcher = RateLimitedFetcher(2.0)
    
    # notion
    assert fetcher.fetch("https://www.notion.com/about", ("notion.com",)).error is None
    assert fetcher.fetch("https://www.notion.com/careers", ("notion.com",)).error is None
    assert fetcher.fetch("https://www.notion.com/blog/x", ("notion.com",)).error is None
    assert fetcher.fetch("https://www.notion.com/invite/abc", ("notion.com",)).error == "blocked by robots.txt"

    # amazon
    assert fetcher.fetch("https://amazon.jobs/en/", ("amazon.jobs",)).error is None
    assert fetcher.fetch("https://amazon.jobs/content/en/how-we-hire", ("amazon.jobs",)).error is None
    assert fetcher.fetch("https://amazon.jobs/en/internal", ("amazon.jobs",)).error == "blocked by robots.txt"
