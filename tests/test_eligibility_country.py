from __future__ import annotations

from dataclasses import replace

import pytest

from src.eligibility import (
    CountryEvidence,
    classify_country,
    load_eligibility_config,
)


@pytest.mark.parametrize(
    "location",
    ["New York, NY", "San Diego, CA", "Austin, Texas", "United States", "Remote - USA"],
)
def test_country_allowed_us_evidence(location: str) -> None:
    result = classify_country(location, load_eligibility_config())

    assert result.evidence is CountryEvidence.EXPLICIT_ALLOWED
    assert result.country_codes == ("US",)


@pytest.mark.parametrize(
    "location",
    [
        "Toronto, Canada",
        "Remote - Canada",
        "Vancouver, BC, Canada",
        "London, United Kingdom",
        "Bengaluru, India",
    ],
)
def test_country_disallowed_evidence(location: str) -> None:
    result = classify_country(location, load_eligibility_config())

    assert result.evidence is CountryEvidence.EXPLICIT_DISALLOWED
    assert "US" not in result.country_codes


@pytest.mark.parametrize("location", ["Remote", "", None, "Worldwide", "Atlantis City"])
def test_country_unknown_without_explicit_country(location: str | None) -> None:
    result = classify_country(location, load_eligibility_config())

    assert result.evidence is CountryEvidence.UNKNOWN
    assert result.country_codes == ()


def test_state_code_collision_prefers_city_state_for_us_state() -> None:
    result = classify_country("San Diego, CA", load_eligibility_config())

    assert result.evidence is CountryEvidence.EXPLICIT_ALLOWED
    assert result.country_codes == ("US",)
    assert "CA" in result.matched_text


def test_country_name_still_matches_canada_not_california() -> None:
    result = classify_country("Toronto, Canada", load_eligibility_config())

    assert result.evidence is CountryEvidence.EXPLICIT_DISALLOWED
    assert result.country_codes == ("CA",)


@pytest.mark.parametrize("location", ["engineering", "Austin", "business analyst", "infrastructure"])
def test_short_codes_do_not_match_inside_words(location: str) -> None:
    result = classify_country(location, load_eligibility_config())

    assert result.evidence is CountryEvidence.UNKNOWN


def test_allowed_countries_are_configurable_without_code_change() -> None:
    config = load_eligibility_config()
    ca_config = replace(config, countries=replace(config.countries, allowed=("CA",)))

    assert classify_country("Toronto, Canada", ca_config).evidence is CountryEvidence.EXPLICIT_ALLOWED
    assert classify_country("New York, NY", ca_config).evidence is CountryEvidence.EXPLICIT_DISALLOWED
