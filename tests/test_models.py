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
