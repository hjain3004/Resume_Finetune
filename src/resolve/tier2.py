from typing import Protocol
from dataclasses import dataclass

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

class PoliteSession:
    """Mock for PoliteSession from src.resolve.base, let's assume it exists and we'll just patch the file instead of creating a new one."""
    pass
