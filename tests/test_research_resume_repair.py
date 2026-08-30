from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.research_resume_evidence import ResearchTarget, run_scrape_batch
from src.resolve.tier2 import Tier2Page


TARGET = ResearchTarget("a", "https://huntr.co/resume-examples/a", "huntr", None)


def test_firecrawl_command_requires_basic_proxy(tmp_path):
    calls = []

    def runner(argv):
        calls.append(argv)
        Path(argv[-1]).write_text(json.dumps({"data": {"markdown": "## Synthetic", "links": []}}), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    run_scrape_batch((TARGET,), tmp_path, runner=runner, sleeper=lambda _: None, clock=lambda: 0.0)
    assert calls[0][calls[0].index("--proxy") + 1] == "basic"
    assert "auto" not in calls[0] and "enhanced" not in calls[0] and "stealth" not in calls[0]


def test_real_shaped_retrieval_failure_uses_one_fallback_lifecycle(tmp_path):
    events = []

    class FakeClient:
        def start(self): events.append("start")
        def crawl(self, url):
            events.append(("crawl", url))
            return Tier2Page("## Synthetic", "<h2>Synthetic</h2>", url, None, "crawl4ai", 0)
        def close(self): events.append("close")

    def runner(argv):
        return subprocess.CompletedProcess(argv, 1, "", "All scraping engines failed to retrieve content from this URL.")

    result = run_scrape_batch((TARGET,), tmp_path, runner=runner, sleeper=lambda _: events.append("sleep"), clock=lambda: 0.0, allow_crawl4ai_fallback=True, fallback_factory=FakeClient)
    assert result.succeeded == ("a",)
    assert events == ["sleep", "start", ("crawl", TARGET.url), "close"] or events == ["start", ("crawl", TARGET.url), "close"]
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text())
    assert [attempt["transport"] for attempt in checkpoint["captures"][0]["attempts"]] == ["firecrawl", "crawl4ai"]


def test_terminal_failure_never_constructs_fallback(tmp_path):
    constructed = []
    def runner(argv):
        return subprocess.CompletedProcess(argv, 1, "", "authentication failed")
    with pytest.raises(ValueError):
        run_scrape_batch((TARGET,), tmp_path, runner=runner, sleeper=lambda _: None, clock=lambda: 0.0, allow_crawl4ai_fallback=True, fallback_factory=lambda: constructed.append(True))
    assert constructed == []


def test_two_transport_failures_stop_without_retry(tmp_path):
    fallback_calls = []
    def runner(argv):
        return subprocess.CompletedProcess(argv, 1, "", "All scraping engines failed to retrieve content from this URL.")
    def fallback(url):
        fallback_calls.append(url)
        raise RuntimeError("browser unavailable")
    with pytest.raises(RuntimeError):
        run_scrape_batch((TARGET,), tmp_path, runner=runner, sleeper=lambda _: None, clock=lambda: 0.0, allow_crawl4ai_fallback=True, fallback_runner=fallback)
    assert fallback_calls == [TARGET.url]
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text())
    assert checkpoint["captures"][0]["status"] == "failed"
    assert len(checkpoint["captures"][0]["attempts"]) == 2


def test_spacing_uses_remaining_interval_between_primary_and_fallback(tmp_path):
    now = [10.0]
    sleeps = []
    def clock(): return now[0]
    def sleeper(delay): sleeps.append(delay); now[0] += delay
    def runner(argv):
        return subprocess.CompletedProcess(argv, 1, "", "All scraping engines failed to retrieve content from this URL.")
    class FakeClient:
        def start(self): pass
        def crawl(self, url): return Tier2Page("## Synthetic", "<h2>Synthetic</h2>", url, None, "crawl4ai", 0)
        def close(self): pass
    run_scrape_batch((TARGET,), tmp_path, runner=runner, sleeper=sleeper, clock=clock, allow_crawl4ai_fallback=True, fallback_factory=FakeClient)
    assert sleeps == [2.0]


def test_malformed_checkpoint_stops_before_runner(tmp_path):
    (tmp_path / "checkpoint.json").write_text(json.dumps({"schema_version": "wrong", "captures": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint"):
        run_scrape_batch((TARGET,), tmp_path, runner=lambda _: (_ for _ in ()).throw(AssertionError("runner called")), sleeper=lambda _: None, clock=lambda: 0.0)


def test_subprocess_runner_passes_finite_timeout(monkeypatch):
    seen = {}
    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    from scripts.research_resume_evidence import _default_runner
    _default_runner(("firecrawl", "scrape"))
    assert seen["timeout"] == 180


def test_cli_default_does_not_enable_or_construct_crawl4ai(monkeypatch, tmp_path):
    import scripts.research_resume_evidence as operator
    captured = {}
    monkeypatch.setattr(operator, "run_scrape_batch", lambda *args, **kwargs: captured.update(kwargs) or SimpleNamespace(succeeded=(), skipped=()))
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("schema_version: m8q.resume_research.v1\ntargets: []\n", encoding="utf-8")
    assert operator.main(["scrape-batch", "--manifest", str(manifest), "--output", str(tmp_path / "out"), "--max-pages", "1"]) == 0
    assert captured["allow_crawl4ai_fallback"] is False
    assert captured["fallback_factory"] is None


def test_cli_flag_enables_existing_browser_factory_without_constructing_it(monkeypatch, tmp_path):
    import scripts.research_resume_evidence as operator
    captured = {}
    monkeypatch.setattr(operator, "run_scrape_batch", lambda *args, **kwargs: captured.update(kwargs) or SimpleNamespace(succeeded=(), skipped=()))
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("schema_version: m8q.resume_research.v1\ntargets: []\n", encoding="utf-8")
    assert operator.main(["scrape-batch", "--manifest", str(manifest), "--output", str(tmp_path / "out"), "--max-pages", "1", "--allow-crawl4ai-fallback"]) == 0
    assert captured["allow_crawl4ai_fallback"] is True
    assert captured["fallback_factory"] is operator._default_fallback_factory
