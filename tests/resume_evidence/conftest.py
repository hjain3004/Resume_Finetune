"""Synthetic fixtures for resume-evidence serde tests.

Every value here is invented. No real names, resume text, emails, phone numbers,
postal addresses, or paid-book text appears in this module.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from src.resume_evidence.serde import (
    parse_canonical_corpus,
    parse_doctrine_candidate,
    parse_doctrine_record,
    parse_outcome_candidate,
    parse_outcome_record,
    parse_pattern_card,
)

_SHA_ZERO = "0" * 64
_SHA_ONE = "1" * 64
_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _staged_source(source_id: str, sha: str) -> dict:
    return {
        "source_id": source_id,
        "url": f"https://example.test/{source_id}",
        "title": f"Synthetic source {source_id}",
        "retrieved_at": "2026-02-01T00:00:00Z",
        "content_sha256": sha,
        "snapshot_file": f"sources/{source_id}.md",
    }


def _canonical_source(source_id: str, sha: str) -> dict:
    src = _staged_source(source_id, sha)
    src.pop("snapshot_file")
    return src


def _outcome_body(*, staged: bool) -> dict:
    body = {
        "schema_version": "m8q.resume_evidence.v1",
        "reference_id": "cand_synthetic_001",
        "source_kind": "individual_public_story",
        "sources": [
            (_staged_source if staged else _canonical_source)("src_resume", _SHA_ZERO),
            (_staged_source if staged else _canonical_source)("src_outcome", _SHA_ONE),
        ],
        "resume_source_id": "src_resume",
        "outcome_source_id": "src_outcome",
        "layout_sha256": _SHA_A,
        "role_family": "general_swe",
        "target_role": "Software Engineer",
        "target_level": "New Grad",
        "graduation_month": "2025-05",
        "professional_intervals": [{"start_month": "2025-06", "end_month": "2026-01"}],
        "internship_intervals": [{"start_month": "2024-05", "end_month": "2024-08"}],
        "professional_experience_months": 7,
        "experience_confidence": "derived",
        "outcome_tier": "final_interview",
        "outcome_evidence_quote": "Reached the final round for the platform team.",
        "outcome_evidence_confidence": "self_reported",
        "resume_representation": "anonymized",
        "resume_version_attribution": "publisher_linked",
        "section_order": ["summary", "experience", "projects", "education"],
        "feature_tags": ["one_page", "quantified_bullets"],
        "editorial_ratings": [
            {
                "dimension": "technical_specificity",
                "score": 3,
                "explanation": "Some specific tools are named.",
            },
            {
                "dimension": "ownership_clarity",
                "score": 2,
                "explanation": "Individual versus team contribution is unclear.",
            },
        ],
        "limitations": ["Single anonymized data point."],
    }
    if staged:
        # layout_file sits before layout_sha256 in the dataclass field order.
        ordered = {}
        for key, value in body.items():
            if key == "layout_sha256":
                ordered["layout_file"] = "layouts/synthetic.typ"
            ordered[key] = value
        return ordered
    return body


def _doctrine_body(*, staged: bool) -> dict:
    return {
        "schema_version": "m8q.resume_evidence.v1",
        "doctrine_id": "doc_quantify_impact",
        "source": (_staged_source if staged else _canonical_source)("src_doctrine", _SHA_B),
        "authority_kind": "practitioner_first_party",
        "principle": "Quantify impact with concrete numbers where the data supports it.",
        "early_career_applicability": "High: interns can cite measurable project outcomes.",
        "affected_dimensions": ["technical_specificity", "claim_credibility"],
        "supporting_quote": "Numbers make accomplishments legible to a busy reviewer.",
        "conflicts_or_qualifications": ["Avoid fabricated precision when data is unavailable."],
        "confidence": "medium",
        "permitted_uses": ["rubric_candidate", "pattern_context"],
    }


def _pattern_body() -> dict:
    return {
        "schema_version": "m8q.resume_evidence.v1",
        "pattern_id": "pat_lead_with_outcome",
        "text": "Lead each bullet with the outcome, then the method.",
        "anti_pattern": False,
        "role_families": ["general_swe", "backend_platform"],
        "outcome_record_ids": ["cand_synthetic_001"],
        "doctrine_record_ids": ["doc_quantify_impact"],
        "limitations": ["Derived from a small synthetic sample."],
        "confidence": "low",
        "prohibited_uses": ["auto_rewrite_without_review"],
        "candidate_dimensions": ["ownership_clarity", "technical_specificity"],
    }


def _corpus_body() -> dict:
    return {
        "schema_version": "m8q.resume_evidence.v1",
        "corpus_version": "2026.02.0",
        "approved_at": "2026-02-15T12:00:00Z",
        "approval_report_sha256": _SHA_B,
        "outcomes": [_outcome_body(staged=False)],
        "doctrine": [_doctrine_body(staged=False)],
        "patterns": [_pattern_body()],
    }


@pytest.fixture
def candidate_mapping() -> dict:
    """Raw dict that round-trips through parse_outcome_candidate (function scope)."""
    return _outcome_body(staged=True)


@pytest.fixture
def outcome_record_mapping() -> dict:
    return _outcome_body(staged=False)


@pytest.fixture
def doctrine_candidate_mapping() -> dict:
    return _doctrine_body(staged=True)


@pytest.fixture
def doctrine_record_mapping() -> dict:
    return _doctrine_body(staged=False)


@pytest.fixture
def pattern_card_mapping() -> dict:
    return _pattern_body()


@pytest.fixture
def corpus_mapping() -> dict:
    return _corpus_body()


@pytest.fixture
def write_yaml(tmp_path: Path):
    """Serialize a mapping to a tmp YAML file and return its path."""

    def _write(mapping: dict, name: str = "bundle.yaml") -> Path:
        path = tmp_path / name
        path.write_text(
            yaml.safe_dump(mapping, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path

    return _write


@pytest.fixture
def valid_candidate(candidate_mapping, write_yaml):
    return parse_outcome_candidate(write_yaml(candidate_mapping))


@pytest.fixture
def valid_outcome_record(outcome_record_mapping, write_yaml):
    return parse_outcome_record(write_yaml(outcome_record_mapping, "outcome_record.yaml"))


@pytest.fixture
def valid_doctrine_candidate(doctrine_candidate_mapping, write_yaml):
    return parse_doctrine_candidate(
        write_yaml(doctrine_candidate_mapping, "doctrine_candidate.yaml")
    )


@pytest.fixture
def valid_doctrine_record(doctrine_record_mapping, write_yaml):
    return parse_doctrine_record(write_yaml(doctrine_record_mapping, "doctrine_record.yaml"))


@pytest.fixture
def valid_pattern_card(pattern_card_mapping, write_yaml):
    return parse_pattern_card(write_yaml(pattern_card_mapping, "pattern_card.yaml"))


@pytest.fixture
def valid_corpus(corpus_mapping, tmp_path):
    root = tmp_path / "corpus_root"
    root.mkdir()
    (root / "corpus.yaml").write_text(
        yaml.safe_dump(copy.deepcopy(corpus_mapping), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return parse_canonical_corpus(root)
