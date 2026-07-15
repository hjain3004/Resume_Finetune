"""Typed, deterministic eligibility policy engine.

M6.11 keeps business policy in config/eligibility.yaml and local vocabulary in
config/location_taxonomy.yaml. This module is intentionally pure: no SQLite, no
network, no browser, and no logging side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Pattern

import yaml


class EligibilityConfigError(ValueError):
    pass


@dataclass(frozen=True)
class DateWindow:
    earliest: date
    latest: date


@dataclass(frozen=True)
class OpportunityTypePolicy:
    enabled: bool
    start_windows: tuple[DateWindow, ...] = ()
    allowed_seasons: tuple[str, ...] = ()
    year_only_evidence: str | None = None
    unknown_start_pre_resolution: str | None = None
    unknown_start_post_resolution: str | None = None


@dataclass(frozen=True)
class CountryPolicy:
    allowed: tuple[str, ...]
    explicit_non_match: str
    unknown_pre_resolution: str
    unknown_post_resolution: str
    remote_without_country: str


@dataclass(frozen=True)
class SeasonPolicy:
    months: tuple[int, ...]


@dataclass(frozen=True)
class RoleFamily:
    name: str
    patterns: tuple[Pattern[str], ...]


@dataclass(frozen=True)
class RoleFamilyPolicy:
    include: tuple[RoleFamily, ...]


@dataclass(frozen=True)
class SeniorityPolicy:
    title_exclude_patterns: tuple[Pattern[str], ...]
    years_cap: int


@dataclass(frozen=True)
class OpportunityTypesPolicy:
    classification_order: tuple[str, ...]
    default_when_unmarked: str
    patterns: Mapping[str, tuple[Pattern[str], ...]]
    types: Mapping[str, OpportunityTypePolicy]


@dataclass(frozen=True)
class WorkAuthorizationPolicy:
    silence: str
    ambiguous: str
    explicit_no_sponsorship: str
    citizenship_required: str
    patterns: Mapping[str, tuple[Pattern[str], ...]]


@dataclass(frozen=True)
class FlagNames:
    country_unknown: str
    start_date_unknown: str
    authorization_ambiguous: str
    opportunity_type_inferred: str


@dataclass(frozen=True)
class CountryTaxonomyEntry:
    names: tuple[str, ...]
    codes: tuple[str, ...]
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class LocationTaxonomy:
    version: int
    countries: Mapping[str, CountryTaxonomyEntry]
    us_states: Mapping[str, str]


@dataclass(frozen=True)
class EligibilityConfig:
    version: int
    countries: CountryPolicy
    opportunity_types: OpportunityTypesPolicy
    seasons: Mapping[str, SeasonPolicy]
    role_families: RoleFamilyPolicy
    seniority: SeniorityPolicy
    work_authorization: WorkAuthorizationPolicy
    flags: FlagNames
    taxonomy: LocationTaxonomy


_COUNTRY_CODES = {
    "AD","AE","AF","AG","AI","AL","AM","AO","AQ","AR","AS","AT","AU","AW","AX","AZ",
    "BA","BB","BD","BE","BF","BG","BH","BI","BJ","BL","BM","BN","BO","BQ","BR","BS",
    "BT","BV","BW","BY","BZ","CA","CC","CD","CF","CG","CH","CI","CK","CL","CM","CN",
    "CO","CR","CU","CV","CW","CX","CY","CZ","DE","DJ","DK","DM","DO","DZ","EC","EE",
    "EG","EH","ER","ES","ET","FI","FJ","FK","FM","FO","FR","GA","GB","GD","GE","GF",
    "GG","GH","GI","GL","GM","GN","GP","GQ","GR","GS","GT","GU","GW","GY","HK","HM",
    "HN","HR","HT","HU","ID","IE","IL","IM","IN","IO","IQ","IR","IS","IT","JE","JM",
    "JO","JP","KE","KG","KH","KI","KM","KN","KP","KR","KW","KY","KZ","LA","LB","LC",
    "LI","LK","LR","LS","LT","LU","LV","LY","MA","MC","MD","ME","MF","MG","MH","MK",
    "ML","MM","MN","MO","MP","MQ","MR","MS","MT","MU","MV","MW","MX","MY","MZ","NA",
    "NC","NE","NF","NG","NI","NL","NO","NP","NR","NU","NZ","OM","PA","PE","PF","PG",
    "PH","PK","PL","PM","PN","PR","PS","PT","PW","PY","QA","RE","RO","RS","RU","RW",
    "SA","SB","SC","SD","SE","SG","SH","SI","SJ","SK","SL","SM","SN","SO","SR","SS",
    "ST","SV","SX","SY","SZ","TC","TD","TF","TG","TH","TJ","TK","TL","TM","TN","TO",
    "TR","TT","TV","TW","TZ","UA","UG","UM","US","UY","UZ","VA","VC","VE","VG","VI",
    "VN","VU","WF","WS","YE","YT","ZA","ZM","ZW",
}

_POLICY_VALUES = {"allow", "reject", "defer", "allow_with_flag", "unknown"}
_YEAR_ONLY_VALUES = {"sufficient", "insufficient"}


def load_eligibility_config(
    policy_path: str | Path = "config/eligibility.yaml",
    taxonomy_path: str | Path = "config/location_taxonomy.yaml",
) -> EligibilityConfig:
    policy = _read_yaml(Path(policy_path), "eligibility")
    taxonomy = _read_yaml(Path(taxonomy_path), "location_taxonomy")
    return _parse_config(policy, taxonomy)


def _read_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            payload = yaml.safe_load(f) or {}
    except OSError as exc:
        raise EligibilityConfigError(f"{label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise EligibilityConfigError(f"{label}: expected mapping")
    return payload


def _parse_config(policy: dict[str, Any], taxonomy_payload: dict[str, Any]) -> EligibilityConfig:
    if policy.get("version") != 2:
        raise EligibilityConfigError("version must be 2")
    taxonomy = _parse_taxonomy(taxonomy_payload)
    countries = _parse_countries(policy.get("countries"), taxonomy)
    seasons = _parse_seasons(policy.get("seasons"))
    opportunity_types = _parse_opportunity_types(policy.get("opportunity_types"), seasons)
    role_families = _parse_role_families(policy.get("role_families"))
    seniority = _parse_seniority(policy.get("seniority"))
    work_authorization = _parse_work_authorization(policy.get("work_authorization"))
    flags = _parse_flags(policy.get("flags"))
    return EligibilityConfig(
        version=2,
        countries=countries,
        opportunity_types=opportunity_types,
        seasons=seasons,
        role_families=role_families,
        seniority=seniority,
        work_authorization=work_authorization,
        flags=flags,
        taxonomy=taxonomy,
    )


def _parse_taxonomy(payload: Any) -> LocationTaxonomy:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise EligibilityConfigError("location_taxonomy.version must be 1")
    countries_payload = payload.get("countries")
    if not isinstance(countries_payload, dict):
        raise EligibilityConfigError("location_taxonomy.countries must be mapping")
    countries: dict[str, CountryTaxonomyEntry] = {}
    for code, entry in countries_payload.items():
        if code not in _COUNTRY_CODES:
            raise EligibilityConfigError(f"location_taxonomy.countries.{code}: unknown ISO code")
        if not isinstance(entry, dict):
            raise EligibilityConfigError(f"location_taxonomy.countries.{code}: expected mapping")
        countries[code] = CountryTaxonomyEntry(
            names=_string_tuple(entry.get("names"), f"location_taxonomy.countries.{code}.names"),
            codes=_string_tuple(entry.get("codes"), f"location_taxonomy.countries.{code}.codes"),
            aliases=_string_tuple(entry.get("aliases") or [], f"location_taxonomy.countries.{code}.aliases"),
        )
    missing = sorted(_COUNTRY_CODES - set(countries))
    if missing:
        raise EligibilityConfigError(f"location_taxonomy.countries missing ISO codes: {', '.join(missing)}")
    states_payload = payload.get("us_states")
    if not isinstance(states_payload, dict):
        raise EligibilityConfigError("location_taxonomy.us_states must be mapping")
    return LocationTaxonomy(
        version=1,
        countries=MappingProxyType(countries),
        us_states=MappingProxyType({str(k): str(v) for k, v in states_payload.items()}),
    )


def _parse_countries(payload: Any, taxonomy: LocationTaxonomy) -> CountryPolicy:
    if not isinstance(payload, dict):
        raise EligibilityConfigError("countries must be mapping")
    allowed = _string_tuple(payload.get("allowed"), "countries.allowed")
    for code in allowed:
        if code not in taxonomy.countries:
            raise EligibilityConfigError(f"countries.allowed: unknown ISO country {code}")
    return CountryPolicy(
        allowed=allowed,
        explicit_non_match=_policy_value(payload.get("explicit_non_match"), "countries.explicit_non_match"),
        unknown_pre_resolution=_policy_value(payload.get("unknown_pre_resolution"), "countries.unknown_pre_resolution"),
        unknown_post_resolution=_policy_value(payload.get("unknown_post_resolution"), "countries.unknown_post_resolution"),
        remote_without_country=_policy_value(payload.get("remote_without_country"), "countries.remote_without_country"),
    )


def _parse_seasons(payload: Any) -> Mapping[str, SeasonPolicy]:
    if not isinstance(payload, dict):
        raise EligibilityConfigError("seasons must be mapping")
    seasons = {}
    for name, value in payload.items():
        months = value.get("months") if isinstance(value, dict) else None
        if not isinstance(months, list) or not months or any(not isinstance(m, int) or m < 1 or m > 12 for m in months):
            raise EligibilityConfigError(f"seasons.{name}.months")
        seasons[str(name)] = SeasonPolicy(months=tuple(months))
    return MappingProxyType(seasons)


def _parse_opportunity_types(payload: Any, seasons: Mapping[str, SeasonPolicy]) -> OpportunityTypesPolicy:
    if not isinstance(payload, dict):
        raise EligibilityConfigError("opportunity_types must be mapping")
    order = _string_tuple(payload.get("classification_order"), "opportunity_types.classification_order")
    patterns_payload = payload.get("patterns")
    if not isinstance(patterns_payload, dict):
        raise EligibilityConfigError("opportunity_types.patterns must be mapping")
    patterns: dict[str, tuple[Pattern[str], ...]] = {}
    for type_name, values in patterns_payload.items():
        patterns[str(type_name)] = _compile_patterns(values, f"opportunity_types.patterns.{type_name}")
    for type_name in order:
        if type_name not in patterns:
            raise EligibilityConfigError(f"opportunity_types.classification_order: missing patterns for {type_name}")
    types_payload = payload.get("types")
    if not isinstance(types_payload, dict):
        raise EligibilityConfigError("opportunity_types.types must be mapping")
    types: dict[str, OpportunityTypePolicy] = {}
    for type_name in order:
        if type_name not in types_payload:
            raise EligibilityConfigError(f"opportunity_types.types.{type_name}: missing policy")
        type_payload = types_payload[type_name]
        if not isinstance(type_payload, dict):
            raise EligibilityConfigError(f"opportunity_types.types.{type_name}: expected mapping")
        enabled = bool(type_payload.get("enabled"))
        allowed_seasons = _string_tuple(type_payload.get("allowed_seasons") or [], f"opportunity_types.types.{type_name}.allowed_seasons")
        for season in allowed_seasons:
            if season not in seasons:
                raise EligibilityConfigError(f"opportunity_types.types.{type_name}.allowed_seasons: unknown season {season}")
        types[type_name] = OpportunityTypePolicy(
            enabled=enabled,
            start_windows=_parse_windows(type_payload.get("start_windows") or [], f"opportunity_types.types.{type_name}.start_windows"),
            allowed_seasons=allowed_seasons,
            year_only_evidence=_optional_choice(type_payload.get("year_only_evidence"), _YEAR_ONLY_VALUES, f"opportunity_types.types.{type_name}.year_only_evidence"),
            unknown_start_pre_resolution=_optional_policy_value(type_payload.get("unknown_start_pre_resolution"), f"opportunity_types.types.{type_name}.unknown_start_pre_resolution"),
            unknown_start_post_resolution=_optional_policy_value(type_payload.get("unknown_start_post_resolution"), f"opportunity_types.types.{type_name}.unknown_start_post_resolution"),
        )
    default = str(payload.get("default_when_unmarked") or "")
    if default not in types:
        raise EligibilityConfigError("opportunity_types.default_when_unmarked")
    return OpportunityTypesPolicy(
        classification_order=order,
        default_when_unmarked=default,
        patterns=MappingProxyType(patterns),
        types=MappingProxyType(types),
    )


def _parse_windows(payload: Any, path: str) -> tuple[DateWindow, ...]:
    if not isinstance(payload, list):
        raise EligibilityConfigError(path)
    windows = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise EligibilityConfigError(f"{path}[{idx}]")
        earliest = _parse_date(item.get("earliest"), f"{path}[{idx}].earliest")
        latest = _parse_date(item.get("latest"), f"{path}[{idx}].latest")
        if earliest > latest:
            raise EligibilityConfigError(f"{path}[{idx}]: earliest after latest")
        windows.append(DateWindow(earliest, latest))
    return tuple(windows)


def _parse_role_families(payload: Any) -> RoleFamilyPolicy:
    include = payload.get("include") if isinstance(payload, dict) else None
    if not isinstance(include, list) or not include:
        raise EligibilityConfigError("role_families.include")
    families = []
    for idx, item in enumerate(include):
        if not isinstance(item, dict) or not item.get("name"):
            raise EligibilityConfigError(f"role_families.include[{idx}]")
        families.append(
            RoleFamily(
                name=str(item["name"]),
                patterns=_compile_patterns(item.get("patterns"), f"role_families.include[{idx}].patterns"),
            )
        )
    return RoleFamilyPolicy(include=tuple(families))


def _parse_seniority(payload: Any) -> SeniorityPolicy:
    if not isinstance(payload, dict):
        raise EligibilityConfigError("seniority")
    years_cap = payload.get("years_cap")
    if not isinstance(years_cap, int) or years_cap < 0:
        raise EligibilityConfigError("seniority.years_cap")
    return SeniorityPolicy(
        title_exclude_patterns=_compile_patterns(payload.get("title_exclude_patterns"), "seniority.title_exclude_patterns"),
        years_cap=years_cap,
    )


def _parse_work_authorization(payload: Any) -> WorkAuthorizationPolicy:
    if not isinstance(payload, dict):
        raise EligibilityConfigError("work_authorization")
    patterns_payload = payload.get("patterns")
    if not isinstance(patterns_payload, dict):
        raise EligibilityConfigError("work_authorization.patterns")
    patterns = {
        str(name): _compile_patterns(values, f"work_authorization.patterns.{name}")
        for name, values in patterns_payload.items()
    }
    return WorkAuthorizationPolicy(
        silence=_policy_value(payload.get("silence"), "work_authorization.silence"),
        ambiguous=_policy_value(payload.get("ambiguous"), "work_authorization.ambiguous"),
        explicit_no_sponsorship=_policy_value(payload.get("explicit_no_sponsorship"), "work_authorization.explicit_no_sponsorship"),
        citizenship_required=_policy_value(payload.get("citizenship_required"), "work_authorization.citizenship_required"),
        patterns=MappingProxyType(patterns),
    )


def _parse_flags(payload: Any) -> FlagNames:
    if not isinstance(payload, dict):
        raise EligibilityConfigError("flags")
    return FlagNames(
        country_unknown=_required_str(payload.get("country_unknown"), "flags.country_unknown"),
        start_date_unknown=_required_str(payload.get("start_date_unknown"), "flags.start_date_unknown"),
        authorization_ambiguous=_required_str(payload.get("authorization_ambiguous"), "flags.authorization_ambiguous"),
        opportunity_type_inferred=_required_str(payload.get("opportunity_type_inferred"), "flags.opportunity_type_inferred"),
    )


def _string_tuple(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise EligibilityConfigError(path)
    return tuple(value)


def _required_str(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise EligibilityConfigError(path)
    return value


def _policy_value(value: Any, path: str) -> str:
    if value not in _POLICY_VALUES:
        raise EligibilityConfigError(path)
    return str(value)


def _optional_policy_value(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _policy_value(value, path)


def _optional_choice(value: Any, choices: set[str], path: str) -> str | None:
    if value is None:
        return None
    if value not in choices:
        raise EligibilityConfigError(path)
    return str(value)


def _parse_date(value: Any, path: str) -> date:
    if not isinstance(value, str):
        raise EligibilityConfigError(path)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EligibilityConfigError(path) from exc


def _compile_patterns(value: Any, path: str) -> tuple[Pattern[str], ...]:
    values = _string_tuple(value, path)
    compiled = []
    for idx, pattern in enumerate(values):
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise EligibilityConfigError(f"{path}[{idx}]: invalid regex") from exc
    return tuple(compiled)
