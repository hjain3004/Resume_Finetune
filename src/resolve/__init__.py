"""Router: dispatch a discovered URL to the right resolver by hostname,
routing on the final URL after redirects per ARCHITECTURE §6.1."""

from __future__ import annotations

from urllib.parse import urlparse

import requests

from src.models import ResolvedJD
from src.resolve import amazon_jobs, ashby, browser, generic, greenhouse, jobright, lever, workday, wrapper
from src.resolve.browser import BrowserUnavailableError
from src.resolve.outcomes import ResolutionOutcome
from src.resolve.tier2 import Tier2ContentRejected, Tier2Deferred

# I9 (docs/SELF_HEALING.md §1): bump whenever resolver/cleaner behavior
# changes so active rows resolved under an older version get flagged for
# re-resolution by the audit. PROTECTED-adjacent: bumping this is expected
# maintenance (not a schema/threshold change), but do it deliberately — every
# bump makes the next audit run WARN on every currently-active row.
LOGIC_VERSION = 1

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


def resolve(
    url: str, session, *, browser_backend: str = "off", browser_client=None
) -> ResolvedJD | None:
    response = session.get(url)
    if response.status_code != 200:
        if browser_backend != "off" and browser_client is not None and route(url) is generic:
            return browser.resolve(url, session, browser_client, provider_name=browser_backend)
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
        
        result = generic.extract_from_html(response.text)
        if result is not None:
            return result
            
        if browser_backend != "off" and browser_client is not None:
            return browser.resolve(final_url, session, browser_client, provider_name=browser_backend)
        return None
    if module is jobright:
        return jobright.resolve(
            final_url,
            response.text,
            session,
            browser_backend=browser_backend,
            browser_client=browser_client,
        )
    return module.resolve(final_url, session)


def attempt(
    url: str,
    session,
    *,
    browser_backend: str = "off",
    browser_client=None,
) -> ResolutionOutcome:
    """M6.10: typed orchestration boundary. Individual resolver modules keep
    their `ResolvedJD | None` contract; this wrapper turns a `requests`
    transport failure or a browser-unavailable failure into
    `TRANSIENT_FAILURE` (neither consumes `resolve_attempts`), and a `None`
    result into `CONTENT_FAILURE` (the only outcome that does)."""
    try:
        result = resolve(
            url,
            session,
            browser_backend=browser_backend,
            browser_client=browser_client,
        )
    except requests.exceptions.RequestException as exc:
        return ResolutionOutcome.transient("http_transport", exc)
    except BrowserUnavailableError as exc:
        return ResolutionOutcome.transient("browser_unavailable", exc)
    except Tier2ContentRejected as exc:
        # M9F-0: the page was fetched and judged unacceptable. The request is
        # already charged and in cooldown, so this consumes the row's attempt
        # budget exactly like any other content failure.
        return ResolutionOutcome.content_failure(f"tier2_{exc.rejection.value}", str(exc))
    except Tier2Deferred as exc:
        # Budget exhaustion, URL cooldown, or --dry-run: no fetch happened and
        # no content judgment was made, so no attempt is consumed.
        return ResolutionOutcome.transient(f"tier2_{exc.reason_code}", exc)
    except Exception as exc:
        # Catch provider errors dynamically so we don't import firecrawl in __init__.py unless necessary
        exc_name = type(exc).__name__
        if exc_name in ("ProviderTransientError", "ProviderAuthError", "ConfigurationError", "BudgetExhaustedError"):
            return ResolutionOutcome.transient("provider_transient", exc)
        if exc_name == "ProviderContractError":
            # The provider answered but delivered no page. Not a content
            # judgment, so the row keeps its attempt budget.
            return ResolutionOutcome.internal("provider_contract", exc)
        raise
    return (
        ResolutionOutcome.resolved(result)
        if result is not None
        else ResolutionOutcome.content_failure("no_acceptable_content")
    )


MANUAL_DOMAINS_PATH = "config/manual_domains.txt"


def load_manual_domains(path: str = MANUAL_DOMAINS_PATH) -> set[str]:
    domains: set[str] = set()
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                domains.add(line)
    return domains


def is_manual_domain(url: str, manual_domains: set[str] | None = None) -> bool:
    """I2 (docs/SELF_HEALING.md §2 'I2 fires' step 3): a hostname listed in
    config/manual_domains.txt is known bot-gated — routes straight to the
    digest's 'needs your help' section without spending the resolve_attempts
    retry budget. run_ingest.run_resolution() checks this before calling
    resolve()."""
    manual_domains = load_manual_domains() if manual_domains is None else manual_domains
    hostname = urlparse(url).hostname or ""
    return hostname in manual_domains
