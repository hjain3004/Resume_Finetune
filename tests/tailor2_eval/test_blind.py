"""Required tests 11-13 and 17: blind ordering determinism, identity hiding,
comparison provenance, and optional manual reference."""

from __future__ import annotations

import dataclasses

import pytest

from src.tailor2_eval.blind import (
    ComparisonProvenanceError,
    blind_package_to_dict,
    build_blind_package,
    build_blind_pairs_from_results,
    validate_comparison_provenance,
)
from src.tailor2_eval.schemas import ComparisonCandidate, ComparisonPair


def _pair(**overrides) -> ComparisonPair:
    base = dict(
        schema_version="1.0",
        comparison_id="cmp-zoom_4766",
        target_id="zoom_4766",
        jd_checksum="3cb0db9d4a8b3af912332a1d52213c52742cc7c73a29281f119ce807d3d3c72f",
        profile_checksum="6412c9fd6e7ea390c64a7c773c46afda74199de36966369afb6f79c746534c8d",
        candidate_a=ComparisonCandidate("candidate", "run-a", "checksum-a", "candidate.tex"),
        candidate_b=ComparisonCandidate("baseline", "run-b", "checksum-b", "baseline.tex"),
    )
    base.update(overrides)
    return ComparisonPair(**base)


def test_blind_ordering_is_deterministic_from_seed() -> None:
    pair = _pair()
    p1 = build_blind_package(pair, target_role_summary="Zoom SDE", resume_text_a="AAA", resume_text_b="BBB", seed=7)
    p2 = build_blind_package(pair, target_role_summary="Zoom SDE", resume_text_a="AAA", resume_text_b="BBB", seed=7)
    assert p1.candidates[0].resume_text == p2.candidates[0].resume_text
    assert p1.candidates[1].resume_text == p2.candidates[1].resume_text
    assert p1.integrity_checksum == p2.integrity_checksum


def test_blind_ordering_can_differ_across_seeds() -> None:
    pair = _pair()
    orders = set()
    for seed in range(20):
        pkg = build_blind_package(pair, target_role_summary="Zoom SDE", resume_text_a="AAA", resume_text_b="BBB", seed=seed)
        orders.add(pkg.candidates[0].resume_text)
    assert orders == {"AAA", "BBB"}  # both orderings occur across enough seeds


def test_blind_package_hides_pipeline_and_model_identities() -> None:
    pair = _pair()
    pkg = build_blind_package(pair, target_role_summary="Zoom SDE", resume_text_a="AAA", resume_text_b="BBB", seed=1)
    payload = blind_package_to_dict(pkg)
    dumped = str(payload)
    # "candidate_1"/"candidate_2" are the intended safe anonymized IDs (they
    # legitimately contain the substring "candidate"); what must never leak
    # is the real pipeline-side label ("candidate"/"baseline" as a bare
    # field), the provider/model names, or the source run_ids.
    assert "label" not in payload["candidates"][0] and "label" not in payload["candidates"][1]
    for leaked in ("claude", "openai", "gemini", "run-a", "run-b", "\"baseline\"", "'baseline'"):
        assert leaked not in dumped
    assert {c["anon_id"] for c in payload["candidates"]} == {"candidate_1", "candidate_2"}


def test_comparison_provenance_validated() -> None:
    good = _pair()
    validate_comparison_provenance(good)  # does not raise

    bad = dataclasses.replace(good, target_id="")
    with pytest.raises(ComparisonProvenanceError):
        validate_comparison_provenance(bad)


def test_missing_manual_reference_does_not_block_pair_building() -> None:
    """A comparison pair only ever names two sides (schemas.ComparisonPair);
    nothing requires a third 'manual' candidate to exist for a pair -- so
    building pairs for targets that have no manual reference at all must
    succeed exactly like any other pair."""
    pair_without_manual = _pair(comparison_id="cmp-doordash_4608", target_id="doordash_4608")
    resume_texts = {"candidate.tex": "candidate text", "baseline.tex": "baseline text"}
    packages = build_blind_pairs_from_results([pair_without_manual], resume_texts, seed=3)
    assert len(packages) == 1
    assert packages[0].comparison_id == "cmp-doordash_4608"
