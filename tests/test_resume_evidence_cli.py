from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.resume_evidence import main
from tests.resume_evidence.test_importer import _base_corpus


def test_validate_bundle_success(tmp_path, capsys):
    root, _ = _base_corpus(tmp_path)
    code = main(["validate-bundle", str(root / "outcomes" / "outcome_a")])
    assert code == 0
    assert "Valid outcome bundle" in capsys.readouterr().out


def test_validate_bundle_invalid_returns_one(tmp_path, capsys):
    root, _ = _base_corpus(tmp_path)
    bundle = root / "outcomes" / "outcome_a" / "bundle.yaml"
    payload = yaml.safe_load(bundle.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    bundle.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    assert main(["validate-bundle", str(bundle.parent)]) == 1
    assert "INVALID:" in capsys.readouterr().err


def test_validate_bundle_unreadable_returns_two(tmp_path, capsys):
    assert main(["validate-bundle", str(tmp_path / "missing")]) == 2
    assert "ERROR:" in capsys.readouterr().err


def test_validate_corpus_success(tmp_path, capsys):
    root, manifest = _base_corpus(tmp_path)
    code = main(
        ["validate-corpus", "--inbox", str(root), "--manifest", str(manifest)]
    )
    assert code == 0
    assert "2 outcomes" in capsys.readouterr().out


def test_report_writes_json_last_as_commit_marker(tmp_path, capsys):
    root, manifest = _base_corpus(tmp_path)
    output = tmp_path / "report"
    args = [
        "report",
        "--inbox",
        str(root),
        "--manifest",
        str(manifest),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    assert (output / "report.md").is_file()
    payload = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert payload["outcome_counts"]["total"] == 2
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    assert main(args) == 0
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
    assert "Report SHA-256" in capsys.readouterr().out


def test_report_conflict_returns_one_without_mutation(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    output = tmp_path / "report"
    output.mkdir()
    marker = output / "user.txt"
    marker.write_text("preserve", encoding="utf-8")
    code = main(
        [
            "report",
            "--inbox",
            str(root),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ]
    )
    assert code == 1
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert sorted(path.name for path in output.iterdir()) == ["user.txt"]


def test_import_requires_matching_64_hex_approval_hash(tmp_path, capsys):
    root, manifest = _base_corpus(tmp_path)
    code = main(
        [
            "import-corpus",
            "--inbox",
            str(root),
            "--manifest",
            str(manifest),
            "--bank-root",
            str(tmp_path / "bank"),
            "--approved-report-sha256",
            "not-a-hash",
            "--approved-at",
            "2026-08-30T12:00:00Z",
        ]
    )
    assert code == 1
    assert "INVALID:" in capsys.readouterr().err


def test_lookup_missing_returns_three(tmp_path, capsys):
    code = main(["lookup", "--bank-root", str(tmp_path / "missing")])
    assert code == 3
    assert "No matching outcomes" in capsys.readouterr().err


def test_stats_empty_bank_succeeds(tmp_path, capsys):
    assert main(["stats", "--bank-root", str(tmp_path / "missing")]) == 0
    assert "outcomes=0" in capsys.readouterr().out
