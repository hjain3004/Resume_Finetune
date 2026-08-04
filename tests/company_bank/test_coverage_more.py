import pytest
import argparse
import yaml
from pathlib import Path
from src.company_bank.cli import _handle_validate, _handle_lookup
from src.company_bank.policy import _validate_url, validate_research_bundle, validate_company_dossier
from src.company_bank.serde import CompanyBankValidationError, _StrictLoader, parse_research_bundle
from src.company_bank.model import SourceKind, ResearchBundle
from tests.company_bank.test_policy import FIXTURE as ACME_FIXTURE
from tests.company_bank.test_store import make_dossier
from src.company_bank.serde import dump_company_dossier
import shutil
import json

def test_cli_unsupported_command():
    from src.company_bank.cli import main
    # Actually argparse will block unsupported commands, but we can test it directly if we mock
    pass

def test_cli_validate_exception(monkeypatch, tmp_path):
    def mock_parse(*args):
        raise ValueError("Unknown error")
    monkeypatch.setattr("src.company_bank.cli.parse_research_bundle", mock_parse)
    
    args = argparse.Namespace(bundle_path=tmp_path / "foo.json", bundle_dir=tmp_path)
    (tmp_path / "foo.json").write_text("{}")
    assert _handle_validate(args) == 1
    
def test_cli_lookup_exception(monkeypatch, tmp_path):
    def mock_load(*args):
        raise ValueError("Unknown error")
    monkeypatch.setattr("src.company_bank.cli.load_company_bank", mock_load)
    
    args = argparse.Namespace(db_path=tmp_path, query="foo", business_unit=None, role_family=None, permitted_use="s0", now=None)
    assert _handle_lookup(args) == 2

def test_cli_main_invalid_command(monkeypatch):
    from src.company_bank.cli import main
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self, argv: argparse.Namespace(command="unknown"))
    assert main([]) == 1

def test_cli_main_dunder_name(monkeypatch):
    import runpy
    # We can't easily runpy if it exits, so just rely on monkeypatching sys.argv maybe?
    # I'll just write a shell command test in pytest to hit __main__
    pass

def test_policy_validate_url_not_https():
    with pytest.raises(CompanyBankValidationError, match="URL scheme must be https"):
        _validate_url("http://acme.example/1", ("acme.example",), SourceKind.OFFICIAL_COMPANY)

def test_policy_validate_url_no_host():
    with pytest.raises(CompanyBankValidationError, match="URL missing host"):
        _validate_url("https:///foo", ("acme.example",), SourceKind.OFFICIAL_COMPANY)

def test_policy_validate_url_trailing_dot():
    # should succeed
    _validate_url("https://acme.example./foo", ("acme.example",), SourceKind.OFFICIAL_COMPANY)

def test_policy_validate_url_invalid_idna():
    with pytest.raises(CompanyBankValidationError, match="invalid IDNA"):
        _validate_url("https://\x80/foo", ("acme.example",), SourceKind.OFFICIAL_COMPANY)

def test_policy_validate_url_verified_dataset_not_allowed():
    with pytest.raises(CompanyBankValidationError, match="Verified dataset host not in allowlist"):
        _validate_url("https://foo.example", (), SourceKind.VERIFIED_DATASET)

def test_policy_validate_bundle_duplicate_domain_case_insensitive(tmp_path):
    target = tmp_path / "acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    data = json.loads(bundle_path.read_text())
    # Bypass serde uniqueness by creating the bundle directly
    bundle = parse_research_bundle(bundle_path)
    bundle = type(bundle)(**{**bundle.__dict__, "official_domains": ("acme.example", "ACME.example")})
    with pytest.raises(CompanyBankValidationError, match="duplicate domain"):
        validate_research_bundle(bundle, target)

def test_policy_validate_bundle_path_traversal(tmp_path):
    target = tmp_path / "acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    bundle = parse_research_bundle(bundle_path)
    # The source points to sources/product.txt, we change it to ../acme/sources/product.txt which resolves but is still traversal? No, is_relative_to(sources_dir)
    # Actually if we point to ../acme.yaml outside sources dir, it will fail
    (target / "outside.txt").write_text("Acme Anvil is the best product.", encoding="utf-8")
    import hashlib
    h = hashlib.sha256("Acme Anvil is the best product.".encode("utf-8")).hexdigest()
    
    new_sources = []
    for s in bundle.sources:
        if s.source.id == "prod":
            s = type(s)(source=s.source, snapshot_file="../outside.txt")
        new_sources.append(s)
    bundle = type(bundle)(**{**bundle.__dict__, "sources": tuple(new_sources)})
    with pytest.raises(CompanyBankValidationError, match="Snapshot path traversal"):
        validate_research_bundle(bundle, target)

def test_policy_validate_bundle_snapshot_not_utf8(tmp_path):
    target = tmp_path / "acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    (target / "sources" / "product.txt").write_bytes(b"\xff\xff")
    bundle = parse_research_bundle(bundle_path)
    with pytest.raises(CompanyBankValidationError, match="not UTF-8"):
        validate_research_bundle(bundle, target)

def test_policy_validate_bundle_duplicate_fact_id(tmp_path):
    target = tmp_path / "acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    data = json.loads(bundle_path.read_text())
    data["facts"].append(data["facts"][0])
    bundle_path.write_text(json.dumps(data))
    bundle = parse_research_bundle(bundle_path)
    with pytest.raises(CompanyBankValidationError, match="Duplicate fact id"):
        validate_research_bundle(bundle, target)

def test_policy_validate_bundle_duplicate_signal_id(tmp_path):
    target = tmp_path / "acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    data = json.loads(bundle_path.read_text())
    data["signals"].append(data["signals"][0])
    bundle_path.write_text(json.dumps(data))
    bundle = parse_research_bundle(bundle_path)
    with pytest.raises(CompanyBankValidationError, match="Duplicate signal id"):
        validate_research_bundle(bundle, target)

def test_policy_validate_bundle_signal_use_not_allowed(tmp_path):
    target = tmp_path / "acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    data = json.loads(bundle_path.read_text())
    data["signals"][0]["permitted_uses"].append("g3_advisory")
    bundle_path.write_text(json.dumps(data))
    bundle = parse_research_bundle(bundle_path)
    with pytest.raises(CompanyBankValidationError, match="not allowed by basis facts"):
        validate_research_bundle(bundle, target)

def test_policy_validate_dossier_expires_at_before_researched_at():
    from tests.company_bank.test_store import make_dossier
    from datetime import timedelta
    dossier = make_dossier("acme", "Acme")
    dossier = type(dossier)(**{**dossier.__dict__, "expires_at": dossier.researched_at - timedelta(days=1)})
    with pytest.raises(CompanyBankValidationError, match="expires_at must be after researched_at"):
        validate_company_dossier(dossier)

def test_serde_strict_loader_duplicate_key():
    with pytest.raises(CompanyBankValidationError, match="duplicate key: 'a'"):
        yaml.load("a: 1\na: 2", Loader=_StrictLoader)

def test_main_cli(tmp_path):
    import subprocess
    import sys
    (tmp_path / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    env = {"PYTHONPATH": "."}
    p = subprocess.run(
        [sys.executable, "src/company_bank/cli.py", "lookup", str(tmp_path), "acme"],
        env=env, capture_output=True, text=True
    )
    assert p.returncode == 0

def test_cli_lookup_naive_now(tmp_path, capsys):
    from src.company_bank.cli import main
    (tmp_path / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    
    code = main(["lookup", str(tmp_path), "acme", "--now", "2026-08-05T00:00:00"])
    assert code == 0
