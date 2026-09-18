"""Self-pair-safe comparison construction.

This module is the fix for the defect where `build-blind-pairs` paired an
evaluation result against itself. `build_comparison_for_target` resolves a
genuinely distinct baseline through `baseline_registry.BaselineRegistry`,
verifies target/JD/profile provenance, and raises `SelfPairError` if the
resolved baseline turns out to be indistinguishable from the candidate
(same artifact_id, same resume path, same checksum, or same result_run_id)
-- unless `diagnostic_mode=True`, which is never the default and exists
only so tests (and an explicit CLI flag) can exercise same-system
comparisons on purpose.

`build_blind_pairs_batch` never raises: it turns every exclusion (no
baseline available, provenance mismatch, detected self-pair) into a
`PairExclusion` record so one bad target cannot abort the whole Top-10
batch, and the caller can see exactly what was skipped and why.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from src.tailor2_eval.baseline_registry import BaselineEntry, BaselineKind, BaselineRegistry, DEFAULT_PREFERRED_KINDS
from src.tailor2_eval.blind import BlindPackage, build_blind_package
from src.tailor2_eval.schemas import ComparisonCandidate, ComparisonPair, TargetResult


class SelfPairError(ValueError):
    """Raised when a resolved baseline is not genuinely distinct from the
    candidate it would be compared against."""


class ComparisonProvenanceMismatchError(ValueError):
    """Raised when the candidate and baseline do not share target_id,
    jd_checksum, or profile_checksum."""


def make_artifact_id(label: str, result_run_id: str, resume_checksum: str) -> str:
    """Deterministic fallback artifact_id for a ComparisonCandidate that
    didn't set one explicitly (e.g. a pre-existing caller of
    ComparisonCandidate that predates the artifact_id field)."""
    return f"{label}:{result_run_id}:{resume_checksum[:12]}"


@dataclass(frozen=True)
class PairExclusion:
    target_id: str
    reason: str  # "no_baseline_available" | "provenance_mismatch" | "self_pair_detected"
    detail: str


@dataclass(frozen=True)
class AnswerKeyEntry:
    """The private record of who candidate_1/candidate_2 actually are.
    Never written into the same file as the reviewer-facing BlindPackage --
    callers must persist this separately (see scripts/evaluate_tailor2.py,
    which writes it under an `answer_key/` subdirectory)."""

    comparison_id: str
    target_id: str
    purpose: str
    candidate_artifact_id: str
    candidate_pipeline_id: str
    candidate_model_identities: dict[str, Any]
    baseline_kind: str
    baseline_artifact_id: str
    baseline_pipeline_id: str
    baseline_model_identities: dict[str, Any]
    baseline_provenance: str
    diagnostic_mode: bool


def answer_key_entry_to_dict(entry: AnswerKeyEntry) -> dict[str, Any]:
    return asdict(entry)


def _candidate_side(result: TargetResult) -> ComparisonCandidate:
    resume_path = result.artifact_paths.get("resume_text") or result.artifact_paths.get("resume_text_fallback") or ""
    checksum = result.resume_checksum or ""
    return ComparisonCandidate(
        label="candidate",
        result_run_id=result.run_id,
        resume_checksum=checksum,
        resume_text_path=resume_path,
        artifact_id=make_artifact_id("candidate", result.run_id, checksum),
        pipeline_id="",  # the candidate pipeline identity lives in result.drafter/auditor/... ; recorded in the answer key
        model_identities={
            "drafter": {"provider": result.drafter.provider, "model": result.drafter.model},
            "auditor": {"provider": result.auditor.provider, "model": result.auditor.model},
        },
        provenance=f"tailor2 run {result.run_id} for {result.target_id}",
    )


def _baseline_side(baseline: BaselineEntry) -> ComparisonCandidate:
    return ComparisonCandidate(
        label="baseline",
        result_run_id=baseline.artifact_id,
        resume_checksum=baseline.resume_checksum,
        resume_text_path=baseline.resume_text_path,
        artifact_id=baseline.artifact_id,
        pipeline_id=baseline.pipeline_id,
        model_identities=dict(baseline.model_identities),
        provenance=baseline.provenance,
    )


def check_not_self_pair(candidate: ComparisonCandidate, baseline: ComparisonCandidate, *, diagnostic_mode: bool = False) -> None:
    if diagnostic_mode:
        return
    if candidate.artifact_id and candidate.artifact_id == baseline.artifact_id:
        raise SelfPairError(f"candidate and baseline resolve to the same artifact_id: {candidate.artifact_id!r}")
    if candidate.resume_text_path and candidate.resume_text_path == baseline.resume_text_path:
        raise SelfPairError(f"candidate and baseline share the same artifact path: {candidate.resume_text_path!r}")
    if candidate.resume_checksum and candidate.resume_checksum == baseline.resume_checksum:
        raise SelfPairError(f"candidate and baseline share the same resume checksum: {candidate.resume_checksum!r}")
    if candidate.result_run_id and candidate.result_run_id == baseline.result_run_id:
        raise SelfPairError(f"candidate and baseline share the same result id: {candidate.result_run_id!r}")


def _check_provenance(candidate_result: TargetResult, baseline: BaselineEntry, *, baseline_jd_checksum: str, baseline_profile_checksum: str) -> None:
    if baseline_jd_checksum and baseline_jd_checksum != candidate_result.jd_checksum:
        raise ComparisonProvenanceMismatchError(
            f"baseline jd_checksum {baseline_jd_checksum!r} != candidate jd_checksum {candidate_result.jd_checksum!r}"
        )
    if baseline_profile_checksum and baseline_profile_checksum != candidate_result.profile_checksum:
        raise ComparisonProvenanceMismatchError(
            f"baseline profile_checksum {baseline_profile_checksum!r} != candidate profile_checksum {candidate_result.profile_checksum!r}"
        )


def build_comparison_for_target(
    candidate_result: TargetResult,
    registry: BaselineRegistry,
    *,
    seed: int,
    resume_text_candidate: str,
    resume_text_baseline_lookup: dict[str, str],
    preferred_kinds: tuple[BaselineKind, ...] = DEFAULT_PREFERRED_KINDS,
    diagnostic_mode: bool = False,
    baseline_jd_checksum: str = "",
    baseline_profile_checksum: str = "",
) -> tuple[ComparisonPair, BlindPackage, AnswerKeyEntry] | PairExclusion:
    """Returns either (ComparisonPair, BlindPackage, AnswerKeyEntry) on
    success, or a PairExclusion explaining why the target was skipped.
    Never raises for the two "nothing usable" cases (no baseline, provenance
    mismatch) -- those are ordinary, expected outcomes for a Top-10 batch.
    A detected self-pair also returns a PairExclusion (reason
    "self_pair_detected") rather than raising, so a batch run reports it
    instead of crashing; call check_not_self_pair directly for the raising
    form used by unit tests."""
    baseline = registry.resolve(candidate_result.target_id, preferred_kinds)
    if baseline is None:
        return PairExclusion(
            target_id=candidate_result.target_id,
            reason="no_baseline_available",
            detail=f"no baseline of kind in {preferred_kinds} registered for target {candidate_result.target_id!r}",
        )

    try:
        _check_provenance(
            candidate_result, baseline,
            baseline_jd_checksum=baseline_jd_checksum or candidate_result.jd_checksum,
            baseline_profile_checksum=baseline_profile_checksum or candidate_result.profile_checksum,
        )
    except ComparisonProvenanceMismatchError as exc:
        return PairExclusion(target_id=candidate_result.target_id, reason="provenance_mismatch", detail=str(exc))

    candidate_side = _candidate_side(candidate_result)
    baseline_side = _baseline_side(baseline)

    try:
        check_not_self_pair(candidate_side, baseline_side, diagnostic_mode=diagnostic_mode)
    except SelfPairError as exc:
        return PairExclusion(target_id=candidate_result.target_id, reason="self_pair_detected", detail=str(exc))

    purpose = "diagnostic_same_system" if diagnostic_mode else f"candidate_vs_{baseline.kind}"
    comparison_id = f"cmp-{candidate_result.target_id}-{baseline.kind}"
    pair = ComparisonPair(
        schema_version="1.1",
        comparison_id=comparison_id,
        target_id=candidate_result.target_id,
        jd_checksum=candidate_result.jd_checksum,
        profile_checksum=candidate_result.profile_checksum,
        candidate_a=candidate_side,
        candidate_b=baseline_side,
        purpose=purpose,
    )

    resume_text_baseline = resume_text_baseline_lookup.get(baseline.resume_text_path, "")
    package = build_blind_package(
        pair,
        target_role_summary=f"Target: {candidate_result.target_id}",
        resume_text_a=resume_text_candidate,
        resume_text_b=resume_text_baseline,
        seed=seed,
    )

    answer_key = AnswerKeyEntry(
        comparison_id=comparison_id,
        target_id=candidate_result.target_id,
        purpose=purpose,
        candidate_artifact_id=candidate_side.artifact_id,
        candidate_pipeline_id=candidate_side.pipeline_id,
        candidate_model_identities=candidate_side.model_identities,
        baseline_kind=baseline.kind,
        baseline_artifact_id=baseline_side.artifact_id,
        baseline_pipeline_id=baseline_side.pipeline_id,
        baseline_model_identities=baseline_side.model_identities,
        baseline_provenance=baseline_side.provenance,
        diagnostic_mode=diagnostic_mode,
    )
    return pair, package, answer_key


def build_comparison_between_results(
    result_a: TargetResult,
    result_b: TargetResult,
    *,
    purpose: str,
    seed: int,
    resume_text_a: str,
    resume_text_b: str,
    diagnostic_mode: bool = False,
) -> tuple[ComparisonPair, BlindPackage, AnswerKeyEntry]:
    """Build a comparison directly between two independently-produced
    TargetResults -- e.g. candidate vs. an alternate pipeline configuration,
    or (only with diagnostic_mode=True) candidate vs. candidate for a
    controlled same-system diagnostic. Unlike build_comparison_for_target
    (which resolves a baseline through the registry and only ever returns a
    PairExclusion on failure), this raises directly: it is meant for
    explicit, single-pair construction where the caller wants a hard error
    on mismatched provenance or a detected self-pair, not a batch-skip."""
    if result_a.target_id != result_b.target_id:
        raise ComparisonProvenanceMismatchError(f"target_id mismatch: {result_a.target_id!r} != {result_b.target_id!r}")
    if result_a.jd_checksum != result_b.jd_checksum:
        raise ComparisonProvenanceMismatchError(f"jd_checksum mismatch: {result_a.jd_checksum!r} != {result_b.jd_checksum!r}")
    if result_a.profile_checksum != result_b.profile_checksum:
        raise ComparisonProvenanceMismatchError(
            f"profile_checksum mismatch: {result_a.profile_checksum!r} != {result_b.profile_checksum!r}"
        )

    side_a = _candidate_side(result_a)
    side_b = replace(_candidate_side(result_b), label="candidate_b")
    check_not_self_pair(side_a, side_b, diagnostic_mode=diagnostic_mode)

    comparison_id = f"cmp-{result_a.target_id}-{result_a.run_id}-vs-{result_b.run_id}"
    pair = ComparisonPair(
        schema_version="1.1",
        comparison_id=comparison_id,
        target_id=result_a.target_id,
        jd_checksum=result_a.jd_checksum,
        profile_checksum=result_a.profile_checksum,
        candidate_a=side_a,
        candidate_b=side_b,
        purpose=purpose,
    )
    package = build_blind_package(
        pair, target_role_summary=f"Target: {result_a.target_id}",
        resume_text_a=resume_text_a, resume_text_b=resume_text_b, seed=seed,
    )
    answer_key = AnswerKeyEntry(
        comparison_id=comparison_id,
        target_id=result_a.target_id,
        purpose=purpose,
        candidate_artifact_id=side_a.artifact_id,
        candidate_pipeline_id=side_a.pipeline_id,
        candidate_model_identities=side_a.model_identities,
        baseline_kind="other_pipeline_result",
        baseline_artifact_id=side_b.artifact_id,
        baseline_pipeline_id=side_b.pipeline_id,
        baseline_model_identities=side_b.model_identities,
        baseline_provenance=side_b.provenance,
        diagnostic_mode=diagnostic_mode,
    )
    return pair, package, answer_key


@dataclass
class BatchPairingReport:
    included: list[tuple[ComparisonPair, BlindPackage, AnswerKeyEntry]] = field(default_factory=list)
    excluded: list[PairExclusion] = field(default_factory=list)


def build_blind_pairs_batch(
    candidate_results: list[TargetResult],
    registry: BaselineRegistry,
    *,
    seed: int,
    resume_text_by_candidate_run_id: dict[str, str],
    resume_text_baseline_lookup: dict[str, str],
    preferred_kinds: tuple[BaselineKind, ...] = DEFAULT_PREFERRED_KINDS,
    diagnostic_mode: bool = False,
) -> BatchPairingReport:
    report = BatchPairingReport()
    for result in candidate_results:
        resume_text_candidate = resume_text_by_candidate_run_id.get(result.run_id, "")
        outcome = build_comparison_for_target(
            result,
            registry,
            seed=seed,
            resume_text_candidate=resume_text_candidate,
            resume_text_baseline_lookup=resume_text_baseline_lookup,
            preferred_kinds=preferred_kinds,
            diagnostic_mode=diagnostic_mode,
        )
        if isinstance(outcome, PairExclusion):
            report.excluded.append(outcome)
        else:
            report.included.append(outcome)
    return report
