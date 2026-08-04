import datetime
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.company_bank import model


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


def parse_utc_timestamp(value: object, path: str) -> datetime.datetime:
    """Accept only a string matching exactly YYYY-MM-DDTHH:MM:SSZ and return an aware UTC datetime."""
    if not isinstance(value, str):
        raise CompanyBankValidationError(f"{path}: expected string, got {type(value).__name__}")
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", value):
        raise CompanyBankValidationError(f"{path}: expected exact YYYY-MM-DDTHH:MM:SSZ format")
    try:
        dt = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError as exc:
        raise CompanyBankValidationError(f"{path}: invalid ISO-8601 date/time values: {exc}") from exc
    return dt


def format_utc_timestamp(value: datetime.datetime) -> str:
    """Return seconds-precision ISO-8601 with a trailing Z."""
    if value.tzinfo is None:
        raise ValueError("Cannot format a naive datetime")
    return value.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen = set()
    result = {}
    for k, v in pairs:
        if k in seen:
            raise CompanyBankValidationError(f"duplicate key: {k!r}")
        seen.add(k)
        result[k] = v
    return result


def _check_keys(data: dict, required: set[str], allowed: set[str], path: str):
    missing = required - data.keys()
    if missing:
        raise CompanyBankValidationError(f"{path}: missing {missing}")
    extra = set(data.keys()) - allowed
    if extra:
        raise CompanyBankValidationError(f"{path}: unexpected {extra}")


def _parse_scope(data: Any, path: str) -> model.CompanyScope:
    if not isinstance(data, dict):
        raise CompanyBankValidationError(f"{path}: expected dict")
    _check_keys(data, {"kind", "name"}, {"kind", "name"}, path)
    
    try:
        kind = model.ScopeKind(data["kind"])
    except ValueError:
        raise CompanyBankValidationError(f"{path}.kind: invalid {data['kind']!r}")
    
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise CompanyBankValidationError(f"{path}.name: expected nonempty string")
    
    return model.CompanyScope(kind=kind, name=data["name"])


def _parse_source(data: Any, path: str, require_snapshot: bool) -> model.CompanySource | model.ResearchSource:
    if not isinstance(data, dict):
        raise CompanyBankValidationError(f"{path}: expected dict")
        
    req = {"id", "url", "title", "source_kind", "scope", "retrieved_at", "content_sha256"}
    if require_snapshot:
        req.add("snapshot_file")
        
    _check_keys(data, req, req, path)
    
    if not isinstance(data["id"], str) or not re.match(r"^[a-z][a-z0-9_]*$", data["id"]):
        raise CompanyBankValidationError(f"{path}.id: invalid")
    if not isinstance(data["url"], str) or not data["url"].startswith("https://"):
        raise CompanyBankValidationError(f"{path}.url: invalid")
    if not isinstance(data["title"], str) or not data["title"].strip():
        raise CompanyBankValidationError(f"{path}.title: expected nonempty string")
        
    try:
        source_kind = model.SourceKind(data["source_kind"])
    except ValueError:
        raise CompanyBankValidationError(f"{path}.source_kind: invalid")
        
    scope = _parse_scope(data["scope"], f"{path}.scope")
    retrieved_at = parse_utc_timestamp(data["retrieved_at"], f"{path}.retrieved_at")
    
    if not isinstance(data["content_sha256"], str) or not re.match(r"^[0-9a-f]{64}$", data["content_sha256"]):
        raise CompanyBankValidationError(f"{path}.content_sha256: invalid")
        
    source = model.CompanySource(
        id=data["id"],
        url=data["url"],
        title=data["title"],
        source_kind=source_kind,
        scope=scope,
        retrieved_at=retrieved_at,
        content_sha256=data["content_sha256"]
    )
    
    if require_snapshot:
        snap = data["snapshot_file"]
        if not isinstance(snap, str) or not re.match(r"^sources/[a-z][a-z0-9_]*\.txt$", snap):
            raise CompanyBankValidationError(f"{path}.snapshot_file: invalid")
        return model.ResearchSource(source=source, snapshot_file=snap)
    return source


def _parse_fact(data: Any, path: str) -> model.CompanyFact:
    if not isinstance(data, dict):
        raise CompanyBankValidationError(f"{path}: expected dict")
        
    req = {"id", "kind", "scope", "claim", "quote", "source_id"}
    _check_keys(data, req, req, path)
    
    if not isinstance(data["id"], str) or not re.match(r"^[a-z][a-z0-9_]*$", data["id"]):
        raise CompanyBankValidationError(f"{path}.id: invalid")
        
    try:
        kind = model.FactKind(data["kind"])
    except ValueError:
        raise CompanyBankValidationError(f"{path}.kind: invalid")
        
    scope = _parse_scope(data["scope"], f"{path}.scope")
    
    if not isinstance(data["claim"], str) or not data["claim"].strip():
        raise CompanyBankValidationError(f"{path}.claim: expected nonempty string")
    if not isinstance(data["quote"], str) or not data["quote"].strip():
        raise CompanyBankValidationError(f"{path}.quote: expected nonempty string")
    if not isinstance(data["source_id"], str) or not re.match(r"^[a-z][a-z0-9_]*$", data["source_id"]):
        raise CompanyBankValidationError(f"{path}.source_id: invalid")
        
    return model.CompanyFact(
        id=data["id"],
        kind=kind,
        scope=scope,
        claim=data["claim"],
        quote=data["quote"],
        source_id=data["source_id"]
    )


def _parse_signal(data: Any, path: str) -> model.TailoringSignal:
    if not isinstance(data, dict):
        raise CompanyBankValidationError(f"{path}: expected dict")
        
    req = {"id", "text", "basis_fact_ids", "permitted_uses"}
    _check_keys(data, req, req, path)
    
    if not isinstance(data["id"], str) or not re.match(r"^[a-z][a-z0-9_]*$", data["id"]):
        raise CompanyBankValidationError(f"{path}.id: invalid")
    if not isinstance(data["text"], str) or not data["text"].strip():
        raise CompanyBankValidationError(f"{path}.text: expected nonempty string")
        
    facts = data["basis_fact_ids"]
    if not isinstance(facts, list) or not facts:
        raise CompanyBankValidationError(f"{path}.basis_fact_ids: expected nonempty list")
    if len(set(facts)) != len(facts):
        raise CompanyBankValidationError(f"{path}.basis_fact_ids: duplicate items")
    for i, item in enumerate(facts):
        if not isinstance(item, str) or not re.match(r"^[a-z][a-z0-9_]*$", item):
            raise CompanyBankValidationError(f"{path}.basis_fact_ids.{i}: invalid")
            
    uses = data["permitted_uses"]
    if not isinstance(uses, list) or not uses:
        raise CompanyBankValidationError(f"{path}.permitted_uses: expected nonempty list")
    if len(set(uses)) != len(uses):
        raise CompanyBankValidationError(f"{path}.permitted_uses: duplicate items")
    
    parsed_uses = []
    for i, item in enumerate(uses):
        try:
            parsed_uses.append(model.PermittedUse(item))
        except ValueError:
            raise CompanyBankValidationError(f"{path}.permitted_uses.{i}: invalid")
            
    return model.TailoringSignal(
        id=data["id"],
        text=data["text"],
        basis_fact_ids=tuple(facts),
        permitted_uses=tuple(parsed_uses)
    )


def _normalize_alias(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).casefold()
    name = re.sub(r"[^a-z0-9]+", " ", name).strip()
    return re.sub(r"\s+", " ", name)

def _check_string_array(data: Any, path: str, unique: bool = True, pattern: str = None, normalize_fn: callable = None) -> tuple[str, ...]:
    if not isinstance(data, list):
        raise CompanyBankValidationError(f"{path}: expected list")
    for i, item in enumerate(data):
        if not isinstance(item, str):
            raise CompanyBankValidationError(f"{path}.{i}: expected string")
        if not item.strip():
            raise CompanyBankValidationError(f"{path}.{i}: expected nonempty string")
        if pattern and not re.match(pattern, item):
            raise CompanyBankValidationError(f"{path}.{i}: invalid format")
    if unique:
        seen = set()
        for i, item in enumerate(data):
            val = normalize_fn(item) if normalize_fn else item
            if val in seen:
                raise CompanyBankValidationError(f"{path}.{i}: duplicate item")
            seen.add(val)
    return tuple(data)


def parse_research_bundle(path: str | Path) -> model.ResearchBundle:
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except json.JSONDecodeError as exc:
        raise CompanyBankValidationError(f"malformed JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise CompanyBankValidationError("Root must be a mapping")

    req = {
        "schema_version", "company_id", "display_name", "aliases",
        "official_domains", "researched_at", "sources", "facts", "signals"
    }
    _check_keys(data, req, req, "root")

    if data["schema_version"] != "0.1.0":
        raise CompanyBankValidationError("schema_version must be '0.1.0'")

    if not isinstance(data["company_id"], str) or not re.match(r"^[a-z][a-z0-9_]*$", data["company_id"]):
        raise CompanyBankValidationError("company_id: invalid")
    if not isinstance(data["display_name"], str) or not data["display_name"].strip():
        raise CompanyBankValidationError("display_name: expected nonempty string")

    aliases = _check_string_array(data.get("aliases", []), "aliases", normalize_fn=_normalize_alias)
    official_domains = _check_string_array(
        data.get("official_domains", []), "official_domains", pattern=r"^[a-z0-9.-]+$", normalize_fn=lambda s: s.lower()
    )
    if not official_domains:
        raise CompanyBankValidationError("official_domains: expected nonempty list")

    researched_at = parse_utc_timestamp(data["researched_at"], "researched_at")

    sources = data.get("sources", [])
    if not isinstance(sources, list) or not sources:
        raise CompanyBankValidationError("sources: expected nonempty list")
    parsed_sources = tuple(_parse_source(item, f"sources.{i}", True) for i, item in enumerate(sources))

    facts = data.get("facts", [])
    if not isinstance(facts, list) or not facts:
        raise CompanyBankValidationError("facts: expected nonempty list")
    parsed_facts = tuple(_parse_fact(item, f"facts.{i}") for i, item in enumerate(facts))

    signals = data.get("signals", [])
    if not isinstance(signals, list) or not signals:
        raise CompanyBankValidationError("signals: expected nonempty list")
    parsed_signals = tuple(_parse_signal(item, f"signals.{i}") for i, item in enumerate(signals))

    return model.ResearchBundle(
        schema_version=data["schema_version"],
        company_id=data["company_id"],
        display_name=data["display_name"],
        aliases=aliases,
        official_domains=official_domains,
        researched_at=researched_at,
        sources=parsed_sources,
        facts=parsed_facts,
        signals=parsed_signals,
    )


def parse_company_dossier(path: str | Path) -> model.CompanyDossier:
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.load(text, _StrictLoader)
    except yaml.YAMLError as exc:
        raise CompanyBankValidationError(f"malformed YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise CompanyBankValidationError("Root must be a mapping")

    req = {
        "schema_version", "company_id", "display_name", "aliases",
        "official_domains", "researched_at", "expires_at", "sources", "facts", "signals"
    }
    _check_keys(data, req, req, "root")

    if data["schema_version"] != "0.1.0":
        raise CompanyBankValidationError("schema_version must be '0.1.0'")

    aliases = _check_string_array(data.get("aliases", []), "aliases", normalize_fn=_normalize_alias)
    official_domains = _check_string_array(
        data.get("official_domains", []), "official_domains", pattern=r"^[a-z0-9.-]+$", normalize_fn=lambda s: s.lower()
    )
    researched_at = parse_utc_timestamp(data["researched_at"], "researched_at")
    expires_at = parse_utc_timestamp(data["expires_at"], "expires_at")

    sources = data.get("sources", [])
    parsed_sources = tuple(_parse_source(item, f"sources.{i}", False) for i, item in enumerate(sources))
    facts = data.get("facts", [])
    parsed_facts = tuple(_parse_fact(item, f"facts.{i}") for i, item in enumerate(facts))
    signals = data.get("signals", [])
    parsed_signals = tuple(_parse_signal(item, f"signals.{i}") for i, item in enumerate(signals))

    return model.CompanyDossier(
        schema_version=data["schema_version"],
        company_id=data["company_id"],
        display_name=data["display_name"],
        aliases=aliases,
        official_domains=official_domains,
        researched_at=researched_at,
        expires_at=expires_at,
        sources=parsed_sources,
        facts=parsed_facts,
        signals=parsed_signals,
    )


def dump_company_dossier(dossier: model.CompanyDossier) -> str:
    payload = {
        "schema_version": dossier.schema_version,
        "company_id": dossier.company_id,
        "display_name": dossier.display_name,
        "aliases": list(dossier.aliases),
        "official_domains": list(dossier.official_domains),
        "researched_at": format_utc_timestamp(dossier.researched_at),
        "expires_at": format_utc_timestamp(dossier.expires_at),
        "sources": [
            {
                "id": s.id,
                "url": s.url,
                "title": s.title,
                "source_kind": s.source_kind.value,
                "scope": {"kind": s.scope.kind.value, "name": s.scope.name},
                "retrieved_at": format_utc_timestamp(s.retrieved_at),
                "content_sha256": s.content_sha256,
            }
            for s in dossier.sources
        ],
        "facts": [
            {
                "id": f.id,
                "kind": f.kind.value,
                "scope": {"kind": f.scope.kind.value, "name": f.scope.name},
                "claim": f.claim,
                "quote": f.quote,
                "source_id": f.source_id,
            }
            for f in dossier.facts
        ],
        "signals": [
            {
                "id": s.id,
                "text": s.text,
                "basis_fact_ids": list(s.basis_fact_ids),
                "permitted_uses": [u.value for u in s.permitted_uses],
            }
            for s in dossier.signals
        ],
    }

    return yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=False,
        width=1000,
        default_flow_style=False,
    )
