import pytest

from src.resume_evidence.huntr import HuntrExampleKind, parse_huntr_examples, promotable_huntr_examples


def test_verified_composite_and_illustrative_remain_distinct():
    markdown = """## New Grad Software Engineer Resume Example
Verified composite
Built from resumes attached to jobs that reached the interview stage.
### Experience
Software Engineer | Example Company | 2025-06 - 2026-06
- Built a synthetic test service.

## Entry-Level Data Engineer Resume Example
Illustrative example
Built from job postings in this set.
### Experience
Data Engineering Intern | Example Lab | 2025-06 - 2025-08
- Built a synthetic test pipeline.
"""
    examples = parse_huntr_examples(markdown)
    assert [item.kind for item in examples] == [HuntrExampleKind.VERIFIED_COMPOSITE, HuntrExampleKind.ILLUSTRATIVE]
    assert [item.heading for item in promotable_huntr_examples(examples)] == ["New Grad Software Engineer Resume Example"]


def test_individual_is_distinct_and_quote_is_exact():
    markdown = """### Backend Resume Example
Verified individual
This example reached a recruiter screen.
### Experience
Engineer | Example Org | 2025-01 - 2026-01
- Built a synthetic service.
"""
    example = parse_huntr_examples(markdown)[0]
    assert example.kind is HuntrExampleKind.VERIFIED_INDIVIDUAL
    assert example.outcome_quote == "This example reached a recruiter screen."
    assert example.outcome_quote in example.resume_markdown


def test_unknown_label_never_promotes():
    markdown = "### Backend Resume Example\nUnknown label\n### Experience\nEngineer | Example Org\n- Built a synthetic service.\n"
    examples = parse_huntr_examples(markdown)
    assert examples[0].kind is HuntrExampleKind.UNKNOWN
    assert promotable_huntr_examples(examples) == ()


@pytest.mark.parametrize("markdown", [
    "### Resume Example\nVerified composite\n### Experience\n",
    "### Backend Resume Example\nIllustrative example\n### Experience\n- text\n### Backend Resume Example\nIllustrative example\n### Experience\n- text",
])
def test_ambiguous_unknown_empty_or_duplicate_sections_fail_closed(markdown):
    with pytest.raises(ValueError):
        parse_huntr_examples(markdown)


def test_great_or_polish_does_not_create_outcome_evidence():
    markdown = "### Resume Example\nWhy this resume is great\n### Experience\n- Improved service by 99%.\n"
    examples = parse_huntr_examples(markdown)
    assert examples[0].kind is HuntrExampleKind.UNKNOWN
    assert promotable_huntr_examples(examples) == ()
