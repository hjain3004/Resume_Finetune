import dataclasses
import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Callable

import pytest

from src.company_bank.model import (
    CompanyDossier,
    SourceKind,
    TTL_DAYS,
)
from src.company_bank.serde import (
    CompanyBankValidationError,
    dump_company_dossier,
    parse_company_dossier,
    parse_research_bundle,
)

FIXTURE = Path("tests/fixtures/company_bank/valid_acme")


def _copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "valid_acme"
    shutil.copytree(FIXTURE, target)
    return target / "bundle.json"


def _rewrite(path: Path, mutate: Callable[[dict], None]) -> None:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    mutate(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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


def test_raw_json_with_duplicate_key(tmp_path):
    path = _copy_fixture(tmp_path)
    text = path.read_text(encoding="utf-8")
    text = text.replace('"company_id": "acme",', '"company_id": "acme",\n  "company_id": "acme",')
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="duplicate key"):
        parse_research_bundle(path)


def test_add_unexpected_root_key(tmp_path):
    path = _copy_fixture(tmp_path)
    def mutate(d): d["unexpected"] = "value"
    _rewrite(path, mutate)
    with pytest.raises(CompanyBankValidationError, match="unexpected"):
        parse_research_bundle(path)


def test_add_expires_at_root_key(tmp_path):
    path = _copy_fixture(tmp_path)
    def mutate(d): d["expires_at"] = "2026-08-04T00:00:00Z"
    _rewrite(path, mutate)
    with pytest.raises(CompanyBankValidationError, match="expires_at"):
        parse_research_bundle(path)


def test_delete_display_name(tmp_path):
    path = _copy_fixture(tmp_path)
    def mutate(d): del d["display_name"]
    _rewrite(path, mutate)
    with pytest.raises(CompanyBankValidationError, match="display_name"):
        parse_research_bundle(path)


def test_replace_facts_with_empty_dict(tmp_path):
    path = _copy_fixture(tmp_path)
    def mutate(d): d["facts"] = {}
    _rewrite(path, mutate)
    with pytest.raises(CompanyBankValidationError, match="facts"):
        parse_research_bundle(path)


def test_set_facts_0_kind_to_rumor(tmp_path):
    path = _copy_fixture(tmp_path)
    def mutate(d): d["facts"][0]["kind"] = "rumor"
    _rewrite(path, mutate)
    with pytest.raises(CompanyBankValidationError, match="facts.0.kind"):
        parse_research_bundle(path)


def test_remove_trailing_Z_from_researched_at(tmp_path):
    path = _copy_fixture(tmp_path)
    def mutate(d): d["researched_at"] = d["researched_at"].replace("Z", "")
    _rewrite(path, mutate)
    with pytest.raises(CompanyBankValidationError, match="researched_at"):
        parse_research_bundle(path)


def test_add_prohibited_root_key_visa(tmp_path):
    path = _copy_fixture(tmp_path)
    def mutate(d): d["visa"] = "required"
    _rewrite(path, mutate)
    with pytest.raises(CompanyBankValidationError, match="visa"):
        parse_research_bundle(path)
