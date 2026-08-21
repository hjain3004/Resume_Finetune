"""M9F-0 defect 4: a provider response that delivers no page is a
provider-contract failure, never fabricated empty content.

The previous implementation turned `success: false` into an empty `Tier2Page`
with an unused `error_message`, which downstream code would have judged as a
content failure -- consuming the row's attempt budget and applying a 24h
cooldown for something the page itself never caused.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.firecrawl.client import FirecrawlClient, ProviderContractError

CONFIG = {"scrape": {"timeout_seconds": 5, "max_age_ms": 1000, "location": {"country": "US"}}}
URL = "https://careers.acme.com/job/1"


def _client(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key-not-real")
    return FirecrawlClient(CONFIG)


def _response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


def test_success_false_is_a_provider_contract_failure(monkeypatch):
    client = _client(monkeypatch)
    with patch.object(client.session, "post", return_value=_response(
        {"success": False, "error": "scrape failed upstream"}
    )):
        with pytest.raises(ProviderContractError) as exc:
            client.crawl(URL)

    assert "scrape failed upstream" in str(exc.value)


def test_success_false_does_not_fabricate_an_empty_page(monkeypatch):
    client = _client(monkeypatch)
    with patch.object(client.session, "post", return_value=_response({"success": False})):
        with pytest.raises(ProviderContractError):
            client.crawl(URL)


def test_success_false_does_not_trip_the_breaker(monkeypatch):
    """One URL the provider could not scrape is not a provider-wide outage;
    tripping here would disable Firecrawl for every later row."""
    client = _client(monkeypatch)
    with patch.object(client.session, "post", return_value=_response({"success": False})):
        with pytest.raises(ProviderContractError):
            client.crawl(URL)

    assert client._tripped is False


def test_malformed_success_payload_is_a_provider_contract_failure(monkeypatch):
    client = _client(monkeypatch)
    with patch.object(client.session, "post", return_value=_response(
        {"success": True, "data": {"metadata": {}}}  # no markdown key at all
    )):
        with pytest.raises(ProviderContractError):
            client.crawl(URL)


def test_non_dict_payload_is_a_provider_contract_failure(monkeypatch):
    client = _client(monkeypatch)
    with patch.object(client.session, "post", return_value=_response(["unexpected"])):
        with pytest.raises(ProviderContractError):
            client.crawl(URL)


def test_provider_contract_error_never_leaks_the_api_key(monkeypatch):
    client = _client(monkeypatch)
    with patch.object(client.session, "post", return_value=_response(
        {"success": False, "error": "boom"}
    )):
        with pytest.raises(ProviderContractError) as exc:
            client.crawl(URL)

    assert "test-key-not-real" not in str(exc.value)
    assert "Bearer" not in str(exc.value)


def test_provider_error_message_is_bounded(monkeypatch):
    client = _client(monkeypatch)
    with patch.object(client.session, "post", return_value=_response(
        {"success": False, "error": "x" * 5000}
    )):
        with pytest.raises(ProviderContractError) as exc:
            client.crawl(URL)

    assert len(str(exc.value)) < 1000
