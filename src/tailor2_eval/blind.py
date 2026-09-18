"""Blind A/B comparison package generation.

A package must never leak which side is the candidate/baseline/manual/
render-fill pipeline, which provider produced it, or which model -- so the
`ComparisonCandidate.label` from schemas.py (e.g. "candidate", "baseline")
is deliberately NOT copied into the package; only opaque `anon_id`s
("candidate_1", "candidate_2") are. Ordering is derived from
`hashlib.sha256(f"{seed}:{comparison_id}")` rather than a stateful RNG, so
the same seed always produces the same A/B order for the same comparison
regardless of call order -- what the task calls "deterministic randomized
ordering from a recorded seed."
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.tailor2_eval.checksums import sha256_text
from src.tailor2_eval.schemas import RUBRIC_DIMENSIONS, ComparisonPair


class ComparisonProvenanceError(ValueError):
    """Raised when two candidates in a comparison do not share target/profile
    provenance -- comparing résumés for different JDs or profile versions
    would make the comparison meaningless."""


@dataclass(frozen=True)
class BlindCandidateView:
    anon_id: str  # "candidate_1" | "candidate_2" -- never the real pipeline label
    resume_text: str


@dataclass(frozen=True)
class BlindPackage:
    schema_version: str
    comparison_id: str
    target_role_summary: str
    candidates: tuple[BlindCandidateView, BlindCandidateView]
    rubric_dimensions: tuple[str, ...]
    response_template: dict[str, Any]
    integrity_checksum: str


def _deterministic_order(seed: int, comparison_id: str) -> bool:
    """True if candidate_a should be shown first (as candidate_1). Purely a
    function of (seed, comparison_id) -- no global random state, so calling
    this twice, in any order, for the same inputs always agrees."""
    digest = hashlib.sha256(f"{seed}:{comparison_id}".encode("utf-8")).digest()
    return digest[0] % 2 == 0


def validate_comparison_provenance(pair: ComparisonPair) -> None:
    """The task requires: 'Validate that compared artifacts use the same
    target JD and compatible profile version.' Both candidates in a
    ComparisonPair already share pair.target_id/jd_checksum/profile_checksum
    by construction (schemas.ComparisonPair has one of each, not one per
    side) -- this function exists so callers assembling a pair from two
    separate TargetResults are forced to prove that equality explicitly
    before a pair is ever created."""
    if not pair.target_id or not pair.jd_checksum or not pair.profile_checksum:
        raise ComparisonProvenanceError("comparison pair is missing target_id/jd_checksum/profile_checksum")


def response_template() -> dict[str, Any]:
    return {
        "comparison_id": "<fill in>",
        "reviewer_id": "<fill in>",
        "dimension_preferences": {dim: "TIE" for dim in RUBRIC_DIMENSIONS},
        "overall_preference": "TIE",
        "reviewer_confidence": 0.5,
        "free_text_concerns": "",
        "factual_error_flags": [],
    }


def build_blind_package(
    pair: ComparisonPair,
    *,
    target_role_summary: str,
    resume_text_a: str,
    resume_text_b: str,
    seed: int,
) -> BlindPackage:
    validate_comparison_provenance(pair)

    a_first = _deterministic_order(seed, pair.comparison_id)
    ordered = (
        BlindCandidateView(anon_id="candidate_1", resume_text=resume_text_a),
        BlindCandidateView(anon_id="candidate_2", resume_text=resume_text_b),
    )
    if not a_first:
        ordered = (
            BlindCandidateView(anon_id="candidate_1", resume_text=resume_text_b),
            BlindCandidateView(anon_id="candidate_2", resume_text=resume_text_a),
        )

    integrity_payload = f"{pair.comparison_id}|{ordered[0].resume_text}|{ordered[1].resume_text}"
    package = BlindPackage(
        schema_version="1.0",
        comparison_id=pair.comparison_id,
        target_role_summary=target_role_summary,
        candidates=ordered,
        rubric_dimensions=RUBRIC_DIMENSIONS,
        response_template=response_template(),
        integrity_checksum=sha256_text(integrity_payload),
    )
    return package


def blind_package_to_dict(package: BlindPackage) -> dict[str, Any]:
    return {
        "schema_version": package.schema_version,
        "comparison_id": package.comparison_id,
        "target_role_summary": package.target_role_summary,
        "candidates": [
            {"anon_id": c.anon_id, "resume_text": c.resume_text} for c in package.candidates
        ],
        "rubric_dimensions": list(package.rubric_dimensions),
        "response_template": package.response_template,
        "integrity_checksum": package.integrity_checksum,
    }


def build_blind_pairs_from_results(
    pairs: list[ComparisonPair],
    resume_texts: dict[str, str],
    *,
    seed: int,
) -> list[BlindPackage]:
    """resume_texts maps a ComparisonCandidate.resume_text_path (as recorded
    in the pair) to its actual text content -- kept separate from the pair
    itself so no file path or pipeline label leaks into the package."""
    packages = []
    for pair in pairs:
        text_a = resume_texts[pair.candidate_a.resume_text_path]
        text_b = resume_texts[pair.candidate_b.resume_text_path]
        packages.append(
            build_blind_package(
                pair,
                target_role_summary=f"Target: {pair.target_id}",
                resume_text_a=text_a,
                resume_text_b=text_b,
                seed=seed,
            )
        )
    return packages
