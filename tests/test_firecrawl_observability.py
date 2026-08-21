"""M9F-0 defect 8: Firecrawl activity must be distinguishable in run notes and
the digest, without leaking credentials or external page content.

Crawl4AI/off runs stay readable and backward-compatible.
"""

import json
from unittest.mock import patch

from src import digest, run_ingest
from src.firecrawl.client import FirecrawlRunStats
from src.resolve.outcomes import ResolutionSummary


def _notes(backend, stats=None, remaining=None):
    with patch.object(run_ingest, "_firecrawl_remaining", return_value=remaining):
        return json.loads(
            run_ingest._run_notes(
                run_outcome="ok",
                summary=ResolutionSummary(),
                discovery_issues=(),
                fatal_error=None,
                browser_backend=backend,
                firecrawl_stats=stats,
            )
        )


def test_run_notes_always_record_the_selected_backend():
    assert _notes("crawl4ai")["tier2_backend"] == "crawl4ai"
    assert _notes("off")["tier2_backend"] == "off"


def test_crawl4ai_run_notes_carry_no_firecrawl_block():
    assert "firecrawl" not in _notes("crawl4ai", FirecrawlRunStats())


def test_firecrawl_run_notes_expose_every_required_counter():
    stats = FirecrawlRunStats(
        attempted=5, deferred=2, accepted=3, content_failed=1,
        provider_failed=1, credits_reserved=5, credits_finalized=4,
    )
    remaining = {"monthly": 700, "daily": 20, "run": 5, "purpose_resolution": 400}

    block = _notes("firecrawl", stats, remaining)["firecrawl"]

    assert block["backend"] == "firecrawl"
    assert block["attempted"] == 5
    assert block["deferred"] == 2
    assert block["accepted"] == 3
    assert block["content_failed"] == 1
    assert block["provider_failed"] == 1
    assert block["credits_reserved"] == 5
    assert block["credits_finalized"] == 4
    assert block["remaining"] == remaining


def test_run_notes_are_deterministic_and_sorted():
    stats = FirecrawlRunStats(attempted=1)
    with patch.object(run_ingest, "_firecrawl_remaining", return_value=None):
        first = run_ingest._run_notes(
            run_outcome="ok", summary=ResolutionSummary(), discovery_issues=(),
            fatal_error=None, browser_backend="firecrawl", firecrawl_stats=stats,
        )
        second = run_ingest._run_notes(
            run_outcome="ok", summary=ResolutionSummary(), discovery_issues=(),
            fatal_error=None, browser_backend="firecrawl", firecrawl_stats=stats,
        )
    assert first == second


def test_run_notes_never_contain_a_credential():
    stats = FirecrawlRunStats(attempted=1)
    remaining = {"monthly": 1}
    raw = json.dumps(_notes("firecrawl", stats, remaining))

    for forbidden in ("FIRECRAWL_API_KEY", "Authorization", "Bearer", "api_key"):
        assert forbidden not in raw


def test_remaining_allowance_failure_never_breaks_a_run():
    """Observability must not be able to fail a run that already did its work."""
    with patch.object(run_ingest, "load_firecrawl_config", side_effect=OSError("gone")):
        assert run_ingest._firecrawl_remaining() is None


def test_digest_renders_the_firecrawl_line(tmp_path):
    payload = {
        "run_outcome": "ok",
        "tier2_backend": "firecrawl",
        "firecrawl": {
            "backend": "firecrawl", "attempted": 4, "deferred": 1, "accepted": 2,
            "content_failed": 1, "provider_failed": 0,
            "credits_reserved": 4, "credits_finalized": 3,
            "remaining": {"monthly": 700, "daily": 20, "run": 6, "purpose_resolution": 400},
        },
    }
    section = digest._firecrawl_section(json.dumps(payload))

    assert "firecrawl" in section.lower()
    assert "attempted" in section.lower()
    assert "4" in section and "700" in section


def test_digest_firecrawl_section_is_empty_for_crawl4ai():
    payload = {"run_outcome": "ok", "tier2_backend": "crawl4ai"}
    assert digest._firecrawl_section(json.dumps(payload)) == ""


def test_digest_firecrawl_section_tolerates_unparseable_notes():
    assert digest._firecrawl_section("not json") == ""
    assert digest._firecrawl_section(None) == ""
