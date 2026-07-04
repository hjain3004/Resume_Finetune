from src.models import dedup_key, norm, norm_loc


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
