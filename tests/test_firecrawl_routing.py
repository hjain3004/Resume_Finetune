"""M9F-0 defect 6: integrated offline coverage of the whole tier-2 path.

run_ingest -> backend selection -> router -> throttle -> budget -> fake
transport -> deterministic acceptance -> reconciliation -> ResolutionOutcome
-> resolve_attempt accounting -> run summary.

Every network boundary is faked. A test here that makes a real request is a bug.
"""

from unittest.mock import MagicMock, patch

import pytest

from src import db, run_ingest
from src.discover.base import DiscoveryResult
from src.discover.inbox_manual import InboxResult
from src.models import DiscoveredJob, ResolvedJD, Status
from src.resolve import attempt
from src.resolve.outcomes import ResolutionOutcomeKind
from src.resolve.tier2 import PageRejection, Tier2ContentRejected, Tier2Deferred, Tier2Page

from tests.test_firecrawl_acceptance import GOOD_JD, NAV_SHELL

GENERIC_URL = "https://careers.acme.com/job/1"


def _page(markdown=GOOD_JD, *, status=200, url=GENERIC_URL, provider="firecrawl", credits=1):
    return Tier2Page(markdown, None, url, status, provider, credits)


class _Resp:
    def __init__(self, text="<html><body>nav only</body></html>", status=200, url=GENERIC_URL):
        self.text = text
        self.status_code = status
        self.url = url


class RecordingSession:
    """Fake PoliteSession: records throttle/get order so the etiquette
    requirement (throttle before the paid fetch) is observable."""

    def __init__(self, response=None):
        self.calls = []
        self._response = response

    def get(self, url, **kwargs):
        self.calls.append(("get", url))
        # Echo the requested URL back as the final URL so the router routes on
        # the real host, exactly as a redirect-following session would.
        return self._response if self._response is not None else _Resp(url=url)

    def throttle(self, url):
        self.calls.append(("throttle", url))


class FakeTier2:
    def __init__(self, *, page=None, raises=None):
        self.page = page or _page()
        self.raises = raises
        self.crawl_calls = []

    def start(self):
        pass

    def crawl(self, url):
        self.crawl_calls.append(url)
        if self.raises is not None:
            raise self.raises
        return self.page

    def close(self):
        pass


# ------------------------------------------------ outcome classification


def test_deferred_tier2_does_not_consume_an_attempt():
    session = RecordingSession()
    client = FakeTier2(raises=Tier2Deferred("budget_or_cooldown", "monthly budget exhausted"))

    outcome = attempt(GENERIC_URL, session, browser_backend="firecrawl", browser_client=client)

    assert outcome.kind is ResolutionOutcomeKind.TRANSIENT_FAILURE


def test_rejected_content_consumes_an_attempt():
    session = RecordingSession()
    client = FakeTier2(raises=Tier2ContentRejected(PageRejection.QUALITY_GATE))

    outcome = attempt(GENERIC_URL, session, browser_backend="firecrawl", browser_client=client)

    assert outcome.kind is ResolutionOutcomeKind.CONTENT_FAILURE


def test_provider_contract_failure_does_not_consume_an_attempt():
    from src.firecrawl.client import ProviderContractError

    session = RecordingSession()
    client = FakeTier2(raises=ProviderContractError("provider reported failure: x"))

    outcome = attempt(GENERIC_URL, session, browser_backend="firecrawl", browser_client=client)

    assert outcome.kind is not ResolutionOutcomeKind.CONTENT_FAILURE


def test_acceptable_page_resolves_as_firecrawl_ats_quality():
    session = RecordingSession()
    client = FakeTier2(page=_page())

    outcome = attempt(GENERIC_URL, session, browser_backend="firecrawl", browser_client=client)

    assert outcome.kind is ResolutionOutcomeKind.RESOLVED
    assert outcome.result.resolver == "firecrawl"
    assert outcome.result.jd_quality == "ats"


def test_navigation_shell_is_a_content_failure_not_a_resolution():
    session = RecordingSession()
    client = FakeTier2(page=_page(NAV_SHELL))

    outcome = attempt(GENERIC_URL, session, browser_backend="firecrawl", browser_client=client)

    assert outcome.kind is ResolutionOutcomeKind.CONTENT_FAILURE


# ------------------------------------------------ routing / etiquette


def test_throttle_happens_before_the_tier2_fetch():
    session = RecordingSession()
    client = FakeTier2()

    attempt(GENERIC_URL, session, browser_backend="firecrawl", browser_client=client)

    kinds = [c[0] for c in session.calls]
    assert "throttle" in kinds
    assert kinds.index("throttle") < len(kinds)
    assert client.crawl_calls == [GENERIC_URL]


def test_generic_html_is_fetched_only_once():
    session = RecordingSession()
    client = FakeTier2()

    attempt(GENERIC_URL, session, browser_backend="firecrawl", browser_client=client)

    assert [c for c in session.calls if c[0] == "get"] == [("get", GENERIC_URL)]


def test_structured_ats_route_never_invokes_tier2():
    session = RecordingSession(_Resp(url="https://boards.greenhouse.io/acme/jobs/1"))
    client = FakeTier2()

    with patch("src.resolve.greenhouse.resolve", return_value=ResolvedJD("jd", "greenhouse")):
        attempt(
            "https://boards.greenhouse.io/acme/jobs/1",
            session,
            browser_backend="firecrawl",
            browser_client=client,
        )

    assert client.crawl_calls == []


def test_successful_plain_generic_extraction_never_invokes_tier2():
    session = RecordingSession()
    client = FakeTier2()

    with patch("src.resolve.generic.extract_from_html", return_value=ResolvedJD("jd", "generic")):
        outcome = attempt(GENERIC_URL, session, browser_backend="firecrawl", browser_client=client)

    assert outcome.kind is ResolutionOutcomeKind.RESOLVED
    assert client.crawl_calls == []


def test_tier2_is_not_attempted_when_backend_is_off():
    session = RecordingSession()
    client = FakeTier2()

    attempt(GENERIC_URL, session, browser_backend="off", browser_client=client)

    assert client.crawl_calls == []


# ------------------------------------------------ config


def test_invalid_browser_backend_fails_before_db_creation(tmp_path):
    config_path = tmp_path / "sources.yaml"
    config_path.write_text("browser_backend: banana\nsources: {}\n")

    with pytest.raises(ValueError, match="banana"):
        run_ingest.load_browser_backend(str(config_path))


def test_legacy_browser_resolver_still_migrates(tmp_path):
    config_path = tmp_path / "sources.yaml"
    config_path.write_text("browser_resolver: true\nsources: {}\n")
    assert run_ingest.load_browser_backend(str(config_path)) == "crawl4ai"


def test_production_default_remains_crawl4ai():
    assert run_ingest.load_browser_backend("config/sources.yaml") == "crawl4ai"


# ------------------------------------------------ per-row isolation


def _run_main(tmp_path, jobs, backend, client, extra_argv=()):
    with (
        patch.object(
            run_ingest, "discover_all",
            return_value=DiscoveryResult(tuple(jobs), (), ("tracker_vansh",), ()),
        ),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(run_ingest, "load_browser_backend", return_value=backend),
        patch.object(run_ingest, "_build_tier2_client", return_value=client),
        patch.object(run_ingest, "PoliteSession", RecordingSession),
    ):
        run_ingest.main([
            "--db", str(tmp_path / "jobs.db"),
            "--digest-dir", str(tmp_path / "digests"),
            "--audit-dir", str(tmp_path / "audit"),
            *extra_argv,
        ])


def test_firecrawl_failure_on_one_row_does_not_abort_later_rows(tmp_path):
    from src.firecrawl.client import ProviderAuthError

    jobs = [
        DiscoveredJob("Acme", "SWE", "Remote", GENERIC_URL, "tracker_vansh", None),
        DiscoveredJob("Beta", "SWE", "Remote", "https://boards.greenhouse.io/beta/jobs/2",
                      "tracker_vansh", None),
    ]
    client = FakeTier2(raises=ProviderAuthError("auth"))

    with patch("src.resolve.greenhouse.resolve", return_value=ResolvedJD("beta jd", "greenhouse")):
        _run_main(tmp_path, jobs, "firecrawl", client)

    conn = db.get_connection(str(tmp_path / "jobs.db"))
    rows = {r["url"]: r for r in conn.execute("SELECT url, status, resolve_attempts FROM jobs")}

    # The tier-1 row still resolved despite the tier-2 provider being down.
    assert rows["https://boards.greenhouse.io/beta/jobs/2"]["status"] == Status.RESOLVED
    # Provider failure is transient: no attempt consumed on the generic row.
    assert rows[GENERIC_URL]["resolve_attempts"] == 0
    assert rows[GENERIC_URL]["status"] == Status.DISCOVERED


def test_content_failure_consumes_an_attempt_end_to_end(tmp_path):
    jobs = [DiscoveredJob("Acme", "SWE", "Remote", GENERIC_URL, "tracker_vansh", None)]
    client = FakeTier2(raises=Tier2ContentRejected(PageRejection.QUALITY_GATE))

    _run_main(tmp_path, jobs, "firecrawl", client)

    conn = db.get_connection(str(tmp_path / "jobs.db"))
    row = conn.execute("SELECT resolve_attempts FROM jobs WHERE url = ?", (GENERIC_URL,)).fetchone()
    assert row["resolve_attempts"] == 1


# ------------------------------------------------ defect 5: integrated dry-run


def test_dry_run_makes_no_firecrawl_request_and_writes_no_ledger(tmp_path, monkeypatch):
    """--dry-run must not fetch, not reserve, not create the ledger, and not
    manufacture a content failure. It also preserves the existing global
    no-write guarantee (the DB stays in memory)."""
    ledger = tmp_path / "firecrawl" / "usage-v1.json"
    db_path = tmp_path / "jobs.db"

    real_build = run_ingest._build_tier2_client
    captured = {}

    def build_with_tmp_ledger(backend, *, dry_run, run_ref, stats=None):
        from src.firecrawl.budget import BudgetManager
        from src.firecrawl.client import BudgetAwareTier2Client

        transport = FakeTier2(page=_page())
        captured["transport"] = transport
        budget = BudgetManager(
            run_ingest.load_firecrawl_config(), ledger_path=str(ledger), run_ref=run_ref
        )
        return BudgetAwareTier2Client(transport, budget, "resolution", dry_run, stats=stats)

    jobs = [DiscoveredJob("Acme", "SWE", "Remote", GENERIC_URL, "tracker_vansh", None)]

    with (
        patch.object(
            run_ingest, "discover_all",
            return_value=DiscoveryResult(tuple(jobs), (), ("tracker_vansh",), ()),
        ),
        patch.object(run_ingest.inbox_manual, "ingest", return_value=InboxResult(0, 0)),
        patch.object(run_ingest, "load_browser_backend", return_value="firecrawl"),
        patch.object(run_ingest, "_build_tier2_client", build_with_tmp_ledger),
        patch.object(run_ingest, "PoliteSession", RecordingSession),
    ):
        run_ingest.main([
            "--dry-run",
            "--db", str(db_path),
            "--digest-dir", str(tmp_path / "digests"),
            "--audit-dir", str(tmp_path / "audit"),
        ])

    assert captured["transport"].crawl_calls == [], "dry-run must not call Firecrawl"
    assert not ledger.exists(), "dry-run must not create the ledger"
    assert not db_path.exists(), "dry-run must not write the DB"

    assert real_build is run_ingest._build_tier2_client
