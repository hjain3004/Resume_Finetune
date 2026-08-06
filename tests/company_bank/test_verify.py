import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.company_bank.verify import (
    FetchResult, SourceVerdict, classify_source, quote_coverage, normalize_for_match
)
from scripts.company_bank import RateLimitedFetcher, _handle_lint_snapshots, _handle_verify_sources
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
                "content_sha256": "6ca027405f83d7bee9e0a51fa256671f0c29e4182bde5194a78cc56218b08d02",
                "snapshot_file": "sources/s_1.txt"
            }
        ],
        "facts": [
            {
                "id": "f_1",
                "kind": "product",
                "scope": {"kind": "company", "name": "Test"},
                "claim": "C",
                "quote": "Test quote words here.",
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
    (bundle_dir / "sources" / "s_1.txt").write_text("Test quote words here. " * 10)
    
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
        
        args_verify = argparse.Namespace(inbox=None, bundle_path=bundle_dir / "bundle.json", json_out=None, strict=False, delay=2.0, report_foldable=False, render=False)
        assert _handle_verify_sources(args_verify) == 0
        assert hash_dir(bundle_dir) == h_before
        
        args_verify_strict = argparse.Namespace(inbox=None, bundle_path=bundle_dir / "bundle.json", json_out=None, strict=True, delay=2.0, report_foldable=False, render=False)
        assert _handle_verify_sources(args_verify_strict) == 2
        assert hash_dir(bundle_dir) == h_before

class FakeResponse:
    def __init__(self, status, url="https://test.com/a"):
        self.status = status
        self.url = url

class FakePage:
    def __init__(self, should_fail=False, text="render succeeds, quote found"):
        self.should_fail = should_fail
        self.text = text
        self.url = "https://test.com/a"
        self.waits = 0
        
    def goto(self, url, wait_until, timeout):
        if self.should_fail:
            raise Exception("Timeout")
        return FakeResponse(200, url)
        
    def wait_for_timeout(self, ms):
        self.waits += 1
        
    def evaluate(self, script):
        return self.text

@patch("scripts.company_bank.requests.get")
@patch("scripts.company_bank.time.sleep")
def test_render_fetcher(mock_sleep, mock_get):
    from scripts.company_bank import RateLimitedFetcher
    from unittest.mock import MagicMock
    
    # render succeeds, quote found -> verified (tested downstream but here we just check it returns the text)
    # mock get for robots and plain fetch
    mock_get.return_value = MagicMock(status_code=200, text="", url="https://test.com/a") # fallback is 200 but empty text
    
    page = FakePage(text="this is rendered text containing Q")
    fetcher = RateLimitedFetcher(2.0, page=page)
    res = fetcher.fetch("https://test.com/a", ("test.com",))
    assert res.status == 200
    assert res.text == "this is rendered text containing Q"
    assert res.error is None
    
    # render fails/times out -> falls back to plain-fetch verdict
    page = FakePage(should_fail=True)
    fetcher = RateLimitedFetcher(2.0, page=page)
    res = fetcher.fetch("https://test.com/a", ("test.com",))
    assert res.status == 200
    assert res.text == ""
    
    # --render off -> plain fetch
    fetcher = RateLimitedFetcher(2.0, page=None)
    res = fetcher.fetch("https://test.com/a", ("test.com",))
    assert res.status == 200
    
    # robots disallow -> no render attempted
    def robots_get(*args, **kwargs):
        if args[0].endswith("robots.txt"):
            return MagicMock(status_code=200, text="User-agent: *\nDisallow: /")
        return MagicMock(status_code=200, text="plain", url="https://test.com/a")
    mock_get.side_effect = robots_get
    
    page = FakePage(text="Should not render")
    fetcher = RateLimitedFetcher(2.0, page=page)
    res = fetcher.fetch("https://test.com/a", ("test.com",))
    assert res.error == "blocked by robots.txt"


def test_lint_snapshots_rejects_malformed_bundle_json(tmp_path, capsys):
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text("{not json", encoding="utf-8")

    args = argparse.Namespace(inbox=None, bundle_path=bundle_path, strict=False)

    assert _handle_lint_snapshots(args) == 1
    _, err = capsys.readouterr()
    assert str(bundle_path) in err
    assert "INVALID" in err


def test_lint_snapshots_rejects_missing_bundle(tmp_path, capsys):
    missing = tmp_path / "missing.json"
    args = argparse.Namespace(inbox=None, bundle_path=missing, strict=False)

    assert _handle_lint_snapshots(args) == 2

    _, err = capsys.readouterr()
    assert str(missing) in err
    assert "UNREADABLE" in err


def test_lint_snapshots_rejects_empty_inbox(tmp_path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    args = argparse.Namespace(inbox=inbox, bundle_path=None, strict=False)

    assert _handle_lint_snapshots(args) == 2

    _, err = capsys.readouterr()
    assert str(inbox) in err
    assert "empty" in err.lower()


def test_lint_snapshots_mixed_valid_invalid_inbox_fails_closed(tmp_path, capsys):
    inbox = tmp_path / "inbox"
    shutil.copytree("tests/fixtures/company_bank/valid_acme", inbox / "valid")
    invalid_dir = inbox / "invalid"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "bundle.json").write_text("{not json", encoding="utf-8")
    args = argparse.Namespace(inbox=inbox, bundle_path=None, strict=False)

    assert _handle_lint_snapshots(args) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert str(invalid_dir / "bundle.json") in err


def test_verify_sources_rejects_missing_bundle_without_fetching(tmp_path, capsys):
    missing = tmp_path / "missing.json"

    with patch("scripts.company_bank.RateLimitedFetcher") as fetcher_class:
        args = argparse.Namespace(
            inbox=None,
            bundle_path=missing,
            json_out=None,
            strict=False,
            delay=2.0,
            report_foldable=False,
            render=False,
        )

        assert _handle_verify_sources(args) == 2

    fetcher_class.return_value.fetch.assert_not_called()
    _, err = capsys.readouterr()
    assert str(missing) in err
    assert "UNREADABLE" in err


def test_verify_sources_rejects_empty_inbox_without_fetching(tmp_path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    with patch("scripts.company_bank.RateLimitedFetcher") as fetcher_class:
        args = argparse.Namespace(
            inbox=inbox,
            bundle_path=None,
            json_out=None,
            strict=False,
            delay=2.0,
            report_foldable=False,
            render=False,
        )

        assert _handle_verify_sources(args) == 2

    fetcher_class.return_value.fetch.assert_not_called()
    _, err = capsys.readouterr()
    assert str(inbox) in err
    assert "empty" in err.lower()


def test_verify_sources_mixed_valid_invalid_inbox_fails_before_fetch(tmp_path, capsys):
    inbox = tmp_path / "inbox"
    valid_dir = inbox / "valid"
    invalid_dir = inbox / "invalid"
    shutil.copytree("tests/fixtures/company_bank/valid_acme", valid_dir)
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "bundle.json").write_text("{not json", encoding="utf-8")

    with patch("scripts.company_bank.RateLimitedFetcher") as fetcher_class:
        args = argparse.Namespace(
            inbox=inbox,
            bundle_path=None,
            json_out=None,
            strict=False,
            delay=2.0,
            report_foldable=False,
            render=False,
        )

        assert _handle_verify_sources(args) == 1

    fetcher_class.return_value.fetch.assert_not_called()
    _, err = capsys.readouterr()
    assert str(invalid_dir / "bundle.json") in err


def test_verify_sources_rejects_json_out_under_sources_before_fetch(tmp_path, capsys):
    bundle_dir = tmp_path / "valid_acme"
    shutil.copytree("tests/fixtures/company_bank/valid_acme", bundle_dir)
    prohibited = bundle_dir / "sources" / "verification_report.json"

    with patch("scripts.company_bank.RateLimitedFetcher") as fetcher_class:
        args = argparse.Namespace(
            inbox=None,
            bundle_path=bundle_dir / "bundle.json",
            json_out=prohibited,
            strict=False,
            delay=2.0,
            report_foldable=False,
            render=False,
        )

        assert _handle_verify_sources(args) == 2

    fetcher_class.return_value.fetch.assert_not_called()
    assert not prohibited.exists()
    _, err = capsys.readouterr()
    assert "json-out" in err


def test_verify_sources_rejects_json_out_at_bundle_json_before_fetch(tmp_path, capsys):
    bundle_dir = tmp_path / "valid_acme"
    shutil.copytree("tests/fixtures/company_bank/valid_acme", bundle_dir)
    prohibited = bundle_dir / "bundle.json"

    with patch("scripts.company_bank.RateLimitedFetcher") as fetcher_class:
        args = argparse.Namespace(
            inbox=None,
            bundle_path=bundle_dir / "bundle.json",
            json_out=prohibited,
            strict=False,
            delay=2.0,
            report_foldable=False,
            render=False,
        )

        assert _handle_verify_sources(args) == 2

    fetcher_class.return_value.fetch.assert_not_called()
    _, err = capsys.readouterr()
    assert "bundle.json" in err
    assert "json-out" in err


def test_verify_sources_rejects_json_out_at_bundle_directory_before_fetch(tmp_path, capsys):
    bundle_dir = tmp_path / "valid_acme"
    shutil.copytree("tests/fixtures/company_bank/valid_acme", bundle_dir)

    with patch("scripts.company_bank.RateLimitedFetcher") as fetcher_class:
        args = argparse.Namespace(
            inbox=None,
            bundle_path=bundle_dir / "bundle.json",
            json_out=bundle_dir,
            strict=False,
            delay=2.0,
            report_foldable=False,
            render=False,
        )

        assert _handle_verify_sources(args) == 2

    fetcher_class.return_value.fetch.assert_not_called()
    _, err = capsys.readouterr()
    assert "json-out" in err


def test_verify_sources_closes_browser_when_json_write_fails(tmp_path, capsys):
    bundle_dir = tmp_path / "valid_acme"
    shutil.copytree("tests/fixtures/company_bank/valid_acme", bundle_dir)
    json_out = tmp_path / "verification_report.json"

    browser = MagicMock()
    playwright = MagicMock()
    playwright.chromium.launch.return_value = browser
    browser.new_page.return_value = MagicMock()
    playwright_context = MagicMock()
    playwright_context.start.return_value = playwright

    with (
        patch("scripts.company_bank.sync_playwright", return_value=playwright_context),
        patch("scripts.company_bank._write_json_atomic", side_effect=OSError("disk full")),
        patch("scripts.company_bank.RateLimitedFetcher") as fetcher_class,
    ):
        fetcher_class.return_value.fetch.return_value = FetchResult(
            "https://acme.example/product",
            200,
            "Acme builds widgets for enterprises. " * 50,
            None,
        )
        args = argparse.Namespace(
            inbox=None,
            bundle_path=bundle_dir / "bundle.json",
            json_out=json_out,
            strict=False,
            delay=2.0,
            report_foldable=False,
            render=True,
        )

        assert _handle_verify_sources(args) == 2

    browser.close.assert_called_once()
    playwright.stop.assert_called_once()
    _, err = capsys.readouterr()
    assert "json-out" in err


@patch("scripts.company_bank.requests.get")
def test_http_redirect_to_linkedin_member_is_rejected_without_requesting_destination(mock_get):
    """A permitted source URL redirecting to a LinkedIn member page must stop before destination contact."""

    def fake_get(url, **kwargs):
        if url == "https://test.com/robots.txt":
            return MagicMock(status_code=404, text="", url=url, headers={})
        if url == "https://test.com/a":
            return MagicMock(
                status_code=302,
                text="",
                url=url,
                headers={"Location": "https://www.linkedin.com/in/person"},
            )
        raise AssertionError(f"forbidden destination was requested: {url}")

    mock_get.side_effect = fake_get
    fetcher = RateLimitedFetcher(2.0)

    result = fetcher.fetch("https://test.com/a", ("test.com",))

    assert result.status is None
    assert "LinkedIn" in (result.error or "")
    requested_urls = [call.args[0] for call in mock_get.call_args_list]
    assert "https://www.linkedin.com/in/person" not in requested_urls


@patch("scripts.company_bank.requests.get")
def test_http_redirect_to_official_domain_is_followed_manually(mock_get):
    def fake_get(url, **kwargs):
        if url == "https://test.com/robots.txt":
            return MagicMock(status_code=404, text="", url=url, headers={})
        if url == "https://test.com/a":
            return MagicMock(status_code=302, text="", url=url, headers={"Location": "/b"})
        if url == "https://test.com/b":
            return MagicMock(status_code=200, text="quote text", url=url, headers={})
        raise AssertionError(f"unexpected URL: {url}")

    mock_get.side_effect = fake_get
    fetcher = RateLimitedFetcher(2.0)

    result = fetcher.fetch("https://test.com/a", ("test.com",))

    assert result.status == 200
    assert "quote text" in result.text
    requested_urls = [call.args[0] for call in mock_get.call_args_list]
    assert "https://test.com/b" in requested_urls


@patch("scripts.company_bank.requests.get")
def test_http_redirect_to_off_domain_is_rejected_without_requesting_destination(mock_get):
    def fake_get(url, **kwargs):
        if url == "https://test.com/robots.txt":
            return MagicMock(status_code=404, text="", url=url, headers={})
        if url == "https://test.com/a":
            return MagicMock(status_code=302, text="", url=url, headers={"Location": "https://evil.example/b"})
        raise AssertionError(f"off-domain destination was requested: {url}")

    mock_get.side_effect = fake_get
    fetcher = RateLimitedFetcher(2.0)

    result = fetcher.fetch("https://test.com/a", ("test.com",))

    assert result.status is None
    assert "off-domain" in (result.error or "")
    requested_urls = [call.args[0] for call in mock_get.call_args_list]
    assert "https://evil.example/b" not in requested_urls


def test_render_throttle_happens_before_page_goto(monkeypatch):
    events: list[str] = []
    clock = iter([0.0, 0.0, 0.0, 0.0, 0.1, 0.1])

    def fake_time():
        return next(clock)

    def fake_sleep(seconds):
        events.append(f"sleep:{seconds:.1f}")

    def fake_get(url, **kwargs):
        if url.endswith("/robots.txt"):
            return MagicMock(status_code=404, text="", url=url, headers={})
        return MagicMock(status_code=200, text="", url=url, headers={})

    class RecordingPage:
        url = "https://test.com/a"

        def goto(self, *args, **kwargs):
            events.append("goto")
            return MagicMock(status=200)

        def wait_for_timeout(self, ms):
            events.append(f"wait:{ms}")

        def evaluate(self, script):
            return "rendered quote"

    monkeypatch.setattr("scripts.company_bank.time.time", fake_time)
    monkeypatch.setattr("scripts.company_bank.time.sleep", fake_sleep)
    monkeypatch.setattr("scripts.company_bank.requests.get", fake_get)

    fetcher = RateLimitedFetcher(2.0, page=RecordingPage())
    fetcher.fetch("https://test.com/a", ("test.com",))

    assert events.index("sleep:2.0") < events.index("goto")
