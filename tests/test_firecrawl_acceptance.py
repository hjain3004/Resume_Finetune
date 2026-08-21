"""M9F-0 defects 2, 4, 5: credential validation before reserving, one shared
deterministic page-acceptance decision driving reconciliation, and a dry-run
that neither calls Firecrawl nor fabricates a failed page.

Fully offline: the Firecrawl transport is a fake that counts calls, and the
budget ledger is a real BudgetManager over a tmp_path file.
"""

import json

import pytest

from src.firecrawl.budget import BudgetManager
from src.firecrawl.client import (
    BudgetAwareTier2Client,
    ConfigurationError,
    ProviderAuthError,
    ProviderTransientError,
)
from src.resolve.tier2 import (
    PageRejection,
    Tier2ContentRejected,
    Tier2Deferred,
    Tier2Page,
    page_rejection,
)

GOOD_JD = (
    "About the role\n\n"
    "We are hiring a backend engineer to build and operate our payments platform. "
    "You will design services, own reliability, and mentor other engineers.\n\n"
    "Responsibilities\n"
    "- Build and operate distributed services in production environments\n"
    "- Partner with product and design on new customer-facing capabilities\n\n"
    "Qualifications\n"
    "- 3+ years of professional software engineering experience\n"
    "- Strong skills in Python, Go, or a comparable server-side language\n"
    "- Experience with relational databases and requirement gathering\n"
)

NAV_SHELL = "[Experience requirements](/x) " * 40

DEAD_POSTING = (
    "This job is no longer available.\n\n"
    "The position you are looking for has been filled. Please browse our other "
    "openings to find a role that matches your experience, skills, and "
    "qualifications. We post new requirements regularly and encourage you to "
    "check back often for opportunities across our engineering organisation.\n"
)


def _page(markdown=GOOD_JD, *, status=200, final_url="https://careers.acme.com/job/1",
          provider="firecrawl", credits=1, html=None):
    return Tier2Page(
        markdown=markdown, html=html, final_url=final_url,
        status_code=status, provider=provider, credits_used=credits,
    )


# ------------------------------------------------- defect 4: pure acceptance


def test_good_jd_is_accepted():
    assert page_rejection(_page()) is None


def test_empty_markdown_is_rejected():
    assert page_rejection(_page("")) is PageRejection.EMPTY_MARKDOWN


def test_whitespace_only_markdown_is_rejected():
    assert page_rejection(_page("   \n\t ")) is PageRejection.EMPTY_MARKDOWN


def test_navigation_shell_is_rejected():
    assert page_rejection(_page(NAV_SHELL)) is PageRejection.QUALITY_GATE


def test_dead_posting_is_rejected():
    assert page_rejection(_page(DEAD_POSTING)) is PageRejection.DEAD_POSTING


@pytest.mark.parametrize("status", [404, 410, 500, 503])
def test_error_page_status_is_rejected(status):
    assert page_rejection(_page(status=status)) is PageRejection.BAD_STATUS


def test_absent_status_is_allowed_for_local_backends():
    """Crawl4AI reports no status; that must not be treated as an error page."""
    assert page_rejection(_page(status=None, provider="crawl4ai", credits=0)) is None


@pytest.mark.parametrize("bad", ["", "not-a-url", "ftp://acme.com/x", "file:///etc/passwd"])
def test_invalid_final_url_is_rejected(bad):
    assert page_rejection(_page(final_url=bad)) is PageRejection.BAD_FINAL_URL


# ------------------------------------------------- fakes


class FakeTransport:
    """Stands in for FirecrawlClient. Counts start/crawl so tests can prove
    that no paid network call happened."""

    def __init__(self, *, page=None, raises=None, start_raises=None):
        self.page = page
        self.raises = raises
        self.start_raises = start_raises
        self.start_calls = 0
        self.crawl_calls = 0
        self.closed = False

    def start(self):
        self.start_calls += 1
        if self.start_raises is not None:
            raise self.start_raises

    def crawl(self, url):
        self.crawl_calls += 1
        if self.raises is not None:
            raise self.raises
        return self.page

    def close(self):
        self.closed = True


@pytest.fixture
def cfg():
    return {
        "limits": {
            "monthly_credits": 800,
            "daily_credits": 25,
            "per_run_credits": 10,
            "monthly_by_purpose": {"resolution": 500, "discovery": 250, "research": 50},
        },
        "cooldowns": {"failed_url_hours": 24},
    }


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "usage-v1.json"


def _wrap(transport, cfg, ledger, *, dry_run=False, run_ref="run-1"):
    budget = BudgetManager(cfg, ledger_path=str(ledger), run_ref=run_ref)
    return BudgetAwareTier2Client(transport, budget, "resolution", dry_run), budget


def _records(ledger):
    return json.loads(ledger.read_text()) if ledger.exists() else []


URL = "https://careers.acme.com/job/1"


# ------------------------------------------------- defect 2: credentials


def test_missing_credentials_makes_no_network_call_and_no_reservation(cfg, ledger):
    transport = FakeTransport(start_raises=ConfigurationError("FIRECRAWL_API_KEY not set"))
    client, _ = _wrap(transport, cfg, ledger)

    with pytest.raises(ConfigurationError):
        client.crawl(URL)

    assert transport.crawl_calls == 0
    assert _records(ledger) == []
    assert not ledger.exists()


def test_missing_credentials_disables_firecrawl_for_the_rest_of_the_run(cfg, ledger):
    transport = FakeTransport(start_raises=ConfigurationError("FIRECRAWL_API_KEY not set"))
    client, _ = _wrap(transport, cfg, ledger)

    for _ in range(3):
        with pytest.raises(ConfigurationError):
            client.crawl(URL)

    # Fails fast: start is not retried once it is known to be misconfigured.
    assert transport.start_calls == 1
    assert transport.crawl_calls == 0
    assert _records(ledger) == []


# ------------------------------------------------- defect 5: dry-run


def test_dry_run_never_calls_firecrawl_and_creates_no_ledger(cfg, ledger):
    transport = FakeTransport(page=_page())
    client, _ = _wrap(transport, cfg, ledger, dry_run=True)

    with pytest.raises(Tier2Deferred) as exc:
        client.crawl(URL)

    assert exc.value.reason_code == "dry_run"
    assert transport.crawl_calls == 0
    assert not ledger.exists()


# ------------------------------------------------- defect 4: reconciliation


def test_accepted_page_is_reconciled_as_accepted(cfg, ledger):
    transport = FakeTransport(page=_page())
    client, _ = _wrap(transport, cfg, ledger)

    page = client.crawl(URL)

    assert page.markdown == GOOD_JD
    (record,) = _records(ledger)
    assert record["state"] == "reconciled"
    assert record["outcome_class"] == "accepted"
    assert record["actual_credits"] == 1
    assert record["cooldown_until"] is None


@pytest.mark.parametrize(
    "markdown,status,expected",
    [
        ("", 200, PageRejection.EMPTY_MARKDOWN),
        (NAV_SHELL, 200, PageRejection.QUALITY_GATE),
        (DEAD_POSTING, 200, PageRejection.DEAD_POSTING),
        (GOOD_JD, 404, PageRejection.BAD_STATUS),
        (GOOD_JD, 500, PageRejection.BAD_STATUS),
    ],
)
def test_unacceptable_page_is_charged_and_cooled_down(cfg, ledger, markdown, status, expected):
    transport = FakeTransport(page=_page(markdown, status=status))
    client, _ = _wrap(transport, cfg, ledger)

    with pytest.raises(Tier2ContentRejected) as exc:
        client.crawl(URL)

    assert exc.value.rejection is expected
    (record,) = _records(ledger)
    assert record["state"] == "reconciled"
    assert record["actual_credits"] == 1, "a fetched page is charged"
    assert record["cooldown_until"] is not None, "24h cooldown applies"
    assert expected.value in record["outcome_class"]


def test_url_in_cooldown_is_deferred_without_a_network_call(cfg, ledger):
    first = FakeTransport(page=_page(""))
    client, _ = _wrap(first, cfg, ledger)
    with pytest.raises(Tier2ContentRejected):
        client.crawl(URL)

    second = FakeTransport(page=_page())
    client2, _ = _wrap(second, cfg, ledger, run_ref="run-2")
    with pytest.raises(Tier2Deferred):
        client2.crawl(URL)

    assert second.crawl_calls == 0


def test_budget_exhaustion_defers_without_a_network_call(cfg, ledger):
    cfg["limits"]["per_run_credits"] = 0
    transport = FakeTransport(page=_page())
    client, _ = _wrap(transport, cfg, ledger)

    with pytest.raises(Tier2Deferred):
        client.crawl(URL)

    assert transport.crawl_calls == 0
    assert _records(ledger) == []


@pytest.mark.parametrize(
    "exc", [ProviderAuthError("auth"), ProviderTransientError("429")]
)
def test_provider_failure_marks_charged_and_propagates(cfg, ledger, exc):
    transport = FakeTransport(raises=exc)
    client, _ = _wrap(transport, cfg, ledger)

    with pytest.raises(type(exc)):
        client.crawl(URL)

    (record,) = _records(ledger)
    assert record["state"] == "charged"
    assert record["cooldown_until"] is None, "provider failure is not a content judgment"
