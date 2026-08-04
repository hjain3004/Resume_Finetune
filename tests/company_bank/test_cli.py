import pytest
import shutil
from pathlib import Path

from src.company_bank.cli import main
from tests.company_bank.test_policy import FIXTURE as ACME_FIXTURE
from tests.company_bank.test_store import make_dossier
from src.company_bank.serde import dump_company_dossier


def test_cli_validate_success(tmp_path, capsys):
    target = tmp_path / "valid_acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    
    code = main(["validate-bundle", str(bundle_path), str(target)])
    assert code == 0
    out, err = capsys.readouterr()
    assert "Valid bundle for acme" in out


def test_cli_validate_unreadable(tmp_path, capsys):
    code = main(["validate-bundle", str(tmp_path / "nonexistent.json"), str(tmp_path)])
    assert code == 2
    out, err = capsys.readouterr()
    assert "UNREADABLE" in err


def test_cli_validate_invalid(tmp_path, capsys):
    target = tmp_path / "valid_acme"
    shutil.copytree(ACME_FIXTURE, target)
    bundle_path = target / "bundle.json"
    
    text = bundle_path.read_text(encoding="utf-8")
    bundle_path.write_text(text.replace('"0.1.0"', '"9.9.9"'), encoding="utf-8")
    
    code = main(["validate-bundle", str(bundle_path), str(target)])
    assert code == 1
    out, err = capsys.readouterr()
    assert "INVALID" in err


def test_cli_lookup_success(tmp_path, capsys):
    (tmp_path / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    
    code = main(["lookup", str(tmp_path), "acme", "--now", "2026-08-05T00:00:00Z"])
    assert code == 0
    out, err = capsys.readouterr()
    assert "FRESH: acme" in out


def test_cli_lookup_missing(tmp_path, capsys):
    (tmp_path / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    
    code = main(["lookup", str(tmp_path), "missing", "--now", "2026-08-05T00:00:00Z"])
    assert code == 3
    out, err = capsys.readouterr()
    assert "MISSING" in err


def test_cli_lookup_expired(tmp_path, capsys):
    (tmp_path / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    
    # Expires in 90 days from 2026-08-04, so 2026-12-05 is well past expiry
    code = main(["lookup", str(tmp_path), "acme", "--now", "2026-12-05T00:00:00Z"])
    assert code == 3
    out, err = capsys.readouterr()
    assert "EXPIRED" in err


def test_cli_lookup_invalid_db(tmp_path, capsys):
    (tmp_path / "acme.yaml").write_text("invalid yaml", encoding="utf-8")
    
    code = main(["lookup", str(tmp_path), "acme"])
    assert code == 1
    out, err = capsys.readouterr()
    assert "INVALID" in err


def test_cli_lookup_unreadable_db(tmp_path, capsys, monkeypatch):
    def mock_load(*args, **kwargs):
        raise OSError("Permission denied")
    monkeypatch.setattr("src.company_bank.cli.load_company_bank", mock_load)
    
    code = main(["lookup", str(tmp_path), "acme"])
    assert code == 2
    out, err = capsys.readouterr()
    assert "UNREADABLE" in err


def test_cli_lookup_no_now_arg(tmp_path, capsys):
    (tmp_path / "acme.yaml").write_text(dump_company_dossier(make_dossier("acme", "Acme")), encoding="utf-8")
    
    # Should use current time, so it's probably expired (because make_dossier researches in 2026, and today is 2026 or later, but actually make_dossier uses 2026-08-04). We just want to ensure it doesn't crash.
    code = main(["lookup", str(tmp_path), "acme"])
    assert code in (0, 3)
