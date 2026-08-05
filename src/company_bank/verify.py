from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

from src.company_bank.model import ResearchBundle


class SourceVerdict(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int | None
    text: str
    error: str | None


@dataclass(frozen=True)
class SourceVerification:
    company_id: str
    source_id: str
    url: str
    verdict: SourceVerdict
    reason: str
    quotes_checked: int
    quotes_found: int


@dataclass(frozen=True)
class BundleVerification:
    company_id: str
    results: tuple[SourceVerification, ...]


@dataclass(frozen=True)
class SnapshotLintFinding:
    company_id: str
    source_id: str
    metric: str
    value: float
    threshold: float
    message: str


def normalize_for_match(text: str) -> str:
    """Collapse all whitespace runs to a single space and strip.
    Does not case-fold, strip punctuation, or normalise Unicode quotes.
    """
    return " ".join(text.split())


def classify_source(
    fetch_result: FetchResult,
    quotes: Sequence[str],
    min_text_chars: int = 500,
) -> tuple[SourceVerdict, str, int]:
    """Returns (verdict, reason, quotes_found)"""
    if fetch_result.status in (404, 410):
        return SourceVerdict.FAILED, f"page not found (HTTP {fetch_result.status})", 0
    
    if fetch_result.status in (401, 403, 429) or (fetch_result.status is not None and fetch_result.status >= 500) or fetch_result.error or fetch_result.status is None:
        reason = fetch_result.error if fetch_result.error else f"HTTP {fetch_result.status}"
        return SourceVerdict.INCONCLUSIVE, reason, 0
        
    if fetch_result.status == 200:
        norm_text = normalize_for_match(fetch_result.text)
        if len(norm_text) < min_text_chars:
            return SourceVerdict.INCONCLUSIVE, f"extraction too short ({len(norm_text)} chars) - likely JS-rendered or bot-walled", 0
            
        quotes_found = 0
        for q in quotes:
            norm_q = normalize_for_match(q)
            if norm_q in norm_text:
                quotes_found += 1
                
        if quotes_found == len(quotes):
            return SourceVerdict.VERIFIED, "", quotes_found
        else:
            return SourceVerdict.FAILED, f"{len(quotes) - quotes_found} of {len(quotes)} quotes not found on live page", quotes_found

    return SourceVerdict.INCONCLUSIVE, f"unexpected HTTP status {fetch_result.status}", 0


def verify_bundle_sources(
    bundle: ResearchBundle,
    bundle_dir: Path,
    fetch: Callable[[str], FetchResult],
) -> BundleVerification:
    results = []
    
    for s in bundle.sources:
        quotes = [f.quote for f in bundle.facts if f.source_id == s.source.id]
        if not quotes:
            results.append(SourceVerification(
                company_id=bundle.company_id,
                source_id=s.source.id,
                url=s.source.url,
                verdict=SourceVerdict.INCONCLUSIVE,
                reason="no facts cite this source",
                quotes_checked=0,
                quotes_found=0
            ))
            continue
            
        fetch_result = fetch(s.source.url)
        verdict, reason, quotes_found = classify_source(fetch_result, quotes)
        
        results.append(SourceVerification(
            company_id=bundle.company_id,
            source_id=s.source.id,
            url=s.source.url,
            verdict=verdict,
            reason=reason,
            quotes_checked=len(quotes),
            quotes_found=quotes_found
        ))
        
    return BundleVerification(company_id=bundle.company_id, results=tuple(results))


def quote_coverage(snapshot_text: str, quotes: Sequence[str]) -> float:
    if not snapshot_text:
        return 1.0
    
    distinct_quotes = set(quotes)
    summed_len = sum(len(q) for q in distinct_quotes)
    return summed_len / len(snapshot_text)


def lint_bundle_snapshots(
    bundle: ResearchBundle,
    bundle_dir: Path,
    coverage_threshold: float = 0.6,
) -> tuple[SnapshotLintFinding, ...]:
    findings = []
    
    for s in bundle.sources:
        quotes = [f.quote for f in bundle.facts if f.source_id == s.source.id]
        if not quotes:
            continue
            
        snap_file = bundle_dir / s.snapshot_file
        if not snap_file.exists():
            continue
            
        try:
            content = snap_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
            
        cov = quote_coverage(content, quotes)
        if cov >= coverage_threshold:
            findings.append(SnapshotLintFinding(
                company_id=bundle.company_id,
                source_id=s.source.id,
                metric="quote_coverage",
                value=cov,
                threshold=coverage_threshold,
                message=f"Snapshot is mostly quote (coverage {cov:.2f} >= {coverage_threshold:.2f}) and carries little surrounding page context. Re-verify against live URL."
            ))
            
    return tuple(findings)
