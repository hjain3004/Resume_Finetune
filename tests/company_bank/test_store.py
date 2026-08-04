import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.company_bank.model import (
    CompanyBank,
    CompanyDossier,
    LookupStatus,
    PermittedUse,
    PositioningSignal,
    TailoringSignal,
)
from src.company_bank.serde import CompanyBankValidationError, dump_company_dossier
from src.company_bank.store import load_company_bank, lookup_company


def make_dossier(company_id: str, display_name: str, aliases: tuple[str, ...] = ()) -> CompanyDossier:
    from src.company_bank.model import CompanySource, CompanyScope, SourceKind, ScopeKind, CompanyFact, FactKind, TailoringSignal, PermittedUse
    now = datetime(2026, 8, 4, 0, 0, 0, tzinfo=timezone.utc)
    
    source = CompanySource(
        id="s1", url=f"https://{company_id}.example", title="Title",
        source_kind=SourceKind.OFFICIAL_COMPANY,
        scope=CompanyScope(ScopeKind.COMPANY, display_name),
        retrieved_at=now, content_sha256="0" * 64
    )
    fact = CompanyFact(
        id="f1", kind=FactKind.PRODUCT, scope=CompanyScope(ScopeKind.COMPANY, display_name),
        claim="Claim", quote="Quote", source_id="s1"
    )
    signal = TailoringSignal("sig1", "text", ("f1",), (PermittedUse.S0,))

    return CompanyDossier(
        schema_version="0.1.0",
        company_id=company_id,
        display_name=display_name,
        aliases=aliases,
        official_domains=(f"{company_id}.example",),
        researched_at=now,
        expires_at=now + timedelta(days=90),
        sources=(source,),
        facts=(fact,),
        signals=(signal,),
    )


def test_sorted_scan(tmp_path):
    (tmp_path / "companies").mkdir(exist_ok=True)
    (tmp_path / "companies" / "zeta.yaml").write_text(dump_company_dossier(make_dossier("zeta", "Zeta")), encoding="utf-8")
    (tmp_path / "companies" / "alpha.yaml").write_text(dump_company_dossier(make_dossier("alpha", "Alpha")), encoding="utf-8")
    bank = load_company_bank(tmp_path)
    assert tuple(bank.dossiers) == ("alpha", "zeta")


def test_filename_id_mismatch(tmp_path):
    (tmp_path / "companies").mkdir(exist_ok=True)
    (tmp_path / "companies" / "wrong.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="filename"):
        load_company_bank(tmp_path)


def test_duplicate_id(tmp_path):
    (tmp_path / "companies").mkdir(exist_ok=True)
    (tmp_path / "companies" / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    (tmp_path / "companies" / "other.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme 2")), encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="duplicate company id"):
        load_company_bank(tmp_path)


def test_alias_collision(tmp_path):
    (tmp_path / "companies").mkdir(exist_ok=True)
    (tmp_path / "companies" / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme", aliases=("Acme, Inc.",))), encoding="utf-8")
    (tmp_path / "companies" / "other.yaml").write_text(dump_company_dossier(make_dossier("other", "Other", aliases=("ACME INC",))), encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="alias collision"):
        load_company_bank(tmp_path)


def test_implicit_aliases(tmp_path):
    (tmp_path / "companies").mkdir(exist_ok=True)
    (tmp_path / "companies" / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme Corp")), encoding="utf-8")
    bank = load_company_bank(tmp_path)
    assert bank.alias_index["acme corp"] == "acme"
    assert bank.alias_index["acme"] == "acme"


def test_empty_missing_directory(tmp_path):
    bank = load_company_bank(tmp_path)
    assert not bank.dossiers
    assert not bank.alias_index
    
    bank = load_company_bank(tmp_path / "companies" / "missing")
    assert not bank.dossiers
    assert not bank.alias_index


def test_lookup_status():
    dossier = make_dossier("acme", "Acme")
    bank = CompanyBank(
        dossiers=types.MappingProxyType({"acme": dossier}),
        alias_index=types.MappingProxyType({"acme": "acme"}),
    )
    
    # Fresh
    now = dossier.researched_at
    res = lookup_company(bank, "acme", now=now)
    assert res.status == LookupStatus.FRESH
    assert res.company_id == "acme"
    assert res.view is not None
    
    # Missing
    res = lookup_company(bank, "missing", now=now)
    assert res.status == LookupStatus.MISSING
    assert res.company_id is None
    assert res.view is None
    assert res.message
    
    # Exactly at expiry is expired
    now = dossier.expires_at
    res = lookup_company(bank, "acme", now=now)
    assert res.status == LookupStatus.EXPIRED
    assert res.company_id == "acme"
    assert res.view is None
    assert res.message
    
    # Expired
    now = dossier.expires_at + timedelta(seconds=1)
    res = lookup_company(bank, "acme", now=now)
    assert res.status == LookupStatus.EXPIRED


def _make_signal_dossier():
    from src.company_bank.model import (
        CompanyFact,
        CompanyScope,
        CompanySource,
        FactKind,
        ScopeKind,
        SourceKind,
    )

    now = datetime(2026, 8, 4, 0, 0, 0, tzinfo=timezone.utc)
    
    source = CompanySource(
        id="s1",
        url="https://acme.example",
        title="Acme About",
        source_kind=SourceKind.OFFICIAL_COMPANY,
        scope=CompanyScope(ScopeKind.COMPANY, "Acme"),
        retrieved_at=now,
        content_sha256="0" * 64
    )
    
    fact_co = CompanyFact(
        id="f1", kind=FactKind.PRODUCT,
        scope=CompanyScope(ScopeKind.COMPANY, "Acme"),
        claim="c1", quote="q1", source_id="s1"
    )
    fact_bu = CompanyFact(
        id="f2", kind=FactKind.PRODUCT,
        scope=CompanyScope(ScopeKind.BUSINESS_UNIT, "Cloud"),
        claim="c2", quote="q2", source_id="s1"
    )
    fact_rf = CompanyFact(
        id="f3", kind=FactKind.PRODUCT,
        scope=CompanyScope(ScopeKind.ROLE_FAMILY, "Frontend"),
        claim="c3", quote="q3", source_id="s1"
    )
    
    # Signals
    sig_co = TailoringSignal("sig1", "co_text", ("f1",), (PermittedUse.S0, PermittedUse.S2_TIEBREAK))
    sig_bu = TailoringSignal("sig2", "bu_text", ("f2",), (PermittedUse.S0,))
    sig_rf = TailoringSignal("sig3", "rf_text", ("f3",), (PermittedUse.S0,))
    sig_s2 = TailoringSignal("sig4", "s2_text", ("f1",), (PermittedUse.S2_TIEBREAK,))
    
    dossier = CompanyDossier(
        schema_version="0.1.0",
        company_id="acme",
        display_name="Acme",
        aliases=(),
        official_domains=("acme.example",),
        researched_at=now,
        expires_at=now + timedelta(days=90),
        sources=(source,),
        facts=(fact_co, fact_bu, fact_rf),
        signals=(sig_co, sig_bu, sig_rf, sig_s2),
    )
    
    bank = CompanyBank(
        dossiers=types.MappingProxyType({"acme": dossier}),
        alias_index=types.MappingProxyType({"acme": "acme", "acme corp": "acme"}),
    )
    return bank, now


def test_lookup_projection_scopes():
    bank, now = _make_signal_dossier()
    
    res = lookup_company(bank, "acme corp", now=now)
    assert res.status == LookupStatus.FRESH
    sig_texts = [s.text for s in res.view.signals]
    # Default is S0, company scope only
    assert sig_texts == ["co_text"]
    
    res = lookup_company(bank, "acme", now=now, business_unit="cloud")
    sig_texts = [s.text for s in res.view.signals]
    assert sig_texts == ["co_text", "bu_text"]
    
    res = lookup_company(bank, "acme", now=now, role_family="frontend")
    sig_texts = [s.text for s in res.view.signals]
    assert sig_texts == ["co_text", "rf_text"]
    
    res = lookup_company(bank, "acme", now=now, business_unit="cloud", role_family="frontend")
    sig_texts = [s.text for s in res.view.signals]
    assert sig_texts == ["co_text", "bu_text", "rf_text"]


def test_lookup_projection_uses():
    bank, now = _make_signal_dossier()
    
    res = lookup_company(bank, "acme", now=now, permitted_use=PermittedUse.S2_TIEBREAK)
    sig_texts = [s.text for s in res.view.signals]
    assert sig_texts == ["co_text", "s2_text"]


def test_lookup_projection_citations():
    bank, now = _make_signal_dossier()
    res = lookup_company(bank, "acme", now=now)
    sig = res.view.signals[0]
    assert sig.citations == ("Acme About — https://acme.example",)
