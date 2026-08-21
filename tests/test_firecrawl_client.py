import pytest
import os
from unittest.mock import patch, MagicMock
from src.firecrawl.client import FirecrawlClient, ConfigurationError, ProviderAuthError, ProviderContractError, ProviderTransientError, Tier2Page
import requests

@pytest.fixture
def config():
    return {
        "scrape": {
            "only_main_content": True,
            "remove_base64_images": True,
            "max_age_ms": 86400000,
            "timeout_seconds": 60,
            "location": {"country": "US", "languages": ["en-US"]}
        }
    }

def test_start_without_api_key(config):
    with patch.dict(os.environ, {}, clear=True):
        client = FirecrawlClient(config)
        with pytest.raises(ConfigurationError, match="FIRECRAWL_API_KEY not found in environment"):
            client.start()

def test_crawl_without_api_key(config):
    with patch.dict(os.environ, {}, clear=True):
        client = FirecrawlClient(config)
        with pytest.raises(ConfigurationError, match="FIRECRAWL_API_KEY not found in environment"):
            client.crawl("https://example.com/job")

def test_crawl_success(config):
    with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test_key"}, clear=True):
        client = FirecrawlClient(config)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "markdown": "Job description here",
                "metadata": {
                    "sourceURL": "https://example.com/job-resolved",
                    "statusCode": 200
                }
            }
        }
        
        with patch.object(client.session, "post", return_value=mock_response) as mock_post:
            page = client.crawl("https://example.com/job")
            
            # Verify payload exactness
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["headers"]["Authorization"] == "Bearer test_key"
            assert call_kwargs["json"]["formats"] == ["markdown"]
            assert call_kwargs["json"]["onlyMainContent"] is True
            assert call_kwargs["json"]["proxy"] == "basic"
            assert call_kwargs["json"]["location"] == {"country": "US", "languages": ["en-US"]}
            
            assert page.markdown == "Job description here"
            assert page.final_url == "https://example.com/job-resolved"
            assert page.status_code == 200
            assert page.provider == "firecrawl"
            assert page.credits_used == 1

def test_crawl_auth_error(config):
    with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test_key"}, clear=True):
        client = FirecrawlClient(config)
        
        mock_response = MagicMock()
        mock_response.status_code = 401
        
        with patch.object(client.session, "post", return_value=mock_response):
            with pytest.raises(ProviderAuthError, match="authentication failure"):
                client.crawl("https://example.com/job")
                
            # Circuit breaker should trip
            assert client._tripped
            
            with pytest.raises(ProviderTransientError, match="Firecrawl circuit breaker tripped"):
                client.crawl("https://example.com/job")

def test_crawl_transient_error(config):
    with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test_key"}, clear=True):
        client = FirecrawlClient(config)
        
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        with patch.object(client.session, "post", return_value=mock_response):
            with pytest.raises(ProviderTransientError, match="provider error 500"):
                client.crawl("https://example.com/job")

def test_crawl_request_exception(config):
    with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test_key"}, clear=True):
        client = FirecrawlClient(config)
        
        with patch.object(client.session, "post", side_effect=requests.RequestException("connection failed")):
            with pytest.raises(ProviderTransientError, match="transport failure"):
                client.crawl("https://example.com/job")

def test_crawl_success_false(config):
    with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test_key"}, clear=True):
        client = FirecrawlClient(config)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "error": "Failed to scrape"
        }
        
        # M9F-0 defect 4: this previously returned a fabricated empty Tier2Page,
        # which downstream code judged as a content failure -- charging the row
        # an attempt and a 24h cooldown for a page the provider never delivered.
        # `success: false` is now an explicit provider-contract failure.
        with patch.object(client.session, "post", return_value=mock_response):
            with pytest.raises(ProviderContractError, match="Failed to scrape"):
                client.crawl("https://example.com/job")

def test_secret_redaction(config):
    test_key = "secret_api_key_12345"
    with patch.dict(os.environ, {"FIRECRAWL_API_KEY": test_key}, clear=True):
        client = FirecrawlClient(config)
        
        with patch.object(client.session, "post", side_effect=requests.RequestException(f"failed {test_key}")):
            with pytest.raises(ProviderTransientError) as exc_info:
                client.crawl("https://example.com/job")
            
            # The exception string itself should not contain the key
            assert test_key not in str(exc_info.value)
            
            # The trip reason should not contain the key
            assert test_key not in client._trip_reason
