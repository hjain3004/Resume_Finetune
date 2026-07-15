"""Typed, deterministic eligibility policy engine.

M6.11 keeps business policy in config/eligibility.yaml and local vocabulary in
config/location_taxonomy.yaml. This module is intentionally pure: no SQLite, no
network, no browser, and no logging side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Pattern

import yaml


class EligibilityConfigError(ValueError):
    pass


class CountryEvidence(str, Enum):
    EXPLICIT_ALLOWED = "explicit_allowed"
    EXPLICIT_DISALLOWED = "explicit_disallowed"
    UNKNOWN = "unknown"


class OpportunityType(str, Enum):
    INTERNSHIP = "internship"
    CO_OP = "co_op"
    CONTRACT = "contract"
    PART_TIME = "part_time"
    TEMPORARY = "temporary"
    FULL_TIME = "full_time"


class EligibilityStage(str, Enum):
    PRE_RESOLUTION = "pre_resolution"
    POST_RESOLUTION = "post_resolution"


class EligibilityDisposition(str, Enum):
    PASS = "pass"
    FILTER = "filter"
    DEFER = "defer"


@dataclass(frozen=True)
class DateWindow:
    earliest: date
    latest: date


@dataclass(frozen=True)
class CountryClassification:
    evidence: CountryEvidence
    country_codes: tuple[str, ...]
    matched_text: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityClassification:
    opportunity_type: OpportunityType
    inferred: bool
    matched_text: tuple[str, ...]


@dataclass(frozen=True)
class StartEvidence:
    exact_dates: tuple[date, ...]
    month_years: tuple[tuple[int, int], ...]
    seasons: tuple[tuple[str, int], ...]
    years: tuple[int, ...]
    matched_text: tuple[str, ...]


@dataclass(frozen=True)
class EligibilityDecision:
    disposition: EligibilityDisposition
    reason_code: str | None
    flags: tuple[str, ...]
    evidence: tuple[str, ...]


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


def classify_country(location: str | None, config: EligibilityConfig) -> CountryClassification:
    text = (location or "").strip()
    if not text:
        return CountryClassification(CountryEvidence.UNKNOWN, (), ())

    matched: dict[str, set[str]] = {}
    for code, entry in config.taxonomy.countries.items():
        for phrase in (*entry.names, *entry.aliases):
            if _contains_phrase(text, phrase):
                matched.setdefault(code, set()).add(phrase)
        for country_code in entry.codes:
            if len(country_code) == 2:
                if code == "US" and _contains_phrase(text, country_code):
                    matched.setdefault(code, set()).add(country_code)
                elif country_code not in config.taxonomy.us_states and _contains_phrase(text, country_code):
                    matched.setdefault(code, set()).add(country_code)
            elif _contains_phrase(text, country_code):
                matched.setdefault(code, set()).add(country_code)

    us_matches = _match_us_states(text, config)
    if us_matches:
        matched.setdefault("US", set()).update(us_matches)

    allowed = set(config.countries.allowed)
    disallowed_codes = sorted(code for code in matched if code not in allowed)
    if disallowed_codes:
        return CountryClassification(
            CountryEvidence.EXPLICIT_DISALLOWED,
            tuple(disallowed_codes),
            tuple(sorted({item for code in disallowed_codes for item in matched[code]})),
        )
    allowed_codes = sorted(code for code in matched if code in allowed)
    if allowed_codes:
        return CountryClassification(
            CountryEvidence.EXPLICIT_ALLOWED,
            tuple(allowed_codes),
            tuple(sorted({item for code in allowed_codes for item in matched[code]})),
        )
    return CountryClassification(CountryEvidence.UNKNOWN, (), ())


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def _match_us_states(text: str, config: EligibilityConfig) -> set[str]:
    matches: set[str] = set()
    for abbr, name in config.taxonomy.us_states.items():
        if _contains_phrase(text, name):
            matches.add(name)
        # Treat state abbreviations as state evidence in bounded location-token
        # positions, especially city/state forms. This prevents "CA" from being
        # read as Canada in "San Diego, CA" while avoiding substring accidents.
        if re.search(rf"(?:^|[,\-/\s]){re.escape(abbr)}(?:$|[,\-/\s])", text, re.IGNORECASE):
            matches.add(abbr)
    return matches


def classify_opportunity_type(
    title: str, jd_text: str | None, config: EligibilityConfig
) -> OpportunityClassification:
    for text in (title or "", jd_text or ""):
        if not text:
            continue
        for type_name in config.opportunity_types.classification_order:
            for pattern in config.opportunity_types.patterns[type_name]:
                match = pattern.search(text)
                if match:
                    return OpportunityClassification(
                        OpportunityType(type_name),
                        False,
                        (match.group(0),),
                    )
    return OpportunityClassification(
        OpportunityType(config.opportunity_types.default_when_unmarked),
        True,
        (),
    )


_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_START_CONTEXT_RE = re.compile(
    r"\b(start|starts|starting|available|availability|begin|begins|commence|commences|"
    r"new grad|new graduate|graduate|internship|intern|program|role|co[- ]?op)\b",
    re.IGNORECASE,
)
_NON_START_CONTEXT_RE = re.compile(r"\b(founded|copyright|established|incorporated)\b", re.IGNORECASE)


def extract_start_evidence(text: str, config: EligibilityConfig) -> StartEvidence:
    exact_dates: set[date] = set()
    month_years: set[tuple[int, int]] = set()
    seasons: set[tuple[str, int]] = set()
    years: set[int] = set()
    matched_text: set[str] = set()

    for segment in _evidence_segments(text or ""):
        if not _is_start_context(segment):
            continue
        for match in re.finditer(r"\b(20\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])\b", segment):
            try:
                parsed = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
            exact_dates.add(parsed)
            matched_text.add(match.group(0))
        for match in re.finditer(r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(20\d{2})\b", segment):
            try:
                parsed = date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
            except ValueError:
                continue
            exact_dates.add(parsed)
            matched_text.add(match.group(0))
        month_pattern = "|".join(re.escape(name) for name in sorted(_MONTHS, key=len, reverse=True))
        for match in re.finditer(rf"\b({month_pattern})\.?\s+(20\d{{2}})\b", segment, re.IGNORECASE):
            month = _MONTHS[match.group(1).lower().rstrip(".")]
            year = int(match.group(2))
            month_years.add((year, month))
            matched_text.add(match.group(0))
        for season_name in config.seasons:
            for match in re.finditer(rf"\b{re.escape(season_name)}\s+(20\d{{2}})\b", segment, re.IGNORECASE):
                seasons.add((season_name, int(match.group(1))))
                matched_text.add(match.group(0))
        for match in re.finditer(r"\b(20\d{2})\b", segment):
            years.add(int(match.group(1)))
            matched_text.add(match.group(0))

    # More specific date evidence also contains a year; keep year evidence
    # visible because policy can treat year-only as sufficient/insufficient.
    return StartEvidence(
        exact_dates=tuple(sorted(exact_dates)),
        month_years=tuple(sorted(month_years)),
        seasons=tuple(sorted(seasons)),
        years=tuple(sorted(years)),
        matched_text=tuple(sorted(matched_text)),
    )


def _evidence_segments(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"[.\n;]", text) if segment.strip()]


def _is_start_context(segment: str) -> bool:
    if _NON_START_CONTEXT_RE.search(segment):
        return False
    return _START_CONTEXT_RE.search(segment) is not None


_YEARS_RE = re.compile(
    r"(?:minimum|at least|required|requires?)[^.\n]{0,40}?(\d+)\+?\s*(?:years|yrs)"
    r"|(\d+)\+?\s*(?:years|yrs)[^.\n]{0,40}?(?:minimum|at least|required|requires?)",
    re.IGNORECASE,
)


def evaluate(
    *,
    stage: EligibilityStage,
    title: str,
    location: str | None,
    jd_text: str | None,
    existing_flags: tuple[str, ...],
    config: EligibilityConfig,
) -> EligibilityDecision:
    flags = set(existing_flags)
    evidence: list[str] = []

    country = classify_country(location, config)
    if country.evidence is CountryEvidence.EXPLICIT_DISALLOWED:
        return _decision(EligibilityDisposition.FILTER, "eligibility:country", flags, country.matched_text)
    if country.evidence is CountryEvidence.UNKNOWN:
        if stage is EligibilityStage.PRE_RESOLUTION and config.countries.unknown_pre_resolution == "defer":
            return _decision(EligibilityDisposition.DEFER, None, flags, country.matched_text)
        if stage is EligibilityStage.POST_RESOLUTION:
            if config.countries.unknown_post_resolution == "reject":
                return _decision(EligibilityDisposition.FILTER, "eligibility:country", flags, country.matched_text)
            if config.countries.unknown_post_resolution == "allow_with_flag":
                flags.add(config.flags.country_unknown)

    combined_text = " ".join(part for part in (title, jd_text or "") if part)
    if stage is EligibilityStage.POST_RESOLUTION:
        auth = _evaluate_work_authorization(combined_text, existing_flags, config)
        if auth[0] == "filter":
            return _decision(EligibilityDisposition.FILTER, "eligibility:work_authorization", flags, auth[2])
        if auth[0] == "flag":
            flags.add(config.flags.authorization_ambiguous)
            evidence.extend(auth[2])

    opportunity = classify_opportunity_type(title, jd_text if stage is EligibilityStage.POST_RESOLUTION else None, config)
    if opportunity.inferred:
        flags.add(config.flags.opportunity_type_inferred)
    type_policy = config.opportunity_types.types[opportunity.opportunity_type.value]
    if not type_policy.enabled:
        return _decision(EligibilityDisposition.FILTER, "eligibility:opportunity_type", flags, opportunity.matched_text)

    start = _evaluate_start_window(opportunity.opportunity_type.value, combined_text, type_policy, stage, config)
    if start[0] == "filter":
        return _decision(EligibilityDisposition.FILTER, "eligibility:start_window", flags, start[2])
    if start[0] == "defer":
        return _decision(EligibilityDisposition.DEFER, None, flags, start[2])
    if start[0] == "flag":
        flags.add(config.flags.start_date_unknown)
        evidence.extend(start[2])

    if not any(pattern.search(title) or (stage is EligibilityStage.POST_RESOLUTION and jd_text and pattern.search(jd_text))
               for family in config.role_families.include for pattern in family.patterns):
        return _decision(EligibilityDisposition.FILTER, "eligibility:role_family", flags, ())

    if any(pattern.search(title) for pattern in config.seniority.title_exclude_patterns):
        return _decision(EligibilityDisposition.FILTER, "eligibility:seniority", flags, ())
    seniority_text = title if stage is EligibilityStage.PRE_RESOLUTION else combined_text
    required_years = _years_required(seniority_text)
    if required_years is not None and required_years > config.seniority.years_cap:
        return _decision(EligibilityDisposition.FILTER, "eligibility:seniority", flags, (f"{required_years} years",))

    return _decision(EligibilityDisposition.PASS, None, flags, tuple(evidence))


def _decision(
    disposition: EligibilityDisposition,
    reason_code: str | None,
    flags: set[str],
    evidence: tuple[str, ...],
) -> EligibilityDecision:
    return EligibilityDecision(
        disposition=disposition,
        reason_code=reason_code,
        flags=tuple(sorted(flags)),
        evidence=tuple(sorted(set(evidence))),
    )


def _evaluate_start_window(
    type_name: str,
    text: str,
    policy: OpportunityTypePolicy,
    stage: EligibilityStage,
    config: EligibilityConfig,
) -> tuple[str, str | None, tuple[str, ...]]:
    evidence = extract_start_evidence(text, config)
    matched = evidence.matched_text
    if _evidence_matches_policy(evidence, policy, config):
        return ("pass", None, matched)

    has_evidence = bool(evidence.exact_dates or evidence.month_years or evidence.seasons or evidence.years)
    if has_evidence:
        if type_name == OpportunityType.FULL_TIME.value and policy.year_only_evidence == "sufficient":
            # Any explicit start evidence outside the configured windows is a
            # deterministic miss for full-time.
            return ("filter", "eligibility:start_window", matched)
        if stage is EligibilityStage.PRE_RESOLUTION:
            return ("defer", None, matched)
        return ("filter", "eligibility:start_window", matched)

    unknown_policy = (
        policy.unknown_start_pre_resolution
        if stage is EligibilityStage.PRE_RESOLUTION
        else policy.unknown_start_post_resolution
    )
    if unknown_policy == "defer":
        return ("defer", None, ())
    if unknown_policy == "reject":
        return ("filter", "eligibility:start_window", ())
    if unknown_policy == "allow_with_flag":
        return ("flag", None, ())
    return ("pass", None, ())


def _evidence_matches_policy(evidence: StartEvidence, policy: OpportunityTypePolicy, config: EligibilityConfig) -> bool:
    for exact in evidence.exact_dates:
        if _date_in_windows(exact, policy.start_windows):
            return True
    for year, month in evidence.month_years:
        if _date_in_windows(date(year, month, 1), policy.start_windows):
            return True
    for season, year in evidence.seasons:
        if season in policy.allowed_seasons:
            months = config.seasons[season].months
            if any(_date_in_windows(date(year, month, 1), policy.start_windows) for month in months):
                return True
    if policy.year_only_evidence == "sufficient":
        for year in evidence.years:
            if any(window.earliest.year <= year <= window.latest.year for window in policy.start_windows):
                return True
    return False


def _date_in_windows(value: date, windows: tuple[DateWindow, ...]) -> bool:
    return any(window.earliest <= value <= window.latest for window in windows)


def _evaluate_work_authorization(
    text: str,
    existing_flags: tuple[str, ...],
    config: EligibilityConfig,
) -> tuple[str, str | None, tuple[str, ...]]:
    policy = config.work_authorization
    for key in ("explicit_no_sponsorship", "citizenship_required"):
        for pattern in policy.patterns.get(key, ()):
            match = pattern.search(text)
            if match:
                return ("filter", "eligibility:work_authorization", (match.group(0),))
    for pattern in policy.patterns.get("positive_sponsorship", ()):
        match = pattern.search(text)
        if match:
            return ("pass", None, (match.group(0),))
    for pattern in policy.patterns.get("ambiguous", ()):
        match = pattern.search(text)
        if match:
            return ("flag", None, (match.group(0),))
    return ("pass", None, ())


def _years_required(jd_text: str) -> int | None:
    numbers = []
    for match in _YEARS_RE.finditer(jd_text):
        value = match.group(1) or match.group(2)
        numbers.append(int(value))
    return min(numbers) if numbers else None
