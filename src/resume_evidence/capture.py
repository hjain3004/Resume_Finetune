"""Transport-neutral private captures for bounded resume research."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

SCHEMA_VERSION = "m8q.research_capture.v1"
_SENSITIVE_KEYS = {"api_key", "apikey", "token", "access_token", "auth", "authorization", "password", "passwd", "secret", "session", "cookie"}


class CaptureTransport(str, Enum):
    FIRECRAWL = "firecrawl"
    CRAWL4AI = "crawl4ai"


@dataclass(frozen=True)
class ResearchCapture:
    schema_version: str
    source_url: str
    final_url: str
    transport: CaptureTransport
    captured_at: str
    markdown: str
    links: tuple[str, ...]
    html_sha256: str | None
    layout_capture_available: bool
    transport_metadata: tuple[tuple[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_url": self.source_url,
            "final_url": self.final_url,
            "transport": self.transport.value,
            "captured_at": self.captured_at,
            "markdown": self.markdown,
            "links": list(self.links),
            "html_sha256": self.html_sha256,
            "layout_capture_available": self.layout_capture_available,
            "transport_metadata": dict(self.transport_metadata),
        }


def _url(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: expected URL")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"{field}: unsafe URL")
    if any(key.casefold() in _SENSITIVE_KEYS for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise ValueError(f"{field}: query contains sensitive key")
    if parts.hostname.casefold() == "linkedin.com" or parts.hostname.casefold().endswith(".linkedin.com"):
        raise ValueError(f"{field}: LinkedIn URL is forbidden")
    return urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))


def _validate(raw: object) -> ResearchCapture:
    if not isinstance(raw, dict):
        raise ValueError("capture: expected object")
    fields = {"schema_version", "source_url", "final_url", "transport", "captured_at", "markdown", "links", "html_sha256", "layout_capture_available", "transport_metadata"}
    if set(raw) != fields:
        raise ValueError("capture: unexpected or missing fields")
    if raw["schema_version"] != SCHEMA_VERSION:
        raise ValueError("capture.schema_version: unsupported")
    source_url = _url(raw["source_url"], "capture.source_url")
    final_url = _url(raw["final_url"], "capture.final_url")
    source_host = (urlsplit(source_url).hostname or "").casefold().removeprefix("www.")
    final_host = (urlsplit(final_url).hostname or "").casefold().removeprefix("www.")
    if source_host != final_host:
        raise ValueError("capture.final_url: off-domain redirect")
    if source_host != "huntr.co":
        raise ValueError("capture.source_url: unsupported host")
    try:
        transport = CaptureTransport(raw["transport"])
    except (ValueError, TypeError) as exc:
        raise ValueError("capture.transport: unsupported transport") from exc
    timestamp = raw["captured_at"]
    if not isinstance(timestamp, str) or len(timestamp) != 20 or timestamp[-1] != "Z":
        raise ValueError("capture.captured_at: expected UTC timestamp")
    markdown = raw["markdown"]
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("capture.markdown: expected nonempty string")
    links = raw["links"]
    if not isinstance(links, list):
        raise ValueError("capture.links: expected array")
    normalized_links = tuple(_url(urljoin(source_url, item), "capture.links[]") for item in links if isinstance(item, str))
    if len(normalized_links) != len(links) or len(set(normalized_links)) != len(normalized_links):
        raise ValueError("capture.links: duplicate or invalid link")
    digest = raw["html_sha256"]
    if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or digest != digest.lower() or any(char not in "0123456789abcdef" for char in digest)):
        raise ValueError("capture.html_sha256: invalid hash")
    if not isinstance(raw["layout_capture_available"], bool):
        raise ValueError("capture.layout_capture_available: expected boolean")
    metadata = raw["transport_metadata"]
    if not isinstance(metadata, dict) or any(not isinstance(key, str) for key in metadata):
        raise ValueError("capture.transport_metadata: expected object")
    return ResearchCapture(SCHEMA_VERSION, source_url, final_url, transport, timestamp, markdown, normalized_links, digest, raw["layout_capture_available"], tuple(metadata.items()))


def parse_capture(raw: object) -> ResearchCapture:
    return _validate(raw)


def _links(source_url: str, links: object) -> list[str]:
    if not isinstance(links, list):
        return []
    return [urljoin(source_url, item) for item in links if isinstance(item, str)]


def normalize_firecrawl_capture(raw: object, source_url: str, captured_at: str) -> ResearchCapture:
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), dict):
        raise ValueError("firecrawl capture: expected data object")
    data = raw["data"]
    envelope = {"schema_version": SCHEMA_VERSION, "source_url": source_url, "final_url": data.get("metadata", {}).get("url", source_url) if isinstance(data.get("metadata"), dict) else source_url, "transport": "firecrawl", "captured_at": captured_at, "markdown": data.get("markdown"), "links": _links(source_url, data.get("links", [])), "html_sha256": None, "layout_capture_available": bool(data.get("screenshot")), "transport_metadata": {"firecrawl_attempted": True}}
    return parse_capture(envelope)


def normalize_crawl4ai_capture(raw: object, source_url: str, captured_at: str, *, firecrawl_failure: str | None = None) -> ResearchCapture:
    if not isinstance(raw, dict):
        raise ValueError("crawl4ai capture: expected object")
    html = raw.get("html") or ""
    metadata = {"crawl4ai_attempted": True}
    if firecrawl_failure is not None:
        metadata.update({"firecrawl_attempted": True, "firecrawl_result": firecrawl_failure})
    envelope = {"schema_version": SCHEMA_VERSION, "source_url": source_url, "final_url": raw.get("final_url", source_url), "transport": "crawl4ai", "captured_at": captured_at, "markdown": raw.get("markdown"), "links": _links(source_url, raw.get("links", [])), "html_sha256": hashlib.sha256(html.encode()).hexdigest() if html else None, "layout_capture_available": False, "transport_metadata": metadata}
    return parse_capture(envelope)


def write_capture_atomic(path: Path, capture: ResearchCapture) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(capture.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp, path)
    except Exception:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
