import json
from pathlib import Path
from unittest.mock import patch
import pytest

from src.company_bank.verify import (
    FetchResult, SourceVerdict, classify_source, quote_coverage, normalize_for_match
)
from scripts.company_bank import _handle_lint_snapshots, _handle_verify_sources
import argparse

def test_normalization():
    assert normalize_for_match("hello   \n world") == "hello world"
    assert normalize_for_match("don't") != normalize_for_match("don’t")

def test_classify_source():
    res, rsn, found = classify_source(FetchResult("u", 200, "foo bar baz", None), ["foo bar"], min_text_chars=1)
    assert res == SourceVerdict.VERIFIED
    
    res, rsn, found = classify_source(FetchResult("u", 200, "a" * 600, None), ["foo"], min_text_chars=1)
    assert res == SourceVerdict.FAILED
    
    res, rsn, found = classify_source(FetchResult("u", 404, "", None), ["foo"])
    assert res == SourceVerdict.FAILED
    
    res, rsn, found = classify_source(FetchResult("u", 403, "", None), ["foo"])
    assert res == SourceVerdict.INCONCLUSIVE
    
    res, rsn, found = classify_source(FetchResult("u", 200, "short", None), ["foo"], min_text_chars=50)
    assert res == SourceVerdict.INCONCLUSIVE
    
    res, rsn, found = classify_source(FetchResult("u", None, "", "timeout"), ["foo"])
    assert res == SourceVerdict.INCONCLUSIVE
    
    res, rsn, found = classify_source(FetchResult("u", 301, "", None), ["foo"])
    assert res == SourceVerdict.INCONCLUSIVE
    
    res, rsn, found = classify_source(FetchResult("u", 200, "foo " * 150, None), ["foo", "missing"])
    assert res == SourceVerdict.FAILED
    assert found == 1
    
    res, rsn, found = classify_source(FetchResult("u", 200, "", None), [])
    assert res == SourceVerdict.INCONCLUSIVE

def test_lint_bundle():
    assert quote_coverage("a" * 10, ["a" * 6]) == 0.6
    assert quote_coverage("a" * 10, ["a" * 3]) == 0.3
    assert quote_coverage("a" * 10, ["a" * 6, "a" * 6]) == 0.6
    assert quote_coverage("", ["a"]) == 1.0

def test_cli(tmp_path):
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    
    bundle_data = {
        "schema_version": "0.1.0",
        "company_id": "test",
        "display_name": "Test",
        "aliases": [],
        "official_domains": ["test.com"],
        "researched_at": "2026-08-01T12:00:00Z",
        "sources": [
            {
                "id": "s_1",
                "url": "https://test.com/a",
                "title": "A",
                "source_kind": "official_company",
                "scope": {"kind": "company", "name": "Test"},
                "retrieved_at": "2026-08-01T12:00:00Z",
                "content_sha256": "1f12a65ec33e4e9408888defc122b2d25731af4ca14996414ed38d4dcadce19e",
                "snapshot_file": "sources/s_1.txt"
            }
        ],
        "facts": [
            {
                "id": "f_1",
                "kind": "product",
                "scope": {"kind": "company", "name": "Test"},
                "claim": "C",
                "quote": "Q",
                "source_id": "s_1"
            }
        ],
        "signals": [
            {
                "id": "sig_1",
                "text": "S",
                "basis_fact_ids": ["f_1"],
                "permitted_uses": ["s0"]
            }
        ]
    }
    
    (bundle_dir / "bundle.json").write_text(json.dumps(bundle_data))
    (bundle_dir / "sources").mkdir()
    (bundle_dir / "sources" / "s_1.txt").write_text("Q" * 100)
    
    def hash_dir(d: Path):
        import hashlib
        h = hashlib.sha256()
        for p in sorted(d.rglob("*")):
            if p.is_file():
                h.update(p.read_bytes())
        return h.hexdigest()
        
    h_before = hash_dir(bundle_dir)
    
    args_lint = argparse.Namespace(inbox=None, bundle_path=bundle_dir / "bundle.json", strict=False)
    assert _handle_lint_snapshots(args_lint) == 0
    assert hash_dir(bundle_dir) == h_before
    
    # Mock RateLimitedFetcher to avoid real network
    with patch("scripts.company_bank.RateLimitedFetcher") as mock_fetcher_class:
        mock_instance = mock_fetcher_class.return_value
        mock_instance.fetch.return_value = FetchResult("https://test.com/a", 403, "", None)
        
        args_verify = argparse.Namespace(inbox=None, bundle_path=bundle_dir / "bundle.json", json_out=None, strict=False, delay=2.0)
        assert _handle_verify_sources(args_verify) == 0
        assert hash_dir(bundle_dir) == h_before
        
        args_verify_strict = argparse.Namespace(inbox=None, bundle_path=bundle_dir / "bundle.json", json_out=None, strict=True, delay=2.0)
        assert _handle_verify_sources(args_verify_strict) == 2
        assert hash_dir(bundle_dir) == h_before
