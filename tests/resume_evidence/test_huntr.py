import pytest

from src.resume_evidence.huntr import HuntrExampleKind, parse_huntr_page, parse_huntr_examples, promotable_huntr_examples


METHODOLOGY = "Huntr analyzed resumes from logged recruiter screens, interviews, and offers; examples were reconstructed and anonymized from those outcomes."


def test_verified_composite_and_illustrative_remain_distinct():
    markdown = f"""# Resume Examples
{METHODOLOGY}
## New Grad Software Engineer Resume Example
### Experience
Software Engineer | Example Company | 2025-06 - 2026-06
This resume reached the interview stage.
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


def test_page_methodology_promotes_two_separate_outcome_linked_sections():
    markdown = f"""# Real Resume Examples
{METHODOLOGY}
## Backend Resume Example
### Experience
Engineer | Example Org
This resume reached a recruiter screen.
## Data Resume Example
### Experience
Analyst | Example Lab
This resume reached the interview stage.
"""
    page = parse_huntr_page(markdown)
    assert len(promotable_huntr_examples(page)) == 2
    assert page.context.publisher_reconstructed is True


def test_page_methodology_without_per_example_outcome_does_not_promote():
    page = parse_huntr_page(f"# Examples\n{METHODOLOGY}\n## Backend Resume Example\n### Experience\nEngineer | Org\n- Built systems.\n")
    assert promotable_huntr_examples(page) == ()


def test_per_example_outcome_without_page_methodology_does_not_promote():
    page = parse_huntr_page("## Backend Resume Example\n### Experience\nEngineer | Org\nThis reached an interview stage.\n")
    assert promotable_huntr_examples(page) == ()


def test_illustrative_example_is_excluded_with_page_methodology():
    page = parse_huntr_page(f"# Examples\n{METHODOLOGY}\n## Backend Resume Example\nIllustrative example\n### Experience\nEngineer | Org\nThis reached an interview stage.\n")
    assert page.examples[0].kind is HuntrExampleKind.ILLUSTRATIVE
    assert promotable_huntr_examples(page) == ()


def test_outcome_from_one_section_cannot_promote_another():
    page = parse_huntr_page(f"# Examples\n{METHODOLOGY}\n## Backend Resume Example\n### Experience\nEngineer | Org\nThis reached an interview stage.\n## Data Resume Example\n### Experience\nAnalyst | Lab\n- Built systems.\n")
    assert [item.heading for item in promotable_huntr_examples(page)] == ["Backend Resume Example"]


def test_mixed_heading_levels_keep_all_valid_examples():
    page = parse_huntr_page(f"# Examples\n{METHODOLOGY}\n## Backend Resume Example\n### Experience\nEngineer | Org\nThis reached an interview stage.\n### Data Resume Example\n#### Experience\nAnalyst | Lab\nThis reached a recruiter screen.\n")
    assert len(page.examples) == 2


def test_methodology_words_in_bullet_are_not_page_evidence():
    page = parse_huntr_page("## Backend Resume Example\n### Experience\nEngineer | Org\n- Reconstructed an anonymized data pipeline.\nThis reached an interview stage.\n")
    assert page.context.publisher_reconstructed is False
    assert promotable_huntr_examples(page) == ()


def test_quotes_and_composite_limitation_are_exact():
    outcome = "This resume landed an offer."
    page = parse_huntr_page(f"# Examples\n{METHODOLOGY}\n## Backend Resume Example\n### Experience\nEngineer | Org\n{outcome}\n")
    example = page.examples[0]
    assert page.context.methodology_quote in page.source_markdown
    assert example.outcome_quote in example.resume_markdown
    assert example.page_methodology_quote == page.context.methodology_quote
    assert "composite" in " ".join(example.limitations)


def test_duplicate_anchors_fail_across_heading_levels():
    with pytest.raises(ValueError, match="duplicate"):
        parse_huntr_page(f"# Examples\n{METHODOLOGY}\n## Backend Resume Example\n### Experience\nEngineer | Org\nThis reached an interview.\n### Backend Resume Example\n#### Experience\nEngineer | Org\nThis reached an interview.\n")


def test_unknown_page_label_remains_non_promotable():
    page = parse_huntr_page("# Examples\n## Backend Resume Example\n### Experience\nEngineer | Org\nThis reached an interview stage.\n")
    assert page.examples[0].kind is HuntrExampleKind.UNKNOWN
    assert promotable_huntr_examples(page) == ()


def test_page_context_can_join_separate_provenance_and_reconstruction_quotes():
    page = parse_huntr_page("# Examples\nThese resumes are tied to logged interview outcomes.\nThe publisher reconstructed and anonymized the examples.\n## Backend Resume Example\n### Experience\nEngineer | Org\nThis reached an interview stage.\n")
    assert page.context.publisher_outcome_linked is True
    assert page.context.publisher_reconstructed is True
    assert page.examples[0].page_methodology_quote in page.source_markdown
