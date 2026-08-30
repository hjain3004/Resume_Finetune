import json
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.research_resume_evidence import (
    ResearchTarget,
    load_source_manifest,
    run_scrape_batch,
    validate_research_target,
)


def test_research_operator_contract_exists():
    assert ResearchTarget is not None
    assert callable(load_source_manifest)
    assert callable(validate_research_target)
    assert callable(run_scrape_batch)


def test_only_https_huntr_resume_example_targets_are_allowed():
    validate_research_target(ResearchTarget("x", "https://huntr.co/resume-examples/x", "huntr", None))


@pytest.mark.parametrize("url", [
    "http://huntr.co/resume-examples/x",
    "https://linkedin.com/resume-examples/x",
    "https://example.com/resume-examples/x",
    "https://huntr.co/not-resumes/x",
    "https://huntr.co/resume-examples/x?token=secret",
    "https://huntr.co/resume-examples/x#fragment",
    "https://user:pass@huntr.co/resume-examples/x",
])
def test_rejected_targets_fail_before_runner(url):
    with pytest.raises(ValueError):
        validate_research_target(ResearchTarget("x", url, "huntr", None))


def _raw(markdown="## Synthetic"):
    return {"data": {"markdown": markdown, "links": ["https://huntr.co/resume-examples/other"]}}


def test_runner_arguments_are_allowlisted_and_spacing_is_enforced(tmp_path):
    targets = (ResearchTarget("a", "https://huntr.co/resume-examples/a", "huntr", None), ResearchTarget("b", "https://huntr.co/resume-examples/b", "huntr", None))
    calls = []
    waits = []
    def runner(argv):
        calls.append(argv)
        Path(argv[-1]).write_text(json.dumps(_raw()), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="")
    run_scrape_batch(targets, tmp_path, runner, waits.append, 5)
    assert waits == [2.0]
    forbidden = {"--profile", "--actions", "--proxy", "--cookie", "--api-key", "--enhanced-proxy"}
    assert all(not forbidden.intersection(call) for call in calls)
    assert all("--only-main-content" in call and "--redact-pii" in call for call in calls)


def test_nonzero_firecrawl_stops_without_retry(tmp_path):
    calls = []
    def runner(argv):
        calls.append(argv)
        return SimpleNamespace(returncode=7, stdout="", failure_kind="policy_rejection")
    with pytest.raises(ValueError):
        run_scrape_batch((ResearchTarget("a", "https://huntr.co/resume-examples/a", "huntr", None),), tmp_path, runner, lambda _: None, 5)
    assert len(calls) == 1


def test_retrieval_failure_can_use_one_explicit_crawl4ai_fallback(tmp_path):
    def runner(argv):
        return SimpleNamespace(returncode=1, stdout="", failure_kind="retrieval_failure")
    def fallback(url):
        return {"markdown": "## Synthetic", "html": "<h2>Synthetic</h2>", "links": [], "final_url": url}
    result = run_scrape_batch((ResearchTarget("a", "https://huntr.co/resume-examples/a", "huntr", None),), tmp_path, runner, lambda _: None, 5, fallback)
    assert result.succeeded == ("a",)
    assert json.loads((tmp_path / "a.json").read_text())["transport"] == "crawl4ai"


@pytest.mark.parametrize("failure_kind", ["captcha", "login_required", "paywall", "robots_denied", "provider_refusal", "policy_rejection", "exhausted_budget"])
def test_non_retrieval_failures_cannot_use_fallback(tmp_path, failure_kind):
    fallback_calls = []
    def runner(argv):
        return SimpleNamespace(returncode=1, stdout="", failure_kind=failure_kind)
    with pytest.raises(ValueError):
        run_scrape_batch((ResearchTarget("a", "https://huntr.co/resume-examples/a", "huntr", None),), tmp_path, runner, lambda _: None, 5, lambda url: fallback_calls.append(url))
    assert fallback_calls == []


def test_hash_matching_rerun_skips_and_unbound_output_conflicts(tmp_path):
    target = ResearchTarget("a", "https://huntr.co/resume-examples/a", "huntr", None)
    run_scrape_batch((target,), tmp_path, lambda argv: (Path(argv[-1]).write_text(json.dumps(_raw()), encoding="utf-8") or SimpleNamespace(returncode=0, stdout="")), lambda _: None, 5)
    digest = __import__("hashlib").sha256((tmp_path / "a.json").read_bytes()).hexdigest()
    skipped = run_scrape_batch((ResearchTarget("a", target.url, "huntr", digest),), tmp_path, lambda _: (_ for _ in ()).throw(AssertionError("runner called")), lambda _: None, 5)
    assert skipped.skipped == ("a",)
    with pytest.raises(ValueError, match="conflict"):
        run_scrape_batch((target,), tmp_path, lambda _: None, lambda _: None, 5)


def test_max_pages_is_hard_bound_and_checkpoint_is_atomic(tmp_path):
    targets = tuple(ResearchTarget(str(i), f"https://huntr.co/resume-examples/{i}", "huntr", None) for i in range(3))
    calls = []
    def runner(argv):
        calls.append(argv)
        Path(argv[-1]).write_text(json.dumps(_raw()), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="")
    result = run_scrape_batch(targets, tmp_path, runner, lambda _: None, 2)
    assert len(calls) == 2
    assert result.checkpoint.exists()


def test_manifest_rejects_duplicate_ids_and_urls(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("schema_version: m8q.resume_research.v1\ntargets:\n  - {target_id: a, url: https://huntr.co/resume-examples/x, source_kind: huntr, captured_sha256: null}\n  - {target_id: a, url: https://huntr.co/resume-examples/y, source_kind: huntr, captured_sha256: null}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate target_id"):
        load_source_manifest(manifest)
    manifest.write_text("schema_version: m8q.resume_research.v1\ntargets:\n  - {target_id: a, url: https://huntr.co/resume-examples/x, source_kind: huntr, captured_sha256: null}\n  - {target_id: b, url: https://www.huntr.co/resume-examples/x, source_kind: huntr, captured_sha256: null}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate canonical URL"):
        load_source_manifest(manifest)


def test_malformed_or_empty_output_stops_batch(tmp_path):
    target = ResearchTarget("a", "https://huntr.co/resume-examples/a", "huntr", None)
    def malformed(argv):
        Path(argv[-1]).write_text("not json", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="")
    with pytest.raises(Exception):
        run_scrape_batch((target,), tmp_path, malformed, lambda _: None, 1)
    (tmp_path / "a.json").unlink()
    def empty(argv):
        Path(argv[-1]).write_text("", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="")
    with pytest.raises(ValueError, match="empty"):
        run_scrape_batch((target,), tmp_path, empty, lambda _: None, 1)


def test_extract_huntr_writes_private_skeleton_without_resume_text(tmp_path):
    from src.resume_evidence.capture import normalize_crawl4ai_capture, write_capture_atomic
    from scripts.research_resume_evidence import extract_huntr
    raw = tmp_path / "raw"; raw.mkdir()
    capture = normalize_crawl4ai_capture({"markdown": "### New Grad Resume Example\nVerified composite\nThis reached the interview stage.\n### Experience\nEngineer | Example\n- Synthetic bullet.\n", "links": [], "final_url": "https://huntr.co/resume-examples/x"}, "https://huntr.co/resume-examples/x", "2026-08-30T08:00:00Z")
    write_capture_atomic(raw / "a.json", capture)
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("schema_version: m8q.resume_research.v1\ntargets:\n  - {target_id: a, url: https://huntr.co/resume-examples/x, source_kind: huntr, captured_sha256: null}\n", encoding="utf-8")
    inbox = tmp_path / "inbox"
    assert extract_huntr(raw, inbox, manifest) == 1
    skeleton = next(inbox.rglob("skeleton.yaml"))
    text = skeleton.read_text(encoding="utf-8")
    assert "m8q.huntr_skeleton.v1" in text and "Synthetic bullet" not in text


def test_operator_has_no_forbidden_production_or_network_imports():
    tree = ast.parse(Path("scripts/research_resume_evidence.py").read_text(encoding="utf-8"))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imports |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    source = Path("scripts/research_resume_evidence.py").read_text(encoding="utf-8")
    assert not {"requests", "crawl4ai", "playwright", "sqlite3"} & imports
    assert "src.db" not in source and "src.tailor" not in source
