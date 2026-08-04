import hashlib
import ipaddress
import re
import unicodedata
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from src.company_bank.model import (
    CompanyDossier,
    FactKind,
    PermittedUse,
    ResearchBundle,
    SourceKind,
    TTL_DAYS,
)
from src.company_bank.serde import CompanyBankValidationError

VERIFIED_DATASET_HOSTS = frozenset({"www.wikidata.org", "raw.githubusercontent.com"})

SOURCE_FACT_KINDS = {
    SourceKind.OFFICIAL_COMPANY: frozenset({
        FactKind.IDENTITY, FactKind.INDUSTRY, FactKind.PRODUCT,
        FactKind.DOMAIN, FactKind.VALUE,
    }),
    SourceKind.OFFICIAL_PRODUCT: frozenset({FactKind.PRODUCT, FactKind.DOMAIN}),
    SourceKind.OFFICIAL_ENGINEERING: frozenset({
        FactKind.PRODUCT, FactKind.DOMAIN, FactKind.ENGINEERING_THEME,
    }),
    SourceKind.OFFICIAL_CAREERS: frozenset({FactKind.VALUE, FactKind.HIRING_GUIDANCE}),
    SourceKind.OFFICIAL_HIRING_GUIDE: frozenset({FactKind.HIRING_GUIDANCE}),
    SourceKind.VERIFIED_DATASET: frozenset({
        FactKind.IDENTITY, FactKind.INDUSTRY, FactKind.ATS,
    }),
}

FACT_PERMITTED_USES = {
    FactKind.IDENTITY: frozenset(),
    FactKind.INDUSTRY: frozenset(),
    FactKind.PRODUCT: frozenset({PermittedUse.S0, PermittedUse.S2_TIEBREAK}),
    FactKind.DOMAIN: frozenset({PermittedUse.S0, PermittedUse.S2_TIEBREAK}),
    FactKind.ENGINEERING_THEME: frozenset({PermittedUse.S0, PermittedUse.S2_TIEBREAK}),
    FactKind.VALUE: frozenset({PermittedUse.S0}),
    FactKind.HIRING_GUIDANCE: frozenset({PermittedUse.S0, PermittedUse.G3_ADVISORY}),
    FactKind.ATS: frozenset({PermittedUse.G3_ADVISORY}),
}

PRIVACY_DENYLIST = frozenset({
    "candidate", "candidate_name", "email", "phone", "resume",
    "master_profile", "sponsorship", "citizenship", "visa",
    "work_authorization", "location_eligibility", "start_window",
})


def normalize_company_name(value: str) -> str:
    nfkc = unicodedata.normalize("NFKC", value)
    casefolded = nfkc.casefold()
    collapsed = re.sub(r"[^a-z0-9]+", " ", casefolded).strip()
    return collapsed


def host_matches_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _validate_url(url: str, official_domains: tuple[str, ...], source_kind: SourceKind):
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise CompanyBankValidationError(f"URL scheme must be https: {url}")
    if parsed.username or parsed.password:
        raise CompanyBankValidationError(f"URL contains credentials: {url}")

    host = parsed.hostname
    if not host:
        raise CompanyBankValidationError(f"URL missing host: {url}")

    # Remove trailing dot if present
    if host.endswith("."):
        host = host[:-1]
    
    # IDNA encode then decode to normalize
    try:
        host = host.encode("idna").decode("utf-8")
    except Exception:
        raise CompanyBankValidationError(f"URL host invalid IDNA: {host}")

    # Reject IP literals
    is_ip = False
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        pass
        
    if is_ip:
        raise CompanyBankValidationError(f"URL host is an IP literal: {url}")

    if source_kind == SourceKind.VERIFIED_DATASET:
        if host not in VERIFIED_DATASET_HOSTS:
            raise CompanyBankValidationError(f"Verified dataset host not in allowlist: {host}")
    else:
        if not any(host_matches_domain(host, domain) for domain in official_domains):
            raise CompanyBankValidationError(f"URL host {host} does not match any official domain")



def _validate_semantics(obj) -> None:
    # Basic field checks not caught by types alone
    if obj.schema_version != "0.1.0":
        raise CompanyBankValidationError("schema_version must be '0.1.0'")
    if not re.match(r"^[a-z][a-z0-9_]*$", obj.company_id):
        raise CompanyBankValidationError("company_id: invalid")
    if not obj.display_name.strip():
        raise CompanyBankValidationError("display_name: expected nonempty string")

    # 1. Aliases case-insensitive duplicate check
    seen_aliases = set()
    for a in obj.aliases:
        norm = normalize_company_name(a)
        if norm in seen_aliases:
            raise CompanyBankValidationError("duplicate alias (case-insensitive)")
        seen_aliases.add(norm)

    # 2. Domains case-insensitive duplicate check
    if not obj.official_domains:
        raise CompanyBankValidationError("official_domains: expected nonempty list")
    seen_domains = set()
    for d in obj.official_domains:
        if d.lower() in seen_domains:
            raise CompanyBankValidationError("duplicate domain (case-insensitive)")
        seen_domains.add(d.lower())

    # Ensure collections are not empty
    if not obj.sources:
        raise CompanyBankValidationError("sources: expected nonempty list")
    if not obj.facts:
        raise CompanyBankValidationError("facts: expected nonempty list")
    if not obj.signals:
        raise CompanyBankValidationError("signals: expected nonempty list")

    # Extract CompanySource list depending on object type
    from src.company_bank.model import ResearchBundle
    is_bundle = isinstance(obj, ResearchBundle)
    company_sources = [rs.source for rs in obj.sources] if is_bundle else obj.sources

    # 3. Source checks
    source_ids = set()
    for s in company_sources:
        if s.id in source_ids:
            raise CompanyBankValidationError(f"Duplicate source id: {s.id}")
        source_ids.add(s.id)

        if s.retrieved_at > obj.researched_at:
            raise CompanyBankValidationError(f"Source {s.id} retrieved after researched_at")

        _validate_url(s.url, obj.official_domains, s.source_kind)

    # 4. Fact checks
    fact_ids = set()
    for f in obj.facts:
        if f.id in fact_ids:
            raise CompanyBankValidationError(f"Duplicate fact id: {f.id}")
        fact_ids.add(f.id)

        if f.source_id not in source_ids:
            raise CompanyBankValidationError(f"Fact {f.id} refers to unresolved source {f.source_id}")

        source_kind = next(s.source_kind for s in company_sources if s.id == f.source_id)
        if f.kind not in SOURCE_FACT_KINDS[source_kind]:
            raise CompanyBankValidationError(f"Fact kind {f.kind.value} not allowed for source kind {source_kind.value}")

        words = f.quote.split()
        if not words:
            raise CompanyBankValidationError(f"Fact {f.id} quote is empty")
        if len(words) > 25:
            raise CompanyBankValidationError(f"Fact {f.id} quote exceeds 25 words")

    # 5. Signal checks
    signal_ids = set()
    for sig in obj.signals:
        if sig.id in signal_ids:
            raise CompanyBankValidationError(f"Duplicate signal id: {sig.id}")
        signal_ids.add(sig.id)

        allowed_uses_for_signal = None
        for bf_id in sig.basis_fact_ids:
            if bf_id not in fact_ids:
                raise CompanyBankValidationError(f"Signal {sig.id} refers to unresolved fact {bf_id}")
            
            fact_kind = next(f.kind for f in obj.facts if f.id == bf_id)
            uses_for_fact = FACT_PERMITTED_USES[fact_kind]
            
            if allowed_uses_for_signal is None:
                allowed_uses_for_signal = set(uses_for_fact)
            else:
                allowed_uses_for_signal = allowed_uses_for_signal.intersection(uses_for_fact)

        for u in sig.permitted_uses:
            if u not in allowed_uses_for_signal:
                raise CompanyBankValidationError(f"Signal {sig.id} has permitted use {u.value} not allowed by basis facts")

def validate_research_bundle(bundle: ResearchBundle, bundle_dir: Path) -> None:
    _validate_semantics(bundle)

    for rs in bundle.sources:
        s = rs.source
        # Snapshot checks
        snap_path = (bundle_dir / rs.snapshot_file).resolve()
        sources_dir = (bundle_dir / "sources").resolve()
        if not snap_path.is_relative_to(sources_dir):
            raise CompanyBankValidationError(f"Snapshot path traversal: {rs.snapshot_file}")
        
        if not snap_path.is_file():
            raise CompanyBankValidationError(f"Snapshot file missing: {rs.snapshot_file}")
            
        try:
            content = snap_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise CompanyBankValidationError(f"Snapshot not UTF-8: {rs.snapshot_file}") from exc

        actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual_hash != s.content_sha256:
            raise CompanyBankValidationError(f"Snapshot hash mismatch for {s.id}")

    for f in bundle.facts:
        # Quote must literally be in the snapshot
        snap_file = next(rs.snapshot_file for rs in bundle.sources if rs.source.id == f.source_id)
        snap_content = (bundle_dir / snap_file).read_text(encoding="utf-8")
        if f.quote not in snap_content:
            raise CompanyBankValidationError(f"Fact {f.id} quote not found in snapshot")

def validate_company_dossier(dossier: CompanyDossier) -> None:
    if dossier.expires_at != dossier.researched_at + timedelta(days=90):
        raise CompanyBankValidationError(f"expires_at must be exactly researched_at + 90 days")
    _validate_semantics(dossier)

def to_company_dossier(bundle: ResearchBundle, bundle_dir: Path) -> CompanyDossier:
    validate_research_bundle(bundle, bundle_dir)
    
    expires_at = bundle.researched_at + timedelta(days=TTL_DAYS)
    sources = tuple(rs.source for rs in bundle.sources)

    dossier = CompanyDossier(
        schema_version=bundle.schema_version,
        company_id=bundle.company_id,
        display_name=bundle.display_name,
        aliases=bundle.aliases,
        official_domains=bundle.official_domains,
        researched_at=bundle.researched_at,
        expires_at=expires_at,
        sources=sources,
        facts=bundle.facts,
        signals=bundle.signals,
    )
    
    validate_company_dossier(dossier)
    return dossier
