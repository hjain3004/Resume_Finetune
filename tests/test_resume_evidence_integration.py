from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

from src.resume_evidence.importer import ImportStatus, import_corpus, validate_corpus
from src.resume_evidence.report import build_report, report_sha256
from tests.resume_evidence.test_importer import _base_corpus

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "resume_evidence"


def _trees():
    for path in sorted(PACKAGE.glob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_resume_evidence_package_imports_no_network_database_or_tailoring_modules():
    forbidden = {
        "requests",
        "crawl4ai",
        "playwright",
        "firecrawl",
        "sqlite3",
        "src.db",
        "src.tailor",
    }
    found = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if any(name == item or name.startswith(item + ".") for item in forbidden):
                    found.append((path.name, name))
    assert found == []


def test_script_exposes_no_fetch_or_scrape_command():
    tree = ast.parse(
        (ROOT / "scripts" / "resume_evidence.py").read_text(encoding="utf-8")
    )
    commands = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_parser"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert "fetch" not in commands
    assert "scrape" not in commands
    assert commands == {
        "validate-bundle",
        "validate-corpus",
        "report",
        "import-corpus",
        "stats",
        "lookup",
    }


def test_synthetic_corpus_round_trip_is_atomic_and_idempotent(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    validated = validate_corpus(root, manifest)
    digest = report_sha256(build_report(validated))
    kwargs = {
        "approved_report_sha256": digest,
        "approved_at": datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc),
    }
    bank_root = tmp_path / "bank"
    first = import_corpus(root, manifest, bank_root, **kwargs)
    before = {
        str(path.relative_to(bank_root)): path.read_bytes()
        for path in sorted(bank_root.rglob("*"))
        if path.is_file()
    }
    second = import_corpus(root, manifest, bank_root, **kwargs)
    after = {
        str(path.relative_to(bank_root)): path.read_bytes()
        for path in sorted(bank_root.rglob("*"))
        if path.is_file()
    }
    assert first.status is ImportStatus.CREATED
    assert second.status is ImportStatus.UNCHANGED
    assert after == before


def test_raw_snapshot_text_never_appears_in_canonical_yaml(tmp_path):
    root, manifest = _base_corpus(tmp_path)
    validated = validate_corpus(root, manifest)
    digest = report_sha256(build_report(validated))
    bank_root = tmp_path / "bank"
    import_corpus(
        root,
        manifest,
        bank_root,
        approved_report_sha256=digest,
        approved_at=datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc),
    )
    canonical = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((bank_root / "current").rglob("*.yaml"))
    )
    raw = (root / "outcomes" / "outcome_a" / "sources" / "resume.md").read_text(
        encoding="utf-8"
    )
    assert raw not in canonical
    assert "queue processor with retries and metrics" not in canonical
    assert "snapshot_file" not in canonical


def test_no_sql_strings_exist_in_resume_evidence_package():
    sql_tokens = ("select ", "insert ", "update ", "delete ", "create table", "alter table")
    found = []
    for path, tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                folded = " ".join(node.value.casefold().split())
                if any(token in folded for token in sql_tokens):
                    found.append((path.name, node.lineno))
    assert found == []


def test_authoritative_docs_record_offline_m8q_boundary():
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "M8Q-0A" in architecture
    assert "50 validated Huntr" in roadmap
    assert "M8Q-0B" in roadmap
