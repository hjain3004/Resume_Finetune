import json
from pathlib import Path
from unittest.mock import MagicMock

from src.resolve import wrapper

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_response(name: str, status_code: int = 200):
    body = (FIXTURES / f"{name}.body").read_bytes()
    response = MagicMock(status_code=status_code)
    response.json.return_value = json.loads(body)
    return response


def _wrapper_html(name: str) -> str:
    return (FIXTURES / f"{name}.body").read_text()


# --- extract_gh_jid / second_level_domain -----------------------------------


def test_extract_gh_jid_reads_query_param():
    url = "https://amperity.com/careers/6799726?gh_jid=6799726&gh_src=053ff1fc1us&gh_jid=6799726"
    assert wrapper.extract_gh_jid(url) == "6799726"


def test_extract_gh_jid_returns_none_when_absent():
    assert wrapper.extract_gh_jid("https://amperity.com/careers/6799726") is None


def test_second_level_domain_strips_www_and_tld():
    assert wrapper.second_level_domain("https://www.esri.com/careers/123") == "esri"
    assert wrapper.second_level_domain("https://amperity.com/careers/123") == "amperity"


# --- find_board_token_in_html -----------------------------------------------


def test_find_board_token_in_html_matches_embed_js_for_param():
    html = _wrapper_html("wrapper_linksquares_page")
    assert wrapper.find_board_token_in_html(html) == "linksquaresinc"


def test_find_board_token_in_html_returns_none_when_absent():
    assert wrapper.find_board_token_in_html("<html>no ats reference here</html>") is None


# --- resolve_gh_jid ----------------------------------------------------------


def test_resolve_gh_jid_succeeds_via_second_level_domain_guess():
    session = MagicMock()
    session.get.return_value = _fixture_response("wrapper_amperity_board_job")

    result = wrapper.resolve_gh_jid(
        "https://amperity.com/careers/8040043?gh_jid=8040043", "<html>no hints</html>", session
    )

    assert result is not None
    assert result.resolver == "greenhouse"
    assert result.raw_title == "Chief of Staff"
    assert result.ats_url == "https://boards.greenhouse.io/amperity/jobs/8040043"
    session.get.assert_called_once_with(
        "https://boards-api.greenhouse.io/v1/boards/amperity/jobs/8040043"
    )


def test_resolve_gh_jid_falls_back_to_html_regex_when_domain_guess_fails():
    session = MagicMock()
    session.get.side_effect = [
        MagicMock(status_code=404),  # wrong guess: "linksquares"
        _fixture_response("wrapper_amperity_board_job"),  # right token from html regex
    ]
    html = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=amperity"></script>'

    result = wrapper.resolve_gh_jid(
        "https://linksquares.com/careers/open-positions/?gh_jid=8040043", html, session
    )

    assert result is not None
    assert result.ats_url == "https://boards.greenhouse.io/amperity/jobs/8040043"
    assert session.get.call_count == 2


def test_resolve_gh_jid_returns_none_when_no_gh_jid_param():
    session = MagicMock()
    result = wrapper.resolve_gh_jid("https://amperity.com/careers/8040043", "<html/>", session)
    assert result is None
    session.get.assert_not_called()


def test_resolve_gh_jid_returns_none_when_all_candidates_fail():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=404)

    result = wrapper.resolve_gh_jid(
        "https://amperity.com/careers/999999?gh_jid=999999", "<html>no hints</html>", session
    )

    assert result is None


# --- resolve_wrapper_map -----------------------------------------------------


_ROBLOX_MAP = {"careers.roblox.com": {"ats": "greenhouse", "board": "roblox", "id_from": "path"}}


def test_resolve_wrapper_map_resolves_known_wrapper():
    session = MagicMock()
    session.get.return_value = _fixture_response("wrapper_roblox_board_job")

    result = wrapper.resolve_wrapper_map(
        "https://careers.roblox.com/jobs/7142298", session, wrapper_map=_ROBLOX_MAP
    )

    assert result is not None
    assert result.raw_title == "[2026] Applied Scientist - PhD Intern"
    assert result.ats_url == "https://boards.greenhouse.io/roblox/jobs/7142298"


def test_resolve_wrapper_map_returns_none_for_unknown_host():
    session = MagicMock()
    result = wrapper.resolve_wrapper_map(
        "https://careers.example.com/jobs/1", session, wrapper_map=_ROBLOX_MAP
    )
    assert result is None
    session.get.assert_not_called()


def test_resolve_wrapper_map_returns_none_for_non_numeric_path_segment():
    session = MagicMock()
    result = wrapper.resolve_wrapper_map(
        "https://careers.roblox.com/jobs/not-a-number", session, wrapper_map=_ROBLOX_MAP
    )
    assert result is None
    session.get.assert_not_called()


def test_load_wrapper_map_reads_seeded_config():
    wrapper_map = wrapper.load_wrapper_map("config/wrapper_map.yaml")
    assert wrapper_map["careers.roblox.com"] == {
        "ats": "greenhouse",
        "board": "roblox",
        "id_from": "path",
    }


def test_load_wrapper_map_returns_empty_dict_for_missing_file(tmp_path):
    assert wrapper.load_wrapper_map(tmp_path / "missing.yaml") == {}
