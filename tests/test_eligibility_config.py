from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path
import re

import pytest
import yaml

from src.eligibility import (
    DateWindow,
    EligibilityConfigError,
    load_eligibility_config,
)


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _base_policy() -> dict:
    with open("config/eligibility.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _base_taxonomy() -> dict:
    with open("config/location_taxonomy.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_from_payloads(tmp_path: Path, policy: dict, taxonomy: dict | None = None):
    policy_path = tmp_path / "eligibility.yaml"
    taxonomy_path = tmp_path / "location_taxonomy.yaml"
    _write_yaml(policy_path, policy)
    _write_yaml(taxonomy_path, taxonomy or _base_taxonomy())
    return load_eligibility_config(policy_path, taxonomy_path)


def test_loads_valid_config_as_frozen_typed_contract() -> None:
    config = load_eligibility_config()

    assert config.version == 2
    assert config.countries.allowed == ("US",)
    assert config.opportunity_types.default_when_unmarked == "full_time"
    assert config.opportunity_types.types["full_time"].start_windows == (
        DateWindow(date(2027, 1, 1), date(2027, 12, 31)),
    )
    assert config.opportunity_types.types["internship"].allowed_seasons == ("spring",)
    assert config.role_families.include[0].name == "software_engineering"
    assert len(config.role_families.include[0].patterns) > 1
    assert config.role_families.include[0].exclude_patterns
    assert any(
        p.search("Senior Research Scientist")
        for p in config.role_families.include[0].exclude_patterns
    )
    assert config.role_families.jd_fallback_min_hits == 2
    assert config.seniority.years_cap == 3
    assert config.flags.country_unknown == "country_unknown"

    with pytest.raises(FrozenInstanceError):
        config.countries.allowed = ("CA",)  # type: ignore[misc]
    with pytest.raises(TypeError):
        config.opportunity_types.classification_order[0] = "contract"  # type: ignore[index]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.update(version=3), "version"),
        (lambda p: p["countries"].update(explicit_non_match="maybe"), "countries.explicit_non_match"),
        (lambda p: p["countries"].update(allowed=["XX"]), "countries.allowed"),
        (
            lambda p: p["opportunity_types"]["types"]["full_time"]["start_windows"][0].update(
                earliest="not-a-date"
            ),
            "opportunity_types.types.full_time.start_windows[0].earliest",
        ),
        (
            lambda p: p["opportunity_types"]["types"]["full_time"]["start_windows"][0].update(
                earliest="2027-12-31", latest="2027-01-01"
            ),
            "opportunity_types.types.full_time.start_windows[0]",
        ),
        (
            lambda p: p["opportunity_types"].update(
                classification_order=["internship", "unknown_type"]
            ),
            "opportunity_types.classification_order",
        ),
        (
            lambda p: p["opportunity_types"]["types"].update(
                internship={"enabled": True, "allowed_seasons": ["winter"], "start_windows": []}
            ),
            "opportunity_types.types.internship.allowed_seasons",
        ),
        (
            lambda p: p["opportunity_types"]["patterns"]["internship"].append("["),
            "opportunity_types.patterns.internship[1]",
        ),
        (lambda p: p["seniority"].update(years_cap=-1), "seniority.years_cap"),
        (lambda p: p["role_families"].update(include=[]), "role_families.include"),
        (lambda p: p["role_families"].update(jd_fallback_min_hits=0), "role_families.jd_fallback_min_hits"),
        (
            lambda p: p["role_families"]["include"][0].update(exclude_patterns=["["]),
            "role_families.include[0].exclude_patterns[0]: invalid regex",
        ),
    ],
)
def test_validation_rejects_invalid_policy(tmp_path: Path, mutate, message: str) -> None:
    policy = _base_policy()
    mutate(policy)

    with pytest.raises(EligibilityConfigError, match=re.escape(message)):
        _load_from_payloads(tmp_path, policy)


def test_validation_rejects_enabled_type_without_policy(tmp_path: Path) -> None:
    policy = _base_policy()
    policy["opportunity_types"]["classification_order"].append("fellowship")
    policy["opportunity_types"]["patterns"]["fellowship"] = [r"\bfellowship\b"]

    with pytest.raises(EligibilityConfigError, match=re.escape("opportunity_types.types.fellowship")):
        _load_from_payloads(tmp_path, policy)


def test_validation_rejects_invalid_taxonomy_country_code(tmp_path: Path) -> None:
    taxonomy = _base_taxonomy()
    taxonomy["countries"]["XX"] = {"names": ["Nowhere"], "codes": ["XX"], "aliases": []}

    with pytest.raises(EligibilityConfigError, match=re.escape("location_taxonomy.countries.XX")):
        _load_from_payloads(tmp_path, _base_policy(), taxonomy)


def test_valid_config_can_be_replaced_without_mutating_original() -> None:
    config = load_eligibility_config()
    changed = replace(config.countries, allowed=("CA",))

    assert config.countries.allowed == ("US",)
    assert changed.allowed == ("CA",)
