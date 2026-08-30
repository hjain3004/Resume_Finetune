"""Strict-rejection matrix and round-trip tests for resume-evidence serde."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.resume_evidence.serde import (
    EvidenceValidationError,
    _parse_utc,
    dump_canonical_corpus,
    dump_doctrine_candidate,
    dump_doctrine_record,
    dump_outcome_candidate,
    dump_outcome_record,
    dump_pattern_card,
    parse_canonical_corpus,
    parse_doctrine_candidate,
    parse_doctrine_record,
    parse_outcome_candidate,
    parse_outcome_record,
    parse_pattern_card,
)

FIXTURE = Path("tests/fixtures/resume_evidence/valid_outcome")


def test_fixture_bundle_parses() -> None:
    candidate = parse_outcome_candidate(FIXTURE / "bundle.yaml")
    assert candidate.reference_id == "cand_fixture_001"
    assert isinstance(candidate.sources, tuple)
    assert candidate.sources[0].snapshot_file == "sources/resume.md"
    assert candidate.editorial_ratings[0].score == 3


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda x: x.pop("reference_id"), "missing keys.*reference_id"),
        (lambda x: x.__setitem__("unexpected", 1), "unexpected keys.*unexpected"),
        (
            lambda x: x.__setitem__("professional_experience_months", True),
            "expected integer",
        ),
        (lambda x: x.__setitem__("outcome_tier", "oa"), "outcome_tier"),
    ],
)
def test_candidate_structure_is_strict(candidate_mapping, write_yaml, mutation, match) -> None:
    mutation(candidate_mapping)
    path = write_yaml(candidate_mapping)
    with pytest.raises(EvidenceValidationError, match=match):
        parse_outcome_candidate(path)


def test_nested_enum_value_must_be_string(candidate_mapping, write_yaml) -> None:
    candidate_mapping["editorial_ratings"][0]["dimension"] = 5
    with pytest.raises(EvidenceValidationError, match="dimension"):
        parse_outcome_candidate(write_yaml(candidate_mapping))


def test_nested_int_rejects_bool(candidate_mapping, write_yaml) -> None:
    candidate_mapping["editorial_ratings"][0]["score"] = True
    with pytest.raises(EvidenceValidationError, match="expected integer"):
        parse_outcome_candidate(write_yaml(candidate_mapping))


def test_case_insensitive_duplicate_string_rejected(candidate_mapping, write_yaml) -> None:
    candidate_mapping["feature_tags"] = ["one_page", "ONE_PAGE"]
    with pytest.raises(EvidenceValidationError, match="feature_tags"):
        parse_outcome_candidate(write_yaml(candidate_mapping))


def test_duplicate_source_id_rejected(candidate_mapping, write_yaml) -> None:
    candidate_mapping["sources"][1]["source_id"] = "src_resume"
    with pytest.raises(EvidenceValidationError, match="source_id"):
        parse_outcome_candidate(write_yaml(candidate_mapping))


def test_literal_duplicate_mapping_key_rejected(tmp_path) -> None:
    path = tmp_path / "dup.yaml"
    path.write_text(
        "schema_version: m8q.resume_evidence.v1\n"
        "reference_id: duplicate\n"
        "reference_id: hidden\n",
        encoding="utf-8",
    )
    with pytest.raises(EvidenceValidationError, match="duplicate mapping key: reference_id"):
        parse_outcome_candidate(path)


def test_parse_utc_rejects_implicit_datetime() -> None:
    with pytest.raises(EvidenceValidationError, match="retrieved_at"):
        _parse_utc(datetime(2026, 2, 1, 0, 0, 0), "retrieved_at")


def test_parse_utc_rejects_non_second_precision() -> None:
    with pytest.raises(EvidenceValidationError, match="approved_at"):
        _parse_utc("2026-02-01T00:00:00.500Z", "approved_at")


def test_unquoted_timestamp_in_yaml_is_rejected(candidate_mapping, tmp_path) -> None:
    # A bare timestamp is parsed by YAML into a datetime, which must be rejected.
    text = (FIXTURE / "bundle.yaml").read_text(encoding="utf-8")
    text = text.replace(
        "retrieved_at: '2026-02-01T00:00:00Z'",
        "retrieved_at: 2026-02-01T00:00:00Z",
    )
    path = tmp_path / "unquoted.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="retrieved_at"):
        parse_outcome_candidate(path)


def test_candidate_round_trip(valid_candidate, tmp_path) -> None:
    path = tmp_path / "bundle.yaml"
    path.write_text(dump_outcome_candidate(valid_candidate), encoding="utf-8")
    assert parse_outcome_candidate(path) == valid_candidate


def test_outcome_record_round_trip(valid_outcome_record, tmp_path) -> None:
    path = tmp_path / "record.yaml"
    path.write_text(dump_outcome_record(valid_outcome_record), encoding="utf-8")
    assert parse_outcome_record(path) == valid_outcome_record


def test_doctrine_candidate_round_trip(valid_doctrine_candidate, tmp_path) -> None:
    path = tmp_path / "dc.yaml"
    path.write_text(dump_doctrine_candidate(valid_doctrine_candidate), encoding="utf-8")
    assert parse_doctrine_candidate(path) == valid_doctrine_candidate


def test_doctrine_record_round_trip(valid_doctrine_record, tmp_path) -> None:
    path = tmp_path / "dr.yaml"
    path.write_text(dump_doctrine_record(valid_doctrine_record), encoding="utf-8")
    assert parse_doctrine_record(path) == valid_doctrine_record


def test_pattern_card_round_trip(valid_pattern_card, tmp_path) -> None:
    path = tmp_path / "pc.yaml"
    path.write_text(dump_pattern_card(valid_pattern_card), encoding="utf-8")
    assert parse_pattern_card(path) == valid_pattern_card


def test_canonical_corpus_round_trip(valid_corpus, tmp_path) -> None:
    root = tmp_path / "rt_corpus"
    root.mkdir()
    (root / "corpus.yaml").write_text(dump_canonical_corpus(valid_corpus), encoding="utf-8")
    assert parse_canonical_corpus(root) == valid_corpus


def test_canonical_dump_has_no_local_only_keys(valid_outcome_record, valid_corpus) -> None:
    record_yaml = dump_outcome_record(valid_outcome_record)
    assert "snapshot_file" not in record_yaml
    assert "layout_file" not in record_yaml

    corpus_yaml = dump_canonical_corpus(valid_corpus)
    assert "snapshot_file" not in corpus_yaml
    assert "layout_file" not in corpus_yaml


def test_doctrine_candidate_structure_is_strict(doctrine_candidate_mapping, write_yaml) -> None:
    doctrine_candidate_mapping["confidence"] = "very_high"
    with pytest.raises(EvidenceValidationError, match="confidence"):
        parse_doctrine_candidate(write_yaml(doctrine_candidate_mapping, "dc.yaml"))
