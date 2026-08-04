import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.company_bank.importer import (
    ImportStatus,
    import_corpus,
    validate_corpus,
)
from src.company_bank.serde import CompanyBankValidationError
from tests.company_bank.test_policy import FIXTURE as ACME_FIXTURE


def setup_inbox(tmp_path: Path) -> tuple[Path, Path, Path]:
    now = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    seeds = tmp_path / "seeds.yaml"
    seeds.write_text("""schema_version: '0.1.0'\ncompanies:\n  acme: Acme Corp\n  zeta: Zeta Inc\n  beta: Beta LLC\n""")

    def copy_bundle(company_id, display_name):
        target = inbox / company_id
        shutil.copytree(ACME_FIXTURE, target)
        bundle_path = target / "bundle.json"
        data = json.loads(bundle_path.read_text())
        data["company_id"] = company_id
        data["display_name"] = display_name
        data["aliases"] = []
        bundle_path.write_text(json.dumps(data))

    copy_bundle("acme", "Acme Corp")
    copy_bundle("zeta", "Zeta Inc")
    copy_bundle("beta", "Beta LLC")

    return inbox, seeds, now


def test_validate_missing_seed_id(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    shutil.rmtree(inbox / "zeta")
    with pytest.raises(CompanyBankValidationError, match="missing bundle for seed company: zeta"):
        validate_corpus(inbox, seeds, now=now)


def test_validate_unexpected_id(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    target = inbox / "extra"
    shutil.copytree(inbox / "acme", target)
    with pytest.raises(CompanyBankValidationError, match="unexpected company directory: extra"):
        validate_corpus(inbox, seeds, now=now)


def test_validate_duplicate_bundle_company_id(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    # Zeta directory but bundle has company_id "acme"
    bundle_path = inbox / "zeta" / "bundle.json"
    data = json.loads(bundle_path.read_text())
    data["company_id"] = "acme"
    bundle_path.write_text(json.dumps(data))
    with pytest.raises(CompanyBankValidationError, match="does not match directory"):
        validate_corpus(inbox, seeds, now=now)


def test_validate_display_name_disagreement(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    bundle_path = inbox / "acme" / "bundle.json"
    data = json.loads(bundle_path.read_text())
    data["display_name"] = "Acme INCORPORATED"
    bundle_path.write_text(json.dumps(data))
    with pytest.raises(CompanyBankValidationError, match="display_name disagreement"):
        validate_corpus(inbox, seeds, now=now)


def test_validate_future_researched_at(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    bundle_path = inbox / "acme" / "bundle.json"
    data = json.loads(bundle_path.read_text())
    data["researched_at"] = "2026-08-05T00:00:00Z"
    bundle_path.write_text(json.dumps(data))
    with pytest.raises(CompanyBankValidationError, match="future"):
        validate_corpus(inbox, seeds, now=now)


def test_validate_expired_bundle(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    bundle_path = inbox / "acme" / "bundle.json"
    data = json.loads(bundle_path.read_text())
    # researched_at is 2026-08-04, expires in 90 days, so if now is 91 days later it's expired
    data["researched_at"] = "2026-01-01T00:00:00Z"
    for s in data["sources"]:
        s["retrieved_at"] = "2026-01-01T00:00:00Z"
    bundle_path.write_text(json.dumps(data))
    with pytest.raises(CompanyBankValidationError, match="expired"):
        validate_corpus(inbox, seeds, now=now)


def test_validate_not_a_directory(tmp_path):
    _, seeds, now = setup_inbox(tmp_path)
    with pytest.raises(CompanyBankValidationError, match="not a directory"):
        validate_corpus(tmp_path / "foo", seeds, now=now)


def test_validate_missing_bundle_json(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    (inbox / "acme" / "bundle.json").unlink()
    with pytest.raises(CompanyBankValidationError, match="bundle.json missing"):
        validate_corpus(inbox, seeds, now=now)


def _snapshot_bank(bank_root: Path) -> dict[str, bytes]:
    companies = bank_root / "companies"
    if not companies.exists():
        return {}
    return {p.name: p.read_bytes() for p in companies.iterdir() if p.is_file()}


def test_import_corrupt_quote(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    bank_root = tmp_path / "bank"
    bank_root.mkdir()

    # Corrupt quote
    bundle_path = inbox / "acme" / "bundle.json"
    data = json.loads(bundle_path.read_text())
    data["facts"][0]["quote"] = "corrupted"
    bundle_path.write_text(json.dumps(data))

    with pytest.raises(CompanyBankValidationError, match="quote not found"):
        import_corpus(inbox, bank_root, seeds, now=now)
    assert not (bank_root / "companies").exists()
    assert not any(p.name.startswith(".companies-stage-") for p in bank_root.iterdir())


def test_import_valid_creation(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    bank_root = tmp_path / "bank"
    bank_root.mkdir()

    res = import_corpus(inbox, bank_root, seeds, now=now)
    assert res.status == ImportStatus.CREATED
    assert res.company_count == 3

    files = [p.name for p in (bank_root / "companies").iterdir()]
    assert sorted(files) == ["acme.yaml", "beta.yaml", "zeta.yaml"]
    assert not any(p.name.startswith(".companies-stage-") for p in bank_root.iterdir())


def test_import_idempotent_unchanged(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    bank_root = tmp_path / "bank"
    bank_root.mkdir()

    import_corpus(inbox, bank_root, seeds, now=now)
    snap1 = _snapshot_bank(bank_root)

    res = import_corpus(inbox, bank_root, seeds, now=now)
    assert res.status == ImportStatus.UNCHANGED

    snap2 = _snapshot_bank(bank_root)
    assert snap1 == snap2
    assert not any(p.name.startswith(".companies-stage-") for p in bank_root.iterdir())


def test_import_refuse_modified(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    bank_root = tmp_path / "bank"
    bank_root.mkdir()

    import_corpus(inbox, bank_root, seeds, now=now)
    snap1 = _snapshot_bank(bank_root)

    # modify bundle
    bundle_path = inbox / "acme" / "bundle.json"
    data = json.loads(bundle_path.read_text())
    data["aliases"].append("Acme Co")
    bundle_path.write_text(json.dumps(data))

    with pytest.raises(CompanyBankValidationError, match="overwrite"):
        import_corpus(inbox, bank_root, seeds, now=now)

    snap2 = _snapshot_bank(bank_root)
    assert snap1 == snap2
    assert not any(p.name.startswith(".companies-stage-") for p in bank_root.iterdir())


def test_import_refuse_extra_entry(tmp_path):
    inbox, seeds, now = setup_inbox(tmp_path)
    bank_root = tmp_path / "bank"
    bank_root.mkdir()

    import_corpus(inbox, bank_root, seeds, now=now)

    extra_dir = bank_root / "companies" / "extra_dir"
    extra_dir.mkdir()

    with pytest.raises(CompanyBankValidationError, match="overwrite"):
        import_corpus(inbox, bank_root, seeds, now=now)


def test_import_cleanup_on_exception(tmp_path, monkeypatch):
    inbox, seeds, now = setup_inbox(tmp_path)
    bank_root = tmp_path / "bank"
    bank_root.mkdir()

    def mock_load(*args, **kwargs):
        raise CompanyBankValidationError("simulated error")

    monkeypatch.setattr("src.company_bank.importer._load_company_directory", mock_load)

    with pytest.raises(CompanyBankValidationError, match="simulated"):
        import_corpus(inbox, bank_root, seeds, now=now)

    assert not any(p.name.startswith(".companies-stage-") for p in bank_root.iterdir())


def test_import_invalid_staged_canonical(tmp_path, monkeypatch):
    inbox, seeds, now = setup_inbox(tmp_path)
    bank_root = tmp_path / "bank"
    bank_root.mkdir()

    import src.company_bank.importer as importer_mod

    original_dump = importer_mod.dump_company_dossier

    def mock_dump(dossier):
        yaml_str = original_dump(dossier)
        # Monkeypatch the YAML to make it semantically invalid (expiry 365 days instead of 90)
        import re
        # Find expires_at and replace it with a string far in the future
        yaml_str = re.sub(r"expires_at:.*", "expires_at: '2099-01-01T00:00:00Z'", yaml_str)
        return yaml_str

    monkeypatch.setattr(importer_mod, "dump_company_dossier", mock_dump)

    with pytest.raises(CompanyBankValidationError, match="expires_at must be exactly"):
        import_corpus(inbox, bank_root, seeds, now=now)

    assert not (bank_root / "companies").exists()
    assert not any(p.name.startswith(".companies-stage-") for p in bank_root.iterdir())
