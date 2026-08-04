# M8 Company Knowledge Bank Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the typed, offline, deterministic validation/import/lookup foundation for the approved Company Knowledge Bank without researching companies, creating real dossiers, or integrating the bank into live tailoring.

**Architecture:** A focused `src/company_bank/` package owns immutable domain types, strict JSON/YAML serialization, evidence and policy validation, canonical loading/lookup, and an all-or-nothing first-corpus importer. A thin `scripts/company_bank.py` CLI exposes those pure operations. Research bundles remain ignored, untrusted inputs; canonical YAML is produced only after the complete seed corpus validates.

**Tech Stack:** Python 3.11+, standard library (`argparse`, `dataclasses`, `datetime`, `enum`, `hashlib`, `json`, `os`, `pathlib`, `re`, `tempfile`, `unicodedata`, `urllib.parse`), existing PyYAML and pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-04-m8-company-knowledge-bank-design.md`

## Global Constraints

- Read `AGENTS.md`, `docs/ARCHITECTURE.md`, the spec above, and `docs/ROADMAP.md` before editing.
- This is **Track A only**. Do not research live companies, browse the web, create `config/company_bank/companies/*.yaml`, run Track B, run Track C, or integrate S0/S2/G3.
- Do not touch SQLite, `src/db.py`, eligibility, sponsorship, scoring, job statuses, `config/master_profile.yaml`, or rendering.
- No new dependency or dependency-file change. Automated tests never access the network.
- Python 3.11+, type hints everywhere, frozen dataclasses at module boundaries, tuples instead of mutable lists, and small pure functions.
- Raw dictionaries are allowed only inside serialization functions. Library code uses `logging` if it logs and never calls `print`; only the CLI may print summaries.
- Duplicate YAML and JSON keys are errors. Unknown keys are errors. Booleans must not pass integer checks. Timestamps are UTC ISO-8601 strings ending in `Z` at the file boundary and timezone-aware `datetime` objects internally.
- Company matching is exact after Unicode NFKC, casefold, non-alphanumeric-run collapse, and whitespace collapse. No fuzzy or substring matching.
- Source hosts use boundary-safe matching: `host == domain` or `host.endswith("." + domain)`. A string suffix such as `fakeamazon.com` must never match `amazon.com`.
- Research bundles omit `expires_at`. Canonical expiry is always importer-computed as `researched_at + 90 days`.
- Import is corpus-wide: one invalid/missing/unexpected company means no canonical directory is created. Version 0.1.0 permits initial creation and byte-identical re-import only; a non-identical existing corpus is refused rather than partially refreshed.
- Commit only Track A files with `feat(m8): add company knowledge bank foundation`, then stop.

## File map

- Create `config/company_bank/seed_companies.yaml`: fixed 30-company id/display-name acceptance set.
- Create `config/company_bank/research_bundle.schema.json`: exact exchange contract for Claude Web output; documentation/fixture contract, validated in code without `jsonschema`.
- Create `src/company_bank/__init__.py`: stable public imports only.
- Create `src/company_bank/model.py`: enums and frozen boundary dataclasses.
- Create `src/company_bank/serde.py`: strict JSON/YAML parsing and deterministic canonical YAML emission.
- Create `src/company_bank/policy.py`: normalization, source/fact/use matrices, evidence validation, and canonical conversion.
- Create `src/company_bank/store.py`: canonical corpus loading, collision checks, scope filtering, freshness, and lookup.
- Create `src/company_bank/importer.py`: seed-set validation, staging, atomic initial adoption, and idempotent re-import.
- Create `scripts/company_bank.py`: `validate-bundle`, `validate-corpus`, `import-corpus`, and `lookup` CLI commands.
- Create `tests/company_bank/`: focused offline tests and synthetic evidence fixtures.
- Modify `docs/ARCHITECTURE.md`: document the new reference-data boundary and layout, explicitly marked as foundation-only.
- Modify `docs/IMPLEMENTATION_PLAN.md`: index Track A as complete only after its acceptance gate; leave Track B/C and live integration open.
- Modify `docs/ROADMAP.md`: record foundation status without claiming that the 30-company bank or live tailoring is complete.

---

### Task 1: Fixed seed contract and immutable domain model

**Files:**
- Create: `config/company_bank/seed_companies.yaml`
- Create: `src/company_bank/__init__.py`
- Create: `src/company_bank/model.py`
- Test: `tests/company_bank/__init__.py`
- Test: `tests/company_bank/test_model.py`

**Interfaces:**
- Consumes: no company-bank code.
- Produces: `SCHEMA_VERSION`, `TTL_DAYS`, all enums/dataclasses, and the first `serde.py` function `load_seed_companies(path: str | Path) -> dict[str, str]` for later tasks.

- [ ] **Step 1: Write the fixed seed file**

Create `config/company_bank/seed_companies.yaml` exactly as:

```yaml
schema_version: "0.1.0"
companies:
  palantir: Palantir
  cisco: Cisco
  notion: Notion
  atos: Atos
  bytedance: ByteDance
  newsbreak: NewsBreak
  quantcast: Quantcast
  google: Google
  microsoft: Microsoft
  amazon: Amazon
  meta: Meta
  apple: Apple
  nvidia: NVIDIA
  netflix: Netflix
  linkedin: LinkedIn
  uber: Uber
  airbnb: Airbnb
  stripe: Stripe
  databricks: Databricks
  snowflake: Snowflake
  cloudflare: Cloudflare
  mongodb: MongoDB
  datadog: Datadog
  doordash: DoorDash
  roblox: Roblox
  capital_one: Capital One
  salesforce: Salesforce
  rippling: Rippling
  plaid: Plaid
  ramp: Ramp
```

- [ ] **Step 2: Write the failing model tests**

Create `tests/company_bank/test_model.py` with these contract assertions (construct full objects with the shown values, not dictionaries):

```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/company_bank/test_model.py -v`

Expected: FAIL because `src.company_bank` and its model do not exist.

- [ ] **Step 4: Implement the domain model**

In `src/company_bank/model.py`, define these exact public contracts:

```python
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
```

Create `src/company_bank/__init__.py` exporting only the stable loader/lookup API after those functions exist; for this task it may be an empty module with a package docstring.

- [ ] **Step 5: Add a minimal strict seed loader and pass the tests**

Create `src/company_bank/serde.py` with `load_seed_companies`. Use the strict YAML loader pattern from `src/profile.py`; accept only root keys `schema_version` and `companies`, require version `0.1.0`, require a nonempty mapping of lowercase snake-case ids to nonempty strings, and reject duplicate normalized display names.

Run: `.venv/bin/pytest tests/company_bank/test_model.py -v`

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add config/company_bank/seed_companies.yaml src/company_bank tests/company_bank
git commit -m "feat(m8): define company bank contracts"
```

---

### Task 2: Strict research-bundle and canonical-dossier serialization

**Files:**
- Create: `config/company_bank/research_bundle.schema.json`
- Modify: `src/company_bank/serde.py`
- Test: `tests/company_bank/test_serde.py`
- Create: `tests/fixtures/company_bank/valid_acme/bundle.json`
- Create: `tests/fixtures/company_bank/valid_acme/sources/product.txt`
- Create: `tests/fixtures/company_bank/valid_acme/sources/engineering.txt`

**Interfaces:**
- Consumes: Task 1 dataclasses and enums.
- Produces: `CompanyBankValidationError(ValueError)`, `parse_research_bundle(path) -> ResearchBundle`, `parse_company_dossier(path) -> CompanyDossier`, and `dump_company_dossier(dossier) -> str`.

- [ ] **Step 1: Write the exact JSON exchange schema**

Create `config/company_bank/research_bundle.schema.json` exactly as this documentation/exchange contract. Runtime code still validates manually because `jsonschema` is not an approved dependency.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://job-pipeline.local/schemas/company-research-bundle-0.1.0.json",
  "title": "Company Research Bundle 0.1.0",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "company_id", "display_name", "aliases",
    "official_domains", "researched_at", "sources", "facts", "signals"
  ],
  "properties": {
    "schema_version": {"const": "0.1.0"},
    "company_id": {"$ref": "#/$defs/id"},
    "display_name": {"$ref": "#/$defs/nonempty"},
    "aliases": {
      "type": "array", "items": {"$ref": "#/$defs/nonempty"}, "uniqueItems": true
    },
    "official_domains": {
      "type": "array", "minItems": 1, "uniqueItems": true,
      "items": {"type": "string", "pattern": "^[a-z0-9.-]+$"}
    },
    "researched_at": {"$ref": "#/$defs/utc"},
    "sources": {
      "type": "array", "minItems": 1, "items": {"$ref": "#/$defs/source"}
    },
    "facts": {
      "type": "array", "minItems": 1, "items": {"$ref": "#/$defs/fact"}
    },
    "signals": {
      "type": "array", "minItems": 1, "items": {"$ref": "#/$defs/signal"}
    }
  },
  "$defs": {
    "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
    "nonempty": {"type": "string", "minLength": 1, "pattern": "\\S"},
    "utc": {
      "type": "string",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
    },
    "scope": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "name"],
      "properties": {
        "kind": {"enum": ["company", "business_unit", "role_family"]},
        "name": {"$ref": "#/$defs/nonempty"}
      }
    },
    "source": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "id", "url", "title", "source_kind", "scope", "retrieved_at",
        "snapshot_file", "content_sha256"
      ],
      "properties": {
        "id": {"$ref": "#/$defs/id"},
        "url": {"type": "string", "pattern": "^https://"},
        "title": {"$ref": "#/$defs/nonempty"},
        "source_kind": {
          "enum": [
            "official_company", "official_product", "official_engineering",
            "official_careers", "official_hiring_guide", "verified_dataset"
          ]
        },
        "scope": {"$ref": "#/$defs/scope"},
        "retrieved_at": {"$ref": "#/$defs/utc"},
        "snapshot_file": {"type": "string", "pattern": "^sources/[a-z][a-z0-9_]*\\.txt$"},
        "content_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
      }
    },
    "fact": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "kind", "scope", "claim", "quote", "source_id"],
      "properties": {
        "id": {"$ref": "#/$defs/id"},
        "kind": {
          "enum": [
            "identity", "industry", "product", "domain", "engineering_theme",
            "value", "hiring_guidance", "ats"
          ]
        },
        "scope": {"$ref": "#/$defs/scope"},
        "claim": {"$ref": "#/$defs/nonempty"},
        "quote": {"$ref": "#/$defs/nonempty"},
        "source_id": {"$ref": "#/$defs/id"}
      }
    },
    "signal": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "text", "basis_fact_ids", "permitted_uses"],
      "properties": {
        "id": {"$ref": "#/$defs/id"},
        "text": {"$ref": "#/$defs/nonempty"},
        "basis_fact_ids": {
          "type": "array", "minItems": 1, "uniqueItems": true,
          "items": {"$ref": "#/$defs/id"}
        },
        "permitted_uses": {
          "type": "array", "minItems": 1, "uniqueItems": true,
          "items": {"enum": ["s0", "s2_tiebreak", "g3_advisory"]}
        }
      }
    }
  }
}
```

The research `source` requires `snapshot_file`; the canonical model does not. `expires_at` is absent and therefore forbidden by `additionalProperties: false`.

- [ ] **Step 2: Create one valid synthetic bundle fixture**

Use `company_id: acme`, official domain `acme.example`, `researched_at: 2026-08-04T00:00:00Z`, two official HTTPS sources, two facts (`product`, `engineering_theme`), and one `s0`/`s2_tiebreak` signal. Each source snapshot contains its fact quote verbatim. Compute and place the real lowercase SHA-256 for each saved snapshot; never use dummy hash text.

- [ ] **Step 3: Write failing strict-parsing tests**

Use a local `_copy_fixture(tmp_path) -> Path` helper that copies `tests/fixtures/company_bank/valid_acme` and returns its `bundle.json`. Use a `_rewrite(path, mutate)` helper that loads the JSON object, applies a callable, and rewrites indented JSON. The happy path and round trip must be exactly:

```python
def test_valid_research_bundle_becomes_frozen_typed_data():
    bundle = parse_research_bundle(FIXTURE / "bundle.json")
    assert bundle.company_id == "acme"
    assert bundle.sources[0].source.source_kind is SourceKind.OFFICIAL_PRODUCT
    assert isinstance(bundle.sources, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        bundle.company_id = "changed"


def test_dump_is_stable_and_round_trips_canonical_dossier(tmp_path):
    bundle = parse_research_bundle(FIXTURE / "bundle.json")
    dossier = CompanyDossier(
        schema_version=bundle.schema_version,
        company_id=bundle.company_id,
        display_name=bundle.display_name,
        aliases=bundle.aliases,
        official_domains=bundle.official_domains,
        researched_at=bundle.researched_at,
        expires_at=bundle.researched_at + timedelta(days=TTL_DAYS),
        sources=tuple(item.source for item in bundle.sources),
        facts=bundle.facts,
        signals=bundle.signals,
    )
    first = dump_company_dossier(dossier)
    second = dump_company_dossier(dossier)
    assert first == second
    assert first.endswith("\n") and not first.endswith("\n\n")
    path = tmp_path / "acme.yaml"
    path.write_text(first, encoding="utf-8")
    assert parse_company_dossier(path) == dossier
```

Add one test per mutation below. Each calls `parse_research_bundle` and asserts `CompanyBankValidationError` contains the indicated path fragment:

| Mutation | Required error fragment |
|---|---|
| write raw JSON with `company_id` twice | `duplicate key` |
| add root key `unexpected` | `unexpected` |
| add root key `expires_at` | `expires_at` |
| delete `display_name` | `display_name` |
| replace `facts` with `{}` | `facts` |
| set `facts[0].kind` to `rumor` | `facts.0.kind` |
| remove the trailing `Z` from `researched_at` | `researched_at` |
| add prohibited root key `visa` | `visa` |

These are separate tests so each failure is diagnostic. Prohibited eligibility/candidate fields never survive the strict serialization boundary.

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/company_bank/test_serde.py -v`

Expected: FAIL because the three public serialization functions are absent.

- [ ] **Step 5: Implement strict serialization**

Implement manual shape validation in `serde.py`; do not add `jsonschema`. Use `json.loads(text, object_pairs_hook=reject_duplicate_pairs)` to reject duplicate JSON keys and the existing `_StrictLoader` pattern for YAML. Centralize helpers for exact keys, string, list, enum, UTC timestamp, scope, source, fact, and signal.

Timestamp helpers must have these contracts:

```python
def parse_utc_timestamp(value: object, path: str) -> datetime:
    """Accept only a string ending in Z and return an aware UTC datetime."""


def format_utc_timestamp(value: datetime) -> str:
    """Return seconds-precision ISO-8601 with a trailing Z."""
```

`dump_company_dossier` must construct an insertion-ordered plain dictionary in canonical field order and call:

```python
yaml.safe_dump(
    payload,
    sort_keys=False,
    allow_unicode=False,
    width=1000,
    default_flow_style=False,
)
```

- [ ] **Step 6: Run focused tests and commit**

Run: `.venv/bin/pytest tests/company_bank/test_model.py tests/company_bank/test_serde.py -v`

Expected: PASS.

```bash
git add config/company_bank/research_bundle.schema.json src/company_bank/serde.py tests/company_bank tests/fixtures/company_bank
git commit -m "feat(m8): parse company research contracts strictly"
```

---

### Task 3: Evidence, authority, privacy, and permitted-use validation

**Files:**
- Create: `src/company_bank/policy.py`
- Test: `tests/company_bank/test_policy.py`

**Interfaces:**
- Consumes: `ResearchBundle`, `CompanyDossier`, `CompanyBankValidationError` and fixture snapshots.
- Produces: `normalize_company_name(value: str) -> str`, `validate_research_bundle(bundle: ResearchBundle, bundle_dir: Path) -> None`, `validate_company_dossier(dossier: CompanyDossier) -> None`, and `to_company_dossier(bundle: ResearchBundle, bundle_dir: Path) -> CompanyDossier`.

- [ ] **Step 1: Write failing normalization and source-authority tests**

Add tests proving:

```python
assert normalize_company_name("  Amazon.com, Inc.  ") == "amazon com inc"
assert normalize_company_name("ＮＶＩＤＩＡ") == "nvidia"
```

Then create mutated versions of the valid synthetic bundle and assert rejection for HTTP URLs, `https://fakeacme.example/...`, missing snapshot, non-UTF-8 snapshot bytes, path traversal, hash mismatch, quote mismatch, duplicate ids, unresolved `source_id`, unresolved `basis_fact_ids`, a source retrieved after `researched_at`, and a verified-dataset source used for a product fact.

- [ ] **Step 2: Write failing policy and privacy tests**

Assert these exact matrices:

```python
SOURCE_FACT_KINDS = {
    SourceKind.OFFICIAL_COMPANY: frozenset({
        FactKind.IDENTITY, FactKind.INDUSTRY, FactKind.PRODUCT,
        FactKind.DOMAIN, FactKind.VALUE,
    }),
    SourceKind.OFFICIAL_PRODUCT: frozenset({FactKind.PRODUCT, FactKind.DOMAIN}),
    SourceKind.OFFICIAL_ENGINEERING: frozenset({
        FactKind.PRODUCT, FactKind.DOMAIN, FactKind.ENGINEERING_THEME,
    }),
    SourceKind.OFFICIAL_CAREERS: frozenset({FactKind.VALUE, FactKind.HIRING_GUIDANCE}),
    SourceKind.OFFICIAL_HIRING_GUIDE: frozenset({FactKind.HIRING_GUIDANCE}),
    SourceKind.VERIFIED_DATASET: frozenset({
        FactKind.IDENTITY, FactKind.INDUSTRY, FactKind.ATS,
    }),
}

FACT_PERMITTED_USES = {
    FactKind.IDENTITY: frozenset(),
    FactKind.INDUSTRY: frozenset(),
    FactKind.PRODUCT: frozenset({PermittedUse.S0, PermittedUse.S2_TIEBREAK}),
    FactKind.DOMAIN: frozenset({PermittedUse.S0, PermittedUse.S2_TIEBREAK}),
    FactKind.ENGINEERING_THEME: frozenset({PermittedUse.S0, PermittedUse.S2_TIEBREAK}),
    FactKind.VALUE: frozenset({PermittedUse.S0}),
    FactKind.HIRING_GUIDANCE: frozenset({PermittedUse.S0, PermittedUse.G3_ADVISORY}),
    FactKind.ATS: frozenset({PermittedUse.G3_ADVISORY}),
}
```

For a signal with multiple basis facts, permitted uses must be a subset of the intersection of their allowed-use sets. Reject duplicate aliases/domains/references case-insensitively, duplicate permitted uses, blank strings, more than 25 whitespace-delimited words in a quote, IP-literal hosts, URL userinfo, and query/fragment credentials. Task 2's strict raw-object parser rejects unknown fields, including this prohibited-field regression set:

```python
PRIVACY_DENYLIST = frozenset({
    "candidate", "candidate_name", "email", "phone", "resume",
    "master_profile", "sponsorship", "citizenship", "visa",
    "work_authorization", "location_eligibility", "start_window",
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/company_bank/test_policy.py -v`

Expected: FAIL because `src.company_bank.policy` does not exist.

- [ ] **Step 4: Implement pure validation and canonical conversion**

Use `urllib.parse.urlsplit`; lowercase and IDNA-normalize hosts; strip one trailing dot; accept an official host only with:

```python
def host_matches_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)
```

Allow verified datasets only from a constant allowlist containing the exact hosts accepted during design review. For version 0.1.0 use:

```python
VERIFIED_DATASET_HOSTS = frozenset({"www.wikidata.org", "raw.githubusercontent.com"})
```

Do not dynamically trust a host merely because a research bundle declares it official. Require official domains to be syntactically valid lowercase DNS names and require every non-dataset source host to match one. Validate snapshot paths as exactly `sources/{source.id}.txt`, resolve them under `bundle_dir`, and assert the resolved path remains below `bundle_dir / "sources"`. Read snapshots explicitly as UTF-8 and convert `UnicodeDecodeError` into a path-specific `CompanyBankValidationError`. Require every source `retrieved_at <= researched_at`.

`to_company_dossier(bundle, bundle_dir)` must call `validate_research_bundle(bundle, bundle_dir)`, drop `snapshot_file`, and set:

```python
expires_at = bundle.researched_at + timedelta(days=TTL_DAYS)
```

Then call `validate_company_dossier` before returning.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/pytest tests/company_bank/test_policy.py tests/company_bank/test_serde.py -v`

Expected: PASS.

```bash
git add src/company_bank/policy.py tests/company_bank/test_policy.py
git commit -m "feat(m8): validate company evidence and use policy"
```

---

### Task 4: Deterministic canonical loader, aliases, freshness, and scoped projection

**Files:**
- Create: `src/company_bank/store.py`
- Modify: `src/company_bank/__init__.py`
- Test: `tests/company_bank/test_store.py`

**Interfaces:**
- Consumes: canonical dossier parsing/validation and Task 3 normalization.
- Produces: `load_company_bank(root: str | Path) -> CompanyBank` and `lookup_company(bank, company_name, *, now, business_unit=None, role_family=None, permitted_use=PermittedUse.S0) -> CompanyLookupResult`.

- [ ] **Step 1: Write failing corpus-load tests**

Build temporary canonical directories with `dump_company_dossier` and a local `make_dossier(company_id, display_name, aliases=())` helper. Add separate tests with these exact assertions:

| Test | Assertion |
|---|---|
| sorted scan | `tuple(bank.dossiers) == ("alpha", "zeta")` even when files were written in reverse order |
| filename/id | `wrong.yaml` containing `company_id: acme` raises with `filename` |
| duplicate id | two files declaring `acme` raise with `duplicate company id` |
| alias collision | `Acme, Inc.` and `ACME INC` on different ids raise with `alias collision` |
| implicit aliases | normalized `company_id` and `display_name` keys both map to the dossier id |
| empty/missing directory | both return a bank with empty dossier and alias mappings |

The collision test must use the exact two aliases shown above.

- [ ] **Step 2: Write failing lookup/projection tests**

Use an injected UTC `now`; never monkeypatch the system clock. Cover fresh, exactly-at-expiry, expired, and missing lookups. Assert:

- exactly at `expires_at` is expired;
- missing/expired results have `view is None` and a visible nonempty message;
- company-wide signals are always eligible;
- business-unit and role-family signals appear only on exact normalized scope-name matches;
- `s2_tiebreak` lookup excludes `s0`-only signals;
- citations contain source URLs/titles but no raw snapshot content or fact quotes;
- output order follows dossier signal order and is deterministic.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/company_bank/test_store.py -v`

Expected: FAIL because the store API is absent.

- [ ] **Step 4: Implement loader and lookup**

The lookup signature is `lookup_company(bank: CompanyBank, company_name: str, *, now: datetime, business_unit: str | None = None, role_family: str | None = None, permitted_use: PermittedUse = PermittedUse.S0) -> CompanyLookupResult`.

Resolve the normalized company name through `alias_index`; return `MISSING` when absent, `EXPIRED` when `now >= expires_at`, otherwise select signals containing `permitted_use`. Include company-scoped signals; include business-unit/role-family signals only when the corresponding optional caller scope normalizes exactly to the fact scope that anchors the signal.

Build citations from each signal's basis facts as stable strings in this form:

```text
{source.title} — {source.url}
```

Deduplicate citations while preserving first occurrence. Wrap the loader's dossier and alias dictionaries in `types.MappingProxyType` before constructing `CompanyBank`. Export `load_company_bank`, `lookup_company`, `CompanyBankValidationError`, `CompanyLookupResult`, and `PermittedUse` from `src/company_bank/__init__.py`.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/pytest tests/company_bank/test_store.py tests/company_bank/test_policy.py -v`

Expected: PASS.

```bash
git add src/company_bank/__init__.py src/company_bank/store.py tests/company_bank/test_store.py
git commit -m "feat(m8): load and query company dossiers deterministically"
```

---

### Task 5: All-or-nothing seed-corpus importer

**Files:**
- Create: `src/company_bank/importer.py`
- Test: `tests/company_bank/test_importer.py`

**Interfaces:**
- Consumes: seed loader, bundle parser/policy conversion, deterministic YAML dump.
- Produces: `ImportStatus`, `ImportResult`, `validate_corpus(inbox_root: Path, seed_path: Path, *, now: datetime) -> tuple[CompanyDossier, ...]`, and `import_corpus(inbox_root: Path, bank_root: Path, seed_path: Path, *, now: datetime) -> ImportResult`.

- [ ] **Step 1: Write failing corpus validation tests**

Generate a three-company temporary seed set for unit tests; do not duplicate the 30 fixture directories. Assert hard failure for missing seed id, unexpected id, duplicate bundle company id, display-name disagreement, company-directory/id disagreement, invalid bundle, future `researched_at`, and expired-on-arrival bundle. Pass an injected `now` to validation so the tests are stable.

- [ ] **Step 2: Write failing atomicity and idempotency tests**

Add one test for each row below using a fixed `now=datetime(2026, 8, 4, 12, tzinfo=timezone.utc)`:

| Test setup | Required assertion |
|---|---|
| corrupt one quote in a three-company inbox | raises and `bank_root / "companies"` does not exist |
| valid three-company inbox | returns `CREATED`; filenames equal sorted seed ids |
| run the same valid import twice | second result is `UNCHANGED`; filename/bytes mapping is identical |
| change one bundle after first import | raises; filename/bytes mapping remains identical |
| successful and failing calls | no child of `bank_root` starts with `.companies-stage-` afterward |

For refusal tests, snapshot every target filename and byte payload before the call and assert exact equality afterward.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/company_bank/test_importer.py -v`

Expected: FAIL because importer contracts are absent.

- [ ] **Step 4: Implement validate-then-stage import**

Use these result types:

```python
class ImportStatus(str, Enum):
    CREATED = "created"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class ImportResult:
    status: ImportStatus
    company_count: int
    target: Path
```

`validate_corpus` must parse all expected `inbox/{company_id}/bundle.json` files, reject any extra company directory, validate all bundles before returning, reject a dossier when `researched_at > now` or `expires_at <= now`, and sort dossiers by `company_id`. `import_corpus` must:

1. call `validate_corpus` before creating a staging directory;
2. render all 30 YAML payloads in memory;
3. write them to a sibling temporary directory named by `tempfile.mkdtemp(prefix=".companies-stage-", dir=bank_root)`;
4. parse and validate the staged YAML corpus;
5. if `companies/` is absent, call `os.replace(stage, companies)`;
6. if `companies/` has exactly identical filenames/bytes, delete the stage and return `UNCHANGED`;
7. otherwise delete the stage and raise `CompanyBankValidationError` without touching the existing corpus.

This initial-adoption contract is intentionally narrower than general refresh. Do not add an overwrite flag.

- [ ] **Step 5: Run focused tests and commit**

Run: `.venv/bin/pytest tests/company_bank/test_importer.py tests/company_bank/test_store.py -v`

Expected: PASS.

```bash
git add src/company_bank/importer.py tests/company_bank/test_importer.py
git commit -m "feat(m8): import company corpus atomically"
```

---

### Task 6: Offline operator CLI, documentation, and milestone acceptance

**Files:**
- Create: `scripts/company_bank.py`
- Test: `tests/company_bank/test_cli.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/IMPLEMENTATION_PLAN.md`
- Modify: `docs/ROADMAP.md`

**Interfaces:**
- Consumes: all Track A public APIs.
- Produces: stable offline commands for Track B checks and Track C adoption.

- [ ] **Step 1: Write failing CLI tests**

Call `main(argv)` directly and use `capsys`. Cover:

```text
validate-bundle PATH
validate-corpus --inbox PATH --seeds PATH --now 2026-08-04T12:00:00Z
import-corpus --inbox PATH --bank-root PATH --seeds PATH --now 2026-08-04T12:00:00Z
lookup COMPANY --bank-root PATH --now 2026-08-04T12:00:00Z [--business-unit X] [--role-family Y] [--use s0]
```

Success exits 0 and prints a one-line summary. Contract/evidence failure exits 1 and writes `INVALID:` to stderr. Unreadable paths exit 2 and write `UNREADABLE:`. `lookup` returns 0 for fresh and 3 for missing/expired so callers can distinguish JD-only fallback without treating it as corrupted data.

- [ ] **Step 2: Run CLI tests to verify they fail**

Run: `.venv/bin/pytest tests/company_bank/test_cli.py -v`

Expected: FAIL because `scripts.company_bank` does not exist.

- [ ] **Step 3: Implement the thin CLI**

Define `build_parser() -> argparse.ArgumentParser` and `main(argv: list[str] | None = None) -> int`. Parse `--now` with `parse_utc_timestamp`; default to `datetime.now(timezone.utc)` only when the flag is absent. CLI code may print; all validation/import logic remains in `src/company_bank`.

- [ ] **Step 4: Document the actual boundary and commands**

Update architecture/layout/dependency sections to list `config/company_bank`, `src/company_bank`, and `data/company_research/inbox` and state that Track A is offline foundation only. In `docs/IMPLEMENTATION_PLAN.md`, add the Track A acceptance criteria below. In `docs/ROADMAP.md`, write “Company Bank foundation complete; research corpus, adoption, and S0/S2 integration pending.” Do not describe Phase 3 or M8 as complete.

- [ ] **Step 5: Run the complete acceptance gate**

Run sequentially:

```bash
.venv/bin/python -m scripts.company_bank --help
.venv/bin/pytest tests/company_bank -v
.venv/bin/pytest -q
git diff --check
```

Expected:

- CLI help exits 0 and shows all four subcommands.
- Every company-bank test passes without network access.
- Full suite passes with only the repository's existing intentional deselection.
- `git diff --check` is silent.
- `config/company_bank/companies/` does not exist and no real company dossier was created.
- No DB, score, eligibility, profile, renderer, or live-tailoring file changed.

- [ ] **Step 6: Commit the Track A milestone and stop**

```bash
git add scripts/company_bank.py tests/company_bank docs/ARCHITECTURE.md docs/IMPLEMENTATION_PLAN.md docs/ROADMAP.md
git commit -m "feat(m8): add company knowledge bank foundation"
git status --short
```

Expected: clean working tree. Report focused/full test counts and commit hash to the user. Do not start company research, corpus adoption, or live-tailoring integration in this session.
