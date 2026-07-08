from unittest.mock import MagicMock

from src.resolve.base import PoliteSession, html_to_text


def _make_session(get_return=None):
    fake_requests_session = MagicMock()
    fake_requests_session.get.return_value = get_return or MagicMock(status_code=200)
    return fake_requests_session


def test_rate_limiter_sleeps_at_least_two_seconds_between_same_host_requests():
    times = iter([100.0, 100.3])
    fake_time = lambda: next(times)
    fake_sleep = MagicMock()
    session = PoliteSession(session=_make_session(), time_func=fake_time, sleep_func=fake_sleep)

    session.get("https://example.com/a")
    session.get("https://example.com/b")

    fake_sleep.assert_called_once()
    (slept,), _ = fake_sleep.call_args
    assert slept >= 1.7  # 2.0 - 0.3 elapsed, allow float slack


def test_rate_limiter_does_not_sleep_for_different_hosts():
    fake_time = lambda: 100.0
    fake_sleep = MagicMock()
    session = PoliteSession(session=_make_session(), time_func=fake_time, sleep_func=fake_sleep)

    session.get("https://example.com/a")
    session.get("https://other.com/b")

    fake_sleep.assert_not_called()


def test_rate_limiter_does_not_sleep_when_interval_already_elapsed():
    times = iter([100.0, 103.0])
    fake_time = lambda: next(times)
    fake_sleep = MagicMock()
    session = PoliteSession(session=_make_session(), time_func=fake_time, sleep_func=fake_sleep)

    session.get("https://example.com/a")
    session.get("https://example.com/b")

    fake_sleep.assert_not_called()


def test_get_uses_timeout_and_allow_redirects_and_user_agent():
    inner = _make_session()
    session = PoliteSession(session=inner, time_func=lambda: 0.0, sleep_func=MagicMock())

    session.get("https://example.com/a")

    _, kwargs = inner.get.call_args
    assert kwargs["timeout"] == 15
    assert kwargs["allow_redirects"] is True
    assert "User-Agent" in kwargs["headers"]
    assert kwargs["headers"]["User-Agent"] == "Mozilla/5.0 (compatible; job-pipeline personal use)"


def test_throttle_sleeps_at_least_two_seconds_between_same_host_requests():
    times = iter([100.0, 100.3])
    fake_time = lambda: next(times)
    fake_sleep = MagicMock()
    session = PoliteSession(session=_make_session(), time_func=fake_time, sleep_func=fake_sleep)

    session.throttle("https://example.com/a")
    session.throttle("https://example.com/b")

    fake_sleep.assert_called_once()
    (slept,), _ = fake_sleep.call_args
    assert slept >= 1.7


def test_throttle_shares_the_same_per_host_clock_as_get():
    times = iter([100.0, 100.3])
    fake_time = lambda: next(times)
    fake_sleep = MagicMock()
    session = PoliteSession(session=_make_session(), time_func=fake_time, sleep_func=fake_sleep)

    session.get("https://example.com/a")
    session.throttle("https://example.com/b")

    fake_sleep.assert_called_once()


def test_get_returns_the_response():
    expected = MagicMock(status_code=200)
    session = PoliteSession(session=_make_session(expected), time_func=lambda: 0.0, sleep_func=MagicMock())

    response = session.get("https://example.com/a")

    assert response is expected


def test_html_to_text_strips_tags_and_unescapes_entities():
    html = "<p>Hello &amp; welcome</p>"
    assert html_to_text(html) == "Hello & welcome"


def test_html_to_text_preserves_list_items_as_dash_lines():
    html = "<ul><li>First</li><li>Second</li></ul>"
    text = html_to_text(html)
    assert "- First" in text
    assert "- Second" in text


def test_html_to_text_preserves_paragraph_breaks():
    html = "<p>First para.</p><p>Second para.</p>"
    text = html_to_text(html)
    paragraphs = [p for p in text.split("\n\n") if p]
    assert len(paragraphs) == 2
