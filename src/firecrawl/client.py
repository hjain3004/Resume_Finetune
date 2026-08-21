from __future__ import annotations
import os
import requests
import logging
from dataclasses import dataclass

from src.firecrawl.budget import BudgetExhaustedError
from src.resolve.tier2 import (
    Tier2Client,
    Tier2ContentRejected,
    Tier2Deferred,
    Tier2Page,
    page_rejection,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BudgetAwareTier2Client",
    "ConfigurationError",
    "FirecrawlClient",
    "FirecrawlScrapeResult",
    "ProviderAuthError",
    "ProviderContractError",
    "ProviderTransientError",
    "Tier2Client",
    "Tier2Page",
]

class ConfigurationError(RuntimeError):
    pass

class ProviderAuthError(RuntimeError):
    pass

class ProviderTransientError(RuntimeError):
    pass

class ProviderContractError(RuntimeError):
    """The provider answered, but did not deliver a usable page.

    Covers `success: false` and a malformed success payload (design section 11,
    "malformed success payload: internal/provider-contract error"). Deliberately
    distinct from a content failure: no page was judged, so the row's
    `resolve_attempts` is not consumed and no cooldown is applied. Also
    deliberately does *not* trip the run-local breaker -- one URL the provider
    could not scrape is not evidence of a provider-wide outage."""

#: Provider diagnostics are echoed back bounded, so a large or hostile error
#: body cannot flood logs or run notes. External text is data, never
#: instructions.
_MAX_PROVIDER_MESSAGE = 300


@dataclass
class FirecrawlRunStats:
    """Run-scoped Firecrawl counters for run notes and the digest (design
    section 14). Deliberately holds no URLs, no page text, and no credentials
    -- only counts and credit totals."""

    attempted: int = 0
    deferred: int = 0
    accepted: int = 0
    content_failed: int = 0
    provider_failed: int = 0
    credits_reserved: int = 0
    credits_finalized: int = 0

    def as_payload(self, *, backend: str, remaining: dict | None = None) -> dict:
        payload = {
            "backend": backend,
            "attempted": self.attempted,
            "deferred": self.deferred,
            "accepted": self.accepted,
            "content_failed": self.content_failed,
            "provider_failed": self.provider_failed,
            "credits_reserved": self.credits_reserved,
            "credits_finalized": self.credits_finalized,
        }
        if remaining is not None:
            payload["remaining"] = remaining
        return payload

@dataclass(frozen=True)
class FirecrawlScrapeResult:
    markdown: str
    final_url: str
    status_code: int | None
    scrape_id: str | None
    credits_used: int
    cache_state: str | None

class FirecrawlClient:
    def __init__(self, config: dict):
        self.config = config
        self.api_key = os.environ.get("FIRECRAWL_API_KEY")
        self.api_url = os.environ.get("FIRECRAWL_API_URL", "https://api.firecrawl.dev/v2")
        self.session = requests.Session()
        self._tripped = False
        self._trip_reason = None
        
    def start(self) -> None:
        if not self.api_key:
            raise ConfigurationError("FIRECRAWL_API_KEY not found in environment")
            
    def crawl(self, url: str) -> Tier2Page:
        if self._tripped:
            raise ProviderTransientError(f"Firecrawl circuit breaker tripped: {self._trip_reason}")
            
        if not self.api_key:
            raise ConfigurationError("FIRECRAWL_API_KEY not found in environment")
            
        scrape_cfg = self.config.get("scrape", {})
        payload = {
            "url": url,
            "formats": ["markdown"],
            "onlyMainContent": scrape_cfg.get("only_main_content", True),
            "removeBase64Images": scrape_cfg.get("remove_base64_images", True),
            "proxy": "basic",
            "maxAge": scrape_cfg.get("max_age_ms", 86400000),
            "storeInCache": True,
            "location": scrape_cfg.get("location", {"country": "US", "languages": ["en-US"]})
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        timeout = scrape_cfg.get("timeout_seconds", 60)
        
        try:
            resp = self.session.post(f"{self.api_url}/scrape", json=payload, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            self._tripped = True
            self._trip_reason = f"transport failure: {type(exc).__name__}"
            raise ProviderTransientError(self._trip_reason) from exc
            
        if resp.status_code in (401, 403):
            self._tripped = True
            self._trip_reason = "authentication failure"
            raise ProviderAuthError("authentication failure (401/403)")
            
        if resp.status_code == 429 or resp.status_code >= 500:
            self._tripped = True
            self._trip_reason = f"provider error {resp.status_code}"
            raise ProviderTransientError(self._trip_reason)
            
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderTransientError("invalid JSON from provider") from exc
            
        if not isinstance(data, dict):
            raise ProviderContractError(
                f"provider returned {type(data).__name__}, expected an object"
            )

        if not data.get("success"):
            # The provider explicitly reports it produced no page. This is a
            # provider-contract failure, not a judgment about the page's
            # content -- fabricating an empty page here would charge the row an
            # attempt and a 24h cooldown for something the page never caused.
            detail = str(data.get("error", "no error message"))[:_MAX_PROVIDER_MESSAGE]
            raise ProviderContractError(f"provider reported failure: {detail}")

        result = data.get("data")
        if not isinstance(result, dict) or "markdown" not in result:
            raise ProviderContractError(
                "provider success payload missing 'data.markdown'"
            )

        markdown = result.get("markdown") or ""
        metadata = result.get("metadata") or {}
        final_url = metadata.get("sourceURL", url)
        status_code = metadata.get("statusCode", 200)

        return Tier2Page(
            markdown=markdown,
            html=None,
            final_url=final_url,
            status_code=status_code,
            provider="firecrawl",
            credits_used=1
        )
        
    def close(self) -> None:
        self.session.close()

class BudgetAwareTier2Client:
    """Wraps a paid tier-2 transport with the local credit budget.

    Ordering is the whole point of this class (M9F-0 defects 2, 4, 5):

    1. the underlying client is started *before* any reservation, so missing
       credentials cost nothing and write no ledger record;
    2. `--dry-run` returns a typed deferral and never reaches the transport;
    3. the reservation is taken before paid network I/O;
    4. the budget is reconciled only *after* the shared deterministic
       acceptance decision, so a nonempty navigation shell is recorded as a
       charged content failure with a cooldown rather than as a success.
    """

    #: Basic scrape is a fixed-cost operation (design section 9).
    RESERVE_CREDITS = 1

    def __init__(
        self,
        client: Tier2Client,
        budget,
        purpose: str,
        dry_run: bool,
        job_ref: str | None = None,
        stats: "FirecrawlRunStats | None" = None,
    ):
        self._client = client
        self._budget = budget
        self._purpose = purpose
        self._dry_run = dry_run
        self._job_ref = job_ref
        self._stats = stats
        self._started = False
        self._disabled_reason: str | None = None

    def start(self) -> None:
        self._ensure_started()

    def _ensure_started(self) -> None:
        """Idempotent. Once the client is known to be misconfigured, fail fast
        without re-attempting startup for the rest of the run."""
        if self._disabled_reason is not None:
            raise ConfigurationError(self._disabled_reason)
        if self._started:
            return
        try:
            self._client.start()
        except ConfigurationError as exc:
            self._disabled_reason = str(exc)
            if self._stats is not None:
                self._stats.provider_failed += 1
            raise
        self._started = True

    def crawl(self, url: str) -> Tier2Page:
        self._ensure_started()

        if self._dry_run:
            # Never a paid request, never a ledger record, and never a fake
            # page that downstream code could mistake for a content failure.
            if self._stats is not None:
                self._stats.deferred += 1
            raise Tier2Deferred("dry_run", "dry-run: no Firecrawl request performed")

        try:
            req_id = self._budget.reserve(
                self._purpose, url, self.RESERVE_CREDITS, job_ref=self._job_ref
            )
        except BudgetExhaustedError as exc:
            if self._stats is not None:
                self._stats.deferred += 1
            raise Tier2Deferred("budget_or_cooldown", str(exc)) from exc

        if self._stats is not None:
            self._stats.attempted += 1
            self._stats.credits_reserved += self.RESERVE_CREDITS

        try:
            page = self._client.crawl(url)
        except Exception as exc:
            # Billing is uncertain once the request left, so fail closed and
            # keep the reservation charged at its reserved cost.
            self._budget.mark_charged(req_id, type(exc).__name__)
            if self._stats is not None:
                self._stats.provider_failed += 1
            raise

        rejection = page_rejection(page)
        if rejection is None:
            self._budget.reconcile(req_id, page.credits_used, "accepted")
            if self._stats is not None:
                self._stats.accepted += 1
                self._stats.credits_finalized += page.credits_used
            return page

        self._budget.reconcile(
            req_id,
            page.credits_used,
            f"content_failed:{rejection.value}",
            content_failed=True,
        )
        if self._stats is not None:
            self._stats.content_failed += 1
            self._stats.credits_finalized += page.credits_used
        raise Tier2ContentRejected(rejection)

    def close(self) -> None:
        self._client.close()
