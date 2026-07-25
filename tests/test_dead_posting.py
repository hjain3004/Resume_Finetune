"""M6.13R: corpus tests for the dead-posting detector.

The M6.13 detector matched unbounded fragments (`has been filled`,
`no longer exists`, `no longer open`) anywhere in a page, which classified at
least one valid JD (job 1246, D2L) from a generic careers-FAQ sentence. The
corrected detector requires an explicit subject that refers to *this* posting,
plus a dead predicate in the same sentence.

Positive wording is taken from the real pages captured in
`data/backups/jobs_pre_dead_posting_remediation_2026-07-22.db`.
"""

from __future__ import annotations

import pytest

from src.resolve.generic import is_dead_posting_text

# --- positives: real dead-page notices ---------------------------------------

DEAD_NOTICES = {
    "esri": "Work with us We're sorry! This job is no longer available There are many "
    "ways to join the Esri team. Please check our open positions.",
    "qualtrics": "We're sorry… the job you are trying to apply for has been filled. "
    "Maybe you would like to consider the Categories below :",
    "adobe": "## We're sorry… the job you are trying to apply for has been filled. "
    "Maybe you would like to consider the Categories below : Card text",
    "royal_caribbean": "Sorry, this position has been filled. We use cookies to offer "
    "you the best possible website experience.",
    "citi": "# Job Not Found The position you're looking for is no longer open, but "
    "there are many other opportunities waiting for you at Citi:",
    "icims_404": "# 404 ## The page you are looking for no longer exists. We're sorry, "
    "but it looks like this job may be no longer available or does not exist.",
    "icims_error": "# Error: The requested job could not be found. Error: The job that "
    "you were looking for either does not exist or is no longer open.",
    "drs": "Sorry, this position is no longer posted. Please search again.",
    "blackrock": "We are sorry this job post no longer exists. Luckily, we have other "
    "jobs you might also be interested in:",
    "apple": "# Page not found. Sorry, this role does not exist or is no longer "
    "available. Search Current Openings",
    "meta": "Sorry, this job is no longer available It looks like the job description "
    "you were looking for has been removed.",
    "spectrum": "# Job No Longer Posted The job you are interested in is no longer "
    "posted. Luckily, we have other jobs you might be interested in.",
    "peraton_headline": "Looks like this opportunity is no longer available. But don't "
    "worry, we have plenty of other great positions to explore!",
    "peraton_body": "You were redirected here because the job listing you clicked on "
    "is either no longer available or has been removed.",
    "no_longer_accepting": "Thank you for your interest. This position is no longer "
    "accepting applications.",
    "expired": "This job posting has expired and is no longer accepting candidates.",
}


@pytest.mark.parametrize("name", sorted(DEAD_NOTICES))
def test_detects_real_dead_page_notice(name: str) -> None:
    assert is_dead_posting_text(DEAD_NOTICES[name]) is True


def test_detects_notice_embedded_in_surrounding_page_furniture() -> None:
    text = (
        "Search jobs keyword location Search jobs " * 5
        + "We are sorry this job post no longer exists. "
        + "Equal opportunity employer. " * 20
    )
    assert is_dead_posting_text(text) is True


# --- negatives: incidental wording on valid or generic pages ------------------

LIVE_TEXTS = {
    # job 1246 (D2L): generic careers-FAQ policy sentence, not a dead notice.
    "d2l_faq": "There are multiple openings for some of the positions listed. When an "
    "opportunity has been filled, we will remove the job posting from the website. "
    "What can I expect in the assessment portion of the interview?",
    "no_longer_remote": "Please note: this position is no longer remote and requires "
    "three days per week onsite in Austin.",
    "backfill": "The previous position has been filled, and the team is hiring for "
    "this new role to support continued growth.",
    "policy_when_filled": "Once this position has been filled, we will notify all "
    "applicants by email.",
    "historical": "Roles like this one have historically been filled by internal "
    "candidates, but we now recruit externally.",
    "removal_policy": "Postings are removed from our site when an opening is no "
    "longer open to new applicants.",
}


@pytest.mark.parametrize("name", sorted(LIVE_TEXTS))
def test_does_not_flag_incidental_wording(name: str) -> None:
    assert is_dead_posting_text(LIVE_TEXTS[name]) is False


def test_does_not_flag_long_valid_jd_containing_policy_language() -> None:
    jd = (
        "Software Engineer, Platform. Responsibilities: design, build, and operate "
        "distributed services. Qualifications: 3+ years of experience with Python "
        "and Go. "
        + LIVE_TEXTS["d2l_faq"]
        + " "
        + LIVE_TEXTS["backfill"]
        + " We offer competitive compensation and comprehensive benefits. " * 20
    )
    assert len(jd) >= 400
    assert is_dead_posting_text(jd) is False


def test_bare_fragments_are_not_sufficient_evidence() -> None:
    """M6.13's unbounded fragments must no longer classify on their own."""
    for fragment in ("has been filled", "no longer exists", "no longer open"):
        assert is_dead_posting_text(f"Some unrelated sentence {fragment} somewhere.") is False


def test_empty_text_is_not_a_dead_posting() -> None:
    assert is_dead_posting_text("") is False
