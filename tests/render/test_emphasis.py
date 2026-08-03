import pytest
from src.render.emphasis import parse_emphasis, EmphasisError


def test_plain_text_has_no_spans():
    assert parse_emphasis("Built an event store.") == ("Built an event store.", ())


def test_single_span_offsets_locate_the_marked_text():
    plain, spans = parse_emphasis("Cut **p99 latency** by 40%.")
    assert plain == "Cut p99 latency by 40%."
    assert spans == ((4, 15),)
    assert plain[4:15] == "p99 latency"


def test_three_spans_are_all_located():
    plain, spans = parse_emphasis(
        "**Reduced footprint by 40%** and improved perf by 25% by building "
        "**data lifecycle management** with **event-driven archival**."
    )
    assert "**" not in plain
    assert [plain[s:e] for s, e in spans] == [
        "Reduced footprint by 40%",
        "data lifecycle management",
        "event-driven archival",
    ]


def test_repeated_substring_resolves_to_the_marked_occurrence():
    plain, spans = parse_emphasis("Kafka and **Kafka** again")
    assert spans == ((10, 15),)
    assert plain[10:15] == "Kafka"


def test_unbalanced_marker_raises():
    with pytest.raises(EmphasisError, match="unbalanced"):
        parse_emphasis("Cut **p99 latency by 40%.")


def test_empty_span_raises():
    with pytest.raises(EmphasisError, match="empty"):
        parse_emphasis("Cut **** latency.")


def test_nested_marker_raises():
    with pytest.raises(EmphasisError, match="nested"):
        parse_emphasis("Cut **p99 **latency** here** now.")


def test_single_asterisk_is_literal_text():
    plain, spans = parse_emphasis("Complexity is O(n*log n).")
    assert plain == "Complexity is O(n*log n)."
    assert spans == ()


def test_three_separate_spans_are_valid():
    plain, spans = parse_emphasis(
        "Cut **p99** **latency** **here** now."
    )
    assert plain == "Cut p99 latency here now."
    assert [plain[start:end] for start, end in spans] == [
        "p99",
        "latency",
        "here",
    ]


def test_adjacent_valid_spans_are_valid():
    plain, spans = parse_emphasis("**alpha****beta**")
    assert plain == "alphabeta"
    assert [plain[s:e] for s, e in spans] == ["alpha", "beta"]


def test_leading_whitespace_inside_span_is_rejected():
    with pytest.raises(EmphasisError, match="unbalanced"):
        parse_emphasis("Cut ** p99** latency.")


def test_trailing_whitespace_inside_span_is_rejected():
    with pytest.raises(EmphasisError, match="unbalanced"):
        parse_emphasis("Cut **p99 ** latency.")
