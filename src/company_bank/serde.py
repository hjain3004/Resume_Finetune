import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

import yaml


class CompanyBankValidationError(ValueError):
    pass


class _StrictLoader(yaml.SafeLoader):
    pass


def _no_duplicates(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise CompanyBankValidationError(
                f"line {key_node.start_mark.line + 1}: duplicate key: {key!r}"
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates
)


def _normalize_name(name: str) -> str:
    # We'll need a full normalization later, but for now simple casefold + strip
    # Actually the spec says: exact after Unicode NFKC, casefold, non-alphanumeric-run collapse, and whitespace collapse.
    nfkc = unicodedata.normalize("NFKC", name)
    casefolded = nfkc.casefold()
    collapsed = re.sub(r"[^a-z0-9]+", " ", casefolded).strip()
    return collapsed


def load_seed_companies(path: str | Path) -> dict[str, str]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.load(text, _StrictLoader)
    except yaml.YAMLError as exc:
        raise CompanyBankValidationError(f"malformed YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise CompanyBankValidationError("Root must be a mapping")

    allowed_keys = {"schema_version", "companies"}
    if set(data.keys()) != allowed_keys:
        raise CompanyBankValidationError(f"Root keys must be exactly {allowed_keys}")

    if data["schema_version"] != "0.1.0":
        raise CompanyBankValidationError("schema_version must be '0.1.0'")

    companies = data["companies"]
    if not isinstance(companies, dict) or not companies:
        raise CompanyBankValidationError("companies must be a nonempty mapping")

    id_pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    seen_normalized = set()
    result = {}

    for k, v in companies.items():
        if not isinstance(k, str) or not id_pattern.match(k):
            raise CompanyBankValidationError(f"Invalid company id: {k!r}")
        if not isinstance(v, str) or not v.strip():
            raise CompanyBankValidationError(f"Invalid company display name for {k!r}")

        norm = _normalize_name(v)
        if norm in seen_normalized:
            raise CompanyBankValidationError(f"Duplicate normalized display name: {v!r} ({norm})")
        seen_normalized.add(norm)
        result[k] = v

    return result
