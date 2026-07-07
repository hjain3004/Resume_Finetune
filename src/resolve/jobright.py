"""Resolver for jobright.com/jobright.ai aggregator pages, per
PHASE2_KICKOFF.md M6.2.

Jobright pages don't host the employer's original posting; two-part fix:

1. ATS link extraction (preferred): scan outbound anchors for a known ATS
   host or an "Apply"/"Original" link, and re-route resolution to it through
   the normal router. Live evidence: jobright's actual apply flow is
   client-rendered (no outbound link in the static HTML), so this rarely
   fires today but stays as the preferred path per spec.
2. Fallback: jobright's own Next.js page embeds a structured `__NEXT_DATA__`
   JSON blob with `jobSummary`/`coreResponsibilities`/`qualifications` and
   boolean flags (`isH1bSponsor` etc.) — this is a cleaner and more robust
   source than regex-scrubbing the rendered HTML text, so we build jd_text
   from it directly. Approved deviation from the doc's literal
   regex-cleaning spec; recorded in DECISIONS.md.
"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import urlparse

from src.models import ResolvedJD

RESOLVER_NAME = "jobright"
_JOBRIGHT_HOSTS = ("jobright.com", "jobright.ai")

_ANCHOR_RE = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


def _is_jobright_host(host: str) -> bool:
    host = host.lower()
    return any(host == needle or host.endswith("." + needle) for needle in _JOBRIGHT_HOSTS)


def find_ats_link(html_text: str) -> str | None:
    """Find an outbound anchor pointing at the underlying ATS/employer posting."""
    from src.resolve import route, generic  # deferred: avoids circular import at load time

    for href, inner_html in _ANCHOR_RE.findall(html_text or ""):
        host = urlparse(href).hostname or ""
        if not host or _is_jobright_host(host):
            continue
        anchor_text = html.unescape(_TAG_RE.sub("", inner_html)).strip().lower()
        if route(href) is not generic or "apply" in anchor_text or "original" in anchor_text:
            return href
    return None


def _extract_job_result(html_text: str) -> dict | None:
    match = _NEXT_DATA_RE.search(html_text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    try:
        return data["props"]["pageProps"]["dataSource"]["jobResult"]
    except (KeyError, TypeError):
        return None


def _format_qualifications(qualifications: dict) -> str:
    lines = []
    for label, key in (("Must have", "mustHave"), ("Preferred", "preferredHave")):
        items = qualifications.get(key) or []
        if items:
            lines.append(f"{label}:")
            lines.extend(f"- {item}" for item in items)
    return "\n".join(lines)


def _build_jd_text(job: dict) -> str:
    parts = []
    summary = job.get("jobSummary")
    if summary:
        parts.append(summary)
    responsibilities = job.get("coreResponsibilities") or []
    if responsibilities:
        parts.append("Responsibilities:\n" + "\n".join(f"- {r}" for r in responsibilities))
    qualifications_text = _format_qualifications(job.get("qualifications") or {})
    if qualifications_text:
        parts.append("Qualifications:\n" + qualifications_text)
    return "\n\n".join(parts)


def resolve(url: str, html_text: str, session) -> ResolvedJD | None:
    ats_link = find_ats_link(html_text)
    if ats_link:
        from src.resolve import route  # deferred: avoids circular import at load time

        result = route(ats_link).resolve(ats_link, session)
        if result is None:
            return None
        return ResolvedJD(
            jd_text=result.jd_text,
            resolver=result.resolver,
            raw_title=result.raw_title,
            raw_location=result.raw_location,
            ats_url=ats_link,
            jd_quality="ats",
            notes=f"jobright: {url}",
        )

    job = _extract_job_result(html_text)
    if job is None:
        return None
    jd_text = _build_jd_text(job)
    if not jd_text:
        return None

    return ResolvedJD(
        jd_text=jd_text,
        resolver=RESOLVER_NAME,
        raw_title=job.get("jobTitle"),
        raw_location=job.get("jobLocation"),
        jd_quality="aggregator",
        flags=["sponsor_likely"] if job.get("isH1bSponsor") else None,
        notes=f"jobright aggregator: {url}",
    )
