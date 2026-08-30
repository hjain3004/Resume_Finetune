import pytest

from src.resume_evidence.capture import (
    CaptureTransport,
    normalize_crawl4ai_capture,
    normalize_firecrawl_capture,
    parse_capture,
)


def _firecrawl():
    return {"data": {"markdown": "## Synthetic", "links": ["https://huntr.co/resume-examples/x"]}}


def test_both_transports_normalize_to_one_contract():
    firecrawl = normalize_firecrawl_capture(_firecrawl(), "https://huntr.co/resume-examples/x", "2026-08-30T08:00:00Z")
    crawl4ai = normalize_crawl4ai_capture({"markdown": "## Synthetic", "links": [], "final_url": "https://huntr.co/resume-examples/x"}, "https://huntr.co/resume-examples/x", "2026-08-30T08:00:00Z", firecrawl_failure="retrieval_failure")
    assert firecrawl.transport is CaptureTransport.FIRECRAWL
    assert crawl4ai.transport is CaptureTransport.CRAWL4AI
    assert parse_capture(crawl4ai.to_dict()) == crawl4ai


@pytest.mark.parametrize("raw", [
    {"schema_version": "x"},
    {"schema_version": "m8q.research_capture.v1", "source_url": "http://huntr.co/x"},
])
def test_capture_rejects_malformed_or_unsafe_envelopes(raw):
    with pytest.raises(ValueError):
        parse_capture(raw)


def test_capture_rejects_duplicate_links_and_off_domain_redirect():
    raw = normalize_firecrawl_capture(_firecrawl(), "https://huntr.co/resume-examples/x", "2026-08-30T08:00:00Z").to_dict()
    raw["links"] = ["https://huntr.co/a", "https://huntr.co/a#fragment"]
    with pytest.raises(ValueError, match="duplicate"):
        parse_capture(raw)
    raw["links"] = []
    raw["final_url"] = "https://linkedin.com/x"
    with pytest.raises(ValueError, match="LinkedIn|off-domain"):
        parse_capture(raw)


def test_provider_normalization_drops_linkedin_and_external_navigation_links():
    raw = {"data": {"markdown": "## Synthetic", "links": [
        "https://www.linkedin.com/in/example",
        "https://example.com/nav",
        "https://www.huntr.co/resume-examples/x#section",
        "https://huntr.co/resume-examples/x",
    ]}}
    capture = normalize_firecrawl_capture(raw, "https://huntr.co/resume-examples/x", "2026-08-30T08:00:00Z")
    assert capture.links == ("https://huntr.co/resume-examples/x",)


def test_provider_normalization_rejects_unsafe_same_domain_link():
    raw = {"data": {"markdown": "## Synthetic", "links": ["https://huntr.co/resume-examples/x?token=secret"]}}
    with pytest.raises(ValueError, match="sensitive"):
        normalize_firecrawl_capture(raw, "https://huntr.co/resume-examples/x", "2026-08-30T08:00:00Z")


def test_crawl4ai_normalization_filters_external_navigation_identically():
    raw = {
        "markdown": "## Synthetic",
        "html": "<h2>Synthetic</h2>",
        "final_url": "https://huntr.co/resume-examples/x",
        "links": ["https://linkedin.com/in/example", "https://huntr.co/resume-examples/x#x", "https://example.com/nav"],
    }
    capture = normalize_crawl4ai_capture(raw, "https://huntr.co/resume-examples/x", "2026-08-30T08:00:00Z")
    assert capture.links == ("https://huntr.co/resume-examples/x",)


def test_provider_normalization_rejects_malformed_same_domain_port():
    raw = {"data": {"markdown": "## Synthetic", "links": ["https://huntr.co:bad/resume-examples/x"]}}
    with pytest.raises(ValueError, match="unsafe"):
        normalize_firecrawl_capture(raw, "https://huntr.co/resume-examples/x", "2026-08-30T08:00:00Z")
