import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from src.company_bank.model import (
    FactKind,
    PermittedUse,
    SourceKind,
)
from src.company_bank.policy import (
    FACT_PERMITTED_USES,
    PRIVACY_DENYLIST,
    SOURCE_FACT_KINDS,
    normalize_company_name,
    to_company_dossier,
    validate_company_dossier,
    validate_research_bundle,
)
from src.company_bank.serde import CompanyBankValidationError, parse_research_bundle

FIXTURE = Path("tests/fixtures/company_bank/valid_acme")


def _copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "valid_acme"
    shutil.copytree(FIXTURE, target)
    return target


def _rewrite(bundle_dir: Path, mutate) -> None:
    path = bundle_dir / "bundle.json"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    mutate(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_normalization():
    assert normalize_company_name("  Amazon.com, Inc.  ") == "amazon com inc"
    assert normalize_company_name("ＮＶＩＤＩＡ") == "nvidia"


def test_policy_matrices():
    assert SOURCE_FACT_KINDS == {
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

    assert FACT_PERMITTED_USES == {
        FactKind.IDENTITY: frozenset(),
        FactKind.INDUSTRY: frozenset(),
        FactKind.PRODUCT: frozenset({PermittedUse.S0, PermittedUse.S2_TIEBREAK}),
        FactKind.DOMAIN: frozenset({PermittedUse.S0, PermittedUse.S2_TIEBREAK}),
        FactKind.ENGINEERING_THEME: frozenset({PermittedUse.S0, PermittedUse.S2_TIEBREAK}),
        FactKind.VALUE: frozenset({PermittedUse.S0}),
        FactKind.HIRING_GUIDANCE: frozenset({PermittedUse.S0, PermittedUse.G3_ADVISORY}),
        FactKind.ATS: frozenset({PermittedUse.G3_ADVISORY}),
    }


def test_privacy_denylist():
    assert PRIVACY_DENYLIST == frozenset({
        "candidate", "candidate_name", "email", "phone", "resume",
        "master_profile", "sponsorship", "citizenship", "visa",
        "work_authorization", "location_eligibility", "start_window",
    })


def test_valid_bundle_to_dossier(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    dossier = to_company_dossier(bundle, bundle_dir)
    validate_company_dossier(dossier)


def test_http_url(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["sources"][0].update(url="http://acme.example/product"))
    with pytest.raises(CompanyBankValidationError, match="invalid"):
        bundle = parse_research_bundle(bundle_dir / "bundle.json")
        validate_research_bundle(bundle, bundle_dir)


def test_fake_domain(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["sources"][0].update(url="https://fakeacme.example/product"))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="domain"):
        validate_research_bundle(bundle, bundle_dir)


def test_missing_snapshot(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    (bundle_dir / "sources" / "product.txt").unlink()
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="missing"):
        validate_research_bundle(bundle, bundle_dir)


def test_path_traversal(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["sources"][0].update(snapshot_file="sources/../product.txt"))
    # Serialization boundary already catches `snapshot_file` regex, but let's just make sure it fails serialization or policy.
    with pytest.raises(CompanyBankValidationError):
        bundle = parse_research_bundle(bundle_dir / "bundle.json")
        validate_research_bundle(bundle, bundle_dir)


def test_hash_mismatch(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    (bundle_dir / "sources" / "product.txt").write_text("corrupted", encoding="utf-8")
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="hash mismatch"):
        validate_research_bundle(bundle, bundle_dir)


def test_quote_mismatch(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["facts"][0].update(quote="This quote is not in the snapshot"))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="quote"):
        validate_research_bundle(bundle, bundle_dir)


def test_duplicate_source_ids(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["sources"][1].update(id=d["sources"][0]["id"]))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="Duplicate source id"):
        validate_research_bundle(bundle, bundle_dir)


def test_unresolved_source_id(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["facts"][0].update(source_id="nonexistent"))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="unresolved source"):
        validate_research_bundle(bundle, bundle_dir)


def test_unresolved_basis_fact_ids(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["signals"][0].update(basis_fact_ids=["nonexistent"]))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="unresolved fact"):
        validate_research_bundle(bundle, bundle_dir)


def test_retrieved_after_researched(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["sources"][0].update(retrieved_at="2026-08-05T00:00:00Z"))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="retrieved after"):
        validate_research_bundle(bundle, bundle_dir)


def test_verified_dataset_product_fact(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["sources"][0].update(source_kind="verified_dataset", url="https://raw.githubusercontent.com/test"))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="not allowed"):
        validate_research_bundle(bundle, bundle_dir)


def test_duplicate_aliases_case_insensitive(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d.update(aliases=["Acme", "ACME"]))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="duplicate alias"):
        validate_research_bundle(bundle, bundle_dir)


def test_duplicate_domains_case_insensitive(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d.update(official_domains=["acme.example", "ACME.EXAMPLE"]))
    # Regex fails in serde since it expects lowercase domains for valid JSON, but let's just make sure it fails either in serde or policy
    with pytest.raises(CompanyBankValidationError):
        bundle = parse_research_bundle(bundle_dir / "bundle.json")
        validate_research_bundle(bundle, bundle_dir)


def test_long_quote(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    long_quote = " ".join(str(i) for i in range(26))
    (bundle_dir / "sources" / "product.txt").write_text(long_quote, encoding="utf-8")
    _rewrite(bundle_dir, lambda d: d["facts"][0].update(quote=long_quote))
    _rewrite(bundle_dir, lambda d: d["sources"][0].update(content_sha256="..."))
    
    # Needs to match hash, so I'll just re-hash
    import hashlib
    h = hashlib.sha256(long_quote.encode("utf-8")).hexdigest()
    _rewrite(bundle_dir, lambda d: d["sources"][0].update(content_sha256=h))
    
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="words"):
        validate_research_bundle(bundle, bundle_dir)


def test_ip_literal_host(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["sources"][0].update(url="https://127.0.0.1/product"))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="IP literal"):
        validate_research_bundle(bundle, bundle_dir)


def test_url_userinfo(tmp_path):
    bundle_dir = _copy_fixture(tmp_path)
    _rewrite(bundle_dir, lambda d: d["sources"][0].update(url="https://user:pass@acme.example/product"))
    bundle = parse_research_bundle(bundle_dir / "bundle.json")
    with pytest.raises(CompanyBankValidationError, match="credentials"):
        validate_research_bundle(bundle, bundle_dir)
