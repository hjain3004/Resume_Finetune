import pytest
from src.company_bank.serde import (
    parse_research_bundle, parse_company_dossier, dump_company_dossier,
    CompanyBankValidationError, _parse_source, _parse_fact, _parse_signal, _parse_scope,
    _check_string_array, parse_utc_timestamp
)
from src.company_bank.serde import load_seed_companies
from pathlib import Path

def test_load_seed_companies_malformed_yaml(tmp_path):
    p = tmp_path / "malformed.yaml"
    p.write_text("a: [", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="malformed YAML"):
        load_seed_companies(p)

def test_load_seed_companies_not_mapping(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- a", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="Root must be a mapping"):
        load_seed_companies(p)

def test_load_seed_companies_invalid_keys(tmp_path):
    p = tmp_path / "invalid_keys.yaml"
    p.write_text("schema_version: '0.1.0'\nfoo: bar", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="Root keys must be exactly"):
        load_seed_companies(p)
        
def test_load_seed_companies_invalid_schema(tmp_path):
    p = tmp_path / "invalid_schema.yaml"
    p.write_text("schema_version: '0.2.0'\ncompanies: {}", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="schema_version must be"):
        load_seed_companies(p)
        
def test_load_seed_companies_empty_companies(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("schema_version: '0.1.0'\ncompanies: {}", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="companies must be a nonempty mapping"):
        load_seed_companies(p)
        
def test_load_seed_companies_invalid_id(tmp_path):
    p = tmp_path / "invalid_id.yaml"
    p.write_text("schema_version: '0.1.0'\ncompanies:\n  '123': 'foo'", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="Invalid company id"):
        load_seed_companies(p)
        
def test_load_seed_companies_invalid_name(tmp_path):
    p = tmp_path / "invalid_name.yaml"
    p.write_text("schema_version: '0.1.0'\ncompanies:\n  abc: 123", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="Invalid company display name"):
        load_seed_companies(p)

def test_load_seed_companies_duplicate_normalized_name(tmp_path):
    p = tmp_path / "dup_norm.yaml"
    p.write_text("schema_version: '0.1.0'\ncompanies:\n  abc: 'Foo'\n  def: 'foo'", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="Duplicate normalized display name"):
        load_seed_companies(p)
        
def test_parse_utc_timestamp_not_string():
    with pytest.raises(CompanyBankValidationError, match="expected string"):
        parse_utc_timestamp(123, "p")

def test_parse_utc_timestamp_invalid():
    with pytest.raises(CompanyBankValidationError, match="expected exact"):
        parse_utc_timestamp("not a timestampZ", "p")

def test_parse_scope_not_dict():
    with pytest.raises(CompanyBankValidationError, match="expected dict"):
        _parse_scope([], "p")

def test_parse_scope_invalid_kind():
    with pytest.raises(CompanyBankValidationError, match="kind: invalid"):
        _parse_scope({"kind": "foo", "name": "bar"}, "p")
        
def test_parse_scope_empty_name():
    with pytest.raises(CompanyBankValidationError, match="name: expected nonempty string"):
        _parse_scope({"kind": "company", "name": ""}, "p")

def test_parse_source_not_dict():
    with pytest.raises(CompanyBankValidationError, match="expected dict"):
        _parse_source([], "p", True)

def test_parse_source_invalid_id():
    with pytest.raises(CompanyBankValidationError, match="id: invalid"):
        _parse_source({"id": "1", "url": "https://a", "title": "a", "source_kind": "official_company", "scope": {"kind": "company", "name": "a"}, "retrieved_at": "2026-08-04T00:00:00Z", "content_sha256": "0"*64, "snapshot_file": "sources/a.txt"}, "p", True)

def test_parse_source_empty_title():
    with pytest.raises(CompanyBankValidationError, match="title: expected nonempty string"):
        _parse_source({"id": "a", "url": "https://a", "title": "", "source_kind": "official_company", "scope": {"kind": "company", "name": "a"}, "retrieved_at": "2026-08-04T00:00:00Z", "content_sha256": "0"*64, "snapshot_file": "sources/a.txt"}, "p", True)

def test_parse_source_invalid_kind():
    with pytest.raises(CompanyBankValidationError, match="source_kind: invalid"):
        _parse_source({"id": "a", "url": "https://a", "title": "a", "source_kind": "foo", "scope": {"kind": "company", "name": "a"}, "retrieved_at": "2026-08-04T00:00:00Z", "content_sha256": "0"*64, "snapshot_file": "sources/a.txt"}, "p", True)

def test_parse_source_invalid_hash():
    with pytest.raises(CompanyBankValidationError, match="content_sha256: invalid"):
        _parse_source({"id": "a", "url": "https://a", "title": "a", "source_kind": "official_company", "scope": {"kind": "company", "name": "a"}, "retrieved_at": "2026-08-04T00:00:00Z", "content_sha256": "0", "snapshot_file": "sources/a.txt"}, "p", True)

def test_parse_fact_not_dict():
    with pytest.raises(CompanyBankValidationError, match="expected dict"):
        _parse_fact([], "p")

def test_parse_fact_invalid_id():
    with pytest.raises(CompanyBankValidationError, match="id: invalid"):
        _parse_fact({"id": "1", "kind": "product", "scope": {"kind": "company", "name": "a"}, "claim": "a", "quote": "a", "source_id": "a"}, "p")

def test_parse_fact_empty_claim():
    with pytest.raises(CompanyBankValidationError, match="claim: expected nonempty string"):
        _parse_fact({"id": "a", "kind": "product", "scope": {"kind": "company", "name": "a"}, "claim": "", "quote": "a", "source_id": "a"}, "p")

def test_parse_fact_empty_quote():
    with pytest.raises(CompanyBankValidationError, match="quote: expected nonempty string"):
        _parse_fact({"id": "a", "kind": "product", "scope": {"kind": "company", "name": "a"}, "claim": "a", "quote": "", "source_id": "a"}, "p")

def test_parse_fact_invalid_source_id():
    with pytest.raises(CompanyBankValidationError, match="source_id: invalid"):
        _parse_fact({"id": "a", "kind": "product", "scope": {"kind": "company", "name": "a"}, "claim": "a", "quote": "a", "source_id": "1"}, "p")

def test_parse_signal_not_dict():
    with pytest.raises(CompanyBankValidationError, match="expected dict"):
        _parse_signal([], "p")

def test_parse_signal_invalid_id():
    with pytest.raises(CompanyBankValidationError, match="id: invalid"):
        _parse_signal({"id": "1", "text": "a", "basis_fact_ids": ["a"], "permitted_uses": ["s0"]}, "p")
        
def test_parse_signal_empty_text():
    with pytest.raises(CompanyBankValidationError, match="text: expected nonempty string"):
        _parse_signal({"id": "a", "text": "", "basis_fact_ids": ["a"], "permitted_uses": ["s0"]}, "p")
        
def test_parse_signal_empty_basis():
    with pytest.raises(CompanyBankValidationError, match="basis_fact_ids: expected nonempty list"):
        _parse_signal({"id": "a", "text": "a", "basis_fact_ids": [], "permitted_uses": ["s0"]}, "p")
        
def test_parse_signal_duplicate_basis():
    with pytest.raises(CompanyBankValidationError, match="basis_fact_ids: duplicate items"):
        _parse_signal({"id": "a", "text": "a", "basis_fact_ids": ["a", "a"], "permitted_uses": ["s0"]}, "p")
        
def test_parse_signal_invalid_basis_id():
    with pytest.raises(CompanyBankValidationError, match="basis_fact_ids.0: invalid"):
        _parse_signal({"id": "a", "text": "a", "basis_fact_ids": ["1"], "permitted_uses": ["s0"]}, "p")
        
def test_parse_signal_empty_uses():
    with pytest.raises(CompanyBankValidationError, match="permitted_uses: expected nonempty list"):
        _parse_signal({"id": "a", "text": "a", "basis_fact_ids": ["a"], "permitted_uses": []}, "p")

def test_parse_signal_duplicate_uses():
    with pytest.raises(CompanyBankValidationError, match="permitted_uses: duplicate items"):
        _parse_signal({"id": "a", "text": "a", "basis_fact_ids": ["a"], "permitted_uses": ["s0", "s0"]}, "p")
        
def test_parse_signal_invalid_use():
    with pytest.raises(CompanyBankValidationError, match="permitted_uses.0: invalid"):
        _parse_signal({"id": "a", "text": "a", "basis_fact_ids": ["a"], "permitted_uses": ["foo"]}, "p")

def test_check_string_array_not_list():
    with pytest.raises(CompanyBankValidationError, match="expected list"):
        _check_string_array({}, "p")
        
def test_check_string_array_duplicate():
    with pytest.raises(CompanyBankValidationError, match="duplicate item"):
        _check_string_array(["a", "a"], "p")

def test_check_string_array_duplicate_alias():
    from src.company_bank.serde import _normalize_alias
    with pytest.raises(CompanyBankValidationError, match="duplicate item"):
        _check_string_array(["Acme Corp", "acme-corp"], "p", normalize_fn=_normalize_alias)

def test_check_string_array_not_string():
    with pytest.raises(CompanyBankValidationError, match="expected string"):
        _check_string_array([{}], "p")

def test_parse_utc_timestamp_exact():
    from src.company_bank.serde import parse_utc_timestamp
    # Should fail for trailing fractional seconds
    with pytest.raises(CompanyBankValidationError, match="expected exact"):
        parse_utc_timestamp("2026-08-04T12:00:00.123Z", "p")
    # Should fail without Z
    with pytest.raises(CompanyBankValidationError, match="expected exact"):
        parse_utc_timestamp("2026-08-04T12:00:00", "p")
    # Should fail for offset
    with pytest.raises(CompanyBankValidationError, match="expected exact"):
        parse_utc_timestamp("2026-08-04T12:00:00+05:00Z", "p")
    # Should fail for impossible dates (passed regex, failed strptime)
    with pytest.raises(CompanyBankValidationError, match="invalid ISO-8601 date/time values"):
        parse_utc_timestamp("2026-13-45T12:00:00Z", "p")

def test_format_utc_timestamp_naive():
    from src.company_bank.serde import format_utc_timestamp
    from datetime import datetime
    with pytest.raises(ValueError, match="Cannot format a naive datetime"):
        format_utc_timestamp(datetime(2026, 8, 4, 12, 0, 0))

def test_check_string_array_empty_string():
    with pytest.raises(CompanyBankValidationError, match="expected nonempty string"):
        _check_string_array([""], "p")

def test_parse_research_bundle_malformed_json(tmp_path):
    p = tmp_path / "malformed.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="malformed JSON"):
        parse_research_bundle(p)

def test_parse_research_bundle_not_mapping(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="Root must be a mapping"):
        parse_research_bundle(p)

def test_parse_research_bundle_invalid_company_id(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"schema_version": "0.1.0", "company_id": "1", "display_name": "a", "aliases": [], "official_domains": ["a.com"], "researched_at": "2026-08-04T00:00:00Z", "sources": [{"id": "a", "url": "https://a", "title": "a", "source_kind": "official_company", "scope": {"kind": "company", "name": "a"}, "retrieved_at": "2026-08-04T00:00:00Z", "snapshot_file": "sources/a.txt", "content_sha256": "' + '0'*64 + '"}], "facts": [{"id": "a", "kind": "product", "scope": {"kind": "company", "name": "a"}, "claim": "a", "quote": "a", "source_id": "a"}], "signals": [{"id": "a", "text": "a", "basis_fact_ids": ["a"], "permitted_uses": ["s0"]}]}', encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="company_id: invalid"):
        parse_research_bundle(p)

def test_parse_research_bundle_empty_display_name(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"schema_version": "0.1.0", "company_id": "a", "display_name": "", "aliases": [], "official_domains": ["a.com"], "researched_at": "2026-08-04T00:00:00Z", "sources": [{"id": "a", "url": "https://a", "title": "a", "source_kind": "official_company", "scope": {"kind": "company", "name": "a"}, "retrieved_at": "2026-08-04T00:00:00Z", "snapshot_file": "sources/a.txt", "content_sha256": "' + '0'*64 + '"}], "facts": [{"id": "a", "kind": "product", "scope": {"kind": "company", "name": "a"}, "claim": "a", "quote": "a", "source_id": "a"}], "signals": [{"id": "a", "text": "a", "basis_fact_ids": ["a"], "permitted_uses": ["s0"]}]}', encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="display_name: expected nonempty string"):
        parse_research_bundle(p)

def test_parse_research_bundle_empty_domains(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"schema_version": "0.1.0", "company_id": "a", "display_name": "a", "aliases": [], "official_domains": [], "researched_at": "2026-08-04T00:00:00Z", "sources": [{"id": "a", "url": "https://a", "title": "a", "source_kind": "official_company", "scope": {"kind": "company", "name": "a"}, "retrieved_at": "2026-08-04T00:00:00Z", "snapshot_file": "sources/a.txt", "content_sha256": "' + '0'*64 + '"}], "facts": [{"id": "a", "kind": "product", "scope": {"kind": "company", "name": "a"}, "claim": "a", "quote": "a", "source_id": "a"}], "signals": [{"id": "a", "text": "a", "basis_fact_ids": ["a"], "permitted_uses": ["s0"]}]}', encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="official_domains: expected nonempty list"):
        parse_research_bundle(p)

def test_parse_research_bundle_empty_sources(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"schema_version": "0.1.0", "company_id": "a", "display_name": "a", "aliases": [], "official_domains": ["a.com"], "researched_at": "2026-08-04T00:00:00Z", "sources": [], "facts": [{"id": "a", "kind": "product", "scope": {"kind": "company", "name": "a"}, "claim": "a", "quote": "a", "source_id": "a"}], "signals": [{"id": "a", "text": "a", "basis_fact_ids": ["a"], "permitted_uses": ["s0"]}]}', encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="sources: expected nonempty list"):
        parse_research_bundle(p)

def test_parse_research_bundle_empty_signals(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"schema_version": "0.1.0", "company_id": "a", "display_name": "a", "aliases": [], "official_domains": ["a.com"], "researched_at": "2026-08-04T00:00:00Z", "sources": [{"id": "a", "url": "https://a", "title": "a", "source_kind": "official_company", "scope": {"kind": "company", "name": "a"}, "retrieved_at": "2026-08-04T00:00:00Z", "snapshot_file": "sources/a.txt", "content_sha256": "' + '0'*64 + '"}], "facts": [{"id": "a", "kind": "product", "scope": {"kind": "company", "name": "a"}, "claim": "a", "quote": "a", "source_id": "a"}], "signals": []}', encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="signals: expected nonempty list"):
        parse_research_bundle(p)

def test_parse_company_dossier_malformed_yaml(tmp_path):
    p = tmp_path / "malformed.yaml"
    p.write_text("a: [", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="malformed YAML"):
        parse_company_dossier(p)

def test_parse_company_dossier_invalid_schema(tmp_path):
    p = tmp_path / "invalid_schema.yaml"
    p.write_text("schema_version: '0.2.0'\ncompany_id: a\ndisplay_name: a\nofficial_domains: [a]\nresearched_at: 2026-08-04T00:00:00Z\nexpires_at: 2026-08-04T00:00:00Z\nsources: []\nfacts: []\nsignals: []\naliases: []", encoding="utf-8")
    with pytest.raises(CompanyBankValidationError, match="schema_version must be '0.1.0'"):
        parse_company_dossier(p)

