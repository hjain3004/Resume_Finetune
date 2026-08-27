from src.models import clean_title, dedup_key, norm, norm_loc


def test_norm_lowercases_and_strips_punctuation():
    assert norm("Acme, Inc.!") == "acme"


def test_norm_strips_corp_suffix_llc():
    assert norm("Widgets LLC") == "widgets"


def test_norm_strips_corp_suffix_corp():
    assert norm("Globex Corp") == "globex"


def test_norm_strips_trailing_requisition_number():
    assert norm("Software Engineer 12345") == "software engineer"


def test_norm_strips_req_parenthetical():
    assert norm("Software Engineer (Req 4821)") == "software engineer"


def test_norm_strips_bracketed_id():
    assert norm("Software Engineer [R-12345]") == "software engineer"


def test_norm_collapses_whitespace():
    assert norm("Software   Engineer  I") == "software engineer i"


def test_norm_strips_accents():
    assert norm("Café Corp") == "cafe"


def test_norm_loc_collapses_remote_variants():
    for variant in ["Remote", "remote us", "Remote USA", "United States Remote", "US Remote"]:
        assert norm_loc(variant) == "remote-us"


def test_norm_loc_empty_is_unknown():
    assert norm_loc(None) == "unknown"
    assert norm_loc("") == "unknown"


def test_norm_loc_regular_city():
    assert norm_loc("San Jose, CA") == "san jose ca"


def test_dedup_key_stable_and_deterministic():
    a = dedup_key("Acme Inc", "Software Engineer 12345", "Remote")
    b = dedup_key("Acme", "Software Engineer", "remote us")
    assert a == b


def test_dedup_key_differs_on_title():
    a = dedup_key("Acme", "Software Engineer", "Remote")
    b = dedup_key("Acme", "Backend Engineer", "Remote")
    assert a != b


def test_clean_title_strips_requisition_id_and_job_details_suffix():
    # M6.9 item 2: live example, id 52.
    assert (
        clean_title("Front End Developer (Hybrid) - 28751 Job Details")
        == "Front End Developer (Hybrid)"
    )


def test_clean_title_strips_job_details_boundary_even_with_trailing_text():
    # Real live raw_title (id 52) has furniture appended even after
    # "Job Details" ("... / HII's Mission Technologies division").
    assert (
        clean_title(
            "Front End Developer (Hybrid) - 28751 Job Details / "
            "HII's Mission Technologies division"
        )
        == "Front End Developer (Hybrid)"
    )


def test_clean_title_strips_piped_careers_suffix():
    assert clean_title("Software Engineer | Careers") == "Software Engineer"


def test_clean_title_strips_site_name_careers_suffix():
    assert clean_title("Software Engineer - Amazon Careers") == "Software Engineer"


def test_clean_title_strips_bare_trailing_requisition_number():
    assert clean_title("Senior SWE - 12345") == "Senior SWE"


def test_clean_title_leaves_clean_title_unchanged():
    assert clean_title("Software Engineer") == "Software Engineer"


def test_clean_title_preserves_legitimate_dashed_title():
    assert clean_title("Backend Engineer - Distributed Systems") == "Backend Engineer - Distributed Systems"


def test_clean_title_handles_none_and_empty():
    assert clean_title(None) is None
    assert clean_title("") == ""


# --- M6.14 URL and Posting Identity tests ---

from src.models import (
    DiscoveredJob,
    ManualUrlError,
    canonical_job_url,
    collision_dedup_key,
    manual_url_dedup_key,
    stable_posting_identity,
)
import pytest


def test_canonical_job_url_normalization():
    # Scheme/host lowercased, default ports removed, empty path -> /, trailing slash removed on non-root
    assert canonical_job_url("  HTTPS://Example.COM:443/jobs/123/  ") == "https://example.com/jobs/123"
    assert canonical_job_url("http://example.com:80") == "http://example.com/"
    assert canonical_job_url("https://example.com:8443/jobs/") == "https://example.com:8443/jobs"


def test_canonical_job_url_query_sorting_and_marketing_param_stripping():
    url1 = "https://jobs.lever.co/acme/123?utm_source=linkedin&gh_jid=456&utm_medium=cpc&b=2&a=1&fbclid=xyz"
    url2 = "https://jobs.lever.co/acme/123?a=1&gh_jid=456&b=2&gclid=abc"
    assert canonical_job_url(url1) == "https://jobs.lever.co/acme/123?a=1&b=2&gh_jid=456"
    assert canonical_job_url(url1) == canonical_job_url(url2)


def test_canonical_job_url_preserves_fragments_and_blank_query_values():
    url = "https://careers.example.com/search?pos=&tag=dev#job/12345"
    canon = canonical_job_url(url)
    assert canon == "https://careers.example.com/search?pos=&tag=dev#job/12345"


def test_canonical_job_url_rejects_credentials_and_secrets():
    # Userinfo in URL
    with pytest.raises(ManualUrlError) as excinfo:
        canonical_job_url("https://user:password@example.com/job/1")
    assert "userinfo" in str(excinfo.value).lower() or "credential" in str(excinfo.value).lower()
    assert "password" not in str(excinfo.value)

    # Sensitive query keys
    sensitive_keys = [
        "token", "access_token", "auth", "authorization", "api_key",
        "apikey", "secret", "signature", "session", "sessionid", "jwt"
    ]
    for key in sensitive_keys:
        with pytest.raises(ManualUrlError) as excinfo:
            canonical_job_url(f"https://example.com/job?{key}=super_secret_value")
        assert "super_secret_value" not in str(excinfo.value)

        # In fragment query too
        with pytest.raises(ManualUrlError) as excinfo:
            canonical_job_url(f"https://example.com/job#route?{key}=secret123")
        assert "secret123" not in str(excinfo.value)


def test_canonical_job_url_rejects_invalid_schemes_or_missing_hosts():
    with pytest.raises(ManualUrlError):
        canonical_job_url("ftp://example.com/job")
    with pytest.raises(ManualUrlError):
        canonical_job_url("example.com/job")
    with pytest.raises(ManualUrlError):
        canonical_job_url("https:///job")


def test_manual_url_dedup_key():
    url1 = "https://www.revolut.com/careers/position/swe-123/?utm_source=foo"
    url2 = "https://www.revolut.com/careers/position/swe-123"
    key1 = manual_url_dedup_key(url1)
    key2 = manual_url_dedup_key(url2)
    assert len(key1) == 64
    assert key1 == key2
    assert all(c in "0123456789abcdef" for c in key1)

    url3 = "https://www.revolut.com/careers/position/swe-456"
    assert manual_url_dedup_key(url3) != key1


def test_stable_posting_identity_greenhouse():
    # gh_jid query param
    assert (
        stable_posting_identity("https://careers.roblox.com/jobs/7114754?gh_jid=7114754")
        == "greenhouse:7114754"
    )
    assert (
        stable_posting_identity("https://job-boards.greenhouse.io/roblox/jobs/7114754")
        == "greenhouse:7114754"
    )
    assert (
        stable_posting_identity("https://boards.greenhouse.io/twitch/jobs/8623578002")
        == "greenhouse:8623578002"
    )
    assert (
        stable_posting_identity("https://careers.roblox.com/jobs/8072244?gh_jid=8072244")
        == "greenhouse:8072244"
    )
    # Direct careers.roblox.com without gh_jid
    assert (
        stable_posting_identity("https://careers.roblox.com/jobs/8072244")
        == "greenhouse:8072244"
    )


def test_stable_posting_identity_supported_ats_and_companies():
    # Ashby
    assert (
        stable_posting_identity("https://jobs.ashbyhq.com/quora/452afc2e-0c79-41f8-8201-1aab7df775db")
        == "ashby:quora:452afc2e-0c79-41f8-8201-1aab7df775db"
    )
    # Lever
    assert (
        stable_posting_identity("https://jobs.lever.co/palantir/12345678-abcd")
        == "lever:palantir:12345678-abcd"
    )
    # Workday
    assert (
        stable_posting_identity("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Software-Engineer_JR1987654")
        == "workday:nvidia.wd5.myworkdayjobs.com:software-engineer_jr1987654"
    )
    # Apple
    assert (
        stable_posting_identity("https://jobs.apple.com/en-us/details/200673336/software-engineer-commerce")
        == "apple:200673336"
    )
    # TikTok
    assert (
        stable_posting_identity("https://lifeattiktok.com/search/7668824169648097541")
        == "tiktok:7668824169648097541"
    )
    # Revolut UUID
    assert (
        stable_posting_identity("https://www.revolut.com/en-US/careers/position/graduate-programme-2027-software-engineer-java-3b79c804-b7e0-4b1a-9ef6-2fd69723dc7a/")
        == "revolut:3b79c804-b7e0-4b1a-9ef6-2fd69723dc7a"
    )


def test_stable_posting_identity_generic_returns_none():
    assert stable_posting_identity("https://example.com/careers/software-engineer") is None
    assert stable_posting_identity("https://unknowncompany.com/job/12345") is None


def test_collision_dedup_key():
    sem_key = dedup_key("Roblox", "Software Engineer", "San Mateo, CA")
    col_key_1 = collision_dedup_key(sem_key, "greenhouse:7114754")
    col_key_2 = collision_dedup_key(sem_key, "greenhouse:8072244")
    assert len(col_key_1) == 64
    assert len(col_key_2) == 64
    assert col_key_1 != col_key_2
    assert col_key_1 != sem_key


def test_discovered_job_identity_key():
    # Backward compatible positional constructor
    job1 = DiscoveredJob("Acme", "SWE", "Remote", "https://example.com/1", "tracker_vansh", None)
    assert job1.identity_key is None

    # Explicit identity key
    job2 = DiscoveredJob("unknown", "revolut.com", None, "https://revolut.com/1", "inbox", None, identity_key="a" * 64)
    assert job2.identity_key == "a" * 64

