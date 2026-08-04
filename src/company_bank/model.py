from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping

SCHEMA_VERSION = "0.1.0"
TTL_DAYS = 90


class ScopeKind(str, Enum):
    COMPANY = "company"
    BUSINESS_UNIT = "business_unit"
    ROLE_FAMILY = "role_family"


class SourceKind(str, Enum):
    OFFICIAL_COMPANY = "official_company"
    OFFICIAL_PRODUCT = "official_product"
    OFFICIAL_ENGINEERING = "official_engineering"
    OFFICIAL_CAREERS = "official_careers"
    OFFICIAL_HIRING_GUIDE = "official_hiring_guide"
    VERIFIED_DATASET = "verified_dataset"


class FactKind(str, Enum):
    IDENTITY = "identity"
    INDUSTRY = "industry"
    PRODUCT = "product"
    DOMAIN = "domain"
    ENGINEERING_THEME = "engineering_theme"
    VALUE = "value"
    HIRING_GUIDANCE = "hiring_guidance"
    ATS = "ats"


class PermittedUse(str, Enum):
    S0 = "s0"
    S2_TIEBREAK = "s2_tiebreak"
    G3_ADVISORY = "g3_advisory"


class LookupStatus(str, Enum):
    FRESH = "fresh"
    EXPIRED = "expired"
    MISSING = "missing"


@dataclass(frozen=True)
class CompanyScope:
    kind: ScopeKind
    name: str


@dataclass(frozen=True)
class CompanySource:
    id: str
    url: str
    title: str
    source_kind: SourceKind
    scope: CompanyScope
    retrieved_at: datetime
    content_sha256: str


@dataclass(frozen=True)
class ResearchSource:
    source: CompanySource
    snapshot_file: str


@dataclass(frozen=True)
class CompanyFact:
    id: str
    kind: FactKind
    scope: CompanyScope
    claim: str
    quote: str
    source_id: str


@dataclass(frozen=True)
class TailoringSignal:
    id: str
    text: str
    basis_fact_ids: tuple[str, ...]
    permitted_uses: tuple[PermittedUse, ...]


@dataclass(frozen=True)
class ResearchBundle:
    schema_version: str
    company_id: str
    display_name: str
    aliases: tuple[str, ...]
    official_domains: tuple[str, ...]
    researched_at: datetime
    sources: tuple[ResearchSource, ...]
    facts: tuple[CompanyFact, ...]
    signals: tuple[TailoringSignal, ...]


@dataclass(frozen=True)
class CompanyDossier:
    schema_version: str
    company_id: str
    display_name: str
    aliases: tuple[str, ...]
    official_domains: tuple[str, ...]
    researched_at: datetime
    expires_at: datetime
    sources: tuple[CompanySource, ...]
    facts: tuple[CompanyFact, ...]
    signals: tuple[TailoringSignal, ...]


@dataclass(frozen=True)
class PositioningSignal:
    id: str
    text: str
    permitted_uses: tuple[PermittedUse, ...]
    citations: tuple[str, ...]


@dataclass(frozen=True)
class CompanyPositioningView:
    company_id: str
    display_name: str
    signals: tuple[PositioningSignal, ...]


@dataclass(frozen=True)
class CompanyLookupResult:
    status: LookupStatus
    company_id: str | None
    view: CompanyPositioningView | None
    message: str


@dataclass(frozen=True)
class CompanyBank:
    dossiers: Mapping[str, CompanyDossier]
    alias_index: Mapping[str, str]
