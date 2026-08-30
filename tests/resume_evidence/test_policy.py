"""Bundle-integrity and admission-policy tests for the resume evidence bank.

Every fixture here is synthetic. No real names, resume text, contact details, or
paid-book material appears in this module. On-disk snapshot files are written by
the test and their SHA-256 is computed here so hash integrity can be exercised
end to end.
"""

from __future__ import annotations

import dataclasses
import itertools
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.resume_evidence import policy, serde
from src.resume_evidence.model import (
    AuthorityKind,
    CanonicalSourceRecord,
    ConfidenceLevel,
    DoctrineCandidate,
    DoctrineUse,
    EditorialDimension,
    EditorialRating,
    EmploymentInterval,
    EvidenceConfidence,
    ExperienceConfidence,
    OutcomeCandidate,
    OutcomeTier,
    PatternCard,
    ResumeRepresentation,
    ResumeVersionAttribution,
    RoleFamily,
    SourceKind,
    SourceRecord,
)
from src.resume_evidence.serde import EvidenceValidationError

SCHEMA = "m8q.resume_evidence.v1"
RETRIEVED = datetime(2026, 2, 1, tzinfo=timezone.utc)

RESUME_TEXT = """\
# Experience
Backend Engineer Intern, synthetic staging team (2024-05 to 2024-08).
Built a rate limiter service exercised only with generated traffic.

# Projects
Distributed key value store prototype with a write ahead log and snapshot compaction.

# Education
State University, B.S. in Computer Science, degree conferred 2025-05.

# Skills
Go, Python, PostgreSQL, gRPC, Kubernetes.
"""

OUTCOME_TEXT = """\
Anonymized candidate update posted publicly on a job tracker.
The candidate reached the final interview round for a backend platform team after a recruiter screen.
Outcome shared voluntarily by the poster and not verified by the platform.
"""

DOCTRINE_TEXT = """\
Numbers make accomplishments legible to a busy reviewer who scans quickly.
Prefer concrete measured outcomes over generic responsibility lists wherever the underlying data exists.
"""

OUTCOME_QUOTE = (
    "reached the final interview round for a backend platform team after a recruiter screen"
)
DOCTRINE_QUOTE = "Numbers make accomplishments legible to a busy reviewer who scans quickly"


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base_kwargs() -> dict:
    return dict(
        schema_version=SCHEMA,
        reference_id="cand_syn_001",
        source_kind=SourceKind.HUNTR,
        layout_file="layouts/syn.typ",
        layout_sha256="a" * 64,
        role_family=RoleFamily.BACKEND_PLATFORM,
        target_role="Backend Engineer",
        target_level="New Grad",
        graduation_month="2025-05",
        professional_intervals=(EmploymentInterval("2025-06", "2026-01"),),
        internship_intervals=(EmploymentInterval("2024-05", "2024-08"),),
        professional_experience_months=7,
        experience_confidence=ExperienceConfidence.DERIVED,
        outcome_tier=OutcomeTier.FINAL_INTERVIEW,
        outcome_evidence_quote=OUTCOME_QUOTE,
        outcome_evidence_confidence=EvidenceConfidence.SELF_REPORTED,
        resume_representation=ResumeRepresentation.ANONYMIZED,
        resume_version_attribution=ResumeVersionAttribution.PUBLISHER_LINKED,
        section_order=("experience", "projects", "education", "skills"),
        feature_tags=("one_page",),
        editorial_ratings=tuple(
            EditorialRating(dim, 2, f"Synthetic note for {dim.value}.")
            for dim in EditorialDimension
        ),
        limitations=("Single synthetic anonymized data point.",),
    )


@pytest.fixture
def make_bundle(tmp_path):
    """Factory: write snapshot files and return (OutcomeCandidate, bundle_dir)."""

    counter = itertools.count()

    def _make(
        *,
        resume_text: str = RESUME_TEXT,
        outcome_text: str = OUTCOME_TEXT,
        same_source: bool = False,
        **overrides,
    ):
        root = tmp_path / f"bundle{next(counter)}"
        (root / "sources").mkdir(parents=True)
        if same_source:
            only = root / "sources" / "combined.md"
            only.write_text(resume_text + "\n" + outcome_text, encoding="utf-8")
            sources = (
                SourceRecord(
                    "src_only",
                    "https://huntr.co/story/one",
                    "combined snapshot",
                    RETRIEVED,
                    _sha(only),
                    "sources/combined.md",
                ),
            )
            rid = oid = "src_only"
        else:
            rp = root / "sources" / "resume.md"
            rp.write_text(resume_text, encoding="utf-8")
            op = root / "sources" / "outcome.md"
            op.write_text(outcome_text, encoding="utf-8")
            sources = (
                SourceRecord(
                    "src_resume",
                    "https://huntr.co/resume/one",
                    "resume snapshot",
                    RETRIEVED,
                    _sha(rp),
                    "sources/resume.md",
                ),
                SourceRecord(
                    "src_outcome",
                    "https://huntr.co/outcome/one",
                    "outcome snapshot",
                    RETRIEVED,
                    _sha(op),
                    "sources/outcome.md",
                ),
            )
            rid, oid = "src_resume", "src_outcome"
        kwargs = _base_kwargs()
        kwargs.update(
            sources=sources, resume_source_id=rid, outcome_source_id=oid, **overrides
        )
        return OutcomeCandidate(**kwargs), root

    return _make


@pytest.fixture
def bundle(make_bundle):
    return make_bundle()


@pytest.fixture
def valid_candidate(bundle):
    return bundle[0]


@pytest.fixture
def bundle_dir(bundle):
    return bundle[1]


@pytest.fixture
def doctrine_bundle(tmp_path):
    root = tmp_path / "doctrine_bundle"
    (root / "sources").mkdir(parents=True)
    sp = root / "sources" / "doctrine.md"
    sp.write_text(DOCTRINE_TEXT, encoding="utf-8")
    source = SourceRecord(
        "src_doc",
        "https://example.org/principles/quantify",
        "doctrine snapshot",
        RETRIEVED,
        _sha(sp),
        "sources/doctrine.md",
    )
    record = DoctrineCandidate(
        schema_version=SCHEMA,
        doctrine_id="doc_quantify_impact",
        source=source,
        authority_kind=AuthorityKind.PRACTITIONER_FIRST_PARTY,
        principle="Quantify measurable outcomes where the data supports it.",
        early_career_applicability="High: interns can cite measurable project outcomes.",
        affected_dimensions=(EditorialDimension.CLAIM_CREDIBILITY,),
        supporting_quote=DOCTRINE_QUOTE,
        conflicts_or_qualifications=("Avoid fabricated precision.",),
        confidence=ConfidenceLevel.MEDIUM,
        permitted_uses=(DoctrineUse.RUBRIC_CANDIDATE,),
    )
    return record, root


# --------------------------------------------------------------------------- #
# evidence-integrity
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "http://huntr.co/example",
        "https://user:pass@huntr.co/example",
        "https://huntr.co/example?token=secret",
        "https://127.0.0.1/example",
    ],
)
def test_unsafe_source_urls_fail(valid_candidate, bundle_dir, url):
    src0 = dataclasses.replace(valid_candidate.sources[0], url=url)
    cand = dataclasses.replace(
        valid_candidate, sources=(src0, valid_candidate.sources[1])
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, bundle_dir)


def test_valid_bundle_passes(valid_candidate, bundle_dir):
    policy.validate_outcome_bundle(valid_candidate, bundle_dir)


def test_resume_and_outcome_source_may_be_equal(make_bundle):
    cand, root = make_bundle(same_source=True)
    policy.validate_outcome_bundle(cand, root)


def test_outcome_quote_must_exist_in_declared_outcome_snapshot(
    valid_candidate, bundle_dir
):
    cand = dataclasses.replace(
        valid_candidate,
        outcome_evidence_quote="this exact phrase is absent from the outcome snapshot entirely",
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, bundle_dir)


def test_outcome_quote_over_25_words_fails(make_bundle):
    long_quote = " ".join(f"token{i}" for i in range(26))
    cand, root = make_bundle(
        outcome_text=f"Lead in.\n{long_quote} and then some.\n",
        outcome_evidence_quote=long_quote,
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, root)


def test_outcome_quote_under_4_words_fails(make_bundle):
    cand, root = make_bundle(
        outcome_text="Short marker phrase here.\n", outcome_evidence_quote="Short marker phrase"
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, root)


def test_resume_source_must_contain_resume_sections(make_bundle):
    cand, root = make_bundle(
        resume_text="Just some prose about a person doing things. No headings at all.\nMore prose.\n"
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, root)


def test_snapshot_hash_mismatch_fails(valid_candidate, bundle_dir):
    src0 = dataclasses.replace(valid_candidate.sources[0], content_sha256="b" * 64)
    cand = dataclasses.replace(
        valid_candidate, sources=(src0, valid_candidate.sources[1])
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, bundle_dir)


def test_snapshot_hash_must_be_lowercase_hex(valid_candidate, bundle_dir):
    bad = valid_candidate.sources[0].content_sha256.upper()
    src0 = dataclasses.replace(valid_candidate.sources[0], content_sha256=bad)
    cand = dataclasses.replace(
        valid_candidate, sources=(src0, valid_candidate.sources[1])
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, bundle_dir)


def test_snapshot_path_may_not_escape_sources_directory(valid_candidate, bundle_dir):
    src0 = dataclasses.replace(
        valid_candidate.sources[0], snapshot_file="../escaped.md"
    )
    cand = dataclasses.replace(
        valid_candidate, sources=(src0, valid_candidate.sources[1])
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, bundle_dir)


def test_unresolved_source_id_fails(valid_candidate, bundle_dir):
    cand = dataclasses.replace(valid_candidate, outcome_source_id="src_missing")
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, bundle_dir)


def test_all_eight_editorial_dimensions_are_required_once(valid_candidate, bundle_dir):
    missing = valid_candidate.editorial_ratings[:-1]
    cand = dataclasses.replace(valid_candidate, editorial_ratings=missing)
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, bundle_dir)

    dup = valid_candidate.editorial_ratings[:-1] + (
        valid_candidate.editorial_ratings[0],
    )
    cand2 = dataclasses.replace(valid_candidate, editorial_ratings=dup)
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand2, bundle_dir)


def test_stored_experience_must_equal_recomputation(make_bundle):
    cand, root = make_bundle(professional_experience_months=99)
    with pytest.raises(EvidenceValidationError):
        policy.validate_outcome_bundle(cand, root)


# --------------------------------------------------------------------------- #
# admission
# --------------------------------------------------------------------------- #
def test_36_month_recruiter_screen_is_accepted(make_bundle):
    cand, _ = make_bundle(
        graduation_month="2022-12",
        professional_intervals=(EmploymentInterval("2023-01", "2026-01"),),
        professional_experience_months=36,
        outcome_tier=OutcomeTier.RECRUITER_SCREEN,
        experience_confidence=ExperienceConfidence.DERIVED,
    )
    decision = policy.evaluate_admission(cand)
    assert decision.status is policy.AdmissionStatus.ACCEPTED
    assert decision.computed_experience_months == 36


def test_37_month_candidate_is_rejected(make_bundle):
    cand, _ = make_bundle(
        graduation_month="2022-12",
        professional_intervals=(EmploymentInterval("2023-01", "2026-02"),),
        professional_experience_months=37,
        outcome_tier=OutcomeTier.OFFER,
        experience_confidence=ExperienceConfidence.DERIVED,
    )
    decision = policy.evaluate_admission(cand)
    assert decision.status is policy.AdmissionStatus.REJECTED
    assert decision.computed_experience_months == 37


def test_ambiguous_experience_needs_review(make_bundle):
    cand, _ = make_bundle(experience_confidence=ExperienceConfidence.AMBIGUOUS)
    decision = policy.evaluate_admission(cand)
    assert decision.status is policy.AdmissionStatus.NEEDS_REVIEW


def test_ambiguous_resume_attribution_needs_review(make_bundle):
    cand, _ = make_bundle(
        resume_version_attribution=ResumeVersionAttribution.AMBIGUOUS
    )
    decision = policy.evaluate_admission(cand)
    assert decision.status is policy.AdmissionStatus.NEEDS_REVIEW


def test_oa_is_not_an_outcome_enum():
    with pytest.raises(ValueError):
        OutcomeTier("oa")
    assert "oa" not in {t.value for t in OutcomeTier}
    assert not hasattr(OutcomeTier, "OA")


# --------------------------------------------------------------------------- #
# conversion / privacy
# --------------------------------------------------------------------------- #
def test_to_outcome_record_drops_private_paths_and_round_trips(
    valid_candidate, bundle_dir, tmp_path
):
    record = policy.to_outcome_record(valid_candidate)
    for src in record.sources:
        assert isinstance(src, CanonicalSourceRecord)
        assert not hasattr(src, "snapshot_file")
    assert record.layout_sha256 == "a" * 64
    assert not hasattr(record, "layout_file")

    out = tmp_path / "record.yaml"
    out.write_text(serde.dump_outcome_record(record), encoding="utf-8")
    assert serde.parse_outcome_record(out) == record


def test_to_doctrine_record_drops_snapshot_file(doctrine_bundle, tmp_path):
    record, _ = doctrine_bundle
    canonical = policy.to_doctrine_record(record)
    assert isinstance(canonical.source, CanonicalSourceRecord)
    assert not hasattr(canonical.source, "snapshot_file")

    out = tmp_path / "doctrine.yaml"
    out.write_text(serde.dump_doctrine_record(canonical), encoding="utf-8")
    assert serde.parse_doctrine_record(out) == canonical


# --------------------------------------------------------------------------- #
# doctrine bundle
# --------------------------------------------------------------------------- #
def test_doctrine_bundle_valid(doctrine_bundle):
    record, root = doctrine_bundle
    policy.validate_doctrine_bundle(record, root)


def test_doctrine_quote_must_be_anchored(doctrine_bundle):
    record, root = doctrine_bundle
    bad = dataclasses.replace(
        record, supporting_quote="a quote that is simply not present in the snapshot text"
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_doctrine_bundle(bad, root)


def test_doctrine_requires_applicability_and_uses(doctrine_bundle):
    record, root = doctrine_bundle
    with pytest.raises(EvidenceValidationError):
        policy.validate_doctrine_bundle(
            dataclasses.replace(record, early_career_applicability="   "), root
        )
    with pytest.raises(EvidenceValidationError):
        policy.validate_doctrine_bundle(
            dataclasses.replace(record, permitted_uses=()), root
        )
    with pytest.raises(EvidenceValidationError):
        policy.validate_doctrine_bundle(
            dataclasses.replace(record, affected_dimensions=()), root
        )


def test_doctrine_url_safety_enforced(doctrine_bundle):
    record, root = doctrine_bundle
    bad = dataclasses.replace(
        record, source=dataclasses.replace(record.source, url="http://example.org/x")
    )
    with pytest.raises(EvidenceValidationError):
        policy.validate_doctrine_bundle(bad, root)


# --------------------------------------------------------------------------- #
# pattern cards
# --------------------------------------------------------------------------- #
def _pattern(**overrides) -> PatternCard:
    base = dict(
        schema_version=SCHEMA,
        pattern_id="pat_lead_with_outcome",
        text="Lead each bullet with the outcome, then the method.",
        anti_pattern=False,
        role_families=(RoleFamily.BACKEND_PLATFORM,),
        outcome_record_ids=("cand_a", "cand_b"),
        doctrine_record_ids=(),
        limitations=("Small synthetic sample.",),
        confidence=ConfidenceLevel.LOW,
        prohibited_uses=("auto_rewrite_without_review",),
        candidate_dimensions=(EditorialDimension.OWNERSHIP_CLARITY,),
    )
    base.update(overrides)
    return PatternCard(**base)


def test_pattern_card_valid_with_two_outcomes():
    policy.validate_pattern_card(
        _pattern(), {"cand_a", "cand_b", "cand_c"}, set()
    )


def test_pattern_card_valid_with_one_doctrine():
    card = _pattern(outcome_record_ids=("cand_a",), doctrine_record_ids=("doc_x",))
    policy.validate_pattern_card(card, {"cand_a"}, {"doc_x"})


def test_pattern_card_insufficient_basis_fails():
    card = _pattern(outcome_record_ids=("cand_a",), doctrine_record_ids=())
    with pytest.raises(EvidenceValidationError):
        policy.validate_pattern_card(card, {"cand_a"}, set())


def test_pattern_card_unknown_reference_fails():
    with pytest.raises(EvidenceValidationError):
        policy.validate_pattern_card(_pattern(), {"cand_a"}, set())
    card = _pattern(outcome_record_ids=("cand_a",), doctrine_record_ids=("doc_x",))
    with pytest.raises(EvidenceValidationError):
        policy.validate_pattern_card(card, {"cand_a"}, {"doc_other"})
