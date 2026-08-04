from datetime import datetime, timezone

from src.company_bank.model import (
    FactKind,
    LookupStatus,
    PermittedUse,
    ScopeKind,
    SourceKind,
    TTL_DAYS,
)
from src.company_bank.serde import load_seed_companies


def test_enum_values_are_the_file_contract():
    assert {item.value for item in ScopeKind} == {
        "company", "business_unit", "role_family"
    }
    assert SourceKind.OFFICIAL_ENGINEERING.value == "official_engineering"
    assert FactKind.HIRING_GUIDANCE.value == "hiring_guidance"
    assert PermittedUse.S2_TIEBREAK.value == "s2_tiebreak"
    assert {item.value for item in LookupStatus} == {"fresh", "expired", "missing"}
    assert TTL_DAYS == 90


def test_seed_file_contains_exactly_30_unique_ids():
    seeds = load_seed_companies("config/company_bank/seed_companies.yaml")
    assert len(seeds) == 30
    assert seeds["palantir"] == "Palantir"
    assert seeds["rippling"] == "Rippling"
    assert seeds["plaid"] == "Plaid"
    assert seeds["ramp"] == "Ramp"
    assert "citadel" not in seeds
    assert "bloomberg" not in seeds
