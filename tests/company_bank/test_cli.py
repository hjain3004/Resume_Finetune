import json
import shutil
from pathlib import Path

from scripts.company_bank import main
from src.company_bank.serde import dump_company_dossier
from tests.company_bank.test_policy import FIXTURE as ACME_FIXTURE
from tests.company_bank.test_store import make_dossier
from tests.company_bank.test_importer import setup_inbox


def test_cli_validate_bundle_success(tmp_path, capsys):
    target = tmp_path / "valid_acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    
    code = main(["validate-bundle", str(bundle_path), str(target)])
    assert code == 0
    out, err = capsys.readouterr()
    assert "Valid bundle for acme" in out


def test_cli_validate_bundle_unreadable(tmp_path, capsys):
    code = main(["validate-bundle", str(tmp_path / "nonexistent.json"), str(tmp_path)])
    assert code == 2
    out, err = capsys.readouterr()
    assert "UNREADABLE" in err


def test_cli_validate_bundle_invalid(tmp_path, capsys):
    target = tmp_path / "valid_acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    
    text = bundle_path.read_text(encoding="utf-8")
    bundle_path.write_text(text.replace('"0.1.0"', '"9.9.9"'), encoding="utf-8")
    
    code = main(["validate-bundle", str(bundle_path), str(target)])
    assert code == 1
    out, err = capsys.readouterr()
    assert "INVALID" in err


def test_cli_validate_bundle_exception(monkeypatch, tmp_path, capsys):
    def mock_parse(*args):
        raise ValueError("Unknown error")
    monkeypatch.setattr("scripts.company_bank.parse_research_bundle", mock_parse)
    
    (tmp_path / "foo.json").write_text("{}")
    code = main(["validate-bundle", str(tmp_path / "foo.json"), str(tmp_path)])
    assert code == 2


def test_cli_validate_corpus_success(tmp_path, capsys):
    inbox, seeds, now = setup_inbox(tmp_path)
    code = main([
        "validate-corpus",
        "--inbox", str(inbox),
        "--seeds", str(seeds),
        "--now", "2026-08-04T12:00:00Z"
    ])
    assert code == 0
    out, err = capsys.readouterr()
    assert "Valid corpus with 3 companies" in out


def test_cli_validate_corpus_invalid(tmp_path, capsys):
    inbox, seeds, now = setup_inbox(tmp_path)
    shutil.rmtree(inbox / "zeta")
    code = main([
        "validate-corpus",
        "--inbox", str(inbox),
        "--seeds", str(seeds),
        "--now", "2026-08-04T12:00:00Z"
    ])
    assert code == 1
    out, err = capsys.readouterr()
    assert "INVALID" in err


def test_cli_validate_corpus_exception(monkeypatch, tmp_path, capsys):
    def mock_val(*args, **kwargs):
        raise ValueError("Unknown error")
    monkeypatch.setattr("scripts.company_bank.validate_corpus", mock_val)
    code = main(["validate-corpus", "--inbox", str(tmp_path), "--seeds", str(tmp_path), "--now", "2026-08-04T12:00:00Z"])
    assert code == 2


def test_cli_import_corpus_success(tmp_path, capsys):
    inbox, seeds, now = setup_inbox(tmp_path)
    bank_root = tmp_path / "bank"
    bank_root.mkdir()
    code = main([
        "import-corpus",
        "--inbox", str(inbox),
        "--bank-root", str(bank_root),
        "--seeds", str(seeds),
        "--now", "2026-08-04T12:00:00Z"
    ])
    assert code == 0
    out, err = capsys.readouterr()
    assert "Import created: 3 companies" in out


def test_cli_import_corpus_invalid(tmp_path, capsys):
    inbox, seeds, now = setup_inbox(tmp_path)
    bank_root = tmp_path / "bank"
    bank_root.mkdir()
    shutil.rmtree(inbox / "zeta")
    code = main([
        "import-corpus",
        "--inbox", str(inbox),
        "--bank-root", str(bank_root),
        "--seeds", str(seeds),
        "--now", "2026-08-04T12:00:00Z"
    ])
    assert code == 1


def test_cli_import_corpus_exception(monkeypatch, tmp_path, capsys):
    def mock_imp(*args, **kwargs):
        raise ValueError("Unknown error")
    monkeypatch.setattr("scripts.company_bank.import_corpus", mock_imp)
    code = main(["import-corpus", "--inbox", str(tmp_path), "--bank-root", str(tmp_path), "--seeds", str(tmp_path), "--now", "2026-08-04T12:00:00Z"])
    assert code == 2


def test_cli_lookup_success(tmp_path, capsys):
    companies_dir = tmp_path / "companies"
    companies_dir.mkdir()
    (companies_dir / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    
    code = main(["lookup", "acme", "--bank-root", str(tmp_path), "--now", "2026-08-05T00:00:00Z"])
    assert code == 0
    out, err = capsys.readouterr()
    assert "FRESH: acme" in out


def test_cli_lookup_missing(tmp_path, capsys):
    companies_dir = tmp_path / "companies"
    companies_dir.mkdir()
    (companies_dir / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    
    code = main(["lookup", "missing", "--bank-root", str(tmp_path), "--now", "2026-08-05T00:00:00Z"])
    assert code == 3
    out, err = capsys.readouterr()
    assert "MISSING" in err


def test_cli_lookup_expired(tmp_path, capsys):
    companies_dir = tmp_path / "companies"
    companies_dir.mkdir()
    (companies_dir / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    
    # Expires in 90 days from 2026-08-04
    code = main(["lookup", "acme", "--bank-root", str(tmp_path), "--now", "2026-12-05T00:00:00Z"])
    assert code == 3
    out, err = capsys.readouterr()
    assert "EXPIRED" in err


def test_cli_lookup_invalid_db(tmp_path, capsys):
    companies_dir = tmp_path / "companies"
    companies_dir.mkdir()
    (companies_dir / "acme.yaml").write_text("invalid yaml", encoding="utf-8")
    
    code = main(["lookup", "acme", "--bank-root", str(tmp_path)])
    assert code == 1
    out, err = capsys.readouterr()
    assert "INVALID" in err


def test_cli_lookup_unreadable_db(tmp_path, capsys, monkeypatch):
    def mock_load(*args, **kwargs):
        raise OSError("Permission denied")
    monkeypatch.setattr("scripts.company_bank.load_company_bank", mock_load)
    
    code = main(["lookup", "acme", "--bank-root", str(tmp_path)])
    assert code == 2
    out, err = capsys.readouterr()
    assert "UNREADABLE" in err


def test_cli_lookup_invalid_now(tmp_path, capsys):
    companies_dir = tmp_path / "companies"
    companies_dir.mkdir()
    (companies_dir / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    code = main(["lookup", "acme", "--bank-root", str(tmp_path), "--now", "invalid"])
    assert code == 1


def test_cli_lookup_no_now_arg(tmp_path, capsys):
    companies_dir = tmp_path / "companies"
    companies_dir.mkdir()
    (companies_dir / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    
    code = main(["lookup", "acme", "--bank-root", str(tmp_path)])
    assert code in (0, 3)


def test_cli_unsupported_command(monkeypatch):
    import argparse
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda self, argv: argparse.Namespace(command="unknown"))
    assert main([]) == 1
