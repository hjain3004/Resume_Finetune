"""Discovery adapter protocol."""

from __future__ import annotations

from typing import Protocol

from src.models import DiscoveredJob


class DiscoverAdapter(Protocol):
    SOURCE_NAME: str

    def discover(self, config: dict) -> list[DiscoveredJob]: ...
