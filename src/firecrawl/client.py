from __future__ import annotations
import os
import requests
import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

class ConfigurationError(RuntimeError):
    pass

class ProviderAuthError(RuntimeError):
    pass

class ProviderTransientError(RuntimeError):
    pass

@dataclass(frozen=True)
class FirecrawlScrapeResult:
    markdown: str
    final_url: str
    status_code: int | None
    scrape_id: str | None
    credits_used: int
    cache_state: str | None

@dataclass(frozen=True)
class Tier2Page:
    markdown: str
    html: str | None
    final_url: str
    status_code: int | None
    provider: str
    credits_used: int

class Tier2Client(Protocol):
    def start(self) -> None: ...
    def crawl(self, url: str) -> Tier2Page: ...
    def close(self) -> None: ...

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
            
        if not data.get("success"):
            # Could be a scraping failure, but not necessarily a transient failure for other pages
            # Actually, per spec, if it's 4xx/5xx from provider, it's transient, but if the scraped page is dead, success is sometimes true or false.
            # "Empty markdown, a fetched 4xx/5xx page, a dead-posting notice, or text failing the existing quality gate is a content failure."
            # Firecrawl returns success=False if it totally fails to scrape. We'll treat it as empty markdown to let the content pipeline handle it, OR we raise transient.
            error_message = data.get("error", "Unknown error")
            return Tier2Page(
                markdown="",
                html=None,
                final_url=url,
                status_code=None,
                provider="firecrawl",
                credits_used=1
            )
            
        result = data.get("data", {})
        markdown = result.get("markdown", "")
        metadata = result.get("metadata", {})
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
    def __init__(self, client: Tier2Client, budget, purpose: str, dry_run: bool):
        self._client = client
        self._budget = budget
        self._purpose = purpose
        self._dry_run = dry_run
        
    def start(self) -> None:
        self._client.start()
        
    def crawl(self, url: str) -> Tier2Page:
        # Resolve reserves 1 credit
        req_id = self._budget.reserve(self._purpose, url, 1, dry_run=self._dry_run)
        if self._dry_run:
            # Fake successful response for dry run
            return Tier2Page("", None, url, 200, "firecrawl", 1)
            
        try:
            page = self._client.crawl(url)
            content_failed = not page.markdown
            self._budget.reconcile(req_id, page.credits_used, "success", content_failed=content_failed)
            return page
        except Exception as exc:
            # Mark charged on transient/internal errors per spec
            self._budget.mark_charged(req_id, type(exc).__name__)
            raise
            
    def close(self) -> None:
        self._client.close()
