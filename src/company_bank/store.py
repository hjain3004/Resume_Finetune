import types
from datetime import datetime
from pathlib import Path

from src.company_bank.model import (
    CompanyBank,
    CompanyDossier,
    CompanyLookupResult,
    CompanyPositioningView,
    LookupStatus,
    PermittedUse,
    PositioningSignal,
    ScopeKind,
)
from src.company_bank.policy import normalize_company_name
from src.company_bank.serde import CompanyBankValidationError, parse_company_dossier


def _load_company_directory(companies_dir: Path) -> CompanyBank:
    if not companies_dir.is_dir():
        return CompanyBank(
            dossiers=types.MappingProxyType({}),
            alias_index=types.MappingProxyType({}),
        )

    dossiers = {}
    alias_index = {}

    from src.company_bank.policy import validate_company_dossier

    for path in sorted(companies_dir.glob("*.yaml")):
        dossier = parse_company_dossier(path)
        validate_company_dossier(dossier)
        
        if dossier.company_id in dossiers:
            raise CompanyBankValidationError(f"duplicate company id: {dossier.company_id}")

        expected_filename = f"{dossier.company_id}.yaml"
        if path.name != expected_filename:
            raise CompanyBankValidationError(
                f"filename mismatch: expected {expected_filename}, got {path.name}"
            )

        dossiers[dossier.company_id] = dossier

        # Register implicit aliases
        names_to_register = [dossier.company_id, dossier.display_name] + list(dossier.aliases)
        for name in names_to_register:
            norm = normalize_company_name(name)
            if norm in alias_index and alias_index[norm] != dossier.company_id:
                raise CompanyBankValidationError(
                    f"alias collision: {name!r} resolves to both {alias_index[norm]} and {dossier.company_id}"
                )
            alias_index[norm] = dossier.company_id

    return CompanyBank(
        dossiers=types.MappingProxyType(dossiers),
        alias_index=types.MappingProxyType(alias_index),
    )


def load_company_bank(root: str | Path) -> CompanyBank:
    return _load_company_directory(Path(root) / "companies")


def lookup_company(
    bank: CompanyBank,
    company_name: str,
    *,
    now: datetime,
    business_unit: str | None = None,
    role_family: str | None = None,
    permitted_use: PermittedUse = PermittedUse.S0,
) -> CompanyLookupResult:
    norm_name = normalize_company_name(company_name)
    company_id = bank.alias_index.get(norm_name)

    if not company_id:
        return CompanyLookupResult(
            status=LookupStatus.MISSING,
            company_id=None,
            view=None,
            message=f"Company not found: {company_name}",
        )

    dossier = bank.dossiers[company_id]
    if now >= dossier.expires_at:
        return CompanyLookupResult(
            status=LookupStatus.EXPIRED,
            company_id=company_id,
            view=None,
            message=f"Company dossier expired on {dossier.expires_at}",
        )

    # Scopes
    target_bu = normalize_company_name(business_unit) if business_unit else None
    target_rf = normalize_company_name(role_family) if role_family else None

    # Fact resolution and scope matching
    valid_facts = set()
    for f in dossier.facts:
        if f.scope.kind == ScopeKind.COMPANY:
            valid_facts.add(f.id)
        elif f.scope.kind == ScopeKind.BUSINESS_UNIT and target_bu:
            if normalize_company_name(f.scope.name) == target_bu:
                valid_facts.add(f.id)
        elif f.scope.kind == ScopeKind.ROLE_FAMILY and target_rf:
            if normalize_company_name(f.scope.name) == target_rf:
                valid_facts.add(f.id)

    source_map = {s.id: s for s in dossier.sources}
    view_signals = []

    for sig in dossier.signals:
        if permitted_use not in sig.permitted_uses:
            continue

        if not all(bf_id in valid_facts for bf_id in sig.basis_fact_ids):
            continue

        citations = []
        for bf_id in sig.basis_fact_ids:
            fact = next(f for f in dossier.facts if f.id == bf_id)
            source = source_map[fact.source_id]
            citation = f"{source.title} — {source.url}"
            if citation not in citations:
                citations.append(citation)

        view_signals.append(
            PositioningSignal(
                id=sig.id,
                text=sig.text,
                permitted_uses=sig.permitted_uses,
                citations=tuple(citations),
            )
        )

    view = CompanyPositioningView(
        company_id=company_id,
        display_name=dossier.display_name,
        signals=tuple(view_signals),
    )

    return CompanyLookupResult(
        status=LookupStatus.FRESH,
        company_id=company_id,
        view=view,
        message="Success",
    )
