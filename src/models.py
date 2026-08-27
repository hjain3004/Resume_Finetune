"""Dataclasses, enums, and normalization helpers shared across the pipeline."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit


class ManualUrlError(ValueError):
    """Raised when a manual job URL is invalid or contains sensitive credentials."""


class Status(StrEnum):
    DISCOVERED = "DISCOVERED"
    RESOLVED = "RESOLVED"
    RESOLVE_FAILED = "RESOLVE_FAILED"
    FILTERED_OUT = "FILTERED_OUT"
    SCORED = "SCORED"
    SHORTLISTED = "SHORTLISTED"
    TAILORED = "TAILORED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"  # M6.8: posting verified dead by a liveness recheck


# M6.8: terminal statuses eligible for repost-detection comparison and for the
# resurfacing rule's "was this ever actually evaluated" check.
TERMINAL_STATUSES: tuple[Status, ...] = (
    Status.FILTERED_OUT,
    Status.REJECTED,
    Status.APPLIED,
    Status.CLOSED,
)


# Source priority for dedup conflict resolution, best first.
SOURCE_PRIORITY: tuple[str, ...] = (
    "inbox",
    "tracker_simplify",
    "tracker_vansh",
    "tracker_jobright",
)


@dataclass(frozen=True)
class DiscoveredJob:
    company: str
    title: str
    location: str | None
    url: str
    source: str
    date_posted: str | None  # ISO date or None
    identity_key: str | None = None


@dataclass(frozen=True)
class ResolvedJD:
    jd_text: str
    resolver: str
    raw_title: str | None = None
    raw_location: str | None = None
    ats_url: str | None = None
    flags: list[str] | None = None
    jd_quality: str | None = None
    notes: str | None = None


_CORP_SUFFIXES = {"inc", "llc", "ltd", "corp", "co"}
_REMOTE_LOCATIONS = {
    "remote",
    "remote us",
    "remote usa",
    "united states remote",
    "us remote",
}
_TRAILING_REQ_ID_RE = re.compile(r"\s*#?\d{4,}\s*$")
_REQ_PAREN_RE = re.compile(r"\s*\(req[^)]*\)\s*$", re.IGNORECASE)
_BRACKET_ID_RE = re.compile(r"\s*\[[A-Za-z]?-?\d[\w-]*\]\s*$")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Lowercase, strip accents/punctuation/requisition IDs, collapse whitespace."""
    s = s or ""
    s = _TRAILING_REQ_ID_RE.sub("", s)
    s = _REQ_PAREN_RE.sub("", s)
    s = _BRACKET_ID_RE.sub("", s)
    s = s.lower()
    s = _strip_accents(s)
    s = _PUNCT_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()

    words = s.split(" ")
    while words and words[-1] in _CORP_SUFFIXES:
        words.pop()
    return " ".join(words)


def norm_loc(s: str | None) -> str:
    if not s:
        return "unknown"
    normalized = norm(s)
    if normalized in _REMOTE_LOCATIONS:
        return "remote-us"
    return normalized or "unknown"


def dedup_key(company: str, title: str, location: str | None) -> str:
    payload = f"{norm(company)}|{norm(title)}|{norm_loc(location)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_JOB_DETAILS_BOUNDARY_RE = re.compile(
    r"\s*[-|·•]\s*#?\d{3,}\s*job details\b.*$",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_TRAILING_FURNITURE_RE = re.compile(
    r"\s*[-|·•]\s*"
    r"(?:#?\d{3,}\s*)?"
    r"(?:[\w.&'-]+\s+)?"
    r"(?:job details|careers?|jobs?|apply(?:\s+now)?|job postings?)?"
    r"\s*$",
    re.IGNORECASE,
)


def clean_title(raw: str | None) -> str | None:
    """Strip trailing requisition IDs and page-furniture suffixes from a
    resolver-backfilled title, e.g. 'Front End Developer (Hybrid) - 28751 Job
    Details' -> 'Front End Developer (Hybrid)'. Unlike norm(), this preserves
    human-readable casing and punctuation — it's for display, not dedup keys.

    A "<reqid> Job Details" marker is treated as a hard boundary even when
    more text follows it (some ATS wrappers append redundant company/division
    furniture after it, e.g. "... 28751 Job Details / Acme's Widgets div")."""
    if not raw:
        return raw
    title = raw.strip()
    boundary_stripped = _JOB_DETAILS_BOUNDARY_RE.sub("", title).strip()
    if boundary_stripped and boundary_stripped != title:
        title = boundary_stripped
    while True:
        stripped = _TITLE_TRAILING_FURNITURE_RE.sub("", title).strip()
        if stripped == title or not stripped:
            return title
        title = stripped


_SENSITIVE_PARAM_KEYS = frozenset({
    "token",
    "access_token",
    "auth",
    "authorization",
    "api_key",
    "apikey",
    "secret",
    "signature",
    "session",
    "sessionid",
    "jwt",
})

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def canonical_job_url(raw_url: str) -> str:
    """Validate and deterministically canonicalize a job URL."""
    if not isinstance(raw_url, str):
        raise ManualUrlError("URL must be a string")
    url = raw_url.strip()
    if not url:
        raise ManualUrlError("empty URL")

    try:
        parsed = urlsplit(url)
    except Exception as exc:
        raise ManualUrlError("malformed URL") from exc

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ManualUrlError("unsupported URL scheme (only http and https allowed)")

    if not parsed.netloc:
        raise ManualUrlError("missing hostname in URL")

    # Reject embedded userinfo
    if "@" in parsed.netloc or parsed.username or parsed.password:
        host = parsed.hostname or "unknown"
        raise ManualUrlError(f"embedded credentials not allowed for {host}")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ManualUrlError("missing hostname in URL")

    # Port handling: omit default 80 for http and 443 for https
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None

    netloc_normalized = f"{hostname}:{port}" if port else hostname

    # Path normalization: empty -> /, non-root trailing slash stripped
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Query inspection & normalization
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    for key, _ in query_items:
        if key.lower() in _SENSITIVE_PARAM_KEYS:
            raise ManualUrlError(f"sensitive query parameter detected for {hostname}")

    # Fragment inspection (for sensitive keys in query-like fragments)
    fragment = parsed.fragment or ""
    if fragment:
        frag_query_part = fragment.split("?", 1)[-1] if "?" in fragment else fragment
        for frag_k, _ in parse_qsl(frag_query_part, keep_blank_values=True):
            if frag_k.lower() in _SENSITIVE_PARAM_KEYS:
                raise ManualUrlError(f"sensitive parameter in URL fragment for {hostname}")

    # Filter out marketing parameters
    filtered_query = [
        (k, v)
        for k, v in query_items
        if not (k.lower().startswith("utm_") or k.lower() in ("fbclid", "gclid"))
    ]
    filtered_query.sort(key=lambda item: (item[0], item[1]))
    query_str = urlencode(filtered_query, doseq=False) if filtered_query else ""

    result = f"{scheme}://{netloc_normalized}{path}"
    if query_str:
        result = f"{result}?{query_str}"
    if fragment:
        result = f"{result}#{fragment}"
    return result


def manual_url_dedup_key(raw_url: str) -> str:
    """Return a deterministic 64-char hex SHA-256 digest for a manual URL."""
    canonical = canonical_job_url(raw_url)
    payload = f"manual-url-v1|{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stable_posting_identity(raw_url: str) -> str | None:
    """Extract a bounded, conservative requisition identity for recognized ATS/host patterns."""
    if not raw_url or not isinstance(raw_url, str):
        return None
    try:
        parsed = urlsplit(raw_url.strip())
    except Exception:
        return None

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return None

    query_dict = dict(parse_qsl(parsed.query, keep_blank_values=True))
    # 1. gh_jid parameter on any host (wrappers/careers)
    if "gh_jid" in query_dict:
        gh_jid = query_dict["gh_jid"].strip()
        if gh_jid.isdigit() and len(gh_jid) <= 30:
            return f"greenhouse:{gh_jid}"

    path = parsed.path or ""

    # 2. Greenhouse board paths
    if hostname in ("job-boards.greenhouse.io", "boards.greenhouse.io"):
        m = re.match(r"^/([^/]+)/jobs/(\d+)(?:/|$)", path)
        if m:
            return f"greenhouse:{m.group(2)}"

    # 3. Roblox careers paths
    if hostname in ("careers.roblox.com", "roblox.com"):
        m = re.match(r"^/jobs/(\d+)(?:/|$)", path)
        if m:
            return f"greenhouse:{m.group(1)}"

    # 4. Ashby
    if hostname == "jobs.ashbyhq.com":
        m = re.match(r"^/([^/]+)/([^/]+)(?:/|$)", path)
        if m:
            org = unquote(m.group(1)).lower().strip()
            jid = unquote(m.group(2)).lower().strip()
            if org and jid and len(org) <= 100 and len(jid) <= 100:
                return f"ashby:{org}:{jid}"

    # 5. Lever
    if hostname == "jobs.lever.co":
        m = re.match(r"^/([^/]+)/([^/]+)(?:/|$)", path)
        if m:
            org = unquote(m.group(1)).lower().strip()
            jid = unquote(m.group(2)).lower().strip()
            if org and jid and len(org) <= 100 and len(jid) <= 100:
                return f"lever:{org}:{jid}"

    # 6. Workday (*.myworkdayjobs.com)
    if hostname.endswith(".myworkdayjobs.com"):
        parts = [unquote(p).lower().strip() for p in path.strip("/").split("/") if p]
        if parts:
            final_component = parts[-1]
            if final_component and len(final_component) <= 150:
                return f"workday:{hostname}:{final_component}"

    # 7. Apple
    if hostname == "jobs.apple.com":
        m = re.search(r"/details/(\d+)(?:/|$)", path)
        if m:
            return f"apple:{m.group(1)}"

    # 8. TikTok
    if hostname in ("lifeattiktok.com", "www.lifeattiktok.com"):
        m = re.search(r"/search/(\d+)(?:/|$)", path)
        if m:
            return f"tiktok:{m.group(1)}"

    # 9. Revolut (final component ends with or is a UUID)
    if hostname in ("www.revolut.com", "revolut.com"):
        parts = [unquote(p).lower().strip() for p in path.strip("/").split("/") if p]
        if parts:
            m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", parts[-1], re.IGNORECASE)
            if m:
                return f"revolut:{m.group(1).lower()}"

    return None


def collision_dedup_key(semantic_key: str, posting_identity: str) -> str:
    """Return a versioned 64-char SHA-256 digest combining semantic key and stable posting identity."""
    payload = f"collision-v1|{semantic_key}|{posting_identity}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

